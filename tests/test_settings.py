"""Tests for the config.json schema (metarmap/settings.py) and Config.edit."""

import json
import shutil
from pathlib import Path

import pytest

from metarmap.settings import NUMBERED, Settings

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
        ("visualizer.active", "3", "wind_direction"),  # by number
        ("visualizer.active", "tfr", "tfr"),
        ("visualizer.auto_rotate.skip", '["Wind", "chase", "1", "wind"]', ["wind", "chase"]),  # names, ids, numbers
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
        ("visualizer.active", "99"),
        ("visualizer.auto_rotate.skip", '["Wind", "nope"]'),
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


# ---- visualizers saved as numbers, before ids ---------------------------------------------------------------------


def ids(*numbers):
    """The ids of visualizers by their number in the last numbering (4)."""
    return tuple(NUMBERED[n][0] for n in numbers)


# numbering 1: before Wind Direction (in at 3); 2: before Advisories (in at 11); 3: before TFR (in at 12). So Rainbow
# went 10 -> 11 -> 12 -> 13
@pytest.mark.parametrize("active, now", [(0, 0), (2, 2), (3, 4), (9, 10), (10, 13), (11, 14)])
def test_an_older_file_keeps_its_visualizer(active, now):
    """A file from before Wind Direction, Advisories and TFR keeps showing the same visualizer."""
    settings = Settings.from_dict({"visualizer": {"active": active}})
    assert (settings.visualizer.active,) == ids(now)
    saved = settings.to_dict()
    assert "numbering" not in saved["visualizer"]
    assert Settings.from_dict(saved).visualizer.active == ids(now)[0]  # once only


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
        (4, 12, 12),  # the last numbering: as it is
    ],
)
def test_a_file_from_before_advisories_or_tfr_keeps_its_visualizer(numbering, active, now):
    """Advisories went in at 11 and TFR at 12, after Dewpoint Spread: Rainbow and Chase moved up each time."""
    settings = Settings.from_dict({"visualizer": {"active": active, "numbering": numbering}})
    assert (settings.visualizer.active,) == ids(now)
    assert "numbering" not in settings.visualizer._extra


def test_a_number_past_the_list_is_the_default():
    assert Settings.from_dict({"visualizer": {"active": 40, "numbering": 4}}).visualizer.active == "flight_category"


def test_no_visualizer_saved_is_the_default():
    assert Settings.from_dict({}).visualizer.active == "flight_category"


def test_an_unknown_id_is_the_default(caplog):
    assert Settings.from_dict({"visualizer": {"active": "nope"}}).visualizer.active == "flight_category"
    assert "Invalid visualizer.active" in caplog.text


def test_skipped_names_become_ids():
    data = {"visualizer": {"auto_rotate": {"skip": ["Wind", "Dewpoint Spread", "tfr", "Nope"]}}}
    # an unknown name makes the list invalid: auto-rotate then leaves nothing out, rather than a guess
    assert Settings.from_dict(data).visualizer.auto_rotate.skip == []
    data["visualizer"]["auto_rotate"]["skip"].remove("Nope")
    assert Settings.from_dict(data).visualizer.auto_rotate.skip == ["wind", "dewpoint_spread", "tfr"]


def test_every_numbered_visualizer_still_exists():
    """NUMBERED is the past (numbering 4): visualizers can be added or renamed since, but an id is never removed."""
    from metarmap import visualizers

    assert {vid for vid, _ in NUMBERED} <= set(visualizers.BY_ID)


# ---- rules ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key, value, error",
    [
        ("led.pin", "7", "led.pin: '7' is not one of 18, 12, 13, 21, 10"),
        ("led.order", "BGR", "led.order: 'BGR' is not one of GRB, RGB"),
        ("lightning.color", "purple", "lightning.color: 'purple' is not one of yellow, white"),
        ("tfr.nearby_nm", "51", "tfr.nearby_nm: '51' is not between 0 and 50 NM"),
        (
            "geo.map.traffic_seconds",
            "1",
            "geo.map.traffic_seconds: '1' is not between 2 and 60 seconds (adsb.fi's limit)",
        ),
        ("led.quiet_hours.start", "7:00", "led.quiet_hours.start: expected local time in 24-hour HH:MM format"),
        ("update.branch", "-x", "update.branch: '-x' isn't a branch name"),
        ("update.channel", "nightly", "update.channel: 'nightly' is not one of releases, latest, branch"),
        ("update.channel", "branch", "update.channel: branch needs dev_mode in config.json"),
    ],
)
def test_set_checks_the_rule(key, value, error):
    s = Settings()
    before = s.get(key)
    with pytest.raises(ValueError) as e:
        s.set(key, value)
    assert str(e.value) == error
    assert s.get(key) == before


@pytest.mark.parametrize(
    "key, value, stored",
    [
        ("led.pin", "13", 13),
        ("led.order", "RGB", "RGB"),
        ("tfr.nearby_nm", "0", 0),
        ("geo.map.traffic_seconds", "60", 60),
        ("led.quiet_hours.end", "06:30", "06:30"),
        ("update.branch", "feature/x", "feature/x"),
    ],
)
def test_set_accepts_what_the_rule_allows(key, value, stored):
    s = Settings()
    assert s.set(key, value) == stored
    assert s.get(key) == stored


def test_branch_channel_with_dev_mode():
    s = Settings()
    s.dev_mode = True
    assert s.set("update.channel", "branch") == "branch"


def test_settings_set_allows_what_only_config_json_changes():
    # the web UI can't (Config.edit refuses it); code and tests can
    s = Settings()
    assert s.set("dev_mode", "true") is True
    assert s.rule("dev_mode").editable is False


def test_rule_of_a_setting_without_one():
    assert Settings().rule("web_server.port") is None
    with pytest.raises(KeyError):
        Settings().rule("geo.nothing")


@pytest.mark.parametrize(
    "section, key, value, default",
    [
        ("led", "pin", 7, 18),
        ("led", "order", "BGR", "GRB"),
        ("lightning", "color", "purple", "yellow"),
        ("tfr", "nearby_nm", 500, 10),
        ("tfr", "nearby_nm", "far", 10),
        ("geo", "city", "Houstn", "Houston"),  # a city the sun times don't know would stop the map at startup
        ("geo", "city", "Europe", "Houston"),  # nor would one of astral's group names, which is no city
    ],
)
def test_a_value_its_rule_rejects_is_reset_on_load(section, key, value, default, caplog):
    data = Settings().to_dict()
    data[section][key] = value
    s = Settings.from_dict(data)
    assert getattr(getattr(s, section), key) == default
    assert f"Invalid {section}.{key} in config.json" in caplog.text


def test_a_nested_value_is_reset_on_load():
    data = Settings().to_dict()
    data["geo"]["map"]["traffic_seconds"] = 0.5
    assert Settings.from_dict(data).geo.map.traffic_seconds == 5


def test_a_valid_value_of_the_wrong_type_is_converted_on_load():
    data = Settings().to_dict()
    data["led"]["pin"] = "12"
    data["geo"]["map"]["traffic_seconds"] = "30"
    s = Settings.from_dict(data)
    assert (s.led.pin, s.geo.map.traffic_seconds) == (12, 30)


def test_load_leaves_rules_that_depend_on_other_settings_alone(caplog):
    # update.channel "branch" without dev_mode works as releases (update_channel()); kept for when dev_mode is back
    data = Settings().to_dict()
    data["update"]["channel"] = "branch"
    s = Settings.from_dict(data)
    assert s.update.channel == "branch"
    assert s.update_channel() == "releases"
    assert "Invalid" not in caplog.text


def test_any_city_the_sun_times_know_is_kept():
    data = Settings().to_dict()
    data["geo"]["city"] = "london"  # case doesn't matter
    assert Settings.from_dict(data).geo.city == "london"


@pytest.mark.parametrize("name", ["Houstn", "Europe", "us"])
def test_setting_a_city_the_sun_times_dont_know_is_refused(name):
    s = Settings()
    with pytest.raises(ValueError, match="not a city the sun times know"):
        s.set("geo.city", name)
    assert s.geo.city == "Houston"
