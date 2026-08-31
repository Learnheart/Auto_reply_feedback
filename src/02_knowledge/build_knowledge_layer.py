"""Job A (ingest-sync) — nửa userguide: fetch Confluence → store `userguide_page` (route agent→page).

Module: ingest-sync (Job A).
Architecture: docs/architecture.md §3 (KNOWLEDGE LAYER, note v3.1 — thay Vector Search), §4.5 (userguide_page).
Plan: docs/2026-08-26/knowledge-retrieval-strategy/plan.md

Thay bản Scholar cũ (nạp userguide+backlog vào Scholar App). v3.1: userguide KHÔNG chunk/embed/index —
chỉ fetch NGUYÊN page/function (đặt tên theo agent) rồi lưu store; B2 route `agent → page` lúc inference.
Backlog (known_gap) fetch LIVE trong pipeline (`knowledge.build_snapshot` → nạp cả danh sách cho LLM, v3.2),
không nằm ở store này.

Cách dùng (đăng nhập trước: databricks auth login --profile tcb-agent-sit):
    python build_knowledge_layer.py --dry-run     # fetch + in page/size + coverage vs feedback, KHÔNG lưu
    python build_knowledge_layer.py               # fetch + lưu store (out/userguide_store.json)
    python build_knowledge_layer.py --out <path>  # store path khác

Cần: pip install httpx databricks-sdk truststore   (Python >= 3.10)
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import mcp_atlassian_call as mcp  # tên file thật (tránh phụ thuộc .pyc `mcp_atlassian_test` cũ)
from userguide_store import (
    DEFAULT_STORE_PATH,
    build_from_confluence_pages,
    coverage_report,
    warn_large_pages,
)

# CSV feedback mẫu — dùng để đối chiếu coverage map agent→page (K-1 acceptance).
DEFAULT_FEEDBACK_CSV = (
    Path(__file__).resolve().parents[2] / "data" / "sample" / "feedback" / "feedback_extracted.csv"
)


def _feedback_agents(csv_path: Path) -> list[str]:
    if not csv_path.exists():
        return []
    with open(csv_path, encoding="utf-8-sig") as f:
        return [(row.get("agent") or "").strip() for row in csv.DictReader(f)]


def build(store_path: Path, feedback_csv: Path, *, dry_run: bool = False) -> None:
    print(f"fetch userguide (root {mcp.USERGUIDE_ROOT}) qua MCP-Atlassian ...")
    raw = mcp.fetch_userguide(mcp.USERGUIDE_ROOT)
    if not raw:
        raise SystemExit("Không lấy được page nào — kiểm tra id/space/quyền.")
    pages = build_from_confluence_pages(raw, mcp.USERGUIDE_ROOT)

    total_chars = sum(len(p.get("markdown", "") or "") for p in raw)
    print(f"\n{len(raw)} page, tổng {total_chars} ký tự:")
    for p in pages._all():
        tag = "(root/overview)" if not p.agent else f"→ agent '{p.agent}'"
        print(f"  • {p.page_id}  v{p.version}  {len(p.markdown):>6} ký tự  {p.title}  {tag}")
    warn_large_pages(pages)

    # Coverage: mọi agent trong feedback có map được page không (K-1).
    agents = _feedback_agents(feedback_csv)
    if agents:
        matched, unmatched = coverage_report(pages, agents)
        print(f"\ncoverage agent→page: {len(matched)}/{len(matched) + len(unmatched)} khớp")
        if unmatched:
            print(f"  ⚠ CHƯA map: {unmatched}  (thêm page đặt tên theo agent, hoặc AGENT_TITLE_OVERRIDES)")

    if dry_run:
        print("\n[dry-run] KHÔNG lưu store.")
        return
    pages.save(store_path)
    print(f"\n✅ lưu store: {store_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Job A — dựng userguide_page store (route agent→page).")
    ap.add_argument("--out", default=str(DEFAULT_STORE_PATH), help="đường dẫn store JSON")
    ap.add_argument("--feedback-csv", default=str(DEFAULT_FEEDBACK_CSV), help="CSV feedback để đối chiếu coverage")
    ap.add_argument("--dry-run", action="store_true", help="fetch + in page/size + coverage, KHÔNG lưu")
    args = ap.parse_args()
    build(Path(args.out), Path(args.feedback_csv), dry_run=args.dry_run)


if __name__ == "__main__":
    main()
