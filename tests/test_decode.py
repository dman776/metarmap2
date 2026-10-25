"""Tests for metarmap.decode: a METAR in plain English for the Map page's Decoded tab."""
from datetime import datetime, timezone

import pytest

from metarmap import decode
from metarmap.metar import parse_report, parse_visibility

OBS = datetime(2026, 10, 24, 17, 53, tzinfo=timezone.utc)


def lines(metar):
    return [(line["label"], line["text"]) for line in decode.decode(metar)]


def test_a_whole_report():
    metar = {"obsTime": OBS, "windDir": "100", "windSpeed": 13, "windGust": True, "windGustSpeed": 19,
             "visibilitySM": 10.0, "visibilityMore": True, "obs": "-RA BR", "tempC": 28, "dewpointC": 17,
             "altimHg": 30.2, "lightning": False,
             "skyConditions": [{"cover": "SCT", "cloudBaseFt": 4300}, {"cover": "BKN", "cloudBaseFt": 8000},
                               {"cover": "OVC", "cloudBaseFt": 12000}]}
    assert lines(metar) == [
        ("Observed", "24 Oct 17:53Z"),
        ("Wind", "100° at 13 kt, gusts 19 kt"),
        ("Visibility", "10+ miles"),
        ("Weather", "Light rain, mist"),
        ("Clouds", "Scattered 4,300 ft"),
        ("", "Broken 8,000 ft (ceiling)"),  # only the lowest broken or overcast layer is the ceiling
        ("", "Overcast 12,000 ft"),
        ("Temperature", "28°C / 82°F"),
        ("Dewpoint", "17°C / 63°F (spread 11°C)"),
        ("Altimeter", "30.20 inHg"),
    ]


def test_not_reporting():
    assert decode.decode({}) == [] and decode.decode(None) == []


def test_only_what_the_report_has():
    assert lines({"raw": "METAR KXXX", "tempC": -2, "lightning": True}) == [
        ("Temperature", "-2°C / 28°F"), ("Lightning", "Lightning observed")]


@pytest.mark.parametrize("metar, text", [
    ({"windSpeed": 0, "windDir": "0"}, "Calm"),
    ({"windSpeed": 4, "windDir": "VRB"}, "Variable at 4 kt"),
    ({"windSpeed": 4, "windDir": ""}, "Variable at 4 kt"),
    ({"windSpeed": 9, "windDir": "50"}, "050° at 9 kt"),
    ({"windSpeed": 25, "windDir": "270", "windGust": True, "windGustSpeed": 35}, "270° at 25 kt, gusts 35 kt"),
])
def test_wind(metar, text):
    assert decode.wind(metar) == text


@pytest.mark.parametrize("miles, more, text", [
    (10.0, True, "10+ miles"),
    (6.0, False, "6 miles"),
    (1.5, False, "1 1/2 miles"),
    (1.0, False, "1 mile"),
    (0.75, False, "3/4 mile"),
    (0.25, False, "1/4 mile"),
    (0.0, False, "0 miles"),
    (None, False, None),
])
def test_visibility(miles, more, text):
    assert decode.visibility(miles, more) == text


@pytest.mark.parametrize("wx, text", [
    ("RA", "Rain"),
    ("-RA", "Light rain"),
    ("+SN", "Heavy snow"),
    ("-RASN", "Light rain and snow"),
    ("-SHRA", "Light rain showers"),
    ("SHRA", "Rain showers"),
    ("VCSH", "Showers in the vicinity"),
    ("TS", "Thunderstorm"),
    ("TSRA", "Thunderstorm with rain"),
    ("+TSRAGR", "Thunderstorm with heavy rain and hail"),
    ("VCTS", "Thunderstorm in the vicinity"),
    ("-FZRA", "Light freezing rain"),
    ("FZFG", "Freezing fog"),
    ("BLSN", "Blowing snow"),
    ("DRSN", "Low drifting snow"),
    ("MIFG", "Shallow fog"),
    ("BCFG", "Patches of fog"),
    ("PRFG", "Partial fog"),
    ("BR HZ", "Mist, haze"),
    ("FU", "Smoke"),
    ("VA", "Volcanic ash"),
    ("UP", "Unknown precipitation"),
    ("SQ", "Squalls"),
    ("FC", "Funnel cloud"),
    ("+FC", "Tornado or waterspout"),
    ("VCFG", "Fog in the vicinity"),
    ("-DZ BR", "Light drizzle, mist"),
    ("NSW", "NSW"),  # not a code we know: shown as it is
    ("RAXX", "RAXX"),
    ("", None),
    (None, None),
])
def test_weather(wx, text):
    assert decode.weather(wx) == text


def test_clouds():
    assert decode.clouds([{"cover": "CLR", "cloudBaseFt": 0}]) == ["Clear"]
    assert decode.clouds([{"cover": "FEW", "cloudBaseFt": 1200}, {"cover": "OVC", "cloudBaseFt": 2500}]) == \
        ["Few 1,200 ft", "Overcast 2,500 ft (ceiling)"]
    assert decode.clouds([{"cover": "OVX", "cloudBaseFt": 0}], vert_vis_ft=300) == \
        ["Sky obscured, vertical visibility 300 ft (ceiling)"]
    assert decode.clouds([]) == [] and decode.clouds(None) == []


# ---- what the decoder reads from metar.py -----------------------------------------------------------------

@pytest.mark.parametrize("value, miles", [
    ("10+", 10.0), ("6.0", 6.0), ("0.25", 0.25), ("1/2", 0.5), ("1 1/2", 1.5), ("", None), (None, None)])
def test_parse_visibility(value, miles):
    assert parse_visibility(value) == miles


def test_parsed_reports_have_what_decode_needs():
    parsed = parse_report({"raw_text": "METAR KTST 241753Z 00000KT 1/2SM FG VV003", "visibility_statute_mi": "1/2",
                              "wx_string": "FG", "vert_vis_ft": "300", "sky_condition": {"@sky_cover": "OVX"},
                              "observation_time": "2026-10-24T17:53:00Z"})
    assert (parsed["vis"], parsed["visibilitySM"], parsed["visibilityMore"]) == (0, 0.5, False)
    assert parsed["vertVisFt"] == 300
    assert lines(parsed)[2:5] == [("Visibility", "1/2 mile"), ("Weather", "Fog"),
                                  ("Clouds", "Sky obscured, vertical visibility 300 ft (ceiling)")]
