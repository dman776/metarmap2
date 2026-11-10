"""Precipitation Forecast: the weather now and as the TAF forecasts it, stepping, as Precipitation looks."""

from dataclasses import replace

import pytest

from metarmap import visualizers
from metarmap.models import Look, Report
from metarmap.settings import Settings
from metarmap.visualizers import flightcategory_forecast, forecast_steps, precipitation, precipitation_forecast as pf
from metarmap.visualizers import style, visualizer


@pytest.fixture
def settings():
    return Settings()


def report(weather="", ahead=((), (), ())):
    return Report(flight_category="VFR", weather=weather, forecast_weather=ahead)


def test_the_most_significant_weather_wins():
    assert pf.most_significant([]) == ""
    assert pf.most_significant(["-RA", "-TSRA"]) == "-TSRA"  # a thunderstorm over rain
    assert pf.most_significant(["BR", "-SN"]) == "-SN"  # snow over mist
    assert pf.most_significant(["-RA", "+RA"]) == "+RA"  # heavier of one kind
    assert pf.most_significant(["-RA", "-RA"]) == "-RA"
    assert pf.most_significant(["BR", "FG"]) == "FG"


def test_steps_look_as_precipitation_does(settings):
    look = pf.look(report("", ((), ("-RA",), ("+SN",))), settings)
    assert look.effect == "cycle" and look.step == forecast_steps.FRAME
    held = forecast_steps.hold_frames(settings)
    segment = held + round(forecast_steps.FADE / forecast_steps.FRAME)
    assert look.colors[0] == (0, 0, 0)  # dry now: off
    # +6h: light rain breathes, so the hold isn't one color; +12h: heavy snow blinks white
    rain = look.colors[2 * segment : 2 * segment + held]
    assert len(set(rain)) > 1 and max(rain) <= precipitation.RAIN
    snow = look.colors[3 * segment : 3 * segment + held]
    assert precipitation.SNOW in snow
    assert {"no_weather", "light", "rain", "heavy", "snow"} <= set(look.legend)


def test_a_dry_forecast_all_day_is_off_not_a_cycle(settings):
    assert pf.look(report(), settings) == Look.solid((0, 0, 0)).tagged("no_weather")


def test_no_taf_is_a_dim_white_not_dry(settings):
    look = pf.look(replace(report("-RA"), forecast_weather=None), settings)
    assert forecast_steps.NO_FORECAST_COLOR in look.colors and look.legend[-1] == forecast_steps.NO_FORECAST
    one = pf.look(report("", (None, ("RA",), ())), settings)  # a TAF that doesn't reach +3h
    assert forecast_steps.NO_FORECAST_COLOR in one.colors


def test_unknown_weather_codes_now_are_missing_data(settings):
    assert pf.look(report("XX"), settings) == style.missing()
    assert pf.look(None, settings) == style.no_report()


def test_a_step_lasts_the_hold_plus_the_fade(settings):
    look = pf.look(report("", ((), ("-RA",), ())), settings)
    assert len(look.colors) * look.step == pytest.approx(4 * forecast_steps.step_seconds(settings))
    assert pf.VISUALIZER.steps(settings) == {
        "labels": ["Now", "+3h", "+6h", "+12h"],
        "seconds": 7.0,
        "prefix": "PF",
    }


def test_the_legend_has_the_precipitation_entries_and_no_forecast(settings):
    keys = [item["key"] for item in visualizer.legend(pf.VISUALIZER, settings)]
    assert {"rain", "snow", "thunderstorm", "no_weather", "no_forecast", "missing", "no_report"} <= set(keys)
    assert keys.index("no_forecast") < keys.index("missing")


def test_registered_after_flight_category_forecast():
    ids = [v.id for v in visualizers.ALL]
    assert ids.index("precipitation_forecast") == ids.index("flight_category_forecast") + 1
    assert pf.VISUALIZER.icon == "umbrella" and flightcategory_forecast.VISUALIZER.icon == "clock"
