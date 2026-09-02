"""Sinh `data/golden/feedback_gold_solved.csv` — gold `solved` cho B2 bước 1 (guideline resolve).

Module: Offline analysis (ngoài hệ thống) — dữ liệu gold cho `inference.draft` (B2).
Architecture: docs/architecture.md §4.4 bước 1 (câu hỏi "tính năng đã tồn tại chưa"), §6.3 bước 6
              ("đo chuỗi §4.4 trên tập gold trước khi bật").
Plan: docs/2026-09-03/guideline-resolve-batch/plan.md (D1 định nghĩa solved, D2 gold 2 labeler + adjudication)

Deterministic, không LLM:
  1. 127 dòng bug/new_feature của data/golden/feedback_gold.csv (id = fb_<i:04d> theo thứ tự dòng).
  2. Hai labeler độc lập: data/golden/solved_labelers/labels_A.csv, labels_B.csv (cùng rubric, cùng dump
     13 docx). Kappa(solved) = 0.89, bất đồng 5 dòng.
  3. Dòng hai labeler trùng ⇒ lấy A. Dòng bất đồng + dòng đổi do mở rộng map `tai` → thêm page GenUI
     (guideline_docx.PLATFORM_DOC_MAP) ⇒ bảng ADJUDICATIONS bên dưới (PM-proxy, precision-first).
  4. Mọi `referenced` không rỗng được kiểm nguyên văn có trong page của agent (gate D6) — sai ⇒ fail loud.

Chạy:  python scripts/make_feedback_gold_solved.py
"""
from __future__ import annotations

import csv
import importlib.util
import io
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLD_INTENT = REPO_ROOT / "data" / "golden" / "feedback_gold.csv"
LABELS_DIR = REPO_ROOT / "data" / "golden" / "solved_labelers"
OUT = REPO_ROOT / "data" / "golden" / "feedback_gold_solved.csv"
KNOWLEDGE_LABELS = ("bug", "new_feature")

# id -> (solved, match_type, referenced, rationale)  — quyết định adjudication (2026-09-03)
ADJUDICATIONS: dict[str, tuple[bool, str, str, str]] = {
    # ── 5 dòng A/B bất đồng ──
    "fb_0061": (False, "none", "",
                "A/B bất đồng. Doc chỉ nói presentation đã lưu hiện ở homepage, không mô tả cách lưu tiến độ khi đang tạo ⇒ lưỡng lự ⇒ False (precision-first)."),
    "fb_0074": (False, "none", "",
                "A/B bất đồng. 'upload reference files' không khẳng định NHIỀU file cùng lúc (fb_0057 báo ngược lại) ⇒ lưỡng lự ⇒ False."),
    "fb_0137": (False, "limitation", "Image insertion is not supported — slides contain text and vector graphics only",
                "A/B bất đồng về match_type. Paste ảnh làm input slide ⇔ limitation 'Image insertion is not supported' ⇒ limitation (theo B)."),
    "fb_0145": (False, "limitation",
                "During slide editing, only inline content updates are supported. Adding new text boxes or repositioning existing elements is not available",
                "A/B bất đồng về match_type. Nửa sau đòi sửa layout/overlap — doc ghi rõ không reposition được ⇒ limitation (theo B)."),
    "fb_0171": (False, "none", "",
                "A/B bất đồng về match_type. Chuẩn hoá chức danh theo bộ HR ≠ 'domain-specific terminology may need human review' ⇒ none (theo B)."),
    # ── Mở rộng map `tai` → thêm page GenUI (cả A và B đều ghi chú câu trả lời nằm ở GenUI) ──
    "fb_0004": (True, "how_to",
                "The sidebar shows your token usage (e.g., 3 / 10,000). Tips to save tokens:",
                "GenUI §9 Token Meter: sidebar hiện mức dùng token, 'At 90% usage, the bar turns red with a warning' ⇒ chỉ báo đã có ⇒ True."),
    "fb_0032": (True, "how_to",
                "| Language follows your prompt | The EN/VI toggle changes UI only, not response language |",
                "GenUI Limitations xác nhận có toggle EN/VI cho giao diện ⇒ 'có giao diện tiếng Việt không?' = có ⇒ True."),
    "fb_0107": (True, "how_to",
                "| Language follows your prompt | The EN/VI toggle changes UI only, not response language |",
                "'Cần phiên bản tiếng Việt' — toggle EN/VI cho UI đã có; ngôn ngữ trả lời theo prompt ⇒ True."),
    "fb_0023": (False, "limitation",
                "| Language follows your prompt | The EN/VI toggle changes UI only, not response language |",
                "Doc nói ngôn ngữ trả lời theo prompt; user hỏi ENG nhưng nhận VI ⇒ hành vi trái doc = bug, doc chỉ giải thích cơ chế ⇒ limitation."),
}


def _load_mod(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _read(path: Path) -> list[dict]:
    with io.open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _b(s: str) -> bool:
    return str(s).strip().lower() == "true"


def main() -> int:
    gold = [{**r, "id": f"fb_{i:04d}"} for i, r in enumerate(_read(GOLD_INTENT))]
    rows = [r for r in gold if r["label"] in KNOWLEDGE_LABELS]
    la = {r["id"]: r for r in _read(LABELS_DIR / "labels_A.csv")}
    lb = {r["id"]: r for r in _read(LABELS_DIR / "labels_B.csv")}
    assert set(la) == set(lb) == {r["id"] for r in rows}, "labeler CSV lệch id với gold"

    # gate D6: quote phải nguyên văn trong page của agent
    sys.path.insert(0, str(REPO_ROOT / "src" / "02_knowledge"))
    rg = _load_mod("src/03_inference/resolve_guideline.py", "b2_resolve_guideline")
    pages = rg.load_pages()

    out, n_dis, n_adj = [], 0, 0
    for r in rows:
        a, b = la[r["id"]], lb[r["id"]]
        disagree = _b(a["solved"]) != _b(b["solved"]) or a["match_type"] != b["match_type"]
        n_dis += disagree
        if r["id"] in ADJUDICATIONS:
            solved, mt, ref, why = ADJUDICATIONS[r["id"]]
            n_adj += 1
        else:
            assert not disagree, f"{r['id']} bất đồng nhưng chưa có adjudication"
            solved, mt, ref, why = _b(a["solved"]), a["match_type"], a["referenced"] or "", a["rationale"]
        if ref:
            hit = rg.verify_quote(ref, rg.pages_for_agent(pages, r["agent"]))
            assert hit.ok, f"{r['id']}: referenced không nguyên văn trong page của {r['agent']}: {ref[:60]!r}"
            ref = hit.quote
        assert solved == (mt == "how_to"), f"{r['id']}: solved/match_type không nhất quán"
        out.append({"id": r["id"], "agent": r["agent"], "label": r["label"], "content": r["content"],
                    "solved": str(solved), "match_type": mt, "referenced": ref, "rationale": why})

    with io.open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)

    n_true = sum(r["solved"] == "True" for r in out)
    n_lim = sum(r["match_type"] == "limitation" for r in out)
    print(f"{len(out)} dòng → {OUT.relative_to(REPO_ROOT)}")
    print(f"  solved=True {n_true} | limitation {n_lim} | none {len(out) - n_true - n_lim}")
    print(f"  A/B bất đồng {n_dis} dòng | adjudication {n_adj} dòng (gồm {n_adj - n_dis} dòng đổi do map tai→GenUI)")
    print("  True:", ", ".join(r["id"] for r in out if r["solved"] == "True"))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    raise SystemExit(main())
