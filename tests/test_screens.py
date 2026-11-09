"""Tests for what the OLED shows (metarmap/oled/screens.py). No hardware needed."""

from dataclasses import replace
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from types import SimpleNamespace

import pytest

from conftest import airports
from metarmap.models import Report, SkyLayer
from metarmap.oled import screens
from metarmap.oled.screen import GLYPHS, LOGO, logo_points

CENTRAL = ZoneInfo("America/Chicago")

KHOU = Report(
    flight_category="VFR",
    wind_dir="100",
    wind_speed=13,
    wind_gust_speed=19,
    visibility_sm=10.0,
    altimeter_inhg=30.2,
    temp_c=28,
    dewpoint_c=16,
    obs_time=datetime(2026, 10, 24, 17, 53, tzinfo=timezone.utc),
)


def texts(screen):
    return [line["text"] for line in screen["lines"]]


@pytest.mark.parametrize(
    "data, expected",
    [
        (Report(wind_speed=0, wind_dir="100"), "CALM"),
        (Report(wind_speed=7, wind_dir="90"), "090@07"),
        (Report(wind_speed=13, wind_dir="100", wind_gust_speed=19), "100@13G19"),
        (Report(wind_speed=6, wind_dir="VRB"), "VRB@06"),
        (Report(wind_speed=6, wind_dir="vrb"), "VRB@06"),
        (Report(wind_speed=5, wind_dir=""), "VRB@05"),  # speed but no direction reported
    ],
)
def test_wind_text(data, expected):
    assert screens.wind_text(data) == expected


def test_page1():
    screen = screens.screen_for("KHOU", KHOU, 1)
    assert screen["title"] == "KHOU"
    assert screen["badge"] == "VFR"
    assert screen["airport"] == "KHOU"
    assert texts(screen) == ["100@13G19", "10SM", "30.20"]
    assert [line["icon"] for line in screen["lines"]] == ["wind", "visibility", "pressure"]


def test_page2_converts_time_to_local():
    screen = screens.screen_for("KHOU", KHOU, 2, CENTRAL)
    assert texts(screen) == ["28°C / 82°F", "16°C / 61°F", "12:53C 17:53Z"]
    assert [line["icon"] for line in screen["lines"]] == ["temp", "dewpoint", "date"]


def test_page2_missing_values_show_dashes():
    data = replace(KHOU, temp_c=None, dewpoint_c=None, obs_time=None)
    screen = screens.screen_for("KHOU", data, 2, CENTRAL)
    assert texts(screen) == [screens.MISSING] * 3


def test_page1_of_a_report_without_wind_visibility_or_altimeter():
    """What the report leaves out is dashes, not CALM / 0SM / 0.00."""
    screen = screens.screen_for("KTST", Report(flight_category=None), 1)
    assert screen["badge"] == ""
    assert texts(screen) == [screens.MISSING, screens.MISSING, screens.MISSING]


def test_page1_calm_and_zero_visibility_are_shown():
    screen = screens.screen_for("KTST", Report(wind_speed=0, visibility_sm=0.0, altimeter_inhg=29.92), 1)
    assert texts(screen) == ["CALM", "0SM", "29.92"]


@pytest.mark.parametrize(
    "data, badge",
    [
        (Report(flight_category="IFR", visibility_sm=10.0), "IFR"),  # reported: shown as it is
        (Report(flight_category=None, visibility_sm=10.0), "VFR*"),  # estimated from the visibility
        (Report(flight_category=None, visibility_sm=4.0), "MVFR*"),
        (Report(flight_category=None, sky_conditions=[SkyLayer("OVC", 400)]), "LIFR*"),
        (Report(flight_category=None, visibility_sm=None, sky_conditions=[]), ""),  # nothing to estimate from
    ],
)
def test_badge_marks_an_estimated_category(data, badge):
    for page in (1, 2):
        assert screens.screen_for("KTST", data, page, CENTRAL)["badge"] == badge


def test_unavailable_page():
    screen = screens.screen_for("KDKR", None, 0)
    assert screen["page"] == 0
    assert screen["badge"] == ""
    assert texts(screen) == ["Data", "Unavailable", ""]


def test_every_icon_has_a_glyph():
    for page in (1, 2):
        for line in screens.screen_for("KHOU", KHOU, page, CENTRAL)["lines"]:
            assert line["icon"] in GLYPHS


def test_every_icon_name_has_a_glyph():
    for name in screens.ICON_NAMES:
        assert GLYPHS[name]


def test_screens_are_marked_as_airport_pages():
    assert screens.screen_for("KHOU", KHOU, 1)["kind"] == "airport"
    assert screens.screen_for("KHOU", None, 0)["kind"] == "airport"


def test_message_screen():
    m = screens.message_screen("MAP", "info", "Starting..")
    assert m["kind"] == "message"
    assert m["airport"] is None
    assert m["icon"] == "info"
    assert texts(m) == ["Starting..", "", ""]


def test_splash_screen():
    """A message, so anything that doesn't know the splash still shows its title."""
    m = screens.splash_screen()
    assert m["splash"] is True
    assert m["kind"] == "message"
    assert m["title"] == "MetarMap2"
    assert m["airport"] is None
    assert texts(m) == ["", "", ""]


def test_the_logo_is_centered_on_the_blue_rows():
    """Rows 16-63 of the 128x64 OLED (0-15 are the yellow ones, the title's)."""
    assert len({len(row) for row in LOGO}) == 1  # every row as wide
    assert "#" in LOGO[0] and "#" in LOGO[-1]  # no empty rows at either end
    points = logo_points(128, 16, 64)
    xs, ys = [x for x, _ in points], [y for _, y in points]
    assert min(ys) >= 16 and max(ys) <= 63
    assert abs((min(ys) - 16) - (63 - max(ys))) <= 1  # as much room above as below
    assert abs(min(xs) - (127 - max(xs))) <= 2  # and either side


def test_airports_to_show_keeps_led_order():
    leds = airports("KHOU", "KIAH", "", "KGLS", display=("KHOU", "KGLS", ""))
    assert screens.airports_to_show(leds) == [(0, "KHOU"), (3, "KGLS")]  # an LED with no airport isn't shown
    assert screens.airports_to_show([]) == []


def test_a_virtual_airport_is_marked():
    """It has no LED to light up: its code goes in a dashed box instead."""
    assert screens.screen_for("KGLS", None, 0, virtual=True)["virtual"] is True
    assert screens.screen_for("KGLS", Report(flight_category="VFR"), 1, virtual=True)["virtual"] is True
    assert screens.screen_for("KGLS", Report(flight_category="VFR"), 1)["virtual"] is False


def test_dashed_box_fits_between_the_code_the_badge_and_the_first_line():
    """KWWW is the widest code; the 16 px code at (2, -1) has its letters at 2-57 across and 2-13 down."""
    from metarmap.oled.screen import dashed_box

    font = SimpleNamespace(getbbox=lambda text: (0, 3, 56, 15))  # FreeSans 16 px
    box = dashed_box(SimpleNamespace(x=2, y=-1, font=font), "KWWW")
    assert box == (0, 0, 59, 15)  # at the top of the screen
    assert box[2] < 76 and box[3] < 18  # the badge starts at x=76; the first line's letters at y=19


def test_dashed_rectangle():
    from metarmap.oled.screen import dashed_rectangle

    lines = []
    dashed_rectangle(SimpleNamespace(line=lambda xy, fill: lines.append(xy)), (0, 0, 6, 3))
    assert (0, 0, 1, 0) in lines and (4, 0, 5, 0) in lines and (4, 3, 5, 3) in lines  # top and bottom: 2 on, 2 off
    assert (0, 0, 0, 1) in lines and (6, 0, 6, 1) in lines  # left and right sides
    assert all(x <= 6 and y <= 3 for x0, y0, x, y in lines)  # never past the box


def test_pages_for():
    assert screens.pages_for(KHOU) == (1, 2)
    assert screens.pages_for(None) == (0,)
    assert screens.pages_for(None) == (0,)
