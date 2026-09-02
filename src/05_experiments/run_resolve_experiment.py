"""
Module: Offline analysis (NGOÀI hệ thống) — experiment runner cho B2 bước 1 (guideline resolve)
Architecture: docs/architecture.md §3 (Offline — ngoài Databricks Job), §4.4 bước 1 (đối tượng đo),
              §6.3 bước 6 ("đo chuỗi §4.4 trên tập gold trước khi bật")
Plan: docs/2026-09-03/guideline-resolve-batch/plan.md (D7 metric + điều kiện dừng),
      docs/2026-09-03/experiment-tracking-lite/plan.md (khuôn: mỗi phương án = 1 function, mỗi run 1 folder)

Mỗi phương án = 1 function trả (config, metrics). Hồ sơ run ghi vào runs_resolve/<ts>_<approach>/
(config.yaml, metrics.json, report.txt, code_diff.patch nếu dirty) + 1 dòng vào runs_resolve/index.md.
Tái dùng helper của run_experiment.py (git/hash/yaml).

Chạy:
  python src/05_experiments/run_resolve_experiment.py --list
  python src/05_experiments/run_resolve_experiment.py whole_page_nothink --note "baseline"
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve()
REPO_ROOT = _HERE.parents[2]
RUNS_DIR = _HERE.parent / "runs_resolve"
GOLD_CSV = REPO_ROOT / "data" / "golden" / "feedback_gold_solved.csv"
GUIDELINES_DIR = REPO_ROOT / "data" / "guidelines"


def _load(rel: str, name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _rg():
    return _load("src/03_inference/resolve_guideline.py", "b2_resolve_guideline")


def _base():
    return _load("src/05_experiments/run_experiment.py", "b1_run_experiment")


# ══════════════════════════════════════════════════════════════════════════════
# CÁC PHƯƠNG ÁN
# ══════════════════════════════════════════════════════════════════════════════
def _run_cfg(approach: str, desc: str, *, think: bool = False, batch_size: int = 10,
             fuzzy: float | None = None, verify: bool = False, model: str | None = None,
             prompt_style: str = "decide", anchor: bool = False):
    rg = _rg()
    model = model or rg.DEFAULT_MODEL
    stats: dict = {}
    llm = rg.lmstudio_chat_json(model=model, think=think, stats=stats)
    cfg = {
        "approach": approach, "model": desc,
        "llm": f"{model} @ LM Studio (dev thay Haiku 4.5 §5)",
        "think": think, "batch_size": batch_size, "fuzzy_gate": fuzzy, "verify_pass": verify,
        "prompt_style": prompt_style, "anchor_gate": anchor,
        "gate": "quote verbatim trong page của agent (D6); không tìm được ⇒ solved=False",
        "knowledge": "data/guidelines/*.docx → guideline_docx.load_guidelines (whole-page, không chunk)",
    }
    metrics = rg.evaluate_gold(llm, llm_stats=stats, batch_size=batch_size, fuzzy=fuzzy, verify=verify,
                               prompt_style=prompt_style, anchor=anchor)
    return cfg, metrics


def whole_page_nothink():
    """A0 baseline: whole-page/agent, lô 10, qwen3-8b no-think, gate strict."""
    return _run_cfg("whole_page_nothink", "whole-page batch + no-think + strict quote gate")


def whole_page_think():
    """A1: như A0 nhưng bật reasoning Qwen3 (enable_thinking)."""
    return _run_cfg("whole_page_think", "whole-page batch + THINK + strict quote gate", think=True)


def whole_page_nothink_verify():
    """A2: A0 + lượt 2 hỏi lại từng dòng solved=True (precision)."""
    return _run_cfg("whole_page_nothink_verify", "whole-page batch + no-think + verify pass", verify=True)


def whole_page_think_verify():
    """A2': A1 + verify pass."""
    return _run_cfg("whole_page_think_verify", "whole-page batch + THINK + verify pass",
                    think=True, verify=True)


def per_item_nothink():
    """A3: 1 feedback/call (không batch) — đo xem batch có làm giảm chất lượng không."""
    return _run_cfg("per_item_nothink", "per-item (batch_size=1) + no-think", batch_size=1)


def whole_page_think_fuzzy():
    """A4: A1 + gate fuzzy 0.92 (bù LLM chép sai vài ký tự; quote trả về = đoạn tài liệu thật)."""
    return _run_cfg("whole_page_think_fuzzy", "whole-page batch + THINK + fuzzy gate 0.92",
                    think=True, fuzzy=0.92)


def small_batch_think():
    """A5: THINK + lô 5 (ít feedback/call hơn ⇒ model chú ý từng dòng hơn)."""
    return _run_cfg("small_batch_think", "whole-page batch=5 + THINK", think=True, batch_size=5)


def evidence_nothink():
    """A6: prompt evidence-first (trích passage liên quan nhất cho MỌI dòng → relation → solved), no-think."""
    return _run_cfg("evidence_nothink", "evidence-first prompt + no-think + strict gate", prompt_style="evidence")


def evidence_think():
    """A6': evidence-first + THINK."""
    return _run_cfg("evidence_think", "evidence-first prompt + THINK + strict gate", think=True,
                    prompt_style="evidence")


def evidence_think_verify():
    """A7: evidence-first + THINK + verify pass (precision)."""
    return _run_cfg("evidence_think_verify", "evidence-first + THINK + verify pass", think=True,
                    verify=True, prompt_style="evidence")


def evidence_nothink_verify():
    """A7': evidence-first + no-think + verify pass."""
    return _run_cfg("evidence_nothink_verify", "evidence-first + no-think + verify pass",
                    verify=True, prompt_style="evidence")


def evidence_think_anchor():
    """A8: evidence-first + THINK + gate v2 anchor (bù quote chép lệch: '...', gộp heading, bỏ bullet)."""
    return _run_cfg("evidence_think_anchor", "evidence-first + THINK + anchor gate", think=True,
                    prompt_style="evidence", anchor=True)


def evidence_think_anchor_verify():
    """A9: A8 + verify pass (precision)."""
    return _run_cfg("evidence_think_anchor_verify", "evidence-first + THINK + anchor gate + verify",
                    think=True, prompt_style="evidence", anchor=True, verify=True)


def decide_think_anchor():
    """A10: prompt decide + THINK + anchor gate (think thuần có precision 0.80 ở vòng 1)."""
    return _run_cfg("decide_think_anchor", "decide prompt + THINK + anchor gate", think=True, anchor=True)


def decide_think_anchor_verify():
    """A11: A10 + verify pass."""
    return _run_cfg("decide_think_anchor_verify", "decide prompt + THINK + anchor gate + verify",
                    think=True, anchor=True, verify=True)


APPROACHES = {
    "whole_page_nothink": (whole_page_nothink, "A0 baseline: batch 10, no-think, strict gate"),
    "whole_page_think": (whole_page_think, "A1: batch 10, THINK"),
    "whole_page_nothink_verify": (whole_page_nothink_verify, "A2: A0 + verify pass"),
    "whole_page_think_verify": (whole_page_think_verify, "A2': A1 + verify pass"),
    "per_item_nothink": (per_item_nothink, "A3: per-item, no-think"),
    "whole_page_think_fuzzy": (whole_page_think_fuzzy, "A4: THINK + fuzzy gate 0.92"),
    "small_batch_think": (small_batch_think, "A5: THINK + batch 5"),
    "evidence_nothink": (evidence_nothink, "A6: evidence-first prompt, no-think"),
    "evidence_think": (evidence_think, "A6': evidence-first prompt, THINK"),
    "evidence_think_verify": (evidence_think_verify, "A7: evidence-first + THINK + verify"),
    "evidence_nothink_verify": (evidence_nothink_verify, "A7': evidence-first + no-think + verify"),
    "evidence_think_anchor": (evidence_think_anchor, "A8: evidence + THINK + anchor gate"),
    "evidence_think_anchor_verify": (evidence_think_anchor_verify, "A9: A8 + verify"),
    "decide_think_anchor": (decide_think_anchor, "A10: decide + THINK + anchor gate"),
    "decide_think_anchor_verify": (decide_think_anchor_verify, "A11: A10 + verify"),
}


# ══════════════════════════════════════════════════════════════════════════════
# Runner
# ══════════════════════════════════════════════════════════════════════════════
def run(approach: str, note: str = "") -> Path:
    base = _base()
    fn, _ = APPROACHES[approach]
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cfg, metrics = fn()
    report = buf.getvalue()

    dirty = base._git("status", "--porcelain")
    doc_hash = "|".join(f"{p.name}:{base._file_hash(p)}" for p in sorted(GUIDELINES_DIR.glob("*.docx")))
    cfg_full = {
        **cfg, "note": note, "run_at": ts,
        "data": {"gold_solved": f"{GOLD_CSV.relative_to(REPO_ROOT).as_posix()} (hash {base._file_hash(GOLD_CSV)})",
                 "guidelines": doc_hash},
        "git": {"sha": base._git("rev-parse", "--short", "HEAD"), "dirty": bool(dirty),
                "changed_files": dirty.splitlines()},
    }
    out = RUNS_DIR / f"{ts}_{approach}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.yaml").write_text(base._yaml_dump(cfg_full) + "\n", encoding="utf-8")
    (out / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2, default=str),
                                      encoding="utf-8")
    (out / "report.txt").write_text(report, encoding="utf-8")
    if cfg_full["git"]["dirty"]:
        diff = base._git("diff", "HEAD")
        if diff:
            (out / "code_diff.patch").write_text(diff + "\n", encoding="utf-8")

    index = RUNS_DIR / "index.md"
    if not index.exists():
        index.write_text(
            "# Experiment runs — B2 bước 1 guideline resolve (metric chính: F1 lớp solved=True)\n\n"
            "| run | approach | precision | recall | F1 | tp/fp/fn | verbatim | llm calls / s | note |\n"
            "|---|---|---:|---:|---:|---|---:|---|---|\n", encoding="utf-8")
    c = metrics["confusion"]
    llm = metrics.get("llm", {})
    with io.open(index, "a", encoding="utf-8") as f:
        f.write(f"| [{ts}]({ts}_{approach}/report.txt) | {approach} | {metrics['precision']:.2f} "
                f"| {metrics['recall']:.2f} | **{metrics['f1']:.2f}** | {c['tp']}/{c['fp']}/{c['fn']} "
                f"| {metrics['quote_verbatim_rate']:.2f} | {llm.get('calls', '?')} / {llm.get('seconds', 0):.0f}s "
                f"| {note} |\n")
    try:
        print(report)
        print(f"\n[run] đã lưu hồ sơ: {out.relative_to(REPO_ROOT)}")
    except OSError:
        pass
    return out


def main(argv: list[str]) -> int:
    note = ""
    if "--note" in argv:
        i = argv.index("--note")
        note = argv[i + 1] if i + 1 < len(argv) else ""
        argv = argv[:i] + argv[i + 2:]
    if not argv or argv[0] in {"-h", "--help", "--list"}:
        print("Các phương án đã đăng ký:")
        for name, (_fn, desc) in APPROACHES.items():
            print(f"  {name:<28} {desc}")
        return 0
    if argv[0] not in APPROACHES:
        print(f"Không có phương án '{argv[0]}' — xem --list", file=sys.stderr)
        return 1
    run(argv[0], note)
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass
    raise SystemExit(main(sys.argv[1:]))
