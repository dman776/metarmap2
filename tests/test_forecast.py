"""TAFs: the flight category forecast from aviationweather.gov's JSON, and the visualizer that shows it."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from metarmap import forecast
from metarmap.forecast import Forecasts, category_at, parse_tafs
from metarmap.metar import with_forecast
from metarmap.models import Look, Report, SkyLayer
from metarmap.settings import Settings
from metarmap.visualizers import flightcategory, flightcategory_forecast as fcf, style, visualizer

# KHOU: base VFR with a TEMPO to BKN015 (MVFR) until 1794279600; FM1794283200 6 SM, OVC030 (MVFR); a TEMPO to OVC015
# (IFR) 1794297600-1794312000; FM1794315600 back to VFR (valid until 1794355200)
START = 1794272400


@pytest.fixture
def tafs(fixture_bytes):
    return parse_tafs(json.loads(fixture_bytes("taf.json")))


def test_parses_the_latest_taf_of_each_station(tafs):
    assert set(tafs) == {"KHOU", "KJFK"}
    assert tafs["KHOU"].valid_to == 1794355200
    assert [g.kind for g in tafs["KHOU"].groups] == [None, "TEMPO", "FM", "TEMPO", "FM"]
    assert tafs["KHOU"].groups[0].vis == 6.0 and tafs["KHOU"].groups[0].layers[0] == SkyLayer("SCT", 1500)


def test_category_follows_the_groups(tafs):
    khou = tafs["KHOU"]
    assert category_at(khou, START + 3600, include_temporary=False) == "VFR"
    assert category_at(khou, START + 3600) == "MVFR"  # the TEMPO BKN015
    assert category_at(khou, 1794283200 + 60, include_temporary=False) == "MVFR"  # FM: OVC030
    assert category_at(khou, 1794300000, include_temporary=False) == "MVFR"
    assert category_at(khou, 1794300000) == "MVFR"  # the TEMPO OVC015 with 5 SM is no worse
    assert category_at(khou, 1794320000) == "VFR"


def test_no_category_outside_the_taf(tafs):
    assert category_at(tafs["KHOU"], START - 3600) is None
    assert category_at(tafs["KHOU"], 1794355200) is None


def test_becmg_changes_only_what_it_names():
    taf = forecast.Taf(
        valid_to=10_000,
        groups=[
            forecast.Group(0, 10_000, None, 10.0, (SkyLayer("SCT", 5000),)),
            forecast.Group(4000, 4000, "BECMG", None, (SkyLayer("OVC", 800),)),  # the ceiling comes down, vis stays
            forecast.Group(6000, 6000, "BECMG", 0.5),  # then the visibility, the ceiling stays
        ],
    )
    assert category_at(taf, 3000) == "VFR"
    assert category_at(taf, 5000) == "IFR"
    assert category_at(taf, 7000) == "LIFR"


def test_forecasts_fetches_and_throttles(fixture_bytes):
    calls, now = [], [1000.0]

    def get(url, **kwargs):
        calls.append(url)
        return SimpleNamespace(
            status_code=200, raise_for_status=lambda: None, json=lambda: json.loads(fixture_bytes("taf.json"))
        )

    forecasts = Forecasts(get=get, clock=lambda: now[0])
    assert forecasts.fetch(["KHOU", "KJFK", "KXXX", ""])
    assert calls[0].endswith("ids=KHOU,KJFK,KXXX")
    assert not forecasts.fetch(["KHOU", "KJFK", "KXXX"])  # too soon
    assert forecasts.fetch(["KHOU"])  # other airports
    now[0] += forecast.MIN_AGE + 1
    assert forecasts.fetch(["KHOU"])
    assert len(calls) == 3


def test_forecasts_keeps_the_old_tafs_when_a_fetch_fails(fixture_bytes):
    import requests

    answers = [
        SimpleNamespace(
            status_code=200, raise_for_status=lambda: None, json=lambda: json.loads(fixture_bytes("taf.json"))
        )
    ]

    def get(url, **kwargs):
        if answers:
            return answers.pop()
        raise requests.exceptions.ConnectionError("down")

    now = [START + 3600.0]
    forecasts = Forecasts(get=get, clock=lambda: now[0])
    assert forecasts.fetch(["KHOU"])
    now[0] += forecast.MIN_AGE + 1
    assert not forecasts.fetch(["KHOU"])
    assert forecasts.error and forecasts.forecast("KHOU") is not None


def test_forecast_for_the_hours_ahead(fixture_bytes):
    forecasts = Forecasts(clock=lambda: START + 3600.0)
    forecasts._tafs = parse_tafs(json.loads(fixture_bytes("taf.json")))
    # +3h 1794283200+..: MVFR (FM), +6h 1794294000: MVFR, +12h 1794315600: VFR
    assert forecasts.forecast("KHOU") == ("MVFR", "MVFR", "VFR")
    assert forecasts.forecast("KXXX") is None
    reports = with_forecast({"KHOU": Report(), "KXXX": None}, forecasts)
    assert reports["KHOU"].forecast == ("MVFR", "MVFR", "VFR") and reports["KXXX"] is None


# ---- the visualizer ----------------------------------------------------------------------------------------------


@pytest.fixture
def settings():
    return Settings()


def report(category="VFR", ahead=("IFR", "IFR", "VFR")):
    return Report(flight_category=category, forecast=ahead)


def test_look_steps_through_the_categories(settings):
    look = fcf.look(report(), settings)
    assert look.effect == "cycle" and look.step == fcf.FRAME
    held = round(settings.visualizer.forecast_step_seconds / fcf.FRAME)
    colors = look.colors
    c = flightcategory.COLORS
    assert colors[0] == colors[held - 1] == c["VFR"]
    assert colors[held + 4] == c["IFR"]  # the next step, once the fade (4 frames) is over
    assert set(colors) >= {c["VFR"], c["IFR"]} and len(colors) > 2 * held
    assert look.legend == ("VFR", "IFR")


def test_look_fades_between_steps(settings):
    colors = fcf.look(report("VFR", ("LIFR", "LIFR", "LIFR")), settings).colors
    held = round(settings.visualizer.forecast_step_seconds / fcf.FRAME)
    between = colors[held]
    assert between not in (flightcategory.COLORS["VFR"], flightcategory.COLORS["LIFR"])


def test_no_taf_is_a_dim_white_not_good_weather(settings):
    look = fcf.look(Report(flight_category="VFR"), settings)
    assert fcf.NO_FORECAST_COLOR in look.colors and look.legend == ("VFR", fcf.NO_FORECAST)
    assert fcf.NO_FORECAST_COLOR != flightcategory.COLORS["VFR"]


def test_a_forecast_that_never_changes_is_solid(settings):
    assert fcf.look(report("MVFR", ("MVFR", "MVFR", "MVFR")), settings) == Look.solid(flightcategory.COLORS["MVFR"])


def test_the_step_time_sets_how_long_each_is_shown(settings):
    settings.visualizer.forecast_step_seconds = 10
    long = len(fcf.look(report(), settings).colors)
    settings.visualizer.forecast_step_seconds = 2
    assert long > len(fcf.look(report(), settings).colors)


def test_missing_and_no_report(settings):
    assert fcf.look(None, settings) == style.no_report()
    assert fcf.look(Report(), settings) == style.missing()


def test_estimated_now_when_the_station_reports_no_category(settings):
    now = replace(report(None), visibility_sm=0.5)
    assert fcf.look(now, settings).colors[0] == flightcategory.COLORS["LIFR"]


def test_legend_and_registration(settings):
    labels = [item["label"] for item in visualizer.legend(fcf.VISUALIZER, settings)]
    assert labels[:5] == ["VFR", "MVFR", "IFR", "LIFR", "No forecast"]
