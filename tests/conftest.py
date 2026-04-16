"""Test fixtures shared across the suite."""
import shutil
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.fixture
def tmp_path():
    base = Path.cwd() / ".tmp_pytest"
    base.mkdir(exist_ok=True)
    path = base / uuid4().hex
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
