"""
Module: inference.classify (B1)
Architecture: docs/architecture.md §3 Trach nhiem tung module ("Embed feedback moi -> cosine
              toi exemplar -> gan intent + confidence -> routing 3 vung"), §4.2 Flow B (B1),
              §4.3 Flow C Threshold routing, §4.5 Data layer (flag: ok|low_confidence|unclassified),
              §6.1 R2 (cung model embedding), R3 (max cosine toi exemplar, KHONG mean/centroid)
Labeling guide: data/golden/intent_explain.md (dinh nghia 5 nhan)
Plan: docs/2026-09-02/intent-classify-embedding-eval/plan.md

B1 classify bang EMBEDDING MATCHING + CONTRASTIVE SCORING (cau hinh tot nhat da do —
run `contrastive_neg_hf_l03`, strict 51.6% / answered 59.6% tren golden):

  - Positive exemplar: data/sample/exemplars/intent_exemplars.csv (v2 — 10 mau/nhan x 4 nhan,
    complain viet lai + tron register khau ngu; SINH MOI doc lap voi gold, khong leakage).
  - Negative exemplar: data/sample/exemplars/intent_exemplar_negatives.csv (hard negative
    theo cap hay nham). Diem: score(intent) = max_cos(pos) - LAMBDA * max_cos(neg),
    LAMBDA mac dinh 0.3 (do: 0.5 kem hon). Confidence routing = raw cosine POSITIVE cua
    nhan thang => nguong 0.60/0.45 giu nguyen ngu nghia, contrastive chi RE-RANK nhan.
  - `unclassified` KHONG co exemplar: no la sink threshold-routing (§4.3) -- feedback roi
    vao do vi cosine duoi nguong low, KHONG phai vi trung mau.
  - Encoder: tai dung `embed_texts` cua step1_clustering (qwen3 qua Databricks Model Serving,
    L2-norm, cache dia) -- dung R2: exemplar va feedback PHAI cung khong gian vector.
    Encoder inject duoc (callable texts -> (N,dim)) de unit test offline khong can mang.
    KHONG dung instruct prefix (da do: -1.6 diem).

Chay:
  python src/03_inference/classify.py --eval               # eval tren data/golden/feedback_gold.csv
  python src/03_inference/classify.py --eval --hf          # ep dung fallback HF local
  python src/03_inference/classify.py "app bao loi"        # classify 1 cau
  ... --no-contrastive        # tat negative, ve duong positive-only (baseline 49.0%)
  ... --lambda 0.5            # doi he so tru
Encoder: auto (mac dinh) = probe Databricks, hong thi fallback HF local
(Qwen/Qwen3-Embedding-0.6B, sentence-transformers — plan D7, chi cho dev/eval).

Plan: docs/2026-09-02/intent-classify-embedding-eval/plan.md (khung eval),
      docs/2026-09-03/exemplar-v2-instruct-metrics/plan.md (exemplar v2 + metric 3 tang),
      docs/2026-09-03/contrastive-negative-scoring/plan.md (contrastive — cau hinh hien tai)
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import numpy as np

_HERE = Path(__file__).resolve()


def _find_up(start: Path, rel: str) -> Path:
    for p in (start, *start.parents):
        if (p / rel).exists():
            return p
    raise FileNotFoundError(f"Khong tim thay '{rel}' tu {start}")


REPO_ROOT = _find_up(_HERE, "data/golden/feedback_gold.csv")
EXEMPLAR_CSV = REPO_ROOT / "data" / "sample" / "exemplars" / "intent_exemplars.csv"
NEG_EXEMPLAR_CSV = REPO_ROOT / "data" / "sample" / "exemplars" / "intent_exemplar_negatives.csv"
GOLDEN_CSV = REPO_ROOT / "data" / "golden" / "feedback_gold.csv"
_STEP1_PY = REPO_ROOT / "src" / "01_intent_classification" / "2_phase" / "step1_clustering.py"

# Taxonomy 5 nhan (intent_explain.md); 4 nhan co exemplar + 1 sink
INTENT_LABELS = ("bug", "new_feature", "praise", "complain")
SINK_LABEL = "unclassified"

# Nguong mac dinh CHUA calibrate (ke thua ban classify cu; calibrate = buoc sau §6.3-4).
# Nguong "dung" thuoc ve intent/catalog, khong thuoc ve run.
DEFAULT_THRESHOLD_HIGH = 0.60
DEFAULT_THRESHOLD_LOW = 0.45

# He so tru cua contrastive scoring — MAC DINH BAT (cau hinh tot nhat da do).
# lam=0.3 thang lam=0.5 (51.6% vs 50.5% strict); dat None de ve duong positive-only.
DEFAULT_CONTRASTIVE_LAMBDA = 0.3

# Instruct prefix cho PHIA QUERY (dong Qwen3-Embedding train asymmetric: query co
# "Instruct: {task}\nQuery: {text}", document/exemplar KHONG prefix). Ghep o tang text
# => dung duoc cho ca encoder HF lan Databricks. (plan exemplar-v2-instruct-metrics D2)
# DA DO: prefix lam GIAM 1.6 diem => KHONG bat mac dinh, giu de tai kiem chung.
QUERY_INSTRUCTION = ("Given a user feedback about a software product, "
                     "retrieve feedback examples that express the same intent")

Encoder = Callable[[Sequence[str]], np.ndarray]  # texts -> (N, dim), da L2-norm


def default_encoder() -> Encoder:
    """`embed_texts` cua step1_clustering (qwen3 + cache dia). Import qua importlib vi
    ten thu muc bat dau bang so; top-level import cua step1 nhe (numpy).
    Phai dang ky vao sys.modules TRUOC exec_module — @dataclass trong module tra cuu
    sys.modules[cls.__module__] (Python 3.12)."""
    name = "step1_clustering"
    if name in sys.modules:
        return sys.modules[name].embed_texts
    spec = importlib.util.spec_from_file_location(name, _STEP1_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.embed_texts


# ── Fallback: HF local (plan D7) ─────────────────────────────────────────────
HF_MODEL = "Qwen/Qwen3-Embedding-0.6B"   # CUNG base voi endpoint §5 (qwen3-embedding-0-6b)
_HF_CACHE = _HERE.parent / "out" / "hf_embed_cache.json"


def hf_encoder(model_name: str = HF_MODEL) -> Encoder:
    """Encoder local qua sentence-transformers — fallback khi khong co credential Databricks.

    CANH BAO R2: cung base qwen3-0.6b nen cung khong gian vector VE NGUYEN TAC, nhung
    serving co the lech nhe (dtype/pooling) => CHI dung dev/eval; production B1 bat buoc
    Model Serving (§5). Cache RIENG (key prefix 'hf:') va embed lai toan bo text trong run —
    KHONG BAO GIO tron vector Databricks voi vector HF trong cung mot phep so cosine.
    """
    _model: list = []  # lazy — chi tai model khi co cache miss

    def _h(t: str) -> str:
        return hashlib.blake2b(f"hf:{model_name}\x00{t}".encode(), digest_size=16).hexdigest()

    def enc(texts: Sequence[str]) -> np.ndarray:
        texts = list(texts)
        cache: dict[str, list[float]] = {}
        if _HF_CACHE.exists():
            try:
                cache = json.loads(_HF_CACHE.read_text())
            except Exception:  # noqa: BLE001
                cache = {}
        todo = [t for t in dict.fromkeys(texts) if _h(t) not in cache]
        if todo:
            if not _model:
                print(f"[hf] tai model {model_name} (lan dau se download tu HuggingFace)...")
                from sentence_transformers import SentenceTransformer  # lazy import (nang)

                _model.append(SentenceTransformer(model_name))
            print(f"[hf] embed {len(todo)} text moi (cache hit {len(texts) - len(todo)})")
            vecs = _model[0].encode(todo, batch_size=8, normalize_embeddings=True,
                                    show_progress_bar=False)
            for t, v in zip(todo, vecs):
                cache[_h(t)] = [float(x) for x in v]
            _HF_CACHE.parent.mkdir(parents=True, exist_ok=True)
            _HF_CACHE.write_text(json.dumps(cache))
        out = np.asarray([cache[_h(t)] for t in texts], dtype=np.float32)
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.clip(norms, 1e-12, None)

    return enc


def resolve_encoder(mode: str = "auto") -> Encoder:
    """'databricks' | 'hf' | 'auto' (probe Databricks fail-fast, hong -> fallback HF)."""
    if mode == "hf":
        return hf_encoder()
    if mode == "databricks":
        return default_encoder()
    if mode != "auto":
        raise ValueError(f"encoder mode la: {mode!r} (hop le: auto|databricks|hf)")
    try:
        enc = default_encoder()
        sys.modules["step1_clustering"]._openai_client()  # probe auth — khong ton API call
        return enc
    except Exception as e:  # noqa: BLE001 — thieu databrickscfg/token/mang
        print(f"[encoder] Databricks khong san sang ({type(e).__name__}) "
              f"-> fallback HF local {HF_MODEL}")
        print("[encoder] CANH BAO R2: so do tu HF chi la CHI BAO dev/eval — "
              "con so chot phai do lai bang encoder production (§5).")
        return hf_encoder()


# ── Exemplar index ───────────────────────────────────────────────────────────
@dataclass
class ExemplarIndex:
    """Ma tran exemplar da embed. confidence = MAX cosine toi tung exemplar (R3),
    khong lay mean — robust voi cum phi cau, giai thich duoc ('gan mau nay nhat')."""

    labels: list[str]        # nhan cua tung dong trong `vectors` (len = so exemplar)
    texts: list[str]         # text exemplar tuong ung (de bao cao/debug)
    vectors: np.ndarray      # (n_exemplar, dim), L2-normed


def load_exemplars(csv_path: Path = EXEMPLAR_CSV) -> dict[str, list[str]]:
    """label -> [content]. Fail loud khi sai contract (nhan la / co sink / nhan thieu mau)."""
    by_label: dict[str, list[str]] = {}
    with io.open(csv_path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            label = r["label"].strip()
            if label == SINK_LABEL:
                raise ValueError(f"{csv_path.name}: '{SINK_LABEL}' la sink §4.3, khong duoc co exemplar")
            if label not in INTENT_LABELS:
                raise ValueError(f"{csv_path.name}: nhan la '{label}' (hop le: {INTENT_LABELS})")
            by_label.setdefault(label, []).append(r["content"].strip())
    missing = [l for l in INTENT_LABELS if not by_label.get(l)]
    if missing:
        raise ValueError(f"{csv_path.name}: thieu exemplar cho nhan {missing}")
    return by_label


def build_index(encoder: Encoder, csv_path: Path = EXEMPLAR_CSV) -> ExemplarIndex:
    by_label = load_exemplars(csv_path)
    labels: list[str] = []
    texts: list[str] = []
    for label in INTENT_LABELS:
        for t in by_label[label]:
            labels.append(label)
            texts.append(t)
    return ExemplarIndex(labels=labels, texts=texts, vectors=np.asarray(encoder(texts), dtype=np.float32))


def load_negatives(csv_path: Path = NEG_EXEMPLAR_CSV) -> dict[str, list[str]]:
    """NEGATIVE exemplar: `label` = intent BI TRU diem khi feedback gan cau do (contrastive
    scoring, plan contrastive-negative-scoring D2). Hien thuc hoa cot "Khong phai nhan nay
    khi" cua intent_explain.md — tach khoi index duong, dung o tang scoring.
    Khong bat buoc nhan nao cung co negative."""
    by_label: dict[str, list[str]] = {}
    with io.open(csv_path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            label = r["label"].strip()
            if label == SINK_LABEL:
                raise ValueError(f"{csv_path.name}: '{SINK_LABEL}' la sink, khong co negative")
            if label not in INTENT_LABELS:
                raise ValueError(f"{csv_path.name}: nhan la '{label}' (hop le: {INTENT_LABELS})")
            by_label.setdefault(label, []).append(r["content"].strip())
    return by_label


def build_neg_index(encoder: Encoder, csv_path: Path = NEG_EXEMPLAR_CSV) -> ExemplarIndex:
    by_label = load_negatives(csv_path)
    labels: list[str] = []
    texts: list[str] = []
    for label in INTENT_LABELS:
        for t in by_label.get(label, []):
            labels.append(label)
            texts.append(t)
    return ExemplarIndex(labels=labels, texts=texts, vectors=np.asarray(encoder(texts), dtype=np.float32))


# ── Classify ─────────────────────────────────────────────────────────────────
@dataclass
class Classification:
    label: str          # nhan du doan SAU routing (c < low => 'unclassified')
    flag: str           # ok | low_confidence | unclassified  (§4.5)
    confidence: float   # max cosine
    best_label: str     # nhan cua exemplar gan nhat (giu ca khi duoi nguong — §4.5 unclassified_pool.best_intent_id)
    best_exemplar: str  # text exemplar gan nhat (giai thich cho PM)


def classify_texts(
    texts: Sequence[str],
    index: ExemplarIndex,
    encoder: Encoder,
    threshold_high: float = DEFAULT_THRESHOLD_HIGH,
    threshold_low: float = DEFAULT_THRESHOLD_LOW,
    query_instruction: str | None = None,
) -> list[Classification]:
    """Max-cosine toi exemplar + threshold routing 3 vung (§4.3).

    c >= high        -> flag=ok             (nhan = best_label)
    low <= c < high  -> flag=low_confidence (van gan nhan, co canh bao trong INTERNAL)
    c < low          -> flag=unclassified   (KHONG doan nhan)

    `query_instruction`: neu co, feedback duoc embed dang "Instruct: ...\\nQuery: <text>"
    (CHI phia query — exemplar trong index van embed tho, khuon asymmetric Qwen3).
    """
    texts = list(texts)
    if query_instruction:
        texts = [f"Instruct: {query_instruction}\nQuery: {t}" for t in texts]
    vecs = np.asarray(encoder(texts), dtype=np.float32)
    sims = vecs @ index.vectors.T  # (N, n_exemplar) — hai phia da L2-norm => dot = cosine
    out: list[Classification] = []
    for row in sims:
        j = int(np.argmax(row))
        c = float(row[j])
        best = index.labels[j]
        if c >= threshold_high:
            flag, label = "ok", best
        elif c >= threshold_low:
            flag, label = "low_confidence", best
        else:
            flag, label = SINK_LABEL, SINK_LABEL  # khong doan nhan (§4.3)
        out.append(Classification(label=label, flag=flag, confidence=c,
                                  best_label=best, best_exemplar=index.texts[j]))
    return out


def classify_texts_contrastive(
    texts: Sequence[str],
    index: ExemplarIndex,
    neg_index: ExemplarIndex,
    encoder: Encoder,
    lam: float = 0.5,
    threshold_high: float = DEFAULT_THRESHOLD_HIGH,
    threshold_low: float = DEFAULT_THRESHOLD_LOW,
    query_instruction: str | None = None,
) -> list[Classification]:
    """Contrastive scoring (plan contrastive-negative-scoring D1):

        score(intent) = max_cos(positives cua intent) - lam * max_cos(negatives cua intent)

    Nhan = argmax score (negative DAY feedback ra khoi intent hay bi nham).
    CONFIDENCE cho routing = raw max_cos POSITIVE cua nhan thang (khong phai score da tru)
    => nguong 0.60/0.45 giu nguyen ngu nghia, so sanh duoc voi duong plain; contrastive
    chi RE-RANK nhan. lam=0 tuong duong classify_texts.
    """
    texts = list(texts)
    if query_instruction:
        texts = [f"Instruct: {query_instruction}\nQuery: {t}" for t in texts]
    vecs = np.asarray(encoder(texts), dtype=np.float32)
    pos_sims = vecs @ index.vectors.T                      # (N, n_pos)
    neg_sims = vecs @ neg_index.vectors.T if len(neg_index.labels) else None

    pos_mask = {lab: np.asarray([l == lab for l in index.labels]) for lab in INTENT_LABELS}
    neg_mask = {lab: np.asarray([l == lab for l in neg_index.labels]) for lab in INTENT_LABELS}

    out: list[Classification] = []
    for i in range(len(texts)):
        best_label, best_score, best_pos, best_j = None, -np.inf, 0.0, -1
        for lab in INTENT_LABELS:
            cols = np.flatnonzero(pos_mask[lab])
            if not cols.size:  # nhan khong co positive trong index => khong tranh cu
                continue
            j = cols[int(np.argmax(pos_sims[i, cols]))]
            s = float(pos_sims[i, j])
            n = float(np.max(neg_sims[i, neg_mask[lab]])) if (
                neg_sims is not None and neg_mask[lab].any()) else 0.0
            score = s - lam * n
            if score > best_score:
                best_label, best_score, best_pos, best_j = lab, score, s, int(j)
        c = best_pos  # raw cosine positive cua nhan thang — routing nhu duong plain
        if c >= threshold_high:
            flag, label = "ok", best_label
        elif c >= threshold_low:
            flag, label = "low_confidence", best_label
        else:
            flag, label = SINK_LABEL, SINK_LABEL
        out.append(Classification(label=label, flag=flag, confidence=c,
                                  best_label=best_label, best_exemplar=index.texts[best_j]))
    return out


# ── Eval tren golden dataset ─────────────────────────────────────────────────
def load_golden(csv_path: Path = GOLDEN_CSV) -> list[dict[str, str]]:
    """192 dong feedback_gold.csv; them `id` = fb_<idx:04d> theo thu tu dong."""
    with io.open(csv_path, encoding="utf-8-sig") as f:
        return [{**r, "id": f"fb_{i:04d}"} for i, r in enumerate(csv.DictReader(f))]


def _prf(confusion: dict[str, dict[str, int]], labels: Sequence[str]) -> dict:
    """P/R/F1 tung nhan tu confusion (hang=gold, cot=pred)."""
    out = {}
    for lab in labels:
        tp = confusion[lab][lab]
        support = sum(confusion[lab].values())
        pred_n = sum(confusion[g][lab] for g in labels)
        prec = tp / pred_n if pred_n else 0.0
        rec = tp / support if support else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        out[lab] = {"precision": prec, "recall": rec, "f1": f1,
                    "support": support, "predicted": pred_n}
    return out


def evaluate_golden(
    encoder: Encoder | None = None,
    threshold_high: float = DEFAULT_THRESHOLD_HIGH,
    threshold_low: float = DEFAULT_THRESHOLD_LOW,
    query_instruction: str | None = None,
    contrastive_lambda: float | None = DEFAULT_CONTRASTIVE_LAMBDA,
    negatives_csv: Path = NEG_EXEMPLAR_CSV,
    verbose: bool = True,
) -> dict:
    """Classify ca bo gold, so voi nhan vang. Tra dict metrics (test dung lai duoc).

    `contrastive_lambda`: mac dinh DEFAULT_CONTRASTIVE_LAMBDA (0.3) = cau hinh tot nhat;
    dat None de do duong positive-only (baseline).

    3 tang metric (plan exemplar-v2-instruct-metrics D3) — key cu giu nguyen de so run cu:
      (strict) accuracy 5-nhan nhu cu (abstention tron vao — chi de noi tiep lich su);
      (i) `answered`: chat luong PHAN LOAI tren dong model KHONG abstain va gold co nhan
          that (confusion 4x4, P/R/F1); `abstention`: caught/false_abstain/false_accept;
      (ii) `coverage_curve`: quet nguong abstain 0.30->0.75, moi diem (coverage, accuracy
          tren dong tra loi) — chon nguong theo trade-off thay vi mot diem don le.
    """
    encoder = encoder or resolve_encoder("auto")
    gold_rows = load_golden()
    index = build_index(encoder)
    # .strip() de khop hash cache cua step1 (191/192 golden da embed tu Phase 0)
    texts = [r["content"].strip() for r in gold_rows]
    if contrastive_lambda is not None:
        neg_index = build_neg_index(encoder, negatives_csv)
        preds = classify_texts_contrastive(texts, index, neg_index, encoder,
                                           lam=contrastive_lambda,
                                           threshold_high=threshold_high,
                                           threshold_low=threshold_low,
                                           query_instruction=query_instruction)
    else:
        preds = classify_texts(texts, index, encoder,
                               threshold_high, threshold_low, query_instruction=query_instruction)

    # ---------- (strict) 5-nhan nhu cu ----------
    all_labels = [*INTENT_LABELS, SINK_LABEL]
    confusion = {g: {p: 0 for p in all_labels} for g in all_labels}
    flags = {"ok": 0, "low_confidence": 0, SINK_LABEL: 0}
    errors = []
    for row, pr in zip(gold_rows, preds):
        g = row["label"]
        confusion[g][pr.label] += 1
        flags[pr.flag] += 1
        if pr.label != g:
            errors.append((row["id"], g, pr.label, pr.confidence, row["content"][:60]))
    n = len(gold_rows)
    correct = sum(confusion[l][l] for l in all_labels)
    per_label = _prf(confusion, all_labels)

    # ---------- (i) tach abstention khoi chat luong phan loai ----------
    conf4 = {g: {p: 0 for p in INTENT_LABELS} for g in INTENT_LABELS}
    abst = {"gold_unclassified": 0, "caught": 0, "false_accept": 0, "false_abstain": 0}
    for row, pr in zip(gold_rows, preds):
        g = row["label"]
        abstained = pr.flag == SINK_LABEL
        if g == SINK_LABEL:
            abst["gold_unclassified"] += 1
            abst["caught" if abstained else "false_accept"] += 1
        elif abstained:
            abst["false_abstain"] += 1
        else:
            conf4[g][pr.label] += 1
    n_ans = sum(sum(r.values()) for r in conf4.values())
    corr_ans = sum(conf4[l][l] for l in INTENT_LABELS)
    answered = {
        "n": n_ans,
        "accuracy": corr_ans / n_ans if n_ans else 0.0,
        "per_label": _prf(conf4, INTENT_LABELS),
        "confusion": conf4,
    }

    # ---------- (ii) duong coverage–accuracy (nhan = best_label, abstain neu conf < t) ----------
    curve = []
    for t10 in range(30, 80, 5):
        t = t10 / 100
        ans = [(row, pr) for row, pr in zip(gold_rows, preds) if pr.confidence >= t]
        real = [(row, pr) for row, pr in ans if row["label"] != SINK_LABEL]
        curve.append({
            "threshold": t,
            "coverage": len(ans) / n,
            "n_answered": len(ans),
            # gold-unclassified duoc tra loi => tinh la SAI (model dang le phai bo phieu trang)
            "acc_answered": (sum(pr.best_label == row["label"] for row, pr in ans) / len(ans))
                            if ans else 0.0,
            # chi xet dong gold co nhan that: chat luong xep hang thuan
            "acc_answered_gold_real": (sum(pr.best_label == row["label"] for row, pr in real)
                                       / len(real)) if real else 0.0,
        })

    metrics = {
        "n": n,
        "accuracy": correct / n,
        "per_label": per_label,
        "confusion": confusion,
        "flags": flags,
        "thresholds": {"high": threshold_high, "low": threshold_low},
        "query_instruction": query_instruction,
        "contrastive_lambda": contrastive_lambda,
        "answered": answered,
        "abstention": abst,
        "coverage_curve": curve,
        "errors": errors,
    }

    if verbose:
        qi = " + instruct-prefix" if query_instruction else ""
        ct = f" + contrastive lam={contrastive_lambda}" if contrastive_lambda is not None else ""
        print(f"== Eval B1 embedding-matching tren {GOLDEN_CSV.relative_to(REPO_ROOT)}"
              f" (nguong high={threshold_high} low={threshold_low}{qi}{ct})")
        print(f"  accuracy strict 5-nhan (lich su): {correct}/{n} = {metrics['accuracy']:.1%}")

        print(f"\n-- (i) Chat luong phan loai khi model TRA LOI"
              f" (gold co nhan that, khong abstain): {corr_ans}/{n_ans}"
              f" = {answered['accuracy']:.1%}")
        print(f"  {'label':<14}{'prec':>7}{'recall':>8}{'f1':>7}{'support':>9}{'predicted':>11}")
        for lab in INTENT_LABELS:
            m = answered["per_label"][lab]
            print(f"  {lab:<14}{m['precision']:>7.2f}{m['recall']:>8.2f}{m['f1']:>7.2f}"
                  f"{m['support']:>9}{m['predicted']:>11}")
        print(f"\n  confusion 4x4 (hang=gold, cot=pred):")
        head = "".join(f"{l[:9]:>11}" for l in INTENT_LABELS)
        print(f"  {'':<14}{head}")
        for g in INTENT_LABELS:
            print(f"  {g:<14}" + "".join(f"{conf4[g][p]:>11}" for p in INTENT_LABELS))
        print(f"\n  abstention: gold_unclassified={abst['gold_unclassified']}"
              f" | chan dung (caught)={abst['caught']}"
              f" | gan nhan nham (false_accept)={abst['false_accept']}"
              f" | bo phieu trang oan (false_abstain)={abst['false_abstain']}")
        print(f"  phan bo 3 vung: ok={flags['ok']}  low_confidence={flags['low_confidence']}"
              f"  unclassified={flags[SINK_LABEL]}")

        print(f"\n-- (ii) Coverage–accuracy (abstain khi conf < t; nhan = exemplar gan nhat)")
        print(f"  {'t':>6}{'coverage':>10}{'n_ans':>7}{'acc_ans':>9}{'acc_gold_real':>15}")
        for p in curve:
            print(f"  {p['threshold']:>6.2f}{p['coverage']:>10.1%}{p['n_answered']:>7}"
                  f"{p['acc_answered']:>9.1%}{p['acc_answered_gold_real']:>15.1%}")

        print(f"\n  sai {len(errors)} dong theo strict (id | gold -> pred | conf | content):")
        for fid, g, p, c, txt in errors:
            print(f"    {fid} | {g} -> {p} | {c:.2f} | {txt}")
    return metrics


# ── CLI ──────────────────────────────────────────────────────────────────────
def main(argv: list[str]) -> int:
    mode = "auto"
    lam: float | None = DEFAULT_CONTRASTIVE_LAMBDA
    if "--hf" in argv:
        mode, argv = "hf", [a for a in argv if a != "--hf"]
    if "--databricks" in argv:
        mode, argv = "databricks", [a for a in argv if a != "--databricks"]
    if "--no-contrastive" in argv:
        lam, argv = None, [a for a in argv if a != "--no-contrastive"]
    if "--lambda" in argv:
        i = argv.index("--lambda")
        lam = float(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    if not argv or argv[0] in {"-h", "--help"}:
        print(__doc__)
        return 0
    if argv[0] == "--eval":
        evaluate_golden(encoder=resolve_encoder(mode), contrastive_lambda=lam)
        return 0

    encoder = resolve_encoder(mode)
    index = build_index(encoder)
    if lam is None:
        preds = classify_texts(argv, index, encoder)
    else:
        preds = classify_texts_contrastive(argv, index, build_neg_index(encoder), encoder, lam=lam)
    for pr in preds:
        print(f"{pr.label:<14} flag={pr.flag:<15} conf={pr.confidence:.3f} "
              f"(gan nhat: [{pr.best_label}] «{pr.best_exemplar[:50]}»)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
