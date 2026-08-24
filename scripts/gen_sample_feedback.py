"""
Dev fixture generator — KHÔNG phải module production.

Đứng thay cho SOURCE LAYER "Feedback datalake" khi chưa có quyền truy cập bảng thật.
Architecture: docs/architecture.md §2 Overview > Input (schema nguồn Feedback datalake),
              §2 Assumptions A4/A5, §4.5 Data layer
Impl:         docs/impl-phase1-intent-classification.md §2 Step 0 (Data audit),
              Step 1 (Preprocess), Step 3 (Cluster / noise rate)
Plan:         docs/2026-08-25/sample-feedback-fixture/plan.md

Sinh dữ liệu feedback giả lập, deterministic theo seed, đúng tên trường của nguồn thật:
    feedback_id, user_email, agent, content, created_at

Chạy:
    python scripts/gen_sample_feedback.py                 # 520 dòng, seed 20260825
    python scripts/gen_sample_feedback.py -n 1000 --seed 7

Xóa file này khi có quyền truy cập bảng feedback thật.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "data" / "sample"

# 650 để sau khi Step 1 lọc dòng ngắn + dedup vẫn còn ≥ 500 dòng sạch (F3)
DEFAULT_N = 650
DEFAULT_SEED = 20260825
DUPLICATE_RATE = 0.03    # bản trùng chính xác — nguyên liệu cho dedup ở Step 1
WINDOW_DAYS = 180
WINDOW_END = datetime(2026, 8, 24, 18, 0)

# D6 trong plan.md: chỉ TÀI Chat / The Translator / The Powerpoint-er là chắc chắn
# (xuất hiện trong template/). Phần còn lại là placeholder, cần PM xác nhận.
# Trọng số lệch có chủ ý: "The Researcher" là agent ra sau, ít dữ liệu lịch sử —
# mô phỏng R1 (agent mới = nguồn unclassified chính).
AGENTS = [
    ("TÀI Chat", 30),
    ("The Translator", 22),
    ("The Powerpoint-er", 20),
    ("The Summarizer", 13),
    ("The Analyst", 10),
    ("The Researcher", 5),
]

FEATURES_VI = [
    "xuất file PPT ra PDF",
    "đổi ngôn ngữ output",
    "tóm tắt tài liệu dài",
    "chuyển dữ liệu Excel thành biểu đồ",
    "lưu lại lịch sử hội thoại",
    "upload nhiều file cùng lúc",
    "chỉnh giọng văn của bản dịch",
    "tạo mục lục tự động",
    "trích xuất bảng từ file PDF",
    "so sánh hai phiên bản tài liệu",
]
FEATURES_EN = [
    "export the deck to PDF",
    "change the output language",
    "summarize a long document",
    "turn Excel data into charts",
    "keep the conversation history",
    "upload multiple files at once",
    "adjust the tone of the translation",
    "generate a table of contents",
    "extract tables from a PDF",
    "compare two document versions",
]
FORMATS = ["PDF", "DOCX", "XLSX", "PPTX", "CSV", "Markdown"]

# 12 nhóm chủ đề ẩn. `weight` tạo phân bố long-tail như feedback thật.
# Nhãn nhóm KHÔNG đi vào file dữ liệu chính (D3), chỉ ra file sidecar (D4).
THEMES: list[dict] = [
    {
        "theme": "how_to_usage",
        "weight": 18,
        "vi": [
            "Mình không biết cách {feature} trong {agent}, có hướng dẫn nào không ạ?",
            "Làm sao để {feature} vậy team?",
            "Cho hỏi {agent} có cách nào {feature} không?",
            "Em mới dùng nên hơi lúng túng, muốn {feature} thì bấm ở đâu ạ?",
            "Tìm mãi không thấy chỗ {feature}, nhờ team chỉ giúp.",
            "Có tài liệu hướng dẫn dùng {agent} chi tiết hơn không? Bản trên SharePoint hơi sơ sài.",
            "Không rõ phải nhập prompt thế nào để {feature}.",
            "Mình muốn {feature} nhưng không biết bắt đầu từ đâu.",
            "{agent} có hỗ trợ {feature} không, hay phải làm tay?",
        ],
        "en": [
            "How do I {feature_en} in {agent}?",
            "Is there a way to {feature_en}? I could not find the option.",
            "New user here, could you point me to a guide for {agent}?",
            "What prompt should I use to {feature_en}?",
            "Where is the setting to {feature_en}?",
        ],
        "mixed": [
            "Team ơi, mình muốn {feature_en} nhưng không thấy option nào, guide ở đâu ạ?",
        ],
    },
    {
        "theme": "output_quality",
        "weight": 14,
        "vi": [
            "{agent} dịch sai khá nhiều thuật ngữ chuyên ngành ngân hàng, mình phải sửa lại gần hết.",
            "Output của {agent} bị lặp ý, đoạn sau nhắc lại gần nguyên đoạn trước.",
            "Kết quả trả về không khớp với dữ liệu mình upload, số liệu bị lệch.",
            "Bản tóm tắt bỏ mất đúng phần quan trọng nhất của tài liệu.",
            "Font tiếng Việt trong file {fmt} xuất ra bị lỗi, mất dấu hết.",
            "Nội dung sinh ra chung chung quá, không dùng được luôn mà phải viết lại từ đầu.",
            "Bố cục slide {agent} tạo ra lộn xộn, chữ tràn ra ngoài khung.",
            "Dịch xong thì mất hết định dạng bảng biểu trong file gốc.",
        ],
        "en": [
            "{agent} keeps mistranslating banking terminology, I had to fix almost every line.",
            "The summary drops the most important section of the document.",
            "Numbers in the output do not match the file I uploaded.",
            "Vietnamese characters are broken in the exported {fmt} file.",
            "The generated content is too generic to be usable as is.",
        ],
        "mixed": [
            "Mình thấy output bị duplicate content ở phần cuối, please check giúp nhé.",
        ],
    },
    {
        "theme": "error_crash",
        "weight": 12,
        "vi": [
            "Mình bấm generate thì báo lỗi 500, thử lại 3 lần vẫn vậy.",
            "{agent} chạy được nửa chừng rồi đứng, không ra kết quả cũng không báo lỗi.",
            "Upload file xong thì màn hình trắng luôn, phải F5 lại từ đầu.",
            "Báo lỗi 'Something went wrong' mà không nói gì thêm, không biết sửa kiểu gì.",
            "Session bị timeout liên tục, đang làm dở thì mất hết nội dung.",
            "Nhấn nút tải kết quả về thì không có gì xảy ra.",
        ],
        "en": [
            "Getting a 500 error every time I hit generate on {agent}.",
            "The page goes blank right after I upload a file.",
            "It fails with 'Something went wrong' and no further detail.",
            "My session times out in the middle of a long task and I lose everything.",
        ],
        "mixed": [
            "Team ơi, {agent} bị lỗi khi export, error message: 'Request failed with status code 500'. Nhờ team check giúp.",
        ],
    },
    {
        "theme": "feature_request",
        "weight": 13,
        "vi": [
            "Mong team bổ sung tính năng {feature} cho {agent}.",
            "Nếu {agent} hỗ trợ thêm định dạng {fmt} thì tiện hơn nhiều.",
            "Đề xuất: cho phép lưu prompt hay dùng thành template dùng lại.",
            "Có thể thêm chế độ chỉnh sửa kết quả ngay trên giao diện không ạ?",
            "Rất mong có bản dùng được trên điện thoại.",
            "Nên có nút hoàn tác, lỡ tay generate lại là mất bản cũ.",
            "Xin thêm tính năng {feature}, hiện mình vẫn phải làm tay bước đó.",
        ],
        "en": [
            "Please add {fmt} support in {agent}.",
            "It would help a lot if we could save frequently used prompts as templates.",
            "Feature request: let us edit the result directly in the UI.",
            "Any chance of a mobile friendly version?",
        ],
        "mixed": [
            "Đề xuất nhỏ: thêm option {feature_en} thì workflow của team mình gọn hơn nhiều.",
        ],
    },
    {
        "theme": "performance",
        "weight": 9,
        "vi": [
            "{agent} chạy chậm quá, một file 20 trang mất gần 10 phút.",
            "Chờ hơn 5 phút mới ra kết quả, lúc gấp thì gần như không dùng được.",
            "Giờ cao điểm buổi sáng gần như không dùng nổi, cứ quay vòng vòng mãi.",
            "Tốc độ xử lý file lớn chậm hơn hẳn so với tháng trước.",
        ],
        "en": [
            "{agent} is very slow, a 20 page file takes almost 10 minutes.",
            "Response time in the morning is basically unusable.",
            "Processing large files got noticeably slower this month.",
        ],
        "mixed": [],
    },
    {
        "theme": "file_input_limit",
        "weight": 9,
        "vi": [
            "File của mình 60MB, upload lên thì báo vượt giới hạn. Có cách nào tăng không ạ?",
            "Không upload được file {fmt}, hình như chỉ nhận PDF thôi?",
            "PDF scan dạng ảnh thì {agent} đọc không ra chữ nào.",
            "File Excel nhiều sheet thì chỉ đọc được sheet đầu tiên.",
            "Tài liệu hơn 100 trang thì bị cắt giữa chừng, phần sau không được xử lý.",
        ],
        "en": [
            "Upload fails for anything above the size limit, my file is 60MB.",
            "Scanned PDFs are not recognized at all.",
            "Only the first sheet of my Excel workbook gets processed.",
        ],
        "mixed": [],
    },
    {
        "theme": "auth_access",
        "weight": 7,
        "vi": [
            "Mình không đăng nhập được vào TÀI Studio, báo là không có quyền truy cập.",
            "Xin quyền dùng {agent} thì làm thủ tục ở đâu ạ?",
            "Tài khoản mình bị mất quyền dùng {agent} từ tuần trước mà không rõ lý do.",
            "Đăng nhập SSO xong thì bị đá về trang chủ, vào lại vẫn vậy.",
        ],
        "en": [
            "I cannot log in, it says I do not have permission.",
            "How do I request access to {agent}?",
            "SSO redirects me back to the landing page every time.",
        ],
        "mixed": [],
    },
    {
        "theme": "integration",
        "weight": 6,
        "vi": [
            "Có thể tích hợp {agent} với SharePoint để lấy file trực tiếp không?",
            "Mong có nút gửi kết quả sang Teams cho nhanh.",
            "Nếu nối được với Jira để tạo ticket luôn thì tiện lắm.",
            "Có API để gọi {agent} từ hệ thống nội bộ của phòng mình không?",
        ],
        "en": [
            "Any plan to integrate {agent} with SharePoint?",
            "Is there an API so we can call {agent} from our own tools?",
        ],
        "mixed": [],
    },
    {
        "theme": "praise",
        "weight": 8,
        "vi": [
            "{agent} rất hữu ích, tiết kiệm cho mình vài tiếng mỗi tuần. Cảm ơn team!",
            "Bản cập nhật mới nhanh hơn hẳn, cảm ơn team đã lắng nghe phản hồi.",
            "Dùng {agent} soạn bản nháp rồi chỉnh lại, hiệu quả tốt hơn mình nghĩ.",
            "Chất lượng dịch cải thiện rõ so với hồi đầu năm.",
        ],
        "en": [
            "{agent} saves me hours every week, great work.",
            "The latest update feels much faster, thank you.",
            "Translation quality has improved a lot since the start of the year.",
        ],
        "mixed": [],
    },
    {
        "theme": "ui_ux",
        "weight": 7,
        "vi": [
            "Giao diện hơi rối, người mới vào không biết bắt đầu từ đâu.",
            "Nút {feature} nằm khuất quá, mình tìm mãi mới thấy.",
            "Kết quả dài mà không có thanh cuộn riêng, đọc rất mệt.",
            "Nên có chế độ tối cho đỡ mỏi mắt.",
            "Chữ trong ô nhập prompt nhỏ quá, nhìn không rõ.",
        ],
        "en": [
            "The landing page is confusing for a first time user.",
            "The result panel needs its own scrollbar, reading long output is painful.",
            "Please add a dark mode.",
        ],
        "mixed": [],
    },
    {
        "theme": "data_security",
        "weight": 5,
        "vi": [
            "Dữ liệu mình upload có được lưu lại không? Tài liệu nội bộ thì có an toàn không ạ?",
            "Cho hỏi file và feedback có bị dùng để train model không?",
            "Tài liệu mật cấp phòng thì có được phép đưa lên TÀI Studio không?",
        ],
        "en": [
            "Is the uploaded document stored anywhere? These are internal files.",
            "Are our files used for model training?",
        ],
        "mixed": [],
    },
    {
        "theme": "training_support",
        "weight": 5,
        "vi": [
            "Team có tổ chức buổi training dùng TÀI Studio cho phòng mình được không ạ?",
            "Muốn đăng ký buổi demo {agent} cho team khoảng 20 người.",
            "Có video hướng dẫn nào ngắn gọn cho người mới không?",
        ],
        "en": [
            "Could you run a training session for our department?",
            "Is there a short onboarding video for new users?",
        ],
        "mixed": [],
    },
]

# Noise: dòng quá ngắn (Step 1 lọc < 10 ký tự) và dòng lạc đề (dân số unclassified
# tự nhiên ở Step 3). Xem cảnh báo trong plan.md: tỉ trọng này là tham số tôi đặt,
# không phải tính chất của dữ liệu thật.
NOISE_WEIGHT = 12
NOISE_TEXTS = [
    "asdf", "test", "ok", "...", "hay", "good", "N/A", "abc123", "hello",
    "1", "aaaa", "ko có gì", "chưa dùng", ":))", "tốt", "no comment",
    "Wifi tầng 12 yếu quá, họp online hay rớt.",
    "Cho hỏi thủ tục đăng ký nghỉ phép làm ở đâu ạ?",
    "Canteen hết cơm lúc 12h30 rồi.",
    "Máy in tầng 8 kẹt giấy suốt.",
    "Gửi nhầm, bỏ qua giúp mình nhé.",
    "Test thử xem form này có hoạt động không.",
]

# Lớp biến thể bề mặt. Không có nó thì ~90 template sinh ra hàng trăm bản trùng
# chính xác, dedup ở Step 1 ăn mất hơn nửa dữ liệu và không còn đủ 500 dòng sạch.
# "issue" = chủ đề trục trặc, chỉ nhóm này mới gắn thêm câu mô tả bối cảnh.
THEME_KIND = {
    "how_to_usage": "ask", "output_quality": "issue", "error_crash": "issue",
    "feature_request": "ask", "performance": "issue", "file_input_limit": "issue",
    "auth_access": "issue", "integration": "ask", "praise": "other",
    "ui_ux": "ask", "data_security": "ask", "training_support": "ask",
}

OPENERS = {
    "vi": ["Chào team, ", "Team ơi, ", "Cho mình hỏi, ", "Xin chào team, ", "Nhờ team hỗ trợ: "],
    "en": ["Hi team, ", "Hello, ", "Quick question, ", "Hi all, "],
}
CLOSERS = {
    "vi": [" Cảm ơn team!", " Nhờ team hỗ trợ giúp mình nhé.", " Mong team xem giúp ạ.",
           " Cảm ơn nhiều ạ.", " Rất mong sớm nhận được phản hồi."],
    "en": [" Thanks!", " Thank you in advance.", " Appreciate the help.", " Please advise."],
}
CONTEXTS = {
    "vi": [" Mình dùng trên Chrome.", " Tình trạng này bắt đầu từ tuần trước.",
           " Đã thử lại vài lần vẫn vậy.", " Không rõ do máy mình hay do hệ thống.",
           " Mình dùng hằng ngày cho công việc nên khá bất tiện."],
    "en": [" I am on Chrome.", " This started last week.",
           " Tried a few times, same result.", " It happens with every file I try."],
}
# Không hạ chữ hoa đầu câu nếu đó là danh từ riêng.
PROPER_PREFIXES = tuple(a for a, _ in AGENTS) + ("TÀI", "SSO", "PDF", "Excel", "Wifi")

# Pool user sinh máy, pattern giống Techcombank alias (không phải người thật — F9).
_SURNAMES = ["nguyen", "tran", "le", "pham", "hoang", "vu", "dang", "bui", "do", "ngo", "duong", "ly"]
_GIVEN = ["anh", "duong", "thuc", "phuong", "khanh", "linh", "minh", "hai", "trang", "tuan",
          "ngoc", "quang", "thao", "hung", "mai", "son", "chi", "long", "yen", "nam"]


def build_user_pool(rng: random.Random, size: int = 120) -> list[str]:
    """Alias dạng <given><surname-initials><digit?>@techcombank.com.vn, không trùng."""
    pool: set[str] = set()
    while len(pool) < size:
        given = rng.choice(_GIVEN)
        initials = "".join(rng.choice(_SURNAMES)[0] for _ in range(rng.randint(1, 3)))
        suffix = str(rng.randint(1, 40)) if rng.random() < 0.6 else ""
        pool.add(f"{given}{initials}{suffix}@techcombank.com.vn")
    return sorted(pool)


def weighted_pick(rng: random.Random, items: list, weights: list[int]):
    return rng.choices(items, weights=weights, k=1)[0]


def pick_agent(rng: random.Random) -> str:
    return weighted_pick(rng, [a for a, _ in AGENTS], [w for _, w in AGENTS])


def render(rng: random.Random, template: str, agent: str) -> str:
    idx = rng.randrange(len(FEATURES_VI))
    return template.format(
        agent=agent,
        feature=FEATURES_VI[idx],
        feature_en=FEATURES_EN[idx],
        fmt=rng.choice(FORMATS),
    )


def decorate(rng: random.Random, body: str, lang: str, kind: str, agent: str) -> str:
    """Bọc thân feedback bằng opener / bối cảnh / closer / prefix tên agent."""
    if rng.random() < 0.30:
        opener = rng.choice(OPENERS[lang])
        if not body.startswith(PROPER_PREFIXES):
            body = body[0].lower() + body[1:]
        body = opener + body
    if kind == "issue" and rng.random() < 0.35:
        body += rng.choice(CONTEXTS[lang])
    if rng.random() < 0.35:
        body += rng.choice(CLOSERS[lang])
    # kiểu ghi thấy trong feedback thật ở template/ — bỏ qua nếu thân câu đã nhắc tên agent
    if rng.random() < 0.15 and agent not in body:
        body = f"{agent}: {body}"
    return body


def pick_content(rng: random.Random, theme: dict, agent: str) -> str:
    """~62% VI, ~30% EN, ~8% trộn hai thứ tiếng (F4)."""
    roll = rng.random()
    if roll < 0.08 and theme["mixed"]:
        bank, lang = theme["mixed"], "vi"
    elif roll < 0.38 and theme["en"]:
        bank, lang = theme["en"], "en"
    else:
        bank, lang = theme["vi"], "vi"
    body = render(rng, rng.choice(bank), agent)
    return decorate(rng, body, lang, THEME_KIND[theme["theme"]], agent)


def pick_created_at(rng: random.Random) -> datetime:
    """Rải trong WINDOW_DAYS, lệch về ngày trong tuần và giờ hành chính."""
    for _ in range(20):
        day_offset = rng.randrange(WINDOW_DAYS)
        day = (WINDOW_END - timedelta(days=day_offset)).date()
        if day.weekday() >= 5 and rng.random() < 0.85:
            continue  # cuối tuần ít feedback, nhưng không phải là không có
        break
    hour = weighted_pick(
        rng,
        [8, 9, 10, 11, 13, 14, 15, 16, 17, 20, 22],
        [6, 12, 14, 10, 8, 13, 14, 11, 7, 3, 2],
    )
    return datetime(day.year, day.month, day.day, hour, rng.randrange(60))


def generate(n: int, seed: int) -> tuple[list[dict], list[dict]]:
    rng = random.Random(seed)
    users = build_user_pool(rng)
    # vài power user chiếm phần lớn lượt gửi — phân bố thật luôn lệch kiểu này
    user_weights = [rng.randint(6, 14) if i < 12 else rng.randint(1, 4) for i in range(len(users))]

    themes = THEMES + [{"theme": "noise", "weight": NOISE_WEIGHT, "vi": None}]
    theme_weights = [t["weight"] for t in themes]

    n_dup = int(n * DUPLICATE_RATE)
    n_base = n - n_dup

    rows: list[dict] = []
    labels: list[dict] = []

    def emit(content: str, theme: str, agent: str) -> None:
        seq = len(rows) + 1
        rows.append({
            "feedback_id": f"fb_{seq:05d}",
            "user_email": weighted_pick(rng, users, user_weights),
            "agent": agent,
            "content": content,
            "created_at": pick_created_at(rng).isoformat(timespec="seconds"),
        })
        labels.append({"feedback_id": f"fb_{seq:05d}", "latent_theme": theme})

    # Trùng lặp phải là thứ mình cố ý đặt vào (DUPLICATE_RATE) và trùng tự nhiên của
    # dòng rác ("ok", "test"...), không phải hệ quả của bank template hẹp — nếu không,
    # dedup ở Step 1 ăn mất một phần lớn dữ liệu và F3 gãy.
    seen: set[str] = set()
    for _ in range(n_base):
        theme = weighted_pick(rng, themes, theme_weights)
        agent = pick_agent(rng)
        if theme["theme"] == "noise":
            content = rng.choice(NOISE_TEXTS)
        else:
            for _ in range(12):
                content = pick_content(rng, theme, agent)
                if content not in seen:
                    break
            seen.add(content)
        emit(content, theme["theme"], agent)

    # F6 — bản trùng chính xác: cùng content, khác feedback_id/user/thời điểm
    for _ in range(n_dup):
        src_idx = rng.randrange(len(rows))
        emit(rows[src_idx]["content"], labels[src_idx]["latent_theme"], rows[src_idx]["agent"])

    # Đánh lại số sau khi sắp theo thời gian: bảng thật cấp id tăng dần theo lúc gửi.
    order = sorted(range(len(rows)), key=lambda i: rows[i]["created_at"])
    sorted_rows, sorted_labels = [], []
    for seq, i in enumerate(order, start=1):
        fid = f"fb_{seq:05d}"
        sorted_rows.append({**rows[i], "feedback_id": fid})
        sorted_labels.append({**labels[i], "feedback_id": fid})
    return sorted_rows, sorted_labels


def write_outputs(rows: list[dict], labels: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    jsonl = out_dir / "feedback_sample.jsonl"
    with jsonl.open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # utf-8-sig để Excel trên Windows không vỡ dấu tiếng Việt
    csv_path = out_dir / "feedback_sample.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    # Sidecar (D4) — nhãn nhóm sinh máy, CHỈ dùng sanity-check clustering lúc dev.
    # Không phải nhãn tay của Step 7, không được dùng để calibrate ngưỡng.
    labels_path = out_dir / "feedback_sample_labels.jsonl"
    with labels_path.open("w", encoding="utf-8", newline="\n") as f:
        for lab in labels:
            f.write(json.dumps(lab, ensure_ascii=False) + "\n")


def print_audit(rows: list[dict], labels: list[dict]) -> None:
    """Bản pandas-free của câu SQL Step 0, để thấy ngay fixture có hợp lý không."""
    from collections import Counter

    n = len(rows)
    short = sum(1 for r in rows if len(r["content"].strip()) < 10)
    dup = n - len({r["content"] for r in rows})
    noise = sum(1 for lab in labels if lab["latent_theme"] == "noise")
    # số dòng sống sót qua Step 1: dedup exact rồi bỏ dòng < 10 ký tự
    clean = len({c for c in {r["content"] for r in rows} if len(c.strip()) >= 10})

    print(f"rows                : {n}")
    print(f"distinct users      : {len({r['user_email'] for r in rows})}")
    print(f"too_short (<10 ký tự): {short}")
    print(f"exact duplicates    : {dup}")
    print(f"latent noise        : {noise} ({noise / n:.1%})")
    print(f"clean rows (Step 1) : {clean}  ({'≥500, HDBSCAN path' if clean >= 500 else '<500, Direct-LLM path'})")
    print(f"window              : {rows[0]['created_at']} → {rows[-1]['created_at']}")
    print("\nby agent:")
    for agent, cnt in Counter(r["agent"] for r in rows).most_common():
        print(f"  {agent:<20} {cnt:>4}  {cnt / n:>6.1%}")
    print("\nby latent theme (chỉ có trong sidecar, không có ở bảng thật):")
    for theme, cnt in Counter(lab["latent_theme"] for lab in labels).most_common():
        print(f"  {theme:<20} {cnt:>4}  {cnt / n:>6.1%}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("-n", "--rows", type=int, default=DEFAULT_N)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args()

    rows, labels = generate(args.rows, args.seed)
    write_outputs(rows, labels, args.out)
    print(f"Đã ghi {len(rows)} dòng vào {args.out}\n")
    print_audit(rows, labels)


if __name__ == "__main__":
    main()
