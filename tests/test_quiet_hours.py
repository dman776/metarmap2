"""Quiet Hours override and Home schedule; current-period highlighting."""

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


def test_invalid_time_is_reset_even_when_off():
    data = Settings().to_dict()
    data["led"]["quiet_hours"] = {"enabled": False, "start": "22:00", "end": "bad"}
    quiet = Settings.from_dict(data).led.quiet_hours
    assert (quiet.enabled, quiet.start, quiet.end) == (False, "23:00", "05:00")


def test_api_time_validation(tmp_path):
    from metarmap.config import Config

    file = tmp_path / "config.json"
    Settings().save(file)
    cfg = Config(str(file))
    with pytest.raises(ValueError):
        cfg.edit("led.quiet_hours.start", "7:00")


def test_dashboard_current_and_grey_only_inside_interval():
    led = Settings().led
    led.quiet_hours.enabled = True
    led.quiet_hours.start, led.quiet_hours.end = "23:00", "06:00"
    times = {
        name: at(h, m) for name, h, m in [("dawn", 6, 10), ("sunrise", 6, 40), ("sunset", 17, 30), ("dusk", 18, 5)]
    }
    rows = brightness_schedule(times, led.brightness, led.quiet_hours, now=at(12))
    assert len(rows) == 5
    assert [r["name"] for r in rows if r["current"]] == ["Sunrise"]
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
    assert [row["name"] for row in rows if row["current"]] == ["Sunrise"]


def test_current_period_throughout_the_day_and_night():
    led = Settings().led
    times = {
        name: at(h, m) for name, h, m in (("dawn", 6, 13), ("sunrise", 6, 38), ("sunset", 17, 39), ("dusk", 18, 4))
    }
    for hour, minute, expected in (
        (0, 0, "Dusk"),  # the night level was set at yesterday's dusk
        (6, 12, "Dusk"),
        (6, 13, "Dawn"),
        (6, 37, "Dawn"),
        (6, 38, "Sunrise"),
        (12, 0, "Sunrise"),
        (17, 39, "Sunset"),
        (18, 3, "Sunset"),
        (18, 4, "Dusk"),
        (23, 59, "Dusk"),
    ):
        rows = brightness_schedule(times, led.brightness, led.quiet_hours, now=at(hour, minute))
        assert [row["name"] for row in rows if row["current"]] == [expected]
        assert not any(row.get("quiet_event") for row in rows)


@pytest.mark.parametrize(
    "start,end,at_hour,at_minute,expected",
    [
        ("23:00", "05:00", 22, 59, "Dusk"),
        ("23:00", "05:00", 23, 0, "Quiet hours"),
        ("23:00", "05:00", 0, 0, "Quiet hours"),
        ("23:00", "05:00", 4, 59, "Quiet hours"),
        ("23:00", "05:00", 5, 0, "Dusk"),
        ("17:00", "05:00", 16, 59, "Sunrise"),
        ("17:00", "05:00", 17, 0, "Quiet hours"),
        ("17:00", "05:00", 18, 51, "Quiet hours"),
        ("17:00", "05:00", 5, 0, "Dusk"),
        ("07:00", "09:00", 7, 0, "Quiet hours"),
        ("07:00", "09:00", 8, 59, "Quiet hours"),
        ("07:00", "09:00", 9, 0, "Sunrise"),
        ("06:00", "08:00", 7, 0, "Quiet hours"),
        ("06:00", "08:00", 8, 0, "Sunrise"),
        ("17:00", "06:30", 6, 29, "Quiet hours"),
        ("17:00", "06:30", 6, 30, "Dawn"),
    ],
)
def test_current_respects_quiet_hours_and_boundary_times(start, end, at_hour, at_minute, expected):
    led = Settings().led
    led.quiet_hours.enabled = True
    led.quiet_hours.start, led.quiet_hours.end = start, end
    times = {
        name: at(h, m) for name, h, m in (("dawn", 6, 13), ("sunrise", 6, 38), ("sunset", 17, 39), ("dusk", 18, 4))
    }
    rows = brightness_schedule(times, led.brightness, led.quiet_hours, now=at(at_hour, at_minute))
    assert [row["name"] for row in rows if row["current"]] == [expected]
    assert len(rows) == 5
    expected_muted = {
        "23:00": [],
        "17:00": ["Dawn", "Sunset", "Dusk"] if end == "06:30" else ["Sunset", "Dusk"],
        "07:00": [],
        "06:00": ["Dawn", "Sunrise"],
    }
    assert [row["name"] for row in rows if row["muted"]] == expected_muted[start]


def test_equal_quiet_hours_times_do_not_override_current():
    led = Settings().led
    led.quiet_hours.enabled = True
    led.quiet_hours.start = led.quiet_hours.end = "17:00"
    times = {
        name: at(h, m) for name, h, m in (("dawn", 6, 13), ("sunrise", 6, 38), ("sunset", 17, 39), ("dusk", 18, 4))
    }
    rows = brightness_schedule(times, led.brightness, led.quiet_hours, now=at(18, 51))
    assert [row["name"] for row in rows if row["current"]] == ["Dusk"]
    assert len(rows) == 4


def test_disabled_quiet_hours_does_not_override_current():
    led = Settings().led
    led.quiet_hours.enabled = False
    led.quiet_hours.start, led.quiet_hours.end = "17:00", "05:00"
    times = {
        name: at(h, m) for name, h, m in (("dawn", 6, 13), ("sunrise", 6, 38), ("sunset", 17, 39), ("dusk", 18, 4))
    }
    rows = brightness_schedule(times, led.brightness, led.quiet_hours, now=at(18, 51))
    assert [row["name"] for row in rows if row["current"]] == ["Dusk"]
    assert not any(row["muted"] for row in rows)
    assert len(rows) == 4


def test_current_without_sun_times():
    led = Settings().led
    led.quiet_hours.enabled = True
    assert brightness_schedule({}, led.brightness, led.quiet_hours, now=at(23)) == []
