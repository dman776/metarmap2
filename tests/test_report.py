"""Tests for the parsed METAR (models.Report), and that the API sees the same fields as before it existed."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from metarmap import metar
from metarmap.models import Report, SkyLayer

# what parse_report() and parse_raw() gave as dicts, before they returned a Report: to_api() must give the same
GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "reports_golden.json").read_text())
NOW = datetime.fromisoformat(GOLDEN["now"])


@pytest.mark.parametrize("case", GOLDEN["reports"], ids=lambda c: c["input"]["icaoId"])
def test_a_fetched_report_has_the_same_api_fields(case):
    assert metar.parse_report(case["input"]).to_api() == case["expected"]


@pytest.mark.parametrize("case", GOLDEN["raw"], ids=lambda c: c["input"][:24])
def test_a_mock_report_has_the_same_api_fields(case):
    assert metar.parse_raw(case["input"], NOW).to_api() == case["expected"]


def test_api_fields():
    r = Report(
        raw="KTST 241453Z 14009G18KT 1/4SM -RA BKN008 28/22 A2995",
        name="Test",
        flight_category="LIFR",
        wind_dir="140",
        wind_speed=9,
        wind_gust_speed=18,
        visibility_sm=0.25,
        weather="-RA",
        temp_c=28,
        dewpoint_c=22,
        altimeter_inhg=29.95,
        sky_conditions=(SkyLayer("BKN", 800),),
        obs_time=datetime(2026, 10, 24, 14, 53, tzinfo=timezone.utc),
        latitude=29.6,
        longitude=-95.3,
        mock=True,
        tfrs=[],
    )
    api = r.to_api()
    assert (api["windGust"], api["vis"], api["visibilitySM"]) == (True, 0, 0.25)
    assert api["skyConditions"] == [{"cover": "BKN", "cloudBaseFt": 800}]
    assert api["obsTime"] == "2026-10-24T14:53:00+00:00" and api["obs"] == "-RA" and api["altimHg"] == 29.95
    assert "mock" not in api and "tfrs" not in api  # the map's additions, not the report's
    json.dumps(api)  # ready for JSON


def test_derived_fields():
    assert Report().wind_gust is False and Report(wind_gust_speed=25).wind_gust is True
    assert Report().vis == 0 and Report(visibility_sm=2.5).vis == 2 and Report(visibility_sm=9.6).vis == 10


def test_a_report_cant_be_changed():
    with pytest.raises(AttributeError):
        Report().wind_speed = 5
