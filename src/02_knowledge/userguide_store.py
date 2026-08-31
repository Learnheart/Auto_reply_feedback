"""Knowledge layer (userguide) — định tuyến agent → NGUYÊN page, KHÔNG chunk/embed.

Module: ingest-sync (Job A) — nửa userguide.
Architecture: docs/architecture.md §3 (note Knowledge layer v3.1 — thay Vector Search),
  §4.5 (bảng userguide_page), §4.2 (B2 route agent→page).
Plan: docs/2026-08-26/knowledge-retrieval-strategy/plan.md
Data contract (§4.5): userguide_page(agent PK, page_id, version, title, markdown, last_modified, synced_at)

Map agent→page DẪN XUẤT bằng khớp slug(title): page con userguide đặt tên theo agent
(mcp_atlassian_test §309 "mỗi agent 1 page con"). Hệ quả: function MỚI = thêm 1 page đặt tên
theo agent ⇒ tự route, KHÔNG phải sửa map. Override chỉ cho ngoại lệ (tai/tai-studio = nền tảng,
không phải 1 function → trỏ page root/overview).
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

# agent mức nền tảng (không phải 1 function riêng) → dùng page root/overview.
PLATFORM_AGENTS = {"tai", "tai-studio"}
# ngoại lệ khi quy ước đặt tên page KHÔNG khớp slug(agent): slug(agent) -> slug(title). Điền khi phát hiện.
AGENT_TITLE_OVERRIDES: dict[str, str] = {}

# ngưỡng cảnh báo page dài (plan §6): whole-page vào context LLM, page quá lớn ⇒ tốn token.
WARN_PAGE_CHARS = 24_000

# store spike (JSON) — Job A ghi, B2/pipeline đọc. Prod: bảng Delta userguide_page (§4.5).
DEFAULT_STORE_PATH = Path(__file__).resolve().parent / "out" / "userguide_store.json"


def slugify(s: str) -> str:
    """Khoá so khớp agent↔title: bỏ dấu, lowercase, chỉ giữ [a-z0-9], bỏ tiền tố 'the'.

    'the-powerpoint-er' → 'powerpointer' ; 'The PowerPoint-er' → 'powerpointer' (khớp).
    """
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z0-9]+", "", s)
    if s.startswith("the") and len(s) > 3:
        s = s[3:]
    return s


@dataclass
class UserguidePage:
    agent: str          # slug agent (khoá) — vd 'powerpointer'; root: '' (rỗng)
    page_id: str
    version: object
    title: str
    markdown: str
    last_modified: object = None
    synced_at: str | None = None


class UserguidePages:
    """Store userguide_page đã dựng: tra `agent → page` (nguyên page). Không embed, không chunk."""

    def __init__(self, pages: list[UserguidePage], root_page_id: str):
        self.root_page_id = str(root_page_id)
        self.by_slug: dict[str, UserguidePage] = {}
        self.root: UserguidePage | None = None
        for p in pages:
            if str(p.page_id) == self.root_page_id:
                self.root = p
            if p.agent:                       # bỏ root (agent rỗng) khỏi index function
                self.by_slug[p.agent] = p

    def get(self, agent: str) -> UserguidePage | None:
        """agent (giá trị thô từ feedback) → page. None ⇒ B2 coi như không có tài liệu ⇒ we_listen."""
        raw = (agent or "").strip().lower()
        if raw in PLATFORM_AGENTS:
            return self.root
        slug = slugify(agent)
        slug = AGENT_TITLE_OVERRIDES.get(slug, slug)
        page = self.by_slug.get(slug)
        if page is not None:
            return page
        return None                            # không map được: KHÔNG đoán bừa page khác

    # ── persist (spike: JSON; prod: Delta userguide_page) ────────────────────
    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "root_page_id": self.root_page_id,
            "synced_at": datetime.now().isoformat(timespec="seconds"),
            "pages": [asdict(p) for p in self._all()],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _all(self) -> list[UserguidePage]:
        seen: dict[str, UserguidePage] = {}
        if self.root is not None:
            seen[str(self.root.page_id)] = self.root
        for p in self.by_slug.values():
            seen[str(p.page_id)] = p
        return list(seen.values())

    @classmethod
    def load(cls, path: Path) -> "UserguidePages":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        pages = [UserguidePage(**row) for row in payload.get("pages", [])]
        return cls(pages, payload.get("root_page_id", ""))


def build_from_confluence_pages(raw_pages: list[dict], root_page_id: str) -> UserguidePages:
    """list dict từ mcp.fetch_userguide (page_id,title,version,markdown,...) → UserguidePages.

    agent-slug = slug(title); page root (page_id==root) giữ riêng làm overview cho agent nền tảng.
    """
    now = datetime.now().isoformat(timespec="seconds")
    out: list[UserguidePage] = []
    for p in raw_pages:
        pid = str(p.get("page_id", ""))
        title = p.get("title", "")
        agent_slug = "" if pid == str(root_page_id) else slugify(title)
        out.append(
            UserguidePage(
                agent=agent_slug,
                page_id=pid,
                version=p.get("version"),
                title=title,
                markdown=p.get("markdown", "") or "",
                last_modified=p.get("last_modified") or p.get("lastModifiedDateTime"),
                synced_at=now,
            )
        )
    return UserguidePages(out, root_page_id)


def coverage_report(pages: UserguidePages, agent_values: list[str]) -> tuple[list[str], list[str]]:
    """Đối chiếu tập agent (từ feedback) với map. Trả (matched, unmatched) — K-1 acceptance."""
    matched, unmatched = [], []
    for a in sorted(set(agent_values)):
        (matched if pages.get(a) is not None else unmatched).append(a)
    return matched, unmatched


def warn_large_pages(pages: UserguidePages, limit: int = WARN_PAGE_CHARS) -> None:
    """Size-guard (plan §6): log page vượt ngưỡng để cân nhắc lọc theo heading."""
    for p in pages._all():
        if len(p.markdown) > limit:
            print(
                f"[userguide] page '{p.title}' dài {len(p.markdown)} ký tự (>{limit}) "
                f"— cân nhắc lọc theo heading H2 thay vì nạp cả page",
                file=sys.stderr,
            )
