"""
Module: inference (Job B) — chạy tuần tự B1 classify → B2 draft(bước 1 guideline) → B3 deliver.
Architecture: docs/architecture.md §4.2 Flow B (ba task nối tiếp trong MỘT job; mỗi task ghi
              artifact ra đĩa trước khi task sau chạy ⇒ retry được từng chặng),
              §3 Trách nhiệm từng module (B1/B2/B3),
              §5 (Orchestration: Databricks Jobs multi-task DAG — file này là bản chạy-local
                 CÙNG MỘT DAG trong 1 process, dùng cho dev/demo)
Plan: docs/2026-09-03/build-email-eml/plan.md §3 D7 (runner là Job B, không phải module thứ 4),
      §4.2 (contract giữa các bước)

File này KHÔNG chứa logic nghiệp vụ riêng. Nó chỉ nối 3 module và ghi artifact trung gian:

  <in.csv>  (agent, user, date, content[, id])
     │ B1  classify.py       → + label, flag, confidence, best_label
     ▼ b1_classified.csv
     │ B2  resolve_guideline.py (chỉ label ∈ {bug,new_feature}) → + solved, referenced
     ▼ b2_resolved.csv (+ .debug.jsonl: source_ref)
     │ B3  build_email.py    → .eml theo folder nhãn + manifest.csv
     ▼ review/<folder>/<feedback_id>.eml

Chạy:
  python src/03_inference/run_pipeline.py --in data/sample/feedback_e2e_demo.csv
  ... --out-dir src/03_inference/out/pipeline/<run>   # mặc định: đặt theo timestamp
  ... --hf                 # ép encoder HF local cho B1 (không cần Databricks)
  ... --skip-b2            # bỏ bước guideline (mọi bug/new_feature ⇒ we_listen) — không cần LLM
  ... --model qwen/qwen3-8b --base-url http://localhost:1234/v1
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import io
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve()
REPO_ROOT = _HERE.parents[2]
DEFAULT_OUT_ROOT = _HERE.parent / "out" / "pipeline"


def _load(name: str):
    """Thư mục `03_inference` bắt đầu bằng số ⇒ không import thường được (xem src/04_tests/conftest.py)."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _HERE.parent / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def read_rows(path: Path) -> list[dict]:
    with io.open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_rows(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


# ── B1 ───────────────────────────────────────────────────────────────────────
def step_b1(rows: list[dict], out_csv: Path, *, encoder_mode: str = "auto") -> list[dict]:
    """§4.2: embed feedback → max-cosine tới exemplar → nhãn + confidence + routing 3 vùng."""
    cl = _load("classify")
    encoder = cl.resolve_encoder(encoder_mode)
    index = cl.build_index(encoder)
    neg = cl.build_neg_index(encoder)
    preds = cl.classify_texts_contrastive([r["content"].strip() for r in rows], index, neg,
                                          encoder, lam=cl.DEFAULT_CONTRASTIVE_LAMBDA)
    out = []
    for i, (row, pr) in enumerate(zip(rows, preds)):
        rec = dict(row)
        rec.setdefault("id", f"fb_{i:04d}")
        rec.update(label=pr.label, flag=pr.flag,
                   confidence=f"{pr.confidence:.4f}", best_label=pr.best_label)
        out.append(rec)
    write_rows(out, out_csv)
    return out


# ── B2 (bước 1 chuỗi §4.4) ───────────────────────────────────────────────────
def step_b2(in_csv: Path, out_csv: Path, *, model: str, base_url: str) -> dict:
    rg = _load("resolve_guideline")
    llm = rg.lmstudio_chat_json(model=model, base_url=base_url)
    return rg.run_file(in_csv, out_csv, llm)


def step_b2_skipped(rows: list[dict], out_csv: Path) -> list[dict]:
    """Không gọi LLM: mọi dòng `solved` rỗng ⇒ B3 route hết về we_listen (impl §3.2, không claim)."""
    out = [{**r, "solved": "", "referenced": ""} for r in rows]
    write_rows(out, out_csv)
    return out


# ── B3 ───────────────────────────────────────────────────────────────────────
def step_b3(in_csv: Path, review_dir: Path, *, overwrite: bool):
    be = _load("build_email")
    return be.run_file(in_csv, review_dir, overwrite=overwrite)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Job B end-to-end: feedback CSV → .eml theo folder nhãn")
    ap.add_argument("--in", dest="in_csv", required=True, type=Path)
    ap.add_argument("--out-dir", dest="out_dir", type=Path, default=None)
    ap.add_argument("--hf", action="store_true", help="ép encoder HF local cho B1")
    ap.add_argument("--skip-b2", action="store_true", help="bỏ bước guideline (không cần LLM)")
    ap.add_argument("--model", default="qwen/qwen3-8b")
    ap.add_argument("--base-url", default="http://localhost:1234/v1")
    ap.add_argument("--overwrite", action="store_true")
    a = ap.parse_args(argv)

    out_dir = a.out_dir or DEFAULT_OUT_ROOT / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    b1_csv, b2_csv = out_dir / "b1_classified.csv", out_dir / "b2_resolved.csv"
    review = out_dir / "review"

    rows = read_rows(a.in_csv)
    print(f"[in] {len(rows)} feedback ← {a.in_csv}")

    print("[B1] classify ...")
    b1 = step_b1(rows, b1_csv, encoder_mode="hf" if a.hf else "auto")
    dist: dict[str, int] = {}
    for r in b1:
        dist[r["label"]] = dist.get(r["label"], 0) + 1
    print(f"     nhãn: {dict(sorted(dist.items()))}  → {b1_csv.name}")

    n_kb = sum(1 for r in b1 if r["label"] in ("bug", "new_feature"))
    if a.skip_b2 or n_kb == 0:
        print(f"[B2] BỎ QUA ({'--skip-b2' if a.skip_b2 else 'không có dòng bug/new_feature'})")
        step_b2_skipped(b1, b2_csv)
    else:
        print(f"[B2] resolve guideline cho {n_kb} dòng bug/new_feature ({a.model}) ...")
        res = step_b2(b1_csv, b2_csv, model=a.model, base_url=a.base_url)
        n_solved = sum(1 for r in res.values() if r.solved)
        print(f"     solved=True: {n_solved}/{len(res)}  → {b2_csv.name}")

    print("[B3] build email ...")
    st = step_b3(b2_csv, review, overwrite=a.overwrite)
    print(f"     ghi {st.written} .eml | bỏ qua {st.skipped} | lỗi {len(st.errors)}")
    for folder, n in sorted(st.by_folder.items()):
        print(f"       {folder:<14} {n}")
    for fid, err in st.errors:
        print(f"  ERROR {fid}: {err}")
    print(f"\n→ {review}")
    return 1 if st.errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
