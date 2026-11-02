"""Scheduled 0% physical LED brightness and Home schedule for overnight intervals."""

from datetime import datetime

import pytest

from metarmap.settings import Settings
from metarmap.sun import night_off_active
from metarmap.web.views import brightness_schedule


def local_at(hour, minute=0):
    """Build a time in the machine's local timezone, as used by the Pi schedule."""
    tz = datetime.now().astimezone().tzinfo
    return datetime(2026, 11, 2, hour, minute, tzinfo=tz)


@pytest.mark.parametrize(
    "start,end,hour,minute,expected",
    [
        ("23:00", "05:00", 22, 59, False),
        ("23:00", "05:00", 23, 0, True),
        ("23:00", "05:00", 4, 59, True),
        ("23:00", "05:00", 5, 0, False),
        ("17:00", "05:00", 20, 0, True),
        ("09:00", "12:00", 10, 0, True),
        ("09:00", "12:00", 12, 0, False),
    ],
)
def test_night_off_boundaries(start, end, hour, minute, expected):
    cfg = Settings().led.night_off
    cfg.enabled, cfg.start, cfg.end = True, start, end
    assert night_off_active(local_at(hour, minute), cfg) is expected


def test_disabled_and_equal_times_do_not_force_blackout():
    cfg = Settings().led.night_off
    cfg.start, cfg.end = "23:00", "05:00"
    assert not night_off_active(local_at(23), cfg)
    cfg.enabled, cfg.end = True, "23:00"
    assert not night_off_active(local_at(23), cfg)


def test_settings_round_trip_and_bool_conversion():
    cfg = Settings()
    assert cfg.led.night_off.enabled is False
    assert cfg.led.night_off.start == "22:00"
    assert cfg.led.night_off.end == "07:00"
    cfg.set("led.night_off.enabled", "true")
    cfg.set("led.night_off.start", "23:00")
    cfg.set("led.night_off.end", "05:00")
    new = Settings.from_dict(cfg.to_dict())
    assert (new.led.night_off.enabled, new.led.night_off.start, new.led.night_off.end) == (True, "23:00", "05:00")


@pytest.mark.parametrize("value", ["24:00", "23:60", "bad", "1:00", "-1:00", "05:00:00"])
def test_config_rejects_invalid_night_off_times(tmp_path, value):
    from metarmap.config import Config

    path = tmp_path / "config.json"
    Settings().save(path)
    cfg = Config(str(path))
    with pytest.raises(ValueError):
        cfg.edit("led.night_off.start", value)


def test_dashboard_highlights_current_blackout_and_aligns_rows():
    cfg = Settings().led
    cfg.night_off.enabled, cfg.night_off.start, cfg.night_off.end = True, "17:00", "05:00"
    times = {
        key: local_at(hour, minute)
        for key, hour, minute in (("dawn", 6, 10), ("sunrise", 6, 40), ("sunset", 17, 30), ("dusk", 18, 5))
    }
    schedule = brightness_schedule(times, cfg.brightness, cfg.night_off, now=local_at(21))
    assert [s["time"].strftime("%H:%M") for s in schedule] == ["05:00", "06:10", "06:40", "17:00", "17:30", "18:05"]
    assert [s["name"] for s in schedule if s["next"]] == ["Night off"]
    assert next(s for s in schedule if s["name"] == "Sunset")["level"] == 0.0
    assert next(s for s in schedule if s["name"] == "Resume schedule")["level"] == cfg.brightness.off


def test_dashboard_highlights_dusk_before_2300_shutdown():
    cfg = Settings().led
    cfg.night_off.enabled, cfg.night_off.start, cfg.night_off.end = True, "23:00", "05:00"
    times = {
        key: local_at(hour, minute)
        for key, hour, minute in (("dawn", 6, 10), ("sunrise", 6, 40), ("sunset", 17, 30), ("dusk", 18, 5))
    }
    schedule = brightness_schedule(times, cfg.brightness, cfg.night_off, now=local_at(21))
    assert [s["name"] for s in schedule if s["next"]] == ["Dusk"]
    assert [
        s["name"] for s in brightness_schedule(times, cfg.brightness, cfg.night_off, now=local_at(23)) if s["next"]
    ] == ["Night off"]


def test_dashboard_without_blackout_highlights_current_sun_period():
    cfg = Settings().led
    times = {
        key: local_at(hour, minute)
        for key, hour, minute in (("dawn", 6, 10), ("sunrise", 6, 40), ("sunset", 17, 30), ("dusk", 18, 5))
    }
    schedule = brightness_schedule(times, cfg.brightness, cfg.night_off, now=local_at(12))
    assert [s["name"] for s in schedule if s["next"]] == ["Sunrise"]
    assert len(schedule) == 4
