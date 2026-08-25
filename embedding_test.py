"""
Exemplar-based intent matching cho feedback in-app.

Thiết kế theo đúng các quyết định đã chốt:
  - Embed EXEMPLAR, không embed mô tả nhãn  -> hai vế cùng phân phối
  - Symmetric: KHÔNG dùng instruct prefix ở bất kỳ vế nào
  - Cùng một hàm normalize() cho lúc index và lúc inference
  - Tách mệnh đề -> multi-label tự nhiên
  - Ngưỡng theo từng nhãn -> fallback UNKNOWN thay vì ép argmax

Model: text-embedding-qwen3-embedding-0.6b (last-token pooling), phục vụ qua LM Studio
       (OpenAI-compatible endpoint http://localhost:1234/v1, L2-normalize phía client)
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import numpy as np

# ---------------------------------------------------------------- normalize --

_TONE_FIX = {
    "oà": "òa", "oá": "óa", "oả": "ỏa", "oã": "õa", "oạ": "ọa",
    "uý": "úy", "uỳ": "ùy", "uỷ": "ủy", "uỹ": "ũy", "uỵ": "ụy",
}
_URL = re.compile(r"https?://\S+|www\.\S+")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.\w+\b")
_LONGNUM = re.compile(r"\b\d{6,}\b")
_REPEAT = re.compile(r"(.)\1{2,}")
_WS = re.compile(r"\s+")
_TAIL_JUNK = re.compile(r"[\s\u200b]*[\U0001F300-\U0001FAFF\u2600-\u27BF]{2,}\s*$")


def normalize(text: str) -> str:
    """Chuẩn hóa text trước khi embed. Dùng CHUNG cho exemplar và input."""
    t = unicodedata.normalize("NFC", text or "")
    for a, b in _TONE_FIX.items():
        t = t.replace(a, b)
    # caps check tính trên chữ cái, và làm TRƯỚC khi chèn placeholder
    letters = [c for c in t if c.isalpha()]
    if len(letters) > 15 and sum(c.isupper() for c in letters) / len(letters) > 0.7:
        t = t.lower()
    t = _URL.sub("[URL]", t)
    t = _EMAIL.sub("[EMAIL]", t)
    t = _LONGNUM.sub("[MADON]", t)
    t = _REPEAT.sub(r"\1\1", t)          # lagggggg -> lagg, !!!!! -> !!
    t = _TAIL_JUNK.sub("", t)            # last-token pooling nhạy với đuôi
    return _WS.sub(" ", t).strip()


# ------------------------------------------------------------- clause split --

_CLAUSE_SPLIT = re.compile(
    r"(?:[.!?;\n]+)|(?:\s+(?:nhưng|nhung|mà|tuy nhiên|tuy nhien|có điều|co dieu|"
    r"ngoài ra|ngoai ra|còn|con|thêm nữa|them nua|but)\s+)",
    flags=re.IGNORECASE,
)
MIN_CLAUSE_CHARS = 8
SPLIT_ABOVE_CHARS = 60


def split_clauses(text: str) -> list[str]:
    """Feedback dài -> tách mệnh đề. Ngắn -> giữ nguyên (tách sẽ mất ngữ cảnh)."""
    if len(text) <= SPLIT_ABOVE_CHARS:
        return [text]
    parts = [p.strip() for p in _CLAUSE_SPLIT.split(text) if p and p.strip()]
    parts = [p for p in parts if len(p) >= MIN_CLAUSE_CHARS]
    return parts or [text]


# ------------------------------------------------------------------ schema  --

@dataclass
class Intent:
    id: str
    display_name: str
    description: str          # KHÔNG embed - dùng cho prompt LLM / CS đọc
    exemplars: list[str]      # chỉ phần này đi vào index
    threshold: float = 0.60   # calibrate riêng từng nhãn trên tập dev
    route: str = "B_known"    # A_template | B_known | C_llm | D_human
    risk: str = "low"


@dataclass
class IntentHit:
    intent_id: str
    display_name: str
    score: float
    route: str
    risk: str
    evidence: str             # mệnh đề nào kích hoạt nhãn này
    nearest_exemplar: str


@dataclass
class MatchResult:
    text: str
    hits: list[IntentHit] = field(default_factory=list)
    clauses: list[str] = field(default_factory=list)

    @property
    def is_unknown(self) -> bool:
        return not self.hits

    @property
    def top(self) -> IntentHit | None:
        return self.hits[0] if self.hits else None

    @property
    def route(self) -> str:
        """Route thận trọng nhất trong các nhãn trúng."""
        if not self.hits:
            return "C_llm"
        order = {"D_human": 3, "C_llm": 2, "B_known": 1, "A_template": 0}
        return max((h.route for h in self.hits), key=lambda r: order.get(r, 2))


# ------------------------------------------------------------------ encoder --

class LMStudioEncoder:
    """Wrapper mỏng quanh embedding model đang host trên LM Studio.

    Gọi qua endpoint OpenAI-compatible (/v1/embeddings).
    Symmetric matching -> KHÔNG prefix task ("search_query:", "search_document:")
    ở cả hai vế. Nếu muốn thử prefix, phải bọc CẢ exemplar lẫn input cùng chuỗi.
    """

    def __init__(
        self,
        model_name: str = "text-embedding-qwen3-embedding-0.6b",
        base_url: str = "http://localhost:1234/v1",
        api_key: str = "lm-studio",     # LM Studio không kiểm tra, chỉ cần khác rỗng
        dim: int | None = None,         # MRL: cắt chiều (256/512) nếu cần index gọn
        timeout: float = 120.0,
    ):
        from openai import OpenAI       # lazy import

        self.model_name = model_name
        self.dim = dim
        self.client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)

    def encode(self, texts: Sequence[str], batch_size: int = 32) -> np.ndarray:
        texts = list(texts)
        out: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            chunk = texts[i : i + batch_size]
            resp = self.client.embeddings.create(model=self.model_name, input=chunk)
            out.extend(d.embedding for d in sorted(resp.data, key=lambda d: d.index))

        vecs = np.asarray(out, dtype=np.float32)
        if self.dim:                                  # MRL truncate rồi mới norm lại
            vecs = vecs[:, : self.dim]
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        return vecs / np.clip(norms, 1e-12, None)     # L2-normalize -> dot == cosine


# ------------------------------------------------------------------ matcher --

class IntentMatcher:
    def __init__(
        self,
        intents: Iterable[Intent],
        encoder,
        top_k: int = 5,
        margin: float = 0.04,     # nhãn phụ phải nằm trong margin của nhãn top
        max_labels: int = 3,
    ):
        self.intents = {i.id: i for i in intents}
        self.encoder = encoder
        self.top_k = top_k
        self.margin = margin
        self.max_labels = max_labels
        self._build_index()

    def _build_index(self) -> None:
        texts, owners, raws = [], [], []
        for intent in self.intents.values():
            for ex in intent.exemplars:
                norm = normalize(ex)
                if norm:
                    texts.append(norm)
                    owners.append(intent.id)
                    raws.append(ex)
        if not texts:
            raise ValueError("Không có exemplar nào để index.")
        self.matrix = self.encoder.encode(texts)          # (N, D), đã L2-norm
        self.owners = np.array(owners)
        self.raw_exemplars = raws

    # -- API chính ----------------------------------------------------------

    def match(self, feedback: str) -> MatchResult:
        """Nhận feedback thô -> trả về các intent trúng + route."""
        clean = normalize(feedback)
        if not clean:
            return MatchResult(text=feedback)

        clauses = split_clauses(clean)
        vecs = self.encoder.encode(clauses)               # (C, D)
        sims = vecs @ self.matrix.T                       # (C, N) cosine

        # best score + evidence cho từng intent, gộp qua mọi mệnh đề
        best: dict[str, tuple[float, int, str]] = {}
        for ci, row in enumerate(sims):
            k = min(self.top_k, row.shape[0])
            top_idx = np.argpartition(-row, k - 1)[:k]
            for idx in top_idx:
                iid = str(self.owners[idx])
                score = float(row[idx])
                if iid not in best or score > best[iid][0]:
                    best[iid] = (score, int(idx), clauses[ci])

        # lọc theo ngưỡng riêng của từng nhãn
        hits = [
            IntentHit(
                intent_id=str(iid),
                display_name=self.intents[iid].display_name,
                score=round(score, 4),
                route=self.intents[iid].route,
                risk=self.intents[iid].risk,
                evidence=evidence,
                nearest_exemplar=self.raw_exemplars[idx],
            )
            for iid, (score, idx, evidence) in best.items()
            if score >= self.intents[iid].threshold
        ]
        hits.sort(key=lambda h: h.score, reverse=True)

        # multi-label: chỉ giữ nhãn phụ đủ gần nhãn top, hoặc đến từ mệnh đề khác
        if hits:
            top = hits[0]
            hits = [
                h for h in hits
                if h is top
                or h.score >= top.score - self.margin
                or h.evidence != top.evidence
            ][: self.max_labels]

        return MatchResult(text=feedback, hits=hits, clauses=clauses)


# ----------------------------------------------------------------- taxonomy --
# Exemplar viết đúng giọng người dùng thật: viết tắt, không dấu, sai chính tả.

INTENTS: list[Intent] = [
    Intent(
        id="BUG_CRASH",
        display_name="Lỗi / crash ứng dụng",
        description="Người dùng báo app bị văng, treo, đứng hình hoặc không mở được.",
        threshold=0.58, route="B_known", risk="medium",
        exemplars=[
            "app cứ mở tab cá nhân là văng ra ngoài",
            "vào đc 2s r out",
            "mở lên màn hình trắng xoá luôn",
            "bấm vào mục thông báo là đơ ko làm gì đc",
            "cứ update xong là ko vào đc nữa",
            "app bi crash lien tuc tren android",
            "treo máy phải tắt đi mở lại",
            "app dung hinh khong bam duoc gi",
            "vừa mở đã tự thoát",
            "lỗi liên tục mấy hôm nay ko dùng đc",
        ],
    ),
    Intent(
        id="BUG_LOGIN",
        display_name="Lỗi đăng nhập / tài khoản",
        description="Không đăng nhập được, OTP không về, bị đăng xuất, quên mật khẩu.",
        threshold=0.58, route="B_known", risk="medium",
        exemplars=[
            "đăng nhập bằng google toàn báo lỗi",
            "ko nhận đc mã otp",
            "nhap dung mat khau ma van bao sai",
            "tự nhiên bị đăng xuất suốt",
            "quên mk mà bấm khôi phục ko thấy mail",
            "login hoài không vào được tài khoản",
            "xác thực số điện thoại mãi ko xong",
            "tk cua toi bi khoa ma khong biet ly do",
            "đăng ký xong ko đăng nhập đc",
        ],
    ),
    Intent(
        id="PAYMENT_ISSUE",
        display_name="Sự cố thanh toán",
        description="Trừ tiền nhưng không ghi nhận, thanh toán thất bại, sai số tiền.",
        threshold=0.60, route="D_human", risk="high",
        exemplars=[
            "trừ tiền rồi mà đơn ko lên",
            "thanh toán thất bại nhưng tk vẫn bị trừ",
            "bi tru tien 2 lan cho 1 don",
            "chuyển khoản xong ko thấy cộng vào ví",
            "mua goi premium ma khong duoc kich hoat",
            "thẻ của tôi bị trừ mà app báo lỗi",
            "nạp tiền cả tiếng vẫn chưa vào",
            "sao tính phí cao hơn giá hiển thị vậy",
        ],
    ),
    Intent(
        id="REFUND_REQUEST",
        display_name="Yêu cầu hoàn tiền / hủy gói",
        description="Đòi hoàn tiền, hủy đăng ký, khiếu nại về việc bị tính phí.",
        threshold=0.60, route="D_human", risk="high",
        exemplars=[
            "tôi muốn hoàn lại tiền",
            "cho minh huy goi va tra lai tien",
            "hủy đăng ký tự động gia hạn giúp t",
            "đòi lại tiền chứ dùng ko đc gì",
            "yêu cầu refund trong hôm nay",
            "khong dung nua muon lay lai phi",
            "tự động trừ tiền gia hạn mà tôi ko đồng ý",
        ],
    ),
    Intent(
        id="PERF_SLOW",
        display_name="Chậm / giật lag / hao pin",
        description="App tải chậm, giật, tốn pin, tốn dung lượng, nóng máy.",
        threshold=0.58, route="B_known", risk="low",
        exemplars=[
            "app lag kinh khủng",
            "load mãi mới ra",
            "cham nhu rua bo",
            "dùng tí là nóng máy tụt pin",
            "app nang qua chiem het bo nho",
            "cuộn feed bị giật giật khó chịu",
            "mở ảnh lên đợi cả phút",
            "tốn pin quá trời",
        ],
    ),
    Intent(
        id="UX_COMPLAINT",
        display_name="Phàn nàn giao diện / trải nghiệm",
        description="Chê thiết kế, khó dùng, khó tìm chức năng, phàn nàn bản cập nhật.",
        threshold=0.58, route="B_known", risk="low",
        exemplars=[
            "giao diện mới rối quá tìm ko thấy gì",
            "update xong xấu hơn hồi trước",
            "chu nho qua doc khong noi",
            "nút bấm để đâu mà tìm mãi",
            "kho dung, nguoi gia khong biet xai",
            "quảng cáo nhiều quá che hết màn hình",
            "sao bỏ mất chức năng cũ vậy",
            "màu mè khó nhìn",
        ],
    ),
    Intent(
        id="FEATURE_REQUEST",
        display_name="Đề xuất tính năng",
        description="Mong muốn thêm chức năng, cải tiến, hỗ trợ nền tảng mới.",
        threshold=0.58, route="A_template", risk="low",
        exemplars=[
            "mong app thêm dark mode",
            "nen co tinh nang luu ve may",
            "ước gì có thể lọc theo ngày",
            "add thêm thanh toán momo đi ad",
            "hy vong ho tro tieng anh",
            "cho mình xin tính năng tìm kiếm nâng cao",
            "nếu có bản cho ipad thì tuyệt",
            "de xuat them thong bao nhac nho",
        ],
    ),
    Intent(
        id="PRAISE",
        display_name="Khen / phản hồi tích cực",
        description="Người dùng hài lòng, khen app, cảm ơn đội ngũ.",
        threshold=0.58, route="A_template", risk="low",
        exemplars=[
            "app xài ổn lắm",
            "dung rat tien loi cam on team",
            "5 sao nhé quá tuyệt vời",
            "bản update này mượt hẳn",
            "app tot nhat minh tung dung",
            "giao diện đẹp dễ dùng",
            "cảm ơn shop đã hỗ trợ nhanh",
            "rat hai long",
        ],
    ),
]


# --------------------------------------------------------------------- demo --

if __name__ == "__main__":
    encoder = LMStudioEncoder()             # qwen3-embedding-0.6b qua LM Studio
    matcher = IntentMatcher(INTENTS, encoder)

    samples = [
        "giao diện mới nhìn đẹp đấy nhưng đăng nhập bằng google toàn fail",
        "app cu mo len la vang ra, lag vcl",
        "trừ tiền r mà ko thấy đơn đâu, cho t xin lại tiền",
        "mong ad thêm chế độ nền tối với ạ",
        "thời tiết hôm nay đẹp nhỉ",
    ]

    for s in samples:
        r = matcher.match(s)
        print(f"\n> {s}")
        print(f"  route: {r.route}   clauses: {r.clauses}")
        if r.is_unknown:
            print("  -> UNKNOWN (escalate)")
        for h in r.hits:
            print(f"  - {h.intent_id:<16} {h.score:.3f}  «{h.evidence}»")