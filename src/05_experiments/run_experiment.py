"""
Module: Offline intent analysis (Phase 0, NGOAI he thong) — experiment runner cho B1
Architecture: docs/architecture.md §3 (Offline intent analysis — ngoai he thong / khong trong
              Databricks Job), §4.3 (routing 3 vung), §6.3 buoc 4 (calibrate tren holdout)
Plan: docs/2026-09-03/experiment-tracking-lite/plan.md

MOI PHUONG AN = 1 FUNCTION trong APPROACHES (D2): tu chua config, tra (config, metrics).
Thu phuong an moi = viet them 1 function + dang ky — khong sua code loi (tai dung classify.py).

Moi lan chay luu 1 folder runs/<ts>_<approach>/ (D3):
    config.yaml       config resolve + hash data + git sha
    metrics.json      metrics day du (ke ca danh sach dong sai)
    report.txt        ban in nguoi doc duoc
    code_diff.patch   (chi khi git dirty) de tai lap dung code luc chay
va append 1 dong vao runs/index.md de so sanh nhanh.

Chay:
  python src/05_experiments/run_experiment.py --list
  python src/05_experiments/run_experiment.py exemplar_cosine_hf --note "baseline exemplar v1"
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve()
REPO_ROOT = _HERE.parents[2]
RUNS_DIR = _HERE.parent / "runs"
EXEMPLAR_CSV = REPO_ROOT / "data" / "sample" / "exemplars" / "intent_exemplars.csv"
GOLDEN_CSV = REPO_ROOT / "data" / "golden" / "feedback_gold.csv"


def _load_classify():
    """Nap src/03_inference/classify.py (thu muc ten so — khong import thuong duoc)."""
    name = "b1_classify"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "src" / "03_inference" / "classify.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ══════════════════════════════════════════════════════════════════════════════
# CAC PHUONG AN — moi phuong an 1 function, tra (config, metrics)
# ══════════════════════════════════════════════════════════════════════════════
# NGUONG cho cac phuong an: 0.60/0.45 (mac dinh classify.py, routing 3 vung §4.3).
# Lich su: 2026-09-03 PM tung chot MOT nguong 0.50 (high=low, run exemplar_v2_hf_t50)
# roi REVERT ngay trong ngay — nang cua abstain 0.45->0.50 vut dung dai diem tot cua
# new_feature (dai 0.45–0.50 co 13 dung / 4 sai = 76% chinh xac), recall tut 0.57->0.37.
# FIXED_TH chi con dung cho approach t50 (giu lam ho so doi chieu).
FIXED_TH = 0.50
def exemplar_cosine_hf():
    """Baseline: exemplar sinh moi (5/nhan) + max-cosine + routing 3 vung, encoder HF local."""
    classify = _load_classify()
    cfg = {
        "approach": "exemplar_cosine_hf",
        "model": "max-cosine toi exemplar + threshold routing 3 vung (§4.3, R3)",
        "encoder": f"hf:{classify.HF_MODEL} (sentence-transformers, CHI dev/eval — plan D7)",
        "threshold_high": classify.DEFAULT_THRESHOLD_HIGH,
        "threshold_low": classify.DEFAULT_THRESHOLD_LOW,
        "contrastive_lambda": None,
    }
    # contrastive_lambda=None TUONG MINH: classify.py nay mac dinh BAT contrastive (0.3),
    # cac approach lich su phai giu duong positive-only de tai lap dung so da ghi.
    metrics = classify.evaluate_golden(encoder=classify.hf_encoder(),
                                       contrastive_lambda=None, verbose=True)
    return cfg, metrics


def exemplar_cosine_hf_t50_35():
    """Nhu baseline nhung ha nguong: high 0.60->0.50, low 0.45->0.35 (user 2026-09-03).
    Muc dich: keo bot dong roi oan xuong unclassified/low_confidence do phan bo cosine thap."""
    classify = _load_classify()
    th, tl = 0.50, 0.35
    cfg = {
        "approach": "exemplar_cosine_hf_t50_35",
        "model": "max-cosine toi exemplar + threshold routing 3 vung (§4.3, R3)",
        "encoder": f"hf:{classify.HF_MODEL} (sentence-transformers, CHI dev/eval — plan D7)",
        "threshold_high": th,
        "threshold_low": tl,
        "contrastive_lambda": None,
    }
    metrics = classify.evaluate_golden(encoder=classify.hf_encoder(),
                                       threshold_high=th, threshold_low=tl,
                                       contrastive_lambda=None, verbose=True)
    return cfg, metrics


def exemplar_v2_hf():
    """(b) Exemplar v2: complain viet lai (che chat luong cu the, khong malfunction),
    10 mau/nhan, tron register khau ngu. Nguong nhu baseline de quy cong dung cho (b)."""
    classify = _load_classify()
    cfg = {
        "approach": "exemplar_v2_hf",
        "model": "max-cosine toi exemplar + threshold routing 3 vung (§4.3, R3)",
        "encoder": f"hf:{classify.HF_MODEL} (sentence-transformers, CHI dev/eval — plan D7)",
        "threshold_high": classify.DEFAULT_THRESHOLD_HIGH,
        "threshold_low": classify.DEFAULT_THRESHOLD_LOW,
        "exemplar_version": "v2 — complain rewrite + 10/nhan + register khau ngu",
        "contrastive_lambda": None,
    }
    metrics = classify.evaluate_golden(encoder=classify.hf_encoder(),
                                       contrastive_lambda=None, verbose=True)
    return cfg, metrics


def exemplar_v2_instruct_hf():
    """(b)+(c): exemplar v2 + instruct prefix Qwen3 phia query (asymmetric)."""
    classify = _load_classify()
    cfg = {
        "approach": "exemplar_v2_instruct_hf",
        "model": "max-cosine toi exemplar + threshold routing 3 vung (§4.3, R3)",
        "encoder": f"hf:{classify.HF_MODEL} (sentence-transformers, CHI dev/eval — plan D7)",
        "threshold_high": classify.DEFAULT_THRESHOLD_HIGH,
        "threshold_low": classify.DEFAULT_THRESHOLD_LOW,
        "exemplar_version": "v2 — complain rewrite + 10/nhan + register khau ngu",
        "query_instruction": classify.QUERY_INSTRUCTION,
        "contrastive_lambda": None,
    }
    metrics = classify.evaluate_golden(encoder=classify.hf_encoder(),
                                       query_instruction=classify.QUERY_INSTRUCTION,
                                       contrastive_lambda=None, verbose=True)
    return cfg, metrics


def exemplar_v2_hf_t50():
    """Exemplar v2 tai NGUONG CO DINH 0.50 (FIXED_TH, high=low) — moc tham chieu cho
    moi phuong an ke tiep (contrastive scoring, ...)."""
    classify = _load_classify()
    cfg = {
        "approach": "exemplar_v2_hf_t50",
        "model": "max-cosine toi exemplar + MOT nguong co dinh (abstain khi c < 0.50)",
        "encoder": f"hf:{classify.HF_MODEL} (sentence-transformers, CHI dev/eval — plan D7)",
        "threshold_high": FIXED_TH,
        "threshold_low": FIXED_TH,
        "exemplar_version": "v2 — complain rewrite + 10/nhan + register khau ngu",
    }
    metrics = classify.evaluate_golden(encoder=classify.hf_encoder(),
                                       threshold_high=FIXED_TH, threshold_low=FIXED_TH,
                                       verbose=True)
    return cfg, metrics


def _contrastive(lam: float):
    """Contrastive scoring tren nen v2: score = max_cos(pos) - lam*max_cos(neg);
    negative = hard negative theo cap hay nham (plan contrastive-negative-scoring D2).
    Confidence routing = raw cosine positive => nguong 0.60/0.45 giu ngu nghia."""
    classify = _load_classify()
    cfg = {
        "approach": f"contrastive_neg_hf_l{int(lam * 10):02d}",
        "model": f"contrastive: max_cos(pos) - {lam}*max_cos(neg) + routing 3 vung 0.60/0.45",
        "encoder": f"hf:{classify.HF_MODEL} (sentence-transformers, CHI dev/eval — plan D7)",
        "threshold_high": classify.DEFAULT_THRESHOLD_HIGH,
        "threshold_low": classify.DEFAULT_THRESHOLD_LOW,
        "exemplar_version": "v2 positive + negatives v1 (intent_exemplar_negatives.csv)",
        "contrastive_lambda": lam,
    }
    metrics = classify.evaluate_golden(encoder=classify.hf_encoder(),
                                       contrastive_lambda=lam, verbose=True)
    return cfg, metrics


def contrastive_neg_hf_l03():
    return _contrastive(0.3)


def contrastive_neg_hf_l05():
    return _contrastive(0.5)


def best_databricks():
    """CAU HINH TOT NHAT (mac dinh classify.py: v2 + contrastive lam=0.3, nguong 0.60/0.45)
    chay tren encoder PRODUCTION (qwen3 Model Serving §5) — can auth Databricks.
    Day la run chot so that; moi so HF chi la chi bao dev (R2)."""
    classify = _load_classify()
    cfg = {
        "approach": "best_databricks",
        "model": (f"contrastive: max_cos(pos) - {classify.DEFAULT_CONTRASTIVE_LAMBDA}"
                  "*max_cos(neg) + routing 3 vung 0.60/0.45"),
        "encoder": "databricks-qwen3-embedding-0-6b (Model Serving §5 — encoder production)",
        "threshold_high": classify.DEFAULT_THRESHOLD_HIGH,
        "threshold_low": classify.DEFAULT_THRESHOLD_LOW,
        "exemplar_version": "v2 positive + negatives v1",
        "contrastive_lambda": classify.DEFAULT_CONTRASTIVE_LAMBDA,
    }
    metrics = classify.evaluate_golden(encoder=classify.default_encoder(), verbose=True)
    return cfg, metrics


APPROACHES = {
    "exemplar_cosine_hf": (exemplar_cosine_hf, "baseline: exemplar v1 + HF encoder (dev/eval)"),
    "exemplar_cosine_hf_t50_35": (exemplar_cosine_hf_t50_35, "baseline + ha nguong high=0.50 low=0.35"),
    "exemplar_v2_hf": (exemplar_v2_hf, "(b) exemplar v2: complain rewrite + 10/nhan + register"),
    "exemplar_v2_instruct_hf": (exemplar_v2_instruct_hf, "(b)+(c): v2 + instruct prefix Qwen3 phia query"),
    "exemplar_v2_hf_t50": (exemplar_v2_hf_t50, "v2 tai MOT nguong 0.50 (da revert — giu de doi chieu)"),
    "contrastive_neg_hf_l03": (contrastive_neg_hf_l03, "** BEST hien tai: v2 + negative, lam=0.3 **"),
    "contrastive_neg_hf_l05": (contrastive_neg_hf_l05, "v2 + negative exemplar, lam=0.5"),
    "best_databricks": (best_databricks, "cau hinh best tren encoder PRODUCTION (can auth)"),
}


# ══════════════════════════════════════════════════════════════════════════════
# Runner — ghi ho so run (D3)
# ══════════════════════════════════════════════════════════════════════════════
def _file_hash(path: Path) -> str:
    return hashlib.blake2b(path.read_bytes(), digest_size=8).hexdigest()


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=30).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def _yaml_dump(d: dict, indent: int = 0) -> str:
    """YAML don gian (khong phu thuoc pyyaml) — du cho config phang/1 cap lồng."""
    lines = []
    for k, v in d.items():
        if isinstance(v, dict):
            lines.append(f"{'  ' * indent}{k}:")
            lines.append(_yaml_dump(v, indent + 1))
        elif isinstance(v, list):
            lines.append(f"{'  ' * indent}{k}:")
            lines.extend(f"{'  ' * (indent + 1)}- {json.dumps(x, ensure_ascii=False)}" for x in v)
        else:
            sv = json.dumps(v, ensure_ascii=False) if isinstance(v, str) else v
            lines.append(f"{'  ' * indent}{k}: {sv}")
    return "\n".join(lines)


def run(approach: str, note: str = "") -> Path:
    fn, _desc = APPROACHES[approach]
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    # chay phuong an, capture report nguoi doc duoc
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cfg, metrics = fn()
    report = buf.getvalue()
    # LUU HO SO TRUOC roi moi in — print co the chet vi BrokenPipeError khi stdout
    # bi pipe dong som (vd `| Select-Object -First N`), khong duoc keo mat ho so

    # ho so run: config + boi canh tai lap (hash data, git, env)
    dirty_files = _git("status", "--porcelain")
    cfg_full = {
        **cfg,
        "note": note,
        "run_at": ts,
        "data": {
            "golden": f"{GOLDEN_CSV.relative_to(REPO_ROOT).as_posix()} (hash {_file_hash(GOLDEN_CSV)})",
            "exemplars": f"{EXEMPLAR_CSV.relative_to(REPO_ROOT).as_posix()} (hash {_file_hash(EXEMPLAR_CSV)})",
        },
        "git": {
            "sha": _git("rev-parse", "--short", "HEAD"),
            "dirty": bool(dirty_files),
            "changed_files": dirty_files.splitlines(),
        },
        "python": platform.python_version(),
    }

    out = RUNS_DIR / f"{ts}_{approach}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.yaml").write_text(_yaml_dump(cfg_full) + "\n", encoding="utf-8")
    (out / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2, default=list), encoding="utf-8")
    (out / "report.txt").write_text(report, encoding="utf-8")
    if cfg_full["git"]["dirty"]:
        diff = _git("diff", "HEAD")
        if diff:
            (out / "code_diff.patch").write_text(diff + "\n", encoding="utf-8")

    # index.md — 1 dong/run de so nhanh
    per = metrics["per_label"]
    macro_f1 = sum(m["f1"] for m in per.values()) / len(per)
    fl = metrics["flags"]
    index = RUNS_DIR / "index.md"
    if not index.exists():
        index.write_text(
            "# Experiment runs — B1 intent classification\n\n"
            "| run | approach | accuracy | macro-F1 | ok/low/unc | note |\n"
            "|---|---|---:|---:|---|---|\n", encoding="utf-8")
    with io.open(index, "a", encoding="utf-8") as f:
        f.write(f"| [{ts}]({ts}_{approach}/report.txt) | {approach} "
                f"| {metrics['accuracy']:.1%} | {macro_f1:.2f} "
                f"| {fl['ok']}/{fl['low_confidence']}/{fl['unclassified']} | {note} |\n")

    try:
        print(report)
        print(f"\n[run] da luu ho so: {out.relative_to(REPO_ROOT)}")
    except OSError:  # BrokenPipeError — ho so da luu xong, bo qua loi in
        pass
    return out


def main(argv: list[str]) -> int:
    note = ""
    if "--note" in argv:
        i = argv.index("--note")
        note = argv[i + 1] if i + 1 < len(argv) else ""
        argv = argv[:i] + argv[i + 2:]
    if not argv or argv[0] in {"-h", "--help", "--list"}:
        print("Cac phuong an da dang ky:")
        for name, (_fn, desc) in APPROACHES.items():
            print(f"  {name:<28} {desc}")
        print(f"\nChay: python {_HERE.relative_to(REPO_ROOT)} <approach> [--note \"...\"]")
        return 0
    if argv[0] not in APPROACHES:
        print(f"Khong co phuong an '{argv[0]}' — xem --list", file=sys.stderr)
        return 1
    run(argv[0], note)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
