"""Inference 2 bước — orchestrate classify (B1) → respond (B2) cho từng feedback.

Module: inference.classify (B1) + inference.draft (B2, nội dung).
Architecture: docs/architecture.md §4.2 Flow B (classify → draft).
Impl: docs/impl-phase2-auto-feedback-flow.md §5.
Plan: docs/2026-08-26/inference-classify-respond/plan.md (R5).

Pipeline biết action_type nào cần fetch gì (giữ respond.py thuần):
  answer_from_kb → answer_from_userguide(route agent→page)   known_gap → answer_from_backlog_batch(cả danh sách)
  ack_only / unclassified → không fetch gì.

`infer_batch` (đường chính) lọc feedback về nhóm cần knowledge, gom userguide theo `agent` (1 call/agent)
+ backlog một lô chung, dùng CHUNG `KnowledgeSnapshot` (fetch một lần/run — plan §3).

Chạy:
  python pipeline.py --dry-run             # chỉ classify + in flag/route, KHÔNG gọi LLM/backlog
  python pipeline.py                        # đầy đủ: cần LM Studio (embed) + Databricks SSO (Sonnet/MCP)
                                            #   userguide store: --userguide-store <json> hoặc tự fetch live
  python pipeline.py --limit 20 --out out/inference.jsonl
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from catalog import DEFAULT_FEEDBACK_CSV, load_catalog
from classify import Classification, IntentClassifier
from knowledge import (
    KnowledgeSnapshot,
    answer_from_backlog_batch,
    answer_from_userguide,
    answer_from_userguide_batch,
    build_snapshot,
)
from respond import PersonalizedResponse, respond
from userguide_store import UserguidePages


@dataclass
class Feedback:
    content: str
    agent: str          # cột feedback (= tên function) — khoá route agent→userguide_page
    user_name: str = ""  # cột 'user'/'user_name' nếu có → điền {name} trong email
    user_email: str = "" # cột 'user_email' nếu có → trường To của .eml


@dataclass
class InferenceResult:
    classification: Classification
    response: PersonalizedResponse


class InferencePipeline:
    """Giữ classifier (đã index exemplar) + KnowledgeSnapshot (fetch một lần) để tái dùng qua nhiều feedback."""

    def __init__(
        self,
        *,
        catalog_path: Path | None = None,
        snapshot: KnowledgeSnapshot | None = None,
        encoder=None,
    ):
        intents = load_catalog(catalog_path) if catalog_path else load_catalog()
        self.classifier = IntentClassifier(intents, encoder=encoder)
        self.encoder = self.classifier.encoder      # encoder nay CHỈ phục vụ classify (backlog bỏ embedding, v3.2)
        self.snapshot = snapshot or KnowledgeSnapshot()

    def infer(self, feedback: str, agent: str = "") -> InferenceResult:
        """Per-item (back-compat/test). Đường chính là `infer_batch` (gộp call, rẻ hơn)."""
        cls = self.classifier.classify(feedback)

        userguide = None
        backlog_match = None
        if cls.action_type == "answer_from_kb" and self.snapshot.userguide_pages is not None:
            userguide = answer_from_userguide(feedback, agent, self.snapshot.userguide_pages)
        elif cls.action_type == "known_gap" and self.snapshot.backlog_items:
            backlog_match = answer_from_backlog_batch([feedback], self.snapshot.backlog_items)[0]

        resp = respond(cls, userguide=userguide, backlog=backlog_match)
        return InferenceResult(classification=cls, response=resp)

    def infer_batch(self, feedbacks: list["Feedback"]) -> list[InferenceResult]:
        """Classify tất cả → gom theo nhu cầu knowledge → batch prompt → respond per-feedback.

        userguide: gom index `answer_from_kb` theo `agent` ⇒ 1 lô/agent (amortize cả page).
        backlog: gom mọi `known_gap` ⇒ 1 lô chung trên cả danh sách backlog (amortize danh sách).
        Nhánh ack_only/unclassified không fetch gì. Guard `hit=False → we_listen` giữ ở respond.
        """
        classifications = [self.classifier.classify(fb.content) for fb in feedbacks]
        userguides: list[object] = [None] * len(feedbacks)
        backlogs: list[object] = [None] * len(feedbacks)

        # userguide: 1 lô/agent
        if self.snapshot.userguide_pages is not None:
            by_agent: dict[str, list[int]] = {}
            for i, c in enumerate(classifications):
                if c.action_type == "answer_from_kb":
                    by_agent.setdefault(feedbacks[i].agent, []).append(i)
            for agent, idxs in by_agent.items():
                answers = answer_from_userguide_batch(
                    [feedbacks[i].content for i in idxs], agent, self.snapshot.userguide_pages)
                for i, ans in zip(idxs, answers):
                    userguides[i] = ans

        # backlog: 1 lô chung cho mọi known_gap
        if self.snapshot.backlog_items:
            idxs = [i for i, c in enumerate(classifications) if c.action_type == "known_gap"]
            if idxs:
                matches = answer_from_backlog_batch(
                    [feedbacks[i].content for i in idxs], self.snapshot.backlog_items)
                for i, m in zip(idxs, matches):
                    backlogs[i] = m

        return [
            InferenceResult(classification=c, response=respond(c, userguide=userguides[i], backlog=backlogs[i]))
            for i, c in enumerate(classifications)
        ]


def _load_feedbacks(csv_path: Path, limit: int | None) -> list[Feedback]:
    out: list[Feedback] = []
    with open(csv_path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            content = (row.get("content") or "").strip()
            if any(ch.isalpha() for ch in content):     # bỏ content vô nghĩa (khớp preprocess §2.2)
                out.append(Feedback(
                    content=content,
                    agent=(row.get("agent") or "").strip(),
                    user_name=(row.get("user_name") or row.get("user") or "").strip(),
                    user_email=(row.get("user_email") or "").strip(),
                ))
            if limit and len(out) >= limit:
                break
    return out


def _load_userguide_pages(store_arg: str | None) -> UserguidePages:
    """Nạp store userguide_page: từ JSON nếu có, else fetch live qua MCP (Job A on-the-fly).

    02_knowledge đã nằm trong sys.path (knowledge.py insert lúc import) nên import trực tiếp được.
    """
    from userguide_store import DEFAULT_STORE_PATH, build_from_confluence_pages, warn_large_pages

    path = Path(store_arg) if store_arg else DEFAULT_STORE_PATH
    if path.exists():
        print(f"nạp userguide store: {path}")
        pages = UserguidePages.load(path)
    else:
        print(f"store {path} chưa có → fetch live userguide (MCP-Atlassian) ...")
        import mcp_atlassian_call as mcp  # tên file thật (tránh phụ thuộc .pyc `mcp_atlassian_test` cũ)

        raw = mcp.fetch_userguide(mcp.USERGUIDE_ROOT)
        pages = build_from_confluence_pages(raw, mcp.USERGUIDE_ROOT)
        print(f"  userguide: {len(raw)} page fetched")
    warn_large_pages(pages)
    return pages


def main() -> None:
    ap = argparse.ArgumentParser(description="Inference 2 bước: classify → respond.")
    ap.add_argument("--csv", default=str(DEFAULT_FEEDBACK_CSV), help="feedback CSV (cột content)")
    ap.add_argument("--catalog", help="Intent Catalog JSON (mặc định catalog_a.json)")
    ap.add_argument("--userguide-store", help="JSON store userguide_page (mặc định out/userguide_store.json); "
                    "thiếu → fetch live qua MCP-Atlassian")
    ap.add_argument("--backlog-filter", default="Tai Studio", help="filter summary backlog Jira")
    ap.add_argument("--no-backlog", action="store_true", help="bỏ đối chiếu backlog (known_gap → ghi nhận chung)")
    ap.add_argument("--dry-run", action="store_true", help="chỉ classify, KHÔNG fetch userguide/backlog")
    ap.add_argument("--limit", type=int, help="giới hạn số feedback")
    ap.add_argument("--out", help="ghi JSONL (mặc định chỉ in tóm tắt)")
    ap.add_argument("--eml", metavar="OUT_DIR", help="xuất .eml theo folder category (EmlSink) cho admin paste Outlook")
    ap.add_argument("--graph-delegated", action="store_true",
                    help="đẩy draft THẲNG vào Outlook qua Graph delegated (device-code login 1 lần)")
    ap.add_argument("--outlook-mac", action="store_true",
                    help="tạo draft THẲNG vào Outlook for Mac qua AppleScript (macOS, KHÔNG cần Azure)")
    ap.add_argument("--ack-only", action="store_true",
                    help="với --eml/--graph-delegated/--outlook-mac: chỉ xử lý nhánh ack (praise/complaint/unclassified)")
    args = ap.parse_args()

    catalog_path = Path(args.catalog) if args.catalog else None
    feedbacks = _load_feedbacks(Path(args.csv), args.limit)
    print(f"nạp {len(feedbacks)} feedback từ {args.csv}")

    # Dựng pipeline một lần (classifier embed exemplar 1 lần) + snapshot knowledge fetch một lần/run.
    pipe = InferencePipeline(catalog_path=catalog_path)
    if not args.dry_run:
        pages = _load_userguide_pages(args.userguide_store)
        if args.no_backlog:
            pipe.snapshot = KnowledgeSnapshot(userguide_pages=pages, backlog_items=[])
        else:
            print("kéo backlog hiện hành (MCP-Atlassian) ...")
            pipe.snapshot = build_snapshot(pages, backlog_filter=args.backlog_filter)
            print(f"  backlog: {len(pipe.snapshot.backlog_items)} issue trong snapshot")

    results = pipe.infer_batch(feedbacks)

    rows: list[dict] = []
    for fb, res in zip(feedbacks, results):
        c, r = res.classification, res.response
        print(f"\n> [{fb.agent}] {fb.content[:60]}")
        print(f"  [{c.flag}] intent={c.intent_id or '—'} action={c.action_type or '—'} c={c.confidence}")
        if not args.dry_run:
            print(f"  → {r.template}: {r.body_vi[:90]}...")
        rows.append({"agent": fb.agent, "classification": asdict(c), "response": asdict(r)})

    if args.eml:
        from deliver import EmlSink, build_draft
        from render_email import CC_LIST

        sink = EmlSink(Path(args.eml), cc=list(CC_LIST))
        written = skipped = 0
        for i, (fb, res) in enumerate(zip(feedbacks, results)):
            r = res.response
            is_ack = r.action_type in (None, "ack_only")   # praise/complaint (ack_only) + unclassified (None)
            if args.ack_only and not is_ack:
                skipped += 1
                continue
            draft = build_draft(r, f"fb_{i:04d}", fb.user_email, name=(fb.user_name or None))
            ref = sink.deliver(draft)
            written += 1
            print(f"  .eml «{draft.folder}» ← {ref.location}")
        print(f"\n✅ .eml: ghi {written} file vào {args.eml}" + (f" (bỏ qua {skipped} non-ack)" if skipped else ""))

    if args.graph_delegated:
        from deliver import build_draft, graph_sink_from_delegated_env
        from render_email import CC_LIST

        sink = graph_sink_from_delegated_env(cc=list(CC_LIST))   # login 1 lần ở draft đầu, cache cho phần sau
        pushed = skipped = 0
        for i, (fb, res) in enumerate(zip(feedbacks, results)):
            r = res.response
            is_ack = r.action_type in (None, "ack_only")
            if args.ack_only and not is_ack:
                skipped += 1
                continue
            draft = build_draft(r, f"fb_{i:04d}", fb.user_email, name=(fb.user_name or None))
            ref = sink.deliver(draft)
            pushed += 1
            print(f"  Graph draft «{draft.folder}» ← id={ref.message_id}")
        print(f"\n✅ Graph: đẩy {pushed} draft vào Outlook" + (f" (bỏ qua {skipped} non-ack)" if skipped else ""))

    if args.outlook_mac:
        from deliver import build_draft
        from outlook_mac import OutlookMacSink
        from render_email import CC_LIST

        sink = OutlookMacSink(cc=list(CC_LIST))
        made = skipped = 0
        for i, (fb, res) in enumerate(zip(feedbacks, results)):
            r = res.response
            is_ack = r.action_type in (None, "ack_only")
            if args.ack_only and not is_ack:
                skipped += 1
                continue
            draft = build_draft(r, f"fb_{i:04d}", fb.user_email, name=(fb.user_name or None))
            ref = sink.deliver(draft)
            made += 1
            print(f"  Outlook draft ← id={ref.message_id}  ({r.intent_id or 'unclassified'})")
        print(f"\n✅ Outlook Mac: tạo {made} draft trong Drafts" + (f" (bỏ qua {skipped} non-ack)" if skipped else ""))

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"\n✅ ghi {len(rows)} kết quả → {out_path}")


if __name__ == "__main__":
    main()
