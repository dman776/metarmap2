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
    """A minimal stand-in for config.Config: just the airports, in LED order ("" for an LED with no airport)."""
    def make(*codes):
        return SimpleNamespace(airports=airports(*codes))
    return make


def airports(*codes, display=()):
    """An airport list (settings.Airport), one per code in LED order; "" is an LED with no airport."""
    from metarmap.settings import Airport
    return [Airport(code=code, display=code in display) for code in codes]


@pytest.fixture
def make_app(tmp_path):
    """
    Builds a whole map (metarmap.app.build) from a copy of the repo's config.json, on an
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
        for key, value in settings.items():
            config.set(key, value)
        config.save(tmp_path / "config.json")
        return app_module.build(str(tmp_path / "config.json"), strip=FakeStrip(config.led.count),
                                screen=FakeScreen(), fetch=False)
    return make


@pytest.fixture(autouse=True)
def quick_dim(monkeypatch):
    """A METAR fetch dims the LEDs for at least a second; not in tests (renderer tests check the wait)."""
    from metarmap import renderer
    monkeypatch.setattr(renderer, "DIM_SECONDS", 0)


@pytest.fixture(autouse=True)
def no_release_checks(monkeypatch):
    """The map asks GitHub for new releases in the background when it starts; not in tests (they call check())."""
    from metarmap.releases import ReleaseCheck
    monkeypatch.setattr(ReleaseCheck, "check_soon", lambda self: None)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Tests never reach aviationweather.gov; a test that needs it fakes requests.get itself."""
    import requests

    def offline(url, *args, **kwargs):
        raise requests.exceptions.ConnectionError(f"no network in tests: {url}")
    monkeypatch.setattr(requests, "get", offline)
