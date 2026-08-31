"""Bank kịch bản reply TĨNH cho nhánh ack — load YAML + pick deterministic.

Module: inference.draft (B2) — nguồn copy song ngữ cho respond.py (thay câu cứng đơn lẻ).
Architecture: docs/architecture.md §4.3 (ack_only: praise→acknowledge, complaint→apology,
  unclassified→ack trung tính). Impl: docs/impl-phase2-auto-feedback-flow.md §5.
Template rule: template/skill_create_email.md. Plan: docs/2026-08-27/ack-reply-eml/plan.md.

`pick(group, key)` chọn 1 mẫu theo hash ỔN ĐỊNH của `key` (nội dung feedback) → cùng feedback luôn
ra cùng mẫu qua mọi lần chạy (idempotent, khớp tinh thần idempotency §4.5). KHÔNG dùng hash() built-in
vì nó randomized theo process (PYTHONHASHSEED) ⇒ dùng md5.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

import yaml

BANK_PATH = Path(__file__).resolve().parent / "reply_samples.yaml"

# nhóm hợp lệ — khớp mapping trong respond.py
GROUP_THANK_YOU = "thank_you"      # praise
GROUP_APOLOGY = "apology"          # complaint
GROUP_NEUTRAL = "neutral_ack"      # unclassified


@lru_cache(maxsize=1)
def load_bank(path: str | None = None) -> dict[str, list[dict]]:
    """Đọc bank YAML → {group: [ {vi:{greeting,body,closing}, en:{...}}, ... ]}. Cache trong phiên."""
    p = Path(path) if path else BANK_PATH
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    bank: dict[str, list[dict]] = {}
    for group, samples in raw.items():
        if not isinstance(samples, list) or not samples:
            raise ValueError(f"Nhóm '{group}' trong {p.name} rỗng hoặc không phải list.")
        for i, s in enumerate(samples):
            for lang in ("vi", "en"):
                if not (isinstance(s.get(lang), dict) and s[lang].get("body")):
                    raise ValueError(f"{p.name}:{group}[{i}] thiếu '{lang}.body'.")
        bank[group] = samples
    return bank


def _stable_index(key: str, n: int) -> int:
    """md5(key) → int → % n. Ổn định qua mọi process (khác hash() built-in)."""
    digest = hashlib.md5((key or "").encode("utf-8")).hexdigest()
    return int(digest, 16) % n


def pick(group: str, key: str, *, path: str | None = None) -> dict[str, dict[str, str]]:
    """Chọn 1 mẫu của `group` deterministic theo `key`. Trả {'vi': {...}, 'en': {...}}."""
    bank = load_bank(path)
    if group not in bank:
        raise KeyError(f"Nhóm '{group}' không có trong bank (có: {sorted(bank)}).")
    samples = bank[group]
    return samples[_stable_index(key, len(samples))]


def join_copy(side: dict[str, str]) -> str:
    """{greeting,body,closing} → text nhiều đoạn (\\n\\n) cho renderer _p_vi/_p_en."""
    parts = [side.get("greeting", ""), side.get("body", ""), side.get("closing", "")]
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


if __name__ == "__main__":
    bank = load_bank()
    print(f"[bank] {BANK_PATH.name}: " + ", ".join(f"{g}={len(v)}" for g, v in bank.items()))
    for group in (GROUP_THANK_YOU, GROUP_APOLOGY, GROUP_NEUTRAL):
        for key in ("dùng ổn lắm cảm ơn team", "app lỗi hoài bực quá", "xyz random 123"):
            s = pick(group, key)
            idx = _stable_index(key, len(load_bank()[group]))
            print(f"\n[{group}] key='{key[:30]}' → mẫu #{idx}")
            print("  VI:", join_copy(s["vi"])[:90], "...")
