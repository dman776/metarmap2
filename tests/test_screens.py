"""Tests for what the OLED shows (metarmap/oled/screens.py). No hardware needed."""
from datetime import datetime, timezone

import pytest
import pytz

from metarmap.oled import screens
from metarmap.oled.screen import GLYPHS

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
    data = {**KHOU, "tempC": None, "dewpointC": None, "obsTime": None}
    screen = screens.screen_for("KHOU", data, 2, CENTRAL)
    assert texts(screen) == [screens.MISSING] * 3


def test_page1_missing_values_show_dashes():
    screen = screens.screen_for("KTST", {"flightCategory": None}, 1)
    assert screen["badge"] == ""
    assert texts(screen) == [screens.MISSING] * 3


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


def test_airports_to_show_keeps_led_order():
    airports = {"KHOU": {"display": True}, "KIAH": {"display": False}, "NULL1": {}, "KGLS": {"display": True}}
    assert screens.airports_to_show(airports) == [(0, "KHOU"), (3, "KGLS")]
    assert screens.airports_to_show({}) == []


def test_pages_for():
    assert screens.pages_for(KHOU) == (1, 2)
    assert screens.pages_for({}) == (0,)
    assert screens.pages_for(None) == (0,)
