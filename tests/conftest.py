"""Shared test setup."""
from pathlib import Path
from types import SimpleNamespace

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_bytes():
    def read(name):
        return (FIXTURES / name).read_bytes()
    return read


@pytest.fixture
def make_config():
    """A minimal stand-in for config.Config: just the airports, in LED order."""
    def make(*codes):
        return SimpleNamespace(airports={code: {"text": "", "display": False} for code in codes})
    return make
