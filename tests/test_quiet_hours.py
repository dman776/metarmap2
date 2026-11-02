"""Quiet hours override and Home schedule; standard next-event highlighting."""

from datetime import datetime
import pytest
from metarmap.settings import Settings
from metarmap.sun import quiet_hours_active
from metarmap.web.views import brightness_schedule


def at(hour, minute=0):
    return datetime(2026, 11, 2, hour, minute).astimezone()


@pytest.mark.parametrize("hour,expected", [(22, False), (23, True), (0, True), (5, False)])
def test_overnight_boundaries(hour, expected):
    quiet = Settings().led.quiet_hours
    quiet.enabled, quiet.start, quiet.end = True, "23:00", "05:00"
    assert quiet_hours_active(at(hour), quiet) is expected


def test_equal_times_disabled():
    quiet = Settings().led.quiet_hours
    quiet.enabled = True
    quiet.start = quiet.end = "23:00"
    assert not quiet_hours_active(at(23), quiet)


def test_invalid_file_disables_quiet_hours(caplog):
    data = Settings().to_dict()
    data["led"]["quiet_hours"] = {"enabled": True, "start": "7:00", "end": "05:00"}
    cfg = Settings.from_dict(data)
    assert not cfg.led.quiet_hours.enabled
    assert "Invalid quiet hours" in caplog.text


def test_legacy_setting_migrates():
    data = Settings().to_dict()
    data["led"]["night_off"] = {"enabled": True, "start": "23:00", "end": "06:00"}
    del data["led"]["quiet_hours"]
    cfg = Settings.from_dict(data)
    assert cfg.led.quiet_hours.enabled and cfg.led.quiet_hours.start == "23:00"
    assert "night_off" not in cfg.to_dict()["led"]


def test_api_time_validation(tmp_path):
    from metarmap.config import Config

    file = tmp_path / "config.json"
    Settings().save(file)
    cfg = Config(str(file))
    with pytest.raises(ValueError):
        cfg.edit("led.quiet_hours.start", "7:00")


def test_dashboard_next_and_grey_only_inside_interval():
    led = Settings().led
    led.quiet_hours.enabled = True
    led.quiet_hours.start, led.quiet_hours.end = "23:00", "06:00"
    times = {
        name: at(h, m) for name, h, m in [("dawn", 6, 10), ("sunrise", 6, 40), ("sunset", 17, 30), ("dusk", 18, 5)]
    }
    rows = brightness_schedule(times, led.brightness, led.quiet_hours, now=at(12))
    assert len(rows) == 5
    assert [r["name"] for r in rows if r["next"]] == ["Sunset"]
    assert not any(r["muted"] for r in rows)
    led.quiet_hours.start, led.quiet_hours.end = "17:00", "05:00"
    rows = brightness_schedule(times, led.brightness, led.quiet_hours, now=at(12))
    assert [r["name"] for r in rows if r["muted"]] == ["Sunset", "Dusk"]
    assert next(r for r in rows if r["name"] == "Sunset")["level"] == led.brightness.dimmed


def test_dashboard_greys_only_events_inside_cross_midnight_window():
    """Sun-event rows use their displayed HH:MM, not a converted machine timezone."""
    from datetime import timedelta, timezone

    led = Settings().led
    led.quiet_hours.enabled = True
    led.quiet_hours.start, led.quiet_hours.end = "17:40", "06:30"
    # Explicit offset represents a city whose sun times differ from the Pi's timezone.
    city_zone = timezone(timedelta(hours=-7))
    times = {
        name: datetime(2026, 11, 2, hour, minute, tzinfo=city_zone)
        for name, hour, minute in (("dawn", 6, 10), ("sunrise", 6, 36), ("sunset", 17, 33), ("dusk", 17, 58))
    }
    rows = brightness_schedule(times, led.brightness, led.quiet_hours, now=times["sunrise"])
    assert [row["name"] for row in rows if row["muted"]] == ["Dawn", "Dusk"]
    assert [row["name"] for row in rows if row["next"]] == ["Sunset"]
