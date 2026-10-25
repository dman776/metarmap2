"""
Color rules for every visualizer: METAR in, Look out. No LEDs involved.
Colors are in the strip's GRB order (see lib/colors.py).
"""
import pytest

import metarmap.lib.colors as colors_lib
from metarmap.models import Look
from metarmap.settings import Settings
from metarmap import visualizers
from metarmap.visualizers import (chase, density_altitude, flightcategory, precipitation, pressure, rainbow,
                                  temperature, visibility, visualizer, wind, windgusts)
from metarmap.visualizers.density_altitude import calculate_density_altitude

C = colors_lib.get_colors()
OFF = Look.off()
ALL = visualizers.ALL


@pytest.fixture
def settings():
    return Settings()


def metar(**fields):
    base = {"flightCategory": "VFR", "lightning": False, "windSpeed": 0, "windGust": False, "windGustSpeed": 0,
            "windDir": "100", "tempC": 20, "dewpointC": 10, "altimHg": 29.92, "vis": 10, "elevation_m": 100, "obs": ""}
    return {**base, **fields}


def mix(a, b, proportion):
    return tuple(colors_lib.get_color_mix(C[a], C[b], proportion))


# ---- every visualizer ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("v", ALL)
def test_metadata(v, settings):
    assert v.NAME and v.DESCRIPTION and v.EXCLUSIVE in (True, False)
    assert hasattr(v, "look") != hasattr(v, "strip_look"), "one look per airport, or one for the whole strip"
    assert v.legend(settings), "every visualizer explains its colors"
    for item in v.legend(settings):
        assert item["label"] and item["detail"]
        assert item["effect"] in {"solid", "blink", "pulse", "flash", "chase", "off"}


@pytest.mark.parametrize("v", ALL)
def test_leds_without_an_airport_stay_dark(v, settings):
    if visualizer.strip_look(v, settings) is None:
        looks = visualizer.looks(v, ["", "KTST", "KTST"], {"KTST": metar()}, settings)
        assert looks[0] == OFF
        assert looks[1] == looks[2] == v.look(metar(), settings)  # one airport on two LEDs


def test_exclusive_visualizers():
    assert {v.NAME for v in ALL if v.EXCLUSIVE} == {"Precipitation", "Rainbow", "Chase"}


def test_info(settings):
    assert visualizer.info(wind, settings) == {"name": "Wind", "description": wind.DESCRIPTION, "exclusive": False,
                                               "legend": wind.legend(settings)}


# ---- flight category ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("category, attr", [("VFR", "vfr"), ("MVFR", "mvfr"), ("IFR", "ifr"), ("LIFR", "lifr")])
def test_flight_category_colors(settings, category, attr):
    look = flightcategory.look(metar(flightCategory=category), settings)
    assert look == Look.solid(getattr(settings.color.cat, attr))


def test_flight_category_uses_configured_colors(settings):
    settings.color.cat.vfr = [10, 20, 30]
    assert flightcategory.look(metar(flightCategory="VFR"), settings) == Look.solid([10, 20, 30])


def test_flight_category_missing_blinks_red(settings):
    look = flightcategory.look(metar(flightCategory=None), settings)
    assert look == Look.blink(C[colors_lib.RED], period=2)


def test_flight_category_no_report_is_off(settings):
    assert flightcategory.look({}, settings) == OFF


def test_lightning_flashes_over_category(settings):
    look = flightcategory.look(metar(flightCategory="IFR", lightning=True), settings)
    assert look.effect == "cycle"
    assert look.step == 0.1
    assert look.colors == (tuple(settings.color.cat.ifr),) * 15 + (tuple(settings.color.weather.lightning),)


def test_lightning_animation_can_be_turned_off(settings):
    settings.lightning.animation = False
    look = flightcategory.look(metar(flightCategory="IFR", lightning=True), settings)
    assert look == Look.solid(settings.color.cat.ifr)


# ---- wind and gusts -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("speed, expected", [
    (0, tuple(C[colors_lib.DARK_GRAY])),
    (5, tuple(C[colors_lib.PURPLE])),
    (10, tuple(C[colors_lib.BLUE])),
    (15, tuple(C[colors_lib.GREEN])),
    (20, tuple(C[colors_lib.YELLOW])),
    (25, tuple(C[colors_lib.ORANGE])),
    (30, tuple(C[colors_lib.RED])),
    (45, tuple(C[colors_lib.RED])),
])
def test_wind_scale_points(settings, speed, expected):
    assert wind.look(metar(windSpeed=speed), settings).color == expected


def test_wind_blends_between_points(settings):
    assert wind.look(metar(windSpeed=12), settings).color == mix(colors_lib.BLUE, colors_lib.GREEN, 0.4)
    assert wind.look(metar(windSpeed=2), settings).color == mix(colors_lib.OFF, colors_lib.PURPLE, 0.4)


def test_wind_no_report(settings):
    assert wind.look({}, settings) == OFF


@pytest.mark.parametrize("gust, period", [(5, 10), (10, 10), (11, 8), (15, 8), (16, 6), (20, 6), (21, 4), (25, 4),
                                          (26, 1), (30, 1), (31, 0.5), (60, 0.5)])
def test_gusts_pulse_faster_when_stronger(settings, gust, period):
    look = windgusts.look(metar(windSpeed=12, windGust=True, windGustSpeed=gust), settings)
    assert look.effect == "pulse"
    assert look.period == period
    assert look.color == wind.look(metar(windSpeed=12), settings).color


def test_no_gusts_is_solid_wind_color(settings):
    look = windgusts.look(metar(windSpeed=12), settings)
    assert look == wind.look(metar(windSpeed=12), settings)


# ---- temperature --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("celsius, expected", [
    (-20, tuple(C[colors_lib.WHITE])),  # -4 °F
    (-15, mix(colors_lib.WHITE, colors_lib.PURPLE, 0.125)),  # 5 °F
    (10, mix(colors_lib.PURPLE, colors_lib.BLUE, 0.5)),  # 50 °F
    (25, mix(colors_lib.GREEN, colors_lib.YELLOW, 0.7)),  # 77 °F
    (40, tuple(C[colors_lib.RED])),  # 104 °F
])
def test_temperature_scale(settings, celsius, expected):
    assert temperature.look(metar(tempC=celsius), settings).color == expected


@pytest.mark.parametrize("data", [{}, metar(tempC=None)])
def test_temperature_missing_is_off(settings, data):
    assert temperature.look(data, settings) == OFF


# ---- pressure -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("inhg, expected", [
    (29.5, tuple(C[colors_lib.RED])),
    (29.8, tuple(C[colors_lib.RED])),
    (29.92, tuple(C[colors_lib.LIGHT_RED])),
    (30.06, mix(colors_lib.LIGHT_BLUE, colors_lib.BLUE, 0.5)),
    (30.3, tuple(C[colors_lib.BLUE])),
])
def test_pressure_scale(settings, inhg, expected):
    assert pressure.look(metar(altimHg=inhg), settings).color == expected


# ---- visibility ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("vis, level", [(10, 255), (9, 80), (8, 40), (7, 20), (6, 10), (5, 5), (4, 4), (3, 3),
                                        (2, 2), (1, 1)])
def test_visibility_dims_with_distance(settings, vis, level):
    assert visibility.look(metar(vis=vis), settings).color == (level, level, level)


def test_visibility_zero_is_off(settings):
    assert visibility.look(metar(vis=0), settings).color == (0, 0, 0)


def test_visibility_not_reported_is_red(settings):
    assert visibility.look(metar(vis=None), settings) == Look.solid(C[colors_lib.RED])


def test_visibility_no_report_blinks_red(settings):
    assert visibility.look({}, settings) == Look.blink(C[colors_lib.RED], period=2)


# ---- density altitude ---------------------------------------------------------------------------------------

def test_density_altitude_formula():
    # standard day at sea level: density altitude == field elevation (0)
    assert calculate_density_altitude(29.92, 0, 15) == pytest.approx(0)
    assert calculate_density_altitude(None, 100, 20) is None


@pytest.mark.parametrize("fields", [{"tempC": 0}, {"altimHg": 0}, {"elevation_m": 0}, {"tempC": None}])
def test_density_altitude_needs_all_inputs(settings, fields):
    assert density_altitude.look(metar(**fields), settings) == OFF


def test_density_altitude_hot_day_is_red(settings):
    # 10 m field on a 40 °C day with low pressure: DA is about 98 times the field elevation
    look = density_altitude.look(metar(elevation_m=10, tempC=40, altimHg=29.7), settings)
    assert look.color == tuple(C[colors_lib.RED])


def test_density_altitude_warm_day_blends_toward_red(settings):
    # 100 m field, same day: factor about 11, so gray blending toward red
    look = density_altitude.look(metar(elevation_m=100, tempC=40, altimHg=29.7), settings)
    assert look.color == mix(colors_lib.DARK_GRAY, colors_lib.RED, 11 / 40)


def test_density_altitude_cold_day_is_green(settings):
    look = density_altitude.look(metar(elevation_m=10, tempC=-20, altimHg=30.4), settings)
    assert look.color == tuple(C[colors_lib.GREEN])


# ---- precipitation ------------------------------------------------------------------------------------------

def W(settings, name):
    return getattr(settings.color.weather, name)


@pytest.mark.parametrize("obs, expected", [
    ("", lambda s: OFF),
    ("VCTS", lambda s: Look.blink(W(s, "lightning"))),
    ("TS RA", lambda s: Look.blink(W(s, "lightning"))),
    ("-FZDZ", lambda s: Look.pulse(W(s, "drizzle"), period=0.5)),
    ("-FZRA", lambda s: Look.pulse(W(s, "rain"), period=2)),
    ("-SN", lambda s: Look.pulse(C[colors_lib.WHITE], period=2)),
    ("SN", lambda s: Look.pulse(C[colors_lib.WHITE], period=1)),
    ("-RA", lambda s: Look.pulse(W(s, "rain"), period=4)),
    ("RA", lambda s: Look.solid(W(s, "rain"))),
    ("-RA BR", lambda s: Look.pulse(W(s, "rain"), period=4)),  # first matching code wins
    ("-DZ", lambda s: Look.pulse(W(s, "drizzle"), period=4)),
    ("DZ", lambda s: Look.solid(W(s, "drizzle"))),
    ("FG", lambda s: Look.pulse(W(s, "fog"), period=4)),
    ("HZ", lambda s: Look.solid(W(s, "haze"))),
    ("BR", lambda s: Look.solid(W(s, "mist"))),
    ("-UP", lambda s: Look.blink(C[colors_lib.LIGHT_RED])),
    ("UP", lambda s: Look.blink(C[colors_lib.RED])),
    ("SQ", lambda s: Look.blink(C[colors_lib.RED])),  # anything else
])
def test_precipitation(settings, obs, expected):
    assert precipitation.look(metar(obs=obs), settings) == expected(settings)


@pytest.mark.xfail(strict=True, reason="known bug: '+RA' is matched by the 'RA' rule first, so heavy rain is "
                                       "solid, not blinking as the legend says")
def test_heavy_rain_blinks(settings):
    assert precipitation.look(metar(obs="+RA"), settings) == Look.blink(W(settings, "rain"))


# ---- whole-strip patterns -----------------------------------------------------------------------------------

def test_rainbow(settings):
    assert rainbow.strip_look(settings) == Look.rainbow(period=5)


def test_chase_walks_every_led(settings):
    settings.led.count = 30
    look = chase.strip_look(settings)
    assert look == Look.chase([0, 0, 255], step=0.1, size=1, spacing=29)
