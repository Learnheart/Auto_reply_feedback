"""B1 classify — so feedback với Intent Catalog bằng exemplar cosine + routing 3 vùng.

Module: inference.classify (B1).
Architecture: docs/architecture.md §3 (inference.classify), §4.2 Flow B (embed → max-cosine → intent),
  §4.3 Threshold routing (c≥high→ok · low≤c<high→low_confidence · c<low→unclassified).
Catalog contract: docs/method-offline-intent-analysis.md §10.
Plan: docs/2026-08-26/inference-classify-respond/plan.md (R2, D3).

Tái dùng engine đã chốt của `embedding_test.py`: normalize()/split_clauses() (cùng hàm cho index và
inference), encoder qwen3 (symmetric, L2-norm client-side). v3.3: default `DatabricksEncoder` (Model Serving,
architecture §5) thay `LMStudioEncoder` local — inject LMStudioEncoder cho test offline. File này chỉ thêm
lớp: nạp exemplar từ CatalogIntent thật + routing theo ngưỡng từng nhãn thay vì taxonomy hardcode.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from catalog import CatalogIntent
from embedding_test import DatabricksEncoder, normalize, split_clauses

# flag §4.3 — trục quyết định của cả B2 (respond.py).
FLAG_OK = "ok"
FLAG_LOW = "low_confidence"
FLAG_UNCLASSIFIED = "unclassified"


@dataclass
class Classification:
    """Kết quả B1 cho 1 feedback → ghi feedback_processing (§4.5)."""

    feedback: str
    intent_id: str | None            # None khi unclassified (KHÔNG đoán nhãn — §4.3)
    action_type: str | None          # copy từ intent trúng, để respond khỏi tra lại catalog
    confidence: float
    flag: str                        # ok | low_confidence | unclassified
    best_intent_id: str              # intent gần nhất DÙ dưới ngưỡng — nuôi unclassified_pool
    best_confidence: float
    evidence: str                    # mệnh đề kích hoạt nhãn (giải thích cho PM)


class IntentClassifier:
    """Index exemplar của mọi CatalogIntent một lần; `classify()` cho từng feedback mới."""

    def __init__(self, intents: list[CatalogIntent], encoder=None):
        self.intents = {i.intent_id: i for i in intents}
        # v3.3: default Databricks Model Serving (đúng architecture §5); inject LMStudioEncoder cho test offline.
        self.encoder = encoder or DatabricksEncoder()
        self._build_index()

    def _build_index(self) -> None:
        texts, owners = [], []
        for intent in self.intents.values():
            for ex in intent.exemplars:
                norm = normalize(ex)
                if norm:
                    texts.append(norm)
                    owners.append(intent.intent_id)
        if not texts:
            raise ValueError("Không có exemplar nào để index.")
        self.matrix = self.encoder.encode(texts)   # (N, D) đã L2-norm ⇒ dot == cosine
        self.owners = np.array(owners)

    def classify(self, feedback: str) -> Classification:
        """embed (tách mệnh đề) → max cosine → intent trúng + routing theo ngưỡng của chính nhãn đó."""
        clean = normalize(feedback)
        if not clean:
            return Classification(feedback, None, None, 0.0, FLAG_UNCLASSIFIED, "", 0.0, "")

        clauses = split_clauses(clean)
        vecs = self.encoder.encode(clauses)         # (C, D)
        sims = vecs @ self.matrix.T                 # (C, N) cosine

        # confidence = max cosine GLOBAL tới mọi exemplar (§4.2); nhãn trúng = chủ exemplar đó,
        # mệnh đề chứng cứ = mệnh đề đạt max (giải thích được cho PM: "gần ví dụ này nhất").
        g_ci, g_n = np.unravel_index(int(np.argmax(sims)), sims.shape)
        best_intent_id = str(self.owners[g_n])
        best_confidence = float(sims[g_ci, g_n])
        evidence = clauses[g_ci]

        intent = self.intents[best_intent_id]
        if best_confidence >= intent.threshold_high:
            flag = FLAG_OK
        elif best_confidence >= intent.threshold_low:
            flag = FLAG_LOW
        else:
            flag = FLAG_UNCLASSIFIED

        assigned = None if flag == FLAG_UNCLASSIFIED else best_intent_id
        action = None if assigned is None else intent.action_type
        return Classification(
            feedback=feedback,
            intent_id=assigned,
            action_type=action,
            confidence=round(best_confidence, 4),
            flag=flag,
            best_intent_id=best_intent_id,
            best_confidence=round(best_confidence, 4),
            evidence=evidence,
        )


if __name__ == "__main__":
    from catalog import load_catalog

    clf = IntentClassifier(load_catalog())
    for s in [
        "app tạo slide bị lỗi, gửi lại html rồi không nhận lệnh nữa",
        "mong team thêm tính năng upload nhiều file cùng lúc",
        "dùng ổn lắm cảm ơn team nhiều",
        "hôm nay trời đẹp quá đi mất",
    ]:
        r = clf.classify(s)
        print(f"\n> {s}\n  {r.flag:<14} {r.intent_id or '—':<38} c={r.confidence}  «{r.evidence[:50]}»")
