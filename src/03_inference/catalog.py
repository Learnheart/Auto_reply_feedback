"""Nạp Intent Catalog (artifact frozen) + resolve exemplar từ feedback thật.

Module: inference.classify (B1) — input tĩnh Intent Catalog.
Architecture: docs/architecture.md §3 (Intent Catalog = input tĩnh, read-only),
  §4.5 Data layer (intent_catalog: intent_id, label, description, action_type, exemplar, threshold).
Catalog contract: docs/method-offline-intent-analysis.md §10 (schema intents.yaml).
Plan: docs/2026-08-26/inference-classify-respond/plan.md (R1, D1).

Catalog v1 (`catalog_a.yaml`) chưa gắn cột `exemplar_vectors`; nó tham chiếu `supporting_feedback_ids`.
Ta resolve id → text feedback thật để làm exemplar. Map id KHỚP `step1_clustering.load_feedback`:
`fb_<i:04d>` = row index (0-based) trong `data/sample/feedback/feedback_extracted.csv` (đọc bằng
csv.DictReader, encoding utf-8-sig). Đổi cách sinh id ở STEP 1 ⇒ phải đổi cả ở đây.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

# action_type enum §5 method / §4.5 arch. answer_from_kb chưa có trong catalog v1 nhưng
# router (respond.py) wire sẵn — sẽ tự kích hoạt khi PM gắn intent này (plan D1).
ACTION_TYPES = {"answer_from_kb", "known_gap", "ack_only"}

_HERE = Path(__file__).resolve()


def _find_up(start: Path, marker: str) -> Path:
    """Đi ngược cây thư mục tới khi thấy `marker` — định vị repo root không hardcode."""
    for p in (start, *start.parents):
        if (p / marker).exists():
            return p
    raise FileNotFoundError(f"Không tìm thấy '{marker}' từ {start}")


REPO_ROOT = _find_up(_HERE, "data/sample/feedback/feedback_extracted.csv")
DEFAULT_FEEDBACK_CSV = REPO_ROOT / "data" / "sample" / "feedback" / "feedback_extracted.csv"
DEFAULT_CATALOG = (
    REPO_ROOT / "src" / "01_intent_classification" / "out" / "20260826_180647_llm" / "catalog_a.json"
)

# Ngưỡng mặc định khi catalog chưa calibrate (plan D3). Ngưỡng "đúng" thuộc về intent, không thuộc run.
DEFAULT_THRESHOLD_HIGH = 0.60
DEFAULT_THRESHOLD_LOW = 0.45
DEFAULT_MAX_EXEMPLARS = 5  # §6.3 R3: 3-5 mẫu thật/intent


@dataclass
class CatalogIntent:
    """Một intent trong catalog + exemplar đã resolve. `description`/`label` cho prompt LLM, KHÔNG embed."""

    intent_id: str
    label: str
    description: str
    action_type: str
    exemplars: list[str] = field(default_factory=list)  # text feedback thật — chỉ phần này đi vào index
    threshold_high: float = DEFAULT_THRESHOLD_HIGH
    threshold_low: float = DEFAULT_THRESHOLD_LOW
    supporting_feedback_ids: list[str] = field(default_factory=list)


def load_feedback_index(csv_path: Path = DEFAULT_FEEDBACK_CSV) -> dict[str, str]:
    """`fb_<i:04d>` -> content. Cùng thứ tự/encoding với step1_clustering.load_feedback."""
    index: dict[str, str] = {}
    with open(csv_path, encoding="utf-8-sig") as f:
        for i, row in enumerate(csv.DictReader(f)):
            index[f"fb_{i:04d}"] = (row.get("content") or "").strip()
    return index


def load_catalog(
    catalog_path: Path = DEFAULT_CATALOG,
    feedback_csv: Path = DEFAULT_FEEDBACK_CSV,
    max_exemplars: int = DEFAULT_MAX_EXEMPLARS,
) -> list[CatalogIntent]:
    """Nạp catalog YAML + gắn exemplar từ `supporting_feedback_ids`.

    Bỏ intent `unclassified` khỏi tập matcher: nó là *sink* (§4.3), không phải nhãn để so cosine.
    Feedback rơi vào `unclassified` là do dưới ngưỡng (routing), không phải do trúng exemplar.
    """
    raw = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    fb_index = load_feedback_index(feedback_csv)

    intents: list[CatalogIntent] = []
    for it in raw.get("intents", []):
        intent_id = it["intent_id"]
        if intent_id == "unclassified":
            continue  # sink, không index (plan R1)

        action_type = it.get("action_type", "ack_only")
        if action_type not in ACTION_TYPES:
            raise ValueError(f"intent '{intent_id}' có action_type lạ: {action_type!r} (enum {ACTION_TYPES})")

        ids = it.get("supporting_feedback_ids", []) or []
        exemplars: list[str] = []
        for fid in ids:
            text = fb_index.get(fid, "").strip()
            if text:
                exemplars.append(text)
            if len(exemplars) >= max_exemplars:
                break
        if not exemplars:
            raise ValueError(
                f"intent '{intent_id}' không resolve được exemplar nào từ {len(ids)} id — "
                f"kiểm tra map fb_id ↔ {feedback_csv.name}"
            )

        intents.append(
            CatalogIntent(
                intent_id=intent_id,
                label=it.get("label", intent_id),
                description=it.get("description", ""),
                action_type=action_type,
                exemplars=exemplars,
                threshold_high=float(it.get("threshold_high", DEFAULT_THRESHOLD_HIGH)),
                threshold_low=float(it.get("threshold_low", DEFAULT_THRESHOLD_LOW)),
                supporting_feedback_ids=list(ids),
            )
        )

    if not intents:
        raise ValueError(f"Catalog {catalog_path} không có intent nào để index (ngoài unclassified).")
    return intents


if __name__ == "__main__":
    cat = load_catalog()
    print(f"{len(cat)} intent (đã bỏ unclassified sink):\n")
    for c in cat:
        print(f"• {c.intent_id:<40} [{c.action_type}]  {len(c.exemplars)} exemplar")
        print(f"    e.g. «{c.exemplars[0][:70]}»")
