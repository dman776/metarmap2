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
    assert s.geo.map.center == [30.603, -93.581]
    assert s.visualizer.auto_rotate.delay_seconds == 60


def test_missing_keys_get_defaults():
    s = Settings.from_dict({"geo": {"city": "Dallas"}})
    assert s.geo.city == "Dallas"
    assert s.geo.map.view == "airports"
    assert s.geo.map.chart == ""
    assert s.display_screen.delay == 5.0


def test_an_older_files_colors_are_dropped():
    """The LED colors live in the code now; a color section from before isn't kept."""
    s = Settings.from_dict({"color": {"cat": {"vfr": [255, 0, 0]}}, "led": {"count": 3}})
    assert "color" not in s.to_dict() and s.led.count == 3
    with pytest.raises(KeyError):
        s.set("color.cat.vfr", "[0, 255, 0]")


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


@pytest.mark.parametrize(
    "key, value, expected",
    [
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
    ],
)
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


@pytest.mark.parametrize(
    "key, value",
    [
        ("lightning.animation", "maybe"),
        ("visualizer.active", "two"),
        ("visualizer.active", "1.5"),
        ("display_screen.delay", "soon"),
        ("geo.map.center", "not a list"),
    ],
)
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

    config = Config(str(tmp_path / "config.json"))
    config.edit("display_screen.delay", "8")
    config.edit("geo.map.chart", "San Antonio")

    saved = json.loads((tmp_path / "config.json").read_text())
    assert saved["display_screen"]["delay"] == 8
    assert saved["geo"]["map"]["chart"] == "San Antonio"
    assert config.data.display_screen.delay == 8
    with pytest.raises(KeyError):
        config.edit("no.such.setting", "1")


# ---- visualizer numbering -----------------------------------------------------------------------------------------


# numbering 1: before Wind Direction (in at 3); 2: before Advisories (in at 11); 3: before TFR (in at 12). So Rainbow
# went 10 -> 11 -> 12 -> 13
@pytest.mark.parametrize("active, now", [(0, 0), (2, 2), (3, 4), (9, 10), (10, 13), (11, 14)])
def test_an_older_file_keeps_its_visualizer(active, now):
    """A file from before Wind Direction, Advisories and TFR keeps showing the same visualizer."""
    settings = Settings.from_dict({"visualizer": {"active": active}})
    assert (settings.visualizer.active, settings.visualizer.numbering) == (now, 4)
    assert Settings.from_dict(settings.to_dict()).visualizer.active == now  # once only


@pytest.mark.parametrize(
    "numbering, active, now",
    [
        (2, 3, 3),
        (2, 10, 10),
        (2, 11, 13),
        (2, 12, 14),  # before Advisories: Rainbow 11, Chase 12
        (3, 10, 10),
        (3, 11, 11),
        (3, 12, 13),
        (3, 13, 14),  # before TFR: Advisories 11, Rainbow 12, Chase 13
    ],
)
def test_a_file_from_before_advisories_or_tfr_keeps_its_visualizer(numbering, active, now):
    """Advisories went in at 11 and TFR at 12, after Dewpoint Spread: Rainbow and Chase moved up each time."""
    settings = Settings.from_dict({"visualizer": {"active": active, "numbering": numbering}})
    assert (settings.visualizer.active, settings.visualizer.numbering) == (now, 4)


def test_a_current_file_is_not_renumbered():
    assert Settings.from_dict({"visualizer": {"active": 12, "numbering": 4}}).visualizer.active == 12
    assert Settings.from_dict({}).visualizer.active == 0
