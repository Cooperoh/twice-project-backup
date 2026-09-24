from __future__ import annotations

from pathlib import Path
import sys

import pytest


SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


@pytest.fixture
def config_path() -> Path:
    return SRC_DIR / "config.toml"
