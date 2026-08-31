"""Adapter knowledge cho B2 — 2 nguồn cùng một khuôn: snapshot in-memory → whole-content cho LLM → batch.

Module: inference.draft (B2) — nửa RETRIEVE.
Architecture: docs/architecture.md §3 (note Knowledge layer v3.1/v3.2 — whole-content → LLM cho CẢ HAI nguồn),
  §4.2 (Flow B — B2 retrieve theo lô), §4.5 (userguide_page; backlog_ref cột embedding unused).
Impl: docs/impl-phase2-auto-feedback-flow.md §5 (answer_from_kb → userguide; known_gap → backlog).
Plan: docs/2026-08-27/knowledge-layer-batch/plan.md (thống nhất snapshot + whole-content + batch),
  kế thừa docs/2026-08-26/knowledge-retrieval-strategy/plan.md (userguide whole-page).

Hai nhánh — CÙNG khuôn (snapshot một lần/run → nạp cả nội dung cho LLM → trả lời theo lô):
  - userguide (`answer_from_kb`): route `agent → userguide_page`, nạp **cả page** cho LLM sinh câu trả lời
    + cờ `answerable`. `hit=False` (không map page HOẶC answerable=False) ⇒ respond suy giảm we_listen
    (guard impl §3.2, không claim resolved).
  - backlog (`known_gap`, v3.2): nạp **CẢ danh sách backlog** hiện hành cho LLM đối chiếu từng feedback với
    một hạng mục — **bỏ cosine/embedding**. `backlog_ref=null`/index lỗi ⇒ `hit=False` ⇒ ghi nhận chung
    (không hứa nhầm 'team sẽ làm'). Đối xứng gate `answerable` của userguide.

`KnowledgeSnapshot` giữ hai nguồn đã fetch một lần để tái dùng cho mọi feedback trong run.

LƯU Ý lệch kiến trúc (spike): userguide store + backlog list + Haiku qua Databricks Model Serving (reuse
client `reply_scenarios.chat_json`), backlog list qua MCP-Atlassian — thay Vector Search + service principal §5.
Khai báo ở plan §Lệch kiến trúc.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

# src/02_knowledge là "package" script rời (không có __init__) — thêm vào path để import trực tiếp,
# theo đúng convention repo (build_knowledge_layer import cùng kiểu).
_KNOWLEDGE_DIR = Path(__file__).resolve().parents[1] / "02_knowledge"
if str(_KNOWLEDGE_DIR) not in sys.path:
    sys.path.insert(0, str(_KNOWLEDGE_DIR))

from userguide_store import WARN_PAGE_CHARS, UserguidePages  # noqa: E402


@dataclass
class UserguideAnswer:
    hit: bool                    # LLM trả lời được TỪ page không (rag_hit của impl §3.2)
    answer: str                  # câu trả lời văn xuôi (grounded trong page của function)
    page_id: str | None = None   # citation: page_id@version (thay thread_id của bản Scholar)
    version: object = None


@dataclass
class BacklogMatch:
    hit: bool
    jira_key: str | None = None
    summary: str | None = None
    status: str | None = None
    issuetype: str | None = None
    score: float = 0.0           # v3.2: không dùng ở nhánh LLM (giữ field cho respond.py không đổi)


# Batch: 1 call cho K feedback, amortize nội dung (page / danh sách backlog) trên K feedback.
# Feedback lệch mạnh về vài agent ⇒ page/backlog bị nạp lại nhiều lần/run; gom K feedback vào 1 call
# cắt token đi ~K lần. Cap K để LLM không lẫn câu trả lời (sweet spot ~5–8). Serving-agnostic
# (không phụ thuộc prompt caching của Databricks). Mỗi phần tử VẪN có gate riêng (không claim sai).
DEFAULT_BATCH_SIZE = 6


# ── answer_from_kb: route agent→page rồi nạp CẢ PAGE cho LLM ──────────────────
_ANSWER_SYS = (
    "Bạn là trợ lý hỗ trợ người dùng của TÀI Studio. CHỈ được dùng TÀI LIỆU HƯỚNG DẪN đưa ra để trả lời "
    "phản hồi của người dùng — tuyệt đối không bịa thông tin ngoài tài liệu.\n"
    "Nếu tài liệu KHÔNG chứa thông tin đủ để trả lời, đặt answerable=false.\n"
    'Trả về DUY NHẤT một JSON: {"answerable": true|false, "answer": "<hướng dẫn tiếng Việt, ngắn gọn, '
    'theo bước nếu có; rỗng nếu answerable=false>"}.'
)


def _default_llm(feedback: str, title: str, markdown: str) -> dict:
    """Gọi Haiku (reuse client Databricks Model Serving của reply_scenarios). Trả dict {answerable, answer}."""
    from reply_scenarios import chat_json  # reuse OpenAI→Model Serving client (DRY, cùng package)

    user = f"TÀI LIỆU HƯỚNG DẪN — {title}:\n{markdown}\n\nPHẢN HỒI NGƯỜI DÙNG:\n{feedback}"
    data = chat_json(_ANSWER_SYS, user)
    return data if isinstance(data, dict) else {}


def answer_from_userguide(
    feedback: str,
    agent: str,
    pages: UserguidePages,
    *,
    llm=None,
    warn_chars: int = WARN_PAGE_CHARS,
) -> UserguideAnswer:
    """Route `agent → userguide_page` → nạp cả page cho LLM → câu trả lời grounded.

    `hit=False` khi (a) agent không map được page, hoặc (b) LLM báo answerable=False / answer rỗng —
    để respond.py suy giảm về we_listen thay vì claim resolved (guard impl §3.2). `llm` inject được để
    test offline (mặc định gọi Haiku).
    """
    page = pages.get(agent)
    if page is None:
        return UserguideAnswer(hit=False, answer="")

    _warn_if_large(page, warn_chars)
    data = (llm or _default_llm)(feedback, page.title, page.markdown)
    return _to_answer(data, page)


def _warn_if_large(page, warn_chars: int) -> None:
    if len(page.markdown) > warn_chars:        # size-guard (plan §6): page dài → tốn token
        print(
            f"[userguide] page '{page.title}' dài {len(page.markdown)} ký tự (>{warn_chars}) "
            f"— cân nhắc lọc theo heading",
            file=sys.stderr,
        )


def _to_answer(data: dict, page) -> UserguideAnswer:
    answerable = bool(data.get("answerable"))
    answer = (data.get("answer") or "").strip()
    return UserguideAnswer(hit=answerable and bool(answer), answer=answer,
                           page_id=page.page_id, version=page.version)


# ── Batch userguide theo agent: 1 call/page cho K feedback ────────────────────
_ANSWER_BATCH_SYS = (
    "Bạn là trợ lý hỗ trợ người dùng của TÀI Studio. CHỈ được dùng TÀI LIỆU HƯỚNG DẪN đưa ra để trả lời "
    "các phản hồi — tuyệt đối không bịa thông tin ngoài tài liệu.\n"
    "Mỗi phản hồi được đánh số. Trả lời ĐỘC LẬP từng phản hồi, KHÔNG trộn nội dung giữa các phản hồi.\n"
    "Nếu tài liệu KHÔNG đủ thông tin cho một phản hồi, đặt answerable=false cho phản hồi đó.\n"
    'Trả về DUY NHẤT một JSON: {"answers":[{"index":<số thứ tự phản hồi>,"answerable":true|false,'
    '"answer":"<hướng dẫn tiếng Việt ngắn gọn, theo bước nếu có; rỗng nếu answerable=false>"}]}. '
    "Phải có đúng một phần tử cho mỗi index đã cho."
)


def _default_batch_llm(feedbacks: list[str], title: str, markdown: str) -> dict:
    """Gọi Haiku 1 lần cho K feedback cùng page (reuse client reply_scenarios)."""
    from reply_scenarios import chat_json

    listing = "\n".join(f"[{i}] {fb}" for i, fb in enumerate(feedbacks))
    user = f"TÀI LIỆU HƯỚNG DẪN — {title}:\n{markdown}\n\nCÁC PHẢN HỒI NGƯỜI DÙNG:\n{listing}"
    data = chat_json(_ANSWER_BATCH_SYS, user)
    return data if isinstance(data, dict) else {}


def answer_from_userguide_batch(
    feedbacks: list[str],
    agent: str,
    pages: UserguidePages,
    *,
    llm=None,
    warn_chars: int = WARN_PAGE_CHARS,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> list[UserguideAnswer]:
    """K feedback CÙNG agent → nạp page 1 lần cho mỗi lô ≤ `batch_size` → list câu trả lời (theo thứ tự vào).

    Kết quả căn theo `index`; index thiếu/hỏng ⇒ `hit=False` (an toàn: respond suy giảm we_listen). `agent`
    không map được page ⇒ toàn bộ `hit=False`. `llm(feedbacks, title, markdown) -> {"answers":[...]}` inject
    được để test offline (mặc định gọi Haiku theo lô).
    """
    if not feedbacks:
        return []
    page = pages.get(agent)
    if page is None:
        return [UserguideAnswer(hit=False, answer="") for _ in feedbacks]

    _warn_if_large(page, warn_chars)
    call = llm or _default_batch_llm
    out: list[UserguideAnswer] = []
    for start in range(0, len(feedbacks), max(1, batch_size)):
        chunk = feedbacks[start : start + max(1, batch_size)]
        data = call(chunk, page.title, page.markdown)
        by_index = {int(a["index"]): a for a in (data or {}).get("answers", [])
                    if isinstance(a, dict) and "index" in a}
        for i in range(len(chunk)):
            item = by_index.get(i)
            out.append(_to_answer(item, page) if item else UserguideAnswer(hit=False, answer="",
                                                                           page_id=page.page_id,
                                                                           version=page.version))
    return out


# ── known_gap (v3.2): nạp CẢ danh sách backlog cho LLM đối chiếu theo lô ───────
# Bỏ cosine/embedding (BacklogIndex cũ): backlog nhỏ (~chục issue) nên nạp cả danh sách vào prompt,
# để LLM tự đối chiếu từng feedback với một hạng mục — đối xứng userguide whole-page. LLM chỉ trả
# `backlog_ref` (chỉ số hạng mục), ta TỰ resolve field từ danh sách (không tin LLM echo → chống bịa).
WARN_BACKLOG_CHARS = 24_000

_BACKLOG_BATCH_SYS = (
    "Bạn đối chiếu phản hồi người dùng với BACKLOG hiện hành của team TÀI Studio.\n"
    "Mỗi hạng mục backlog được đánh số [B<j>]. Mỗi phản hồi cũng được đánh số.\n"
    "Với TỪNG phản hồi, chọn ĐÚNG MỘT hạng mục backlog THỰC SỰ là tính năng/việc mà phản hồi đề cập "
    "(không chỉ trùng từ ngữ chung chung mà khác bản chất). Nếu KHÔNG hạng mục nào khớp thật, đặt "
    "backlog_ref=null.\n"
    'Trả về DUY NHẤT một JSON: {"matches":[{"index":<số phản hồi>,"backlog_ref":<số j của [B<j>] hoặc '
    'null>}]}. Phải có đúng một phần tử cho mỗi index đã cho.'
)


def _backlog_listing(items: list[dict]) -> str:
    """Danh sách backlog đánh số [B<j>] (summary — status + description) để nạp vào prompt."""
    lines: list[str] = []
    for j, it in enumerate(items):
        head = f"[B{j}] {(it.get('summary') or '').strip()}"
        if it.get("status"):
            head += f" — {it['status']}"
        desc = (it.get("description") or "").strip()
        if desc:
            head += f"\n    {desc}"
        lines.append(head)
    return "\n".join(lines)


def _default_batch_backlog_llm(feedbacks: list[str], backlog_items: list[dict]) -> dict:
    """Gọi Haiku 1 lần cho K feedback trên CẢ danh sách backlog (reuse client reply_scenarios)."""
    from reply_scenarios import chat_json

    fb_listing = "\n".join(f"[{i}] {fb}" for i, fb in enumerate(feedbacks))
    user = (f"BACKLOG HIỆN HÀNH:\n{_backlog_listing(backlog_items)}\n\n"
            f"CÁC PHẢN HỒI NGƯỜI DÙNG:\n{fb_listing}")
    data = chat_json(_BACKLOG_BATCH_SYS, user)
    return data if isinstance(data, dict) else {}


def answer_from_backlog_batch(
    feedbacks: list[str],
    backlog_items: list[dict],
    *,
    llm=None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    warn_chars: int = WARN_BACKLOG_CHARS,
) -> list[BacklogMatch]:
    """K feedback → nạp CẢ danh sách backlog cho mỗi lô ≤ `batch_size` → list BacklogMatch (theo thứ tự vào).

    LLM trả `backlog_ref` (chỉ số hạng mục trong danh sách đã cho); ta TỰ tra `backlog_items[ref]` để lấy
    jira_key/status (không tin LLM echo field). `backlog_ref=null` / index thiếu / ngoài phạm vi ⇒ `hit=False`
    (an toàn: respond ghi nhận chung, không hứa mốc). `backlog_items` rỗng ⇒ toàn bộ `hit=False`.
    `llm(feedbacks, backlog_items) -> {"matches":[...]}` inject được để test offline (mặc định gọi Haiku).
    """
    if not feedbacks:
        return []
    if not backlog_items:
        return [BacklogMatch(hit=False) for _ in feedbacks]

    _warn_if_backlog_large(backlog_items, warn_chars)
    call = llm or _default_batch_backlog_llm
    out: list[BacklogMatch] = []
    for start in range(0, len(feedbacks), max(1, batch_size)):
        chunk = feedbacks[start : start + max(1, batch_size)]
        data = call(chunk, backlog_items)
        by_index = {int(m["index"]): m for m in (data or {}).get("matches", [])
                    if isinstance(m, dict) and "index" in m}
        for i in range(len(chunk)):
            out.append(_resolve_backlog_match(by_index.get(i), backlog_items))
    return out


def _resolve_backlog_match(match: dict | None, backlog_items: list[dict]) -> BacklogMatch:
    """Tra `backlog_ref` về hạng mục thật. Mọi giá trị không hợp lệ ⇒ hit=False (an toàn)."""
    if not match:
        return BacklogMatch(hit=False)
    ref = match.get("backlog_ref")
    if ref is None:
        return BacklogMatch(hit=False)
    try:
        j = int(ref)
    except (TypeError, ValueError):
        return BacklogMatch(hit=False)
    if not 0 <= j < len(backlog_items):
        return BacklogMatch(hit=False)
    it = backlog_items[j]
    return BacklogMatch(hit=True, jira_key=it.get("jira_key"), summary=it.get("summary"),
                        status=it.get("status"), issuetype=it.get("issuetype"))


def _warn_if_backlog_large(items: list[dict], warn_chars: int) -> None:
    total = sum(len(str(it.get("summary", ""))) + len(str(it.get("description", ""))) for it in items)
    if total > warn_chars:
        print(
            f"[backlog] danh sách backlog dài {total} ký tự (>{warn_chars}) — cân nhắc tiền lọc JQL "
            f"(theo agent/keyword) thay vì nạp cả danh sách",
            file=sys.stderr,
        )


# ── Snapshot in-memory (một lần/run) ──────────────────────────────────────────
# Fetch userguide + backlog MỘT LẦN đầu run, giữ trong object, tái dùng cho mọi feedback (plan §3).
BACKLOG_NAME_FILTER = "Tai Studio"


@dataclass
class KnowledgeSnapshot:
    userguide_pages: UserguidePages | None = None
    backlog_items: list[dict] = field(default_factory=list)


def _fetch_backlog_items(name_filter: str = BACKLOG_NAME_FILTER) -> list[dict]:
    """Kéo TOÀN BỘ backlog hiện hành (open, non-Done, sprint EMPTY) qua MCP-Atlassian (spike)."""
    import mcp_atlassian_call as mcp  # tên file thật (tránh phụ thuộc .pyc `mcp_atlassian_test` cũ)

    return mcp.fetch_backlog(name_filter=name_filter)


def build_snapshot(
    userguide_pages: UserguidePages | None,
    *,
    backlog_filter: str = BACKLOG_NAME_FILTER,
    fetch_backlog=None,
) -> KnowledgeSnapshot:
    """Dựng snapshot in-memory: gắn userguide pages đã nạp + fetch backlog MỘT LẦN.

    `fetch_backlog(name_filter) -> list[dict]` inject được để test offline (mặc định kéo qua MCP).
    """
    getter = fetch_backlog or _fetch_backlog_items
    return KnowledgeSnapshot(userguide_pages=userguide_pages, backlog_items=getter(backlog_filter))
