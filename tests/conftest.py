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


@pytest.fixture
def make_app(tmp_path):
    """
    Builds a whole map (metarmap.app.build) from a copy of the repo's config.json and airports.json, on an
    in-memory strip and screen, without fetching METARs. Keyword arguments change settings first,
    e.g. make_app(**{"display_screen.enabled": False}).
    """
    from metarmap import app as app_module
    from metarmap.leds.strip import FakeStrip
    from metarmap.oled.screen import FakeScreen
    from metarmap.settings import Settings

    def make(**settings):
        repo = Path(__file__).parent.parent
        config = Settings.load(repo / "config.json")
        config.airports_file = str(tmp_path / "airports.json")
        for key, value in settings.items():
            config.set(key, value)
        config.save(tmp_path / "config.json")
        (tmp_path / "airports.json").write_text((repo / "airports.json").read_text())
        return app_module.build(str(tmp_path / "config.json"), strip=FakeStrip(config.led.count),
                                screen=FakeScreen(), fetch=False)
    return make
