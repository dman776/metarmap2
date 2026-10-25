"""Tests for the config.json schema (metarmap/settings.py) and Config.edit."""
import json
import shutil
from pathlib import Path

import pytest

from metarmap.settings import Settings

REPO = Path(__file__).parent.parent


def test_repo_config_round_trips():
    raw = json.loads((REPO / "config.json").read_text())
    assert Settings.from_dict(raw).to_dict() == raw


def test_attribute_access_matches_config_json():
    s = Settings.load(REPO / "config.json")
    assert s.led.brightness.normal == 0.5
    assert s.color.cat.vfr == [255, 0, 0]
    assert s.geo.map.center == [30.603, -93.581]
    assert s.visualizer.auto_rotate.delay_seconds == 60


def test_missing_keys_get_defaults():
    s = Settings.from_dict({"geo": {"city": "Dallas"}})
    assert s.geo.city == "Dallas"
    assert s.geo.map.view == "airports"
    assert s.geo.map.chart == ""
    assert s.display_screen.delay == 5.0
    assert s.color.weather.lightning == [255, 255, 0]


def test_unknown_keys_are_kept():
    data = {"custom": {"a": 1}, "geo": {"city": "Austin", "extra_geo": True}}
    out = Settings.from_dict(data).to_dict()
    assert out["custom"] == {"a": 1}
    assert out["geo"]["extra_geo"] is True
    assert out["geo"]["city"] == "Austin"


def test_save_and_load(tmp_path):
    s = Settings()
    s.set("geo.map.chart", "Dallas-Ft Worth")
    path = tmp_path / "config.json"
    s.save(path)
    assert Settings.load(path).geo.map.chart == "Dallas-Ft Worth"


@pytest.mark.parametrize("key, value, expected", [
    ("lightning.animation", "false", False),
    ("lightning.animation", "True", True),
    ("lightning.animation", True, True),
    ("display_screen.delay", "7.5", 7.5),
    ("display_screen.delay", "5", 5),
    ("visualizer.active", "3", 3),
    ("visualizer.auto_rotate.delay_seconds", "120", 120),
    ("geo.map.zoom", "7", 7),
    ("geo.map.zoom", "7.25", 7.25),
    ("geo.map.chart", "Dallas-Ft Worth", "Dallas-Ft Worth"),
    ("geo.map.chart", '"Dallas"', "Dallas"),  # the old quoted form
    ("geo.map.center", "[32.9, -97.0]", [32.9, -97.0]),
    ("color.cat.vfr", "[0, 255, 0]", [0, 255, 0]),
])
def test_set_converts_text(key, value, expected):
    s = Settings()
    assert s.set(key, value) == expected
    section = s
    for part in key.split("."):
        section = getattr(section, part)
    assert section == expected
    assert type(section) is type(expected)


@pytest.mark.parametrize("key", ["nope", "geo.nope", "geo.map.nope", "geo", "geo.map", "_extra", "geo._extra"])
def test_set_unknown_setting(key):
    with pytest.raises(KeyError):
        Settings().set(key, "1")


@pytest.mark.parametrize("key, value", [
    ("lightning.animation", "maybe"),
    ("visualizer.active", "two"),
    ("visualizer.active", "1.5"),
    ("display_screen.delay", "soon"),
    ("geo.map.center", "not a list"),
    ("color.cat.vfr", '{"g": 1}'),
])
def test_set_rejects_bad_values(key, value):
    s = Settings()
    before = s.to_dict()
    with pytest.raises(ValueError):
        s.set(key, value)
    assert s.to_dict() == before


def test_set_cannot_run_code():
    """The old Config.edit ran the value as Python."""
    s = Settings()
    s.set("geo.map.chart", "__import__('os').system('true')")
    assert s.geo.map.chart == "__import__('os').system('true')"


def test_config_edit_writes_file(tmp_path):
    from metarmap.config import Config
    shutil.copy(REPO / "config.json", tmp_path / "config.json")
    shutil.copy(REPO / "airports.json", tmp_path / "airports.json")
    settings = json.loads((tmp_path / "config.json").read_text())
    settings["airports_file"] = str(tmp_path / "airports.json")
    (tmp_path / "config.json").write_text(json.dumps(settings))

    config = Config(str(tmp_path / "config.json"))
    config.edit("display_screen.delay", "8")
    config.edit("geo.map.chart", "San Antonio")

    saved = json.loads((tmp_path / "config.json").read_text())
    assert saved["display_screen"]["delay"] == 8
    assert saved["geo"]["map"]["chart"] == "San Antonio"
    assert config.data.display_screen.delay == 8
    with pytest.raises(KeyError):
        config.edit("no.such.setting", "1")
