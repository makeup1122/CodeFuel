from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure the repo root (containing the usagetray package) is importable.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def claude_usage() -> dict:
    return load_fixture("claude_usage.json")


@pytest.fixture
def codex_usage() -> dict:
    return load_fixture("codex_usage.json")


@pytest.fixture
def deepseek_balance() -> dict:
    return load_fixture("deepseek_balance.json")
