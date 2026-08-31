"""
Module: Offline intent analysis (Phase 0) — Hướng A · STEP 1: clustering (KHÔNG LLM)
Architecture: docs/architecture.md §3 Phase 0 (Embedding→HDBSCAN), §5 Technology Stack, §6.1 R3
Method:       docs/method-offline-intent-analysis.md §2 (audit+preprocess), §3 (embed),
              §4 (cluster + đọc noise)
Plan:         docs/2026-08-26/intent-classification-rebuild/plan.md

STEP 1 chỉ làm phần unsupervised, không gọi LLM:

    load → preprocess → embed(qwen3, cache) → UMAP(10D) → HDBSCAN(over-segment, leaf)
         → cluster_report (cosine similarity) → out/cluster_report.csv + cluster_summary.csv

File này cũng giữ các SHARED HELPER về dữ liệu/embedding/serving-client mà STEP 2
(`step2_llm_label_merge.py`) import lại. STEP 2 (LLM đặt tên/gộp) nằm ở file riêng.

Chạy:  python step1_clustering.py
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence

import numpy as np

try:
    from zoneinfo import ZoneInfo
    _VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")   # giờ Việt Nam (UTC+7)
except Exception:  # noqa: BLE001  (thiếu tzdata → fallback giờ máy)
    _VN_TZ = None

# ── Paths & config ───────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent


def _find_up(start: Path, rel: str, depth: int = 6) -> Path:
    """Đi ngược lên cây thư mục tìm nơi có `rel` — bám repo-root dù file nằm ở
    thư mục con nào (an toàn khi di chuyển file, không phụ thuộc độ sâu)."""
    p = start
    for _ in range(depth):
        if (p / rel).exists():
            return p
        p = p.parent
    return start


REPO_ROOT = _find_up(ROOT, "data/sample/feedback/feedback_extracted.csv")
DATA_CSV = REPO_ROOT / "data" / "sample" / "feedback" / "feedback_extracted.csv"
OUT_DIR = ROOT.parent / "out"   # bám vị trí MODULE (src/01_intent_classification/out), không
                                # hardcode tên thư mục → an toàn khi đổi tên/di chuyển package
EMBED_CACHE = OUT_DIR / "embed_cache.json"               # cache — cố tình KHÔNG timestamp


def run_dir(phase: str) -> Path:
    """Thư mục KẾT QUẢ cho mỗi lần chạy: out/<YYYYmmdd_HHMMSS>_<phase> (giờ VN).

    Mỗi lần chạy ghi vào một folder riêng ⇒ KHÔNG ghi đè kết quả cũ. Chỉ dùng cho
    output (report/catalog); `embed_cache.json` vẫn nằm ở OUT_DIR để tái dùng.
    """
    ts = datetime.now(_VN_TZ).strftime("%Y%m%d_%H%M%S")
    d = OUT_DIR / f"{ts}_{phase}"
    d.mkdir(parents=True, exist_ok=True)
    return d

SEED = 42
PROFILE = os.environ.get("DATABRICKS_PROFILE", "tcb-agent-sit")
EMBED_MODEL = "databricks-qwen3-embedding-0-6b"   # §5 architecture (đa ngôn ngữ, dim 1024)
CHAT_MODEL = "databricks-claude-sonnet-4-6"       # tên endpoint THẬT (≠ -sit-tai ở §5)
EMBED_DIM = 1024


# ── Data model ───────────────────────────────────────────────────────────────
@dataclass
class Feedback:
    feedback_id: str
    agent: str
    content: str
    category: str
    created_at: str


# ══════════════════════════════════════════════════════════════════════════════
# SHARED HELPERS  (data / embedding / serving-client — STEP 2 import lại)
# ══════════════════════════════════════════════════════════════════════════════

# -- data ---------------------------------------------------------------------
def load_feedback(csv_path: Path = DATA_CSV) -> list[Feedback]:
    """Đọc feedback thật. feedback_id = fb_<index> ổn định theo thứ tự file."""
    import csv

    rows: list[Feedback] = []
    with open(csv_path, encoding="utf-8-sig") as f:
        for i, r in enumerate(csv.DictReader(f)):
            rows.append(
                Feedback(
                    feedback_id=f"fb_{i:04d}",
                    agent=(r.get("agent") or "").strip(),
                    content=(r.get("content") or "").strip(),
                    category=(r.get("category") or "").strip(),
                    created_at=(r.get("date") or "").strip(),
                )
            )
    return rows


def preprocess(items: list[Feedback]) -> list[Feedback]:
    """Giữ HẾT feedback của user; chỉ bỏ content không có một ký tự chữ nào.

    §2.2 method: không lọc theo độ dài, không dedup exact, không lowercase/bỏ dấu.
    Tiêu chí giữ: any(ch.isalpha()) (Unicode — gồm tiếng Việt & mọi ngôn ngữ).
    """
    kept = [it for it in items if any(ch.isalpha() for ch in it.content)]
    dropped = len(items) - len(kept)
    print(f"[preprocess] giữ {len(kept)} / {len(items)} feedback (bỏ {dropped} content vô nghĩa)")
    return kept


# -- Databricks serving client (OpenAI-compat) --------------------------------
_CLIENT = None


def _openai_client():
    """OpenAI client trỏ vào Databricks Model Serving.

    Auth: OAuth theo profile ~/.databrickscfg (mặc định tcb-agent-sit) hoặc
    env DATABRICKS_HOST/DATABRICKS_TOKEN. TLS qua truststore vì mạng công ty
    MITM bằng CA nội bộ (giống src/02_knowledge/mcp_atlassian_call.py).
    """
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT

    import httpx
    import truststore
    from openai import OpenAI

    host = os.environ.get("DATABRICKS_HOST")
    token = os.environ.get("DATABRICKS_TOKEN")
    if not (host and token):
        from databricks.sdk import WorkspaceClient

        cfg = WorkspaceClient(profile=PROFILE).config
        host = cfg.host
        token = cfg.authenticate().get("Authorization", "").replace("Bearer ", "")

    base = host.rstrip("/") + "/serving-endpoints"
    ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    _CLIENT = OpenAI(base_url=base, api_key=token, http_client=httpx.Client(verify=ctx, timeout=120))
    return _CLIENT


# -- embedding (cache đĩa, plan D7) -------------------------------------------
def _hash(text: str) -> str:
    return hashlib.blake2b(f"{EMBED_MODEL}\x00{text}".encode(), digest_size=16).hexdigest()


def _load_cache() -> dict[str, list[float]]:
    if EMBED_CACHE.exists():
        try:
            return json.loads(EMBED_CACHE.read_text())
        except Exception:  # noqa: BLE001
            return {}
    return {}


def embed_texts(texts: Sequence[str], batch_size: int = 64) -> np.ndarray:
    """Embed qua qwen3 (Model Serving), cache theo hash. Trả (N, dim) đã L2-norm."""
    texts = list(texts)
    cache = _load_cache()
    todo = [t for t in dict.fromkeys(texts) if _hash(t) not in cache]  # unique, chưa cache

    if todo:
        client = _openai_client()
        print(f"[embed] gọi qwen3 cho {len(todo)} text mới (cache hit {len(texts) - len(todo)})")
        for i in range(0, len(todo), batch_size):
            chunk = todo[i : i + batch_size]
            resp = client.embeddings.create(model=EMBED_MODEL, input=chunk)
            for d in sorted(resp.data, key=lambda d: d.index):
                cache[_hash(chunk[d.index])] = d.embedding
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        EMBED_CACHE.write_text(json.dumps(cache))
    else:
        print(f"[embed] toàn bộ {len(texts)} text đã có trong cache")

    vecs = np.asarray([cache[_hash(t)] for t in texts], dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs / np.clip(norms, 1e-12, None)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — clustering (HDBSCAN over UMAP)
# ══════════════════════════════════════════════════════════════════════════════

def reduce_dims(vecs: np.ndarray, n_components: int = 10, n_neighbors: int = 8) -> np.ndarray:
    """UMAP về không gian chiều thấp (§4.1 method). n_components=10, metric cosine.

    n_neighbors NHỎ (8) để giữ cấu trúc CỤC BỘ — ở n nhỏ, n_neighbors lớn (15) làm
    UMAP nối các chủ đề khác nhau thành ít blob to, khiến HDBSCAN under-resolve.
    n nhỏ ⇒ giới hạn n_neighbors < n. random_state cố định để tái lập (§4.3).
    """
    import umap

    n = vecs.shape[0]
    reducer = umap.UMAP(
        n_neighbors=max(2, min(n_neighbors, n - 1)),
        n_components=min(n_components, n - 2),
        metric="cosine",
        random_state=SEED,
    )
    return reducer.fit_transform(vecs)


def cluster(
    reduced: np.ndarray,
    min_cluster_size: int,
    min_samples: int = 1,
    selection: str = "leaf",
) -> np.ndarray:
    """HDBSCAN. `selection='leaf'` (KHÔNG phải 'eom' mặc định): lấy cụm ở lá cây phân
    cấp ⇒ nhiều cụm nhỏ ĐỒNG NHẤT thay vì vài cụm-cha to lẫn. Đây là điều kiện để
    'cố tình over-segment' (§4.2) hoạt động — eom gom ~55% data vào 1-2 blob khổng lồ."""
    import hdbscan

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        metric="euclidean",
        cluster_selection_method=selection,
    )
    return clusterer.fit_predict(reduced)


def cluster_sweep(reduced: np.ndarray) -> np.ndarray:
    """Cố tình over-segment (§4.2) bằng leaf-extraction. Sweep min_cluster_size;
    ưu tiên cấu hình 15–40 cụm sạch với noise thấp nhất; nếu không đạt lấy điểm cao nhất."""
    best_labels, best_score = None, -1e9
    for mcs in (4, 3, 5, 6, 8):
        labels = cluster(reduced, mcs)
        n_clusters = len({l for l in labels if l >= 0})
        noise = float((labels < 0).mean())
        print(f"[cluster] min_cluster_size={mcs} (leaf): {n_clusters} cụm, noise {noise:.0%}")
        if n_clusters == 0:
            continue
        in_range = 15 <= n_clusters <= 40 and noise < 0.25
        # over-segment (§4.2): trong dải ⇒ ưu tiên NHIỀU cụm sạch (LLM sẽ gộp), phạt nhẹ noise;
        # ngoài dải ⇒ kéo về gần dải, ít noise.
        score = (1000 + n_clusters - noise * 30) if in_range else (n_clusters - abs(25 - n_clusters) - noise * 20)
        if score > best_score:
            best_labels, best_score = labels, score
    if best_labels is None:  # fallback: mọi điểm một cụm
        best_labels = np.zeros(reduced.shape[0], dtype=int)
    n_final = len({l for l in best_labels if l >= 0})
    print(f"[cluster] chọn cấu hình: {n_final} cụm, noise {(best_labels < 0).mean():.0%}")
    return best_labels


# ══════════════════════════════════════════════════════════════════════════════
# CLUSTER REPORT — cosine similarity (deliverable của STEP 1)
# ══════════════════════════════════════════════════════════════════════════════

def _medoid_order(idxs: list[int], vecs: np.ndarray) -> list[int]:
    """Sắp các index trong cụm theo độ gần medoid (cosine)."""
    sub = vecs[idxs]
    sim = sub @ sub.T
    center = int(np.argmax(sim.sum(axis=1)))
    order = np.argsort(-sim[center])
    return [idxs[i] for i in order]


def _members_by_cluster(labels: np.ndarray) -> dict[int, list[int]]:
    out: dict[int, list[int]] = {}
    for i, l in enumerate(labels):
        out.setdefault(int(l), []).append(i)
    return out


def cluster_report(
    labels: np.ndarray, items: list[Feedback], vecs: np.ndarray, out_dir: Path
) -> dict:
    """Report chất lượng cụm bằng COSINE SIMILARITY (không cần LLM). Đo trên embedding
    gốc (ngữ nghĩa), vecs đã L2-norm ⇒ cosine = tích vô hướng.

    - Medoid mỗi cụm = feedback có tổng cosine tới các thành viên khác lớn nhất.
    - Cohesion  = cosine mỗi thành viên → medoid (mean / min = độ chặt của cụm).
    - Separation = cosine medoid↔medoid tới cụm gần nhất (thấp = tách tốt).

    Ghi vào `out_dir`: cluster_report.csv (per-member, có cosine_to_medoid) + cluster_summary.csv.
    """
    import csv

    members = _members_by_cluster(labels)
    cluster_ids = sorted(cid for cid in members if cid >= 0)

    medoid_idx: dict[int, int] = {}
    cos_to_medoid: dict[int, dict[int, float]] = {}
    for cid in cluster_ids:
        idxs = members[cid]
        sub = vecs[idxs]
        sim = sub @ sub.T
        center = int(np.argmax(sim.sum(axis=1)))
        medoid_idx[cid] = idxs[center]
        cos_to_medoid[cid] = {idxs[k]: float(sim[center, k]) for k in range(len(idxs))}

    # separation: cosine giữa các medoid
    if len(cluster_ids) > 1:
        med = np.vstack([vecs[medoid_idx[cid]] for cid in cluster_ids])
        med_sim = med @ med.T
    nearest: dict[int, tuple] = {}
    for a, cid in enumerate(cluster_ids):
        if len(cluster_ids) > 1:
            row = med_sim[a].copy()
            row[a] = -1.0
            b = int(np.argmax(row))
            nearest[cid] = (cluster_ids[b], float(row[b]))
        else:
            nearest[cid] = (None, float("nan"))

    out_dir.mkdir(parents=True, exist_ok=True)

    # per-member report (feedback + cosine_to_medoid của cụm nó)
    with open(out_dir / "cluster_report.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["cluster_id", "feedback_id", "agent", "is_medoid",
                     "cosine_to_medoid", "content"])
        for cid in cluster_ids:
            for j in _medoid_order(members[cid], vecs):
                wr.writerow([cid, items[j].feedback_id, items[j].agent,
                             int(j == medoid_idx[cid]),
                             round(cos_to_medoid[cid][j], 4), items[j].content])
        for j in members.get(-1, []):  # noise: cosine trống
            wr.writerow([-1, items[j].feedback_id, items[j].agent, 0, "", items[j].content])

    # per-cluster summary (cohesion + separation)
    summary_rows = []
    for cid in cluster_ids:
        cs = list(cos_to_medoid[cid].values())
        near_id, near_cos = nearest[cid]
        summary_rows.append({
            "cluster_id": cid,
            "size": len(members[cid]),
            "medoid_feedback_id": items[medoid_idx[cid]].feedback_id,
            "cohesion_mean_cos": round(float(np.mean(cs)), 4),
            "cohesion_min_cos": round(float(np.min(cs)), 4),
            "nearest_cluster": near_id if near_id is not None else "",
            "separation_cos": round(near_cos, 4) if near_id is not None else "",
            "medoid_content": items[medoid_idx[cid]].content,
        })
    with open(out_dir / "cluster_summary.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()) if summary_rows else
                            ["cluster_id", "size", "medoid_feedback_id", "cohesion_mean_cos",
                             "cohesion_min_cos", "nearest_cluster", "separation_cos", "medoid_content"])
        wr.writeheader()
        wr.writerows(summary_rows)

    # console
    noise_n = len(members.get(-1, []))
    rel = out_dir.relative_to(OUT_DIR.parent)
    print(f"\n[report] {len(cluster_ids)} cụm · noise {noise_n}/{len(items)} "
          f"({noise_n / len(items):.0%})  → {rel}/cluster_report.csv + cluster_summary.csv")
    print(f"\n  {'cid':>4} {'size':>4} {'cohes':>6} {'min':>6} {'near':>4} {'sep':>6}  medoid")
    for r in sorted(summary_rows, key=lambda x: -x["size"]):
        print(f"  {r['cluster_id']:>4} {r['size']:>4} {r['cohesion_mean_cos']:>6.3f} "
              f"{r['cohesion_min_cos']:>6.3f} {str(r['nearest_cluster']):>4} "
              f"{r['separation_cos']:>6} {r['medoid_content'][:54]}")

    return {"summary": summary_rows, "medoid_idx": medoid_idx, "noise": noise_n}


def run_step1() -> tuple[np.ndarray, list[Feedback], np.ndarray]:
    print("\n=== STEP 1: clustering (KHÔNG LLM) ===")
    out_dir = run_dir("clustering")            # out/<date_time>_clustering (không ghi đè)
    items = preprocess(load_feedback())
    vecs = embed_texts([it.content for it in items])
    reduced = reduce_dims(vecs)
    labels = cluster_sweep(reduced)
    cluster_report(labels, items, vecs, out_dir)
    return labels, items, vecs


if __name__ == "__main__":
    run_step1()
