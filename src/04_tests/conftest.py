"""
Module: inference.classify (B1) — test support
Architecture: docs/architecture.md §5 Technology Stack (Test: pytest + mock — logic thuần
              không cần LLM/embedding thật)
Plan: docs/2026-09-02/intent-classify-embedding-eval/plan.md

Helper nạp module từ thư mục tên bắt đầu bằng số (`03_inference` không import thường được).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_module(rel_path: str, name: str):
    """Nạp 1 file .py theo đường dẫn tương đối repo-root, cache trong sys.modules."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod
