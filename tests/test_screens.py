"""Tests for what the OLED shows (display.screen_for and its helpers). No hardware needed."""
from datetime import datetime, timezone

import pytest
import pytz

import display

CENTRAL = pytz.timezone("America/Chicago")

KHOU = {"flightCategory": "VFR", "windDir": "100", "windSpeed": 13, "windGustSpeed": 19, "windGust": True,
        "vis": 10, "altimHg": 30.2, "tempC": 28, "dewpointC": 16,
        "obsTime": datetime(2026, 10, 24, 17, 53, tzinfo=timezone.utc)}


def texts(screen):
    return [line["text"] for line in screen["lines"]]


@pytest.mark.parametrize("data, expected", [
    ({"windSpeed": 0, "windDir": "100"}, "CALM"),
    ({"windSpeed": 7, "windDir": "90"}, "090@07"),
    ({"windSpeed": 13, "windDir": "100", "windGustSpeed": 19, "windGust": True}, "100@13G19"),
    ({"windSpeed": 6, "windDir": "VRB"}, "VRB@06"),
    ({"windSpeed": 6, "windDir": "vrb"}, "VRB@06"),
    ({"windSpeed": 5, "windDir": ""}, "VRB@05"),  # speed but no direction reported
])
def test_wind_text(data, expected):
    assert display.wind_text(data) == expected


def test_page1():
    screen = display.screen_for("KHOU", KHOU, 1)
    assert screen["title"] == "KHOU"
    assert screen["badge"] == "VFR"
    assert screen["airport"] == "KHOU"
    assert texts(screen) == ["100@13G19", "10SM", "30.20"]
    assert [line["icon"] for line in screen["lines"]] == ["wind", "visibility", "pressure"]


def test_page2_converts_time_to_local():
    screen = display.screen_for("KHOU", KHOU, 2, CENTRAL)
    assert texts(screen) == ["28°C / 82°F", "16°C / 61°F", "12:53C 17:53Z"]
    assert [line["icon"] for line in screen["lines"]] == ["temp", "dewpoint", "date"]


def test_page2_missing_values_show_dashes():
    data = {**KHOU, "tempC": None, "dewpointC": None, "obsTime": None}
    screen = display.screen_for("KHOU", data, 2, CENTRAL)
    assert texts(screen) == [display.MISSING] * 3


def test_page1_missing_values_show_dashes():
    screen = display.screen_for("KTST", {"flightCategory": None}, 1)
    assert screen["badge"] == ""
    assert texts(screen) == [display.MISSING] * 3


def test_unavailable_page():
    screen = display.screen_for("KDKR", None, 0)
    assert screen["page"] == 0
    assert screen["badge"] == ""
    assert texts(screen) == ["Data", "Unavailable", ""]


def test_every_icon_has_a_glyph():
    for page in (1, 2):
        for line in display.screen_for("KHOU", KHOU, page, CENTRAL)["lines"]:
            assert line["icon"] in display.ICONS
