"""Job A (ingest-sync) — loader guideline OFFLINE: `data/guidelines/*.docx` → store `userguide_page`.

Module: ingest-sync (Job A) — nguồn thay thế Confluence cho dev/eval.
Architecture: docs/architecture.md §3 (KNOWLEDGE STORE whole-content, `userguide_page[agent]`),
              §4.6 (contract `userguide_page(agent PK, page_id, version, title, markdown, ...)`),
              §5 (Knowledge store: whole-content → LLM, KHÔNG chunk/embed/index), §6.1 R6.
Plan: docs/2026-09-03/guideline-resolve-batch/plan.md (D3 map agent→doc viết tay, D4 loader docx)

docx → markdown giữ heading (#/##/###) + bảng (hàng `|`), nguyên văn để B2 trích dẫn được
(gate quote verbatim). `version` = dòng "Last updated: ..." trong file, không có thì hash nội dung.

Map agent → page: slug(title) như `userguide_store.slugify`; ngoại lệ viết tay (D3):
  tai        → TÀI (Super Agent) + TÀI Studio — User guide (overview) + TÀI Studio GenUI + Office 365
  tai-studio → TÀI Studio — User guide (overview) + TÀI Studio GenUI
  the-canvas-designer → KHÔNG có tài liệu ⇒ B2 coi là không khớp (rơi xuống bước 2 §4.4)

Chạy:
  python src/02_knowledge/guideline_docx.py --dump out/guidelines_dump.md   # bản đọc cho người
  python src/02_knowledge/guideline_docx.py --save                           # out/guideline_store.json
"""
from __future__ import annotations

import hashlib
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from userguide_store import UserguidePage, UserguidePages, slugify  # cùng thư mục

_HERE = Path(__file__).resolve()
REPO_ROOT = _HERE.parents[2]
GUIDELINES_DIR = REPO_ROOT / "data" / "guidelines"
DEFAULT_STORE_PATH = _HERE.parent / "out" / "guideline_store.json"

# slug(title) của page cho agent nền tảng — thứ tự = thứ tự nạp vào prompt (D3)
PLATFORM_DOC_MAP: dict[str, tuple[str, ...]] = {
    # GenUI mô tả chính giao diện chat của TÀI (composer, @mention, token meter, toggle EN/VI)
    # ⇒ thuộc `tai` (adjudication gold 2026-09-03: 4 dòng `tai` có câu trả lời nằm ở GenUI).
    "tai": ("taisuperagent", "taistudiouserguide", "taistudiogenui", "office365en"),
    "tai-studio": ("taistudiouserguide", "taistudiogenui"),
}
_TITLE_PREFIX = re.compile(r"^\s*user\s+guide\s*[—–-]\s*", re.IGNORECASE)
_LAST_UPDATED = re.compile(r"last\s+updated\s*:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", re.IGNORECASE)


def _title_from_filename(path: Path) -> str:
    """'User Guide — The Powerpoint-er.docx' → 'The Powerpoint-er'; 'TÀI Studio — User guide' giữ nguyên."""
    stem = path.stem
    return _TITLE_PREFIX.sub("", stem).strip()


def _iter_blocks(doc):
    """Duyệt body theo đúng thứ tự paragraph/table (python-docx tách 2 list riêng)."""
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            yield Paragraph(child, doc)
        elif tag == "tbl":
            yield Table(child, doc)


def docx_to_markdown(path: Path) -> str:
    import docx  # python-docx — lazy: chỉ Job A cần

    d = docx.Document(str(path))
    lines: list[str] = []
    for blk in _iter_blocks(d):
        if blk.__class__.__name__ == "Table":
            rows = []
            for row in blk.rows:
                cells = [" ".join(c.text.split()) for c in row.cells]
                # bỏ ô trùng do merge ngang
                dedup: list[str] = []
                for c in cells:
                    if not dedup or dedup[-1] != c:
                        dedup.append(c)
                if any(dedup):
                    rows.append("| " + " | ".join(dedup) + " |")
            if rows:
                lines.extend(rows)
                lines.append("")
            continue
        text = " ".join(blk.text.split())
        if not text:
            continue
        style = (blk.style.name if blk.style is not None else "") or ""
        m = re.match(r"heading\s*(\d)", style, re.IGNORECASE)
        if m:
            lvl = min(int(m.group(1)), 4)
            lines.append("#" * lvl + " " + text)
        elif style.lower().startswith("title"):
            lines.append("# " + text)
        elif "list" in style.lower():
            lines.append("- " + text)
        else:
            lines.append(text)
    return "\n".join(lines).strip() + "\n"


@dataclass
class Section:
    heading: str   # heading gần nhất phía trên (chuỗi đầy đủ, vd "Limitations")
    text: str


def split_sections(markdown: str) -> list[Section]:
    """Cắt theo heading để B2 dựng `source_ref = page@version#heading` khi quote khớp."""
    out: list[Section] = []
    cur_head, buf = "", []
    for line in markdown.splitlines():
        if line.startswith("#"):
            if buf:
                out.append(Section(cur_head, "\n".join(buf)))
            cur_head, buf = line.lstrip("#").strip(), [line]
        else:
            buf.append(line)
    if buf:
        out.append(Section(cur_head, "\n".join(buf)))
    return out


def load_guidelines(gdir: Path = GUIDELINES_DIR) -> UserguidePages:
    """13 docx → UserguidePages (contract §4.6). page_id = 'docx:<slug>'."""
    now = datetime.now().isoformat(timespec="seconds")
    pages: list[UserguidePage] = []
    for path in sorted(gdir.glob("*.docx")):
        if path.name.startswith("~$"):
            continue
        title = _title_from_filename(path)
        md = docx_to_markdown(path)
        m = _LAST_UPDATED.search(md)
        version = m.group(1) if m else "sha:" + hashlib.blake2b(md.encode(), digest_size=6).hexdigest()
        slug = slugify(title)
        pages.append(UserguidePage(agent=slug, page_id=f"docx:{slug}", version=version, title=title,
                                   markdown=md, last_modified=m.group(1) if m else None, synced_at=now))
    return UserguidePages(pages, root_page_id="")


def pages_for_agent(pages: UserguidePages, agent: str) -> list[UserguidePage]:
    """Tài liệu nạp cho một agent (D3). [] ⇒ không có tài liệu ⇒ solved=False cho cả lô."""
    raw = (agent or "").strip().lower()
    if raw in PLATFORM_DOC_MAP:
        return [p for s in PLATFORM_DOC_MAP[raw] if (p := pages.by_slug.get(s)) is not None]
    page = pages.by_slug.get(slugify(agent))
    return [page] if page is not None else []


def dump_markdown(pages: UserguidePages, out_md: Path) -> None:
    parts = []
    for p in sorted(pages.by_slug.values(), key=lambda x: x.title):
        parts.append(f"\n\n<!-- ===== PAGE {p.page_id} | title: {p.title} | version: {p.version} ===== -->\n\n{p.markdown}")
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("".join(parts).strip() + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    pages = load_guidelines()
    print(f"{len(pages.by_slug)} page từ {GUIDELINES_DIR.relative_to(REPO_ROOT)}:")
    for p in sorted(pages.by_slug.values(), key=lambda x: x.title):
        print(f"  {p.page_id:<26} v{p.version:<12} {len(p.markdown):>6} ký tự  {p.title}")
    if "--dump" in argv:
        out = Path(argv[argv.index("--dump") + 1])
        dump_markdown(pages, out)
        print(f"dump → {out}")
    if "--save" in argv:
        pages.save(DEFAULT_STORE_PATH)
        print(f"store → {DEFAULT_STORE_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    raise SystemExit(main(sys.argv[1:]))
