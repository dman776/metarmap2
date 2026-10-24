"""
Shared test setup.

Some modules still import Raspberry Pi hardware drivers at import time (e.g. visualizers import `neopixel`).
Until the hardware is moved behind interfaces (a later step of the restructure), stand-ins are registered here
so those modules can be imported on any machine. Real drivers are used when they are installed.
"""
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def _stub_if_missing(name, **attrs):
    try:
        __import__(name)
    except (ImportError, NotImplementedError):
        module = types.ModuleType(name)
        module.__dict__.update(attrs)
        sys.modules[name] = module


_stub_if_missing("board", D18=18, SCL=None, SDA=None)
_stub_if_missing("neopixel", NeoPixel=object, RGB="RGB", GRB="GRB")


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
