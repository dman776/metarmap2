"""
Color rules for every visualizer: METAR in, Look out. No LEDs involved.
Colors are in the strip's GRB order (see lib/colors.py).
"""
from types import SimpleNamespace

import pytest

import metarmap.lib.colors as colors_lib
from metarmap.models import Look
from metarmap.settings import Settings
from metarmap.visualizers.chase import Chase
from metarmap.visualizers.density_altitude import DensityAltitude, calculate_density_altitude
from metarmap.visualizers.flightcategory import FlightCategory
from metarmap.visualizers.precipitation import Precipitation
from metarmap.visualizers.pressure import Pressure
from metarmap.visualizers.rainbow import Rainbow
from metarmap.visualizers.temperature import Temperature
from metarmap.visualizers.visibility import Visibility
from metarmap.visualizers.wind import Wind
from metarmap.visualizers.windgusts import WindGusts

C = colors_lib.get_colors()
OFF = Look.off()
ALL = [FlightCategory, Wind, WindGusts, Pressure, Precipitation, Temperature, Visibility, DensityAltitude, Rainbow,
       Chase]


@pytest.fixture
def settings():
    return Settings()


def make(cls, settings):
    return cls(SimpleNamespace(data=settings))


def metar(**fields):
    base = {"flightCategory": "VFR", "lightning": False, "windSpeed": 0, "windGust": False, "windGustSpeed": 0,
            "windDir": "100", "tempC": 20, "dewpointC": 10, "altimHg": 29.92, "vis": 10, "elevation_m": 100, "obs": ""}
    return {**base, **fields}


def mix(a, b, proportion):
    return tuple(colors_lib.get_color_mix(C[a], C[b], proportion))


# ---- every visualizer ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("cls", ALL)
def test_metadata(cls, settings):
    v = make(cls, settings)
    assert v.name and v.description
    assert v.legend, "every visualizer explains its colors"
    for item in v.legend:
        assert item["label"] and item["detail"]
        assert item["effect"] in {"solid", "blink", "pulse", "flash", "chase", "off"}


@pytest.mark.parametrize("cls", ALL)
def test_null_airports_stay_dark(cls, settings):
    v = make(cls, settings)
    if v.strip_look() is None:
        assert v.looks({"NULL1": metar(), "KTST": {}})[0] == OFF


def test_exclusive_visualizers(settings):
    assert {cls.__name__ for cls in ALL if make(cls, settings).exclusive} == {"Precipitation", "Rainbow", "Chase"}


# ---- flight category ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("category, attr", [("VFR", "vfr"), ("MVFR", "mvfr"), ("IFR", "ifr"), ("LIFR", "lifr")])
def test_flight_category_colors(settings, category, attr):
    look = make(FlightCategory, settings).look(metar(flightCategory=category))
    assert look == Look.solid(getattr(settings.color.cat, attr))


def test_flight_category_uses_configured_colors(settings):
    settings.color.cat.vfr = [10, 20, 30]
    assert make(FlightCategory, settings).look(metar(flightCategory="VFR")) == Look.solid([10, 20, 30])


def test_flight_category_missing_blinks_red(settings):
    look = make(FlightCategory, settings).look(metar(flightCategory=None))
    assert look == Look.blink(C[colors_lib.RED], period=2)


def test_flight_category_no_report_is_off(settings):
    assert make(FlightCategory, settings).look({}) == OFF


def test_lightning_flashes_over_category(settings):
    look = make(FlightCategory, settings).look(metar(flightCategory="IFR", lightning=True))
    assert look.effect == "cycle"
    assert look.step == 0.1
    assert look.colors == (tuple(settings.color.cat.ifr),) * 15 + (tuple(settings.color.weather.lightning),)


def test_lightning_animation_can_be_turned_off(settings):
    settings.lightning.animation = False
    look = make(FlightCategory, settings).look(metar(flightCategory="IFR", lightning=True))
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
    assert make(Wind, settings).look(metar(windSpeed=speed)).color == expected


def test_wind_blends_between_points(settings):
    assert make(Wind, settings).look(metar(windSpeed=12)).color == mix(colors_lib.BLUE, colors_lib.GREEN, 0.4)
    assert make(Wind, settings).look(metar(windSpeed=2)).color == mix(colors_lib.OFF, colors_lib.PURPLE, 0.4)


def test_wind_no_report(settings):
    assert make(Wind, settings).look({}) == OFF


@pytest.mark.parametrize("gust, period", [(5, 10), (10, 10), (11, 8), (15, 8), (16, 6), (20, 6), (21, 4), (25, 4),
                                          (26, 1), (30, 1), (31, 0.5), (60, 0.5)])
def test_gusts_pulse_faster_when_stronger(settings, gust, period):
    look = make(WindGusts, settings).look(metar(windSpeed=12, windGust=True, windGustSpeed=gust))
    assert look.effect == "pulse"
    assert look.period == period
    assert look.color == make(Wind, settings).look(metar(windSpeed=12)).color


def test_no_gusts_is_solid_wind_color(settings):
    look = make(WindGusts, settings).look(metar(windSpeed=12))
    assert look == make(Wind, settings).look(metar(windSpeed=12))


# ---- temperature --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("celsius, expected", [
    (-20, tuple(C[colors_lib.WHITE])),  # -4 °F
    (-15, mix(colors_lib.WHITE, colors_lib.PURPLE, 0.125)),  # 5 °F
    (10, mix(colors_lib.PURPLE, colors_lib.BLUE, 0.5)),  # 50 °F
    (25, mix(colors_lib.GREEN, colors_lib.YELLOW, 0.7)),  # 77 °F
    (40, tuple(C[colors_lib.RED])),  # 104 °F
])
def test_temperature_scale(settings, celsius, expected):
    assert make(Temperature, settings).look(metar(tempC=celsius)).color == expected


@pytest.mark.parametrize("data", [{}, metar(tempC=None)])
def test_temperature_missing_is_off(settings, data):
    assert make(Temperature, settings).look(data) == OFF


# ---- pressure -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("inhg, expected", [
    (29.5, tuple(C[colors_lib.RED])),
    (29.8, tuple(C[colors_lib.RED])),
    (29.92, tuple(C[colors_lib.LIGHT_RED])),
    (30.06, mix(colors_lib.LIGHT_BLUE, colors_lib.BLUE, 0.5)),
    (30.3, tuple(C[colors_lib.BLUE])),
])
def test_pressure_scale(settings, inhg, expected):
    assert make(Pressure, settings).look(metar(altimHg=inhg)).color == expected


# ---- visibility ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("vis, level", [(10, 255), (9, 80), (8, 40), (7, 20), (6, 10), (5, 5), (4, 4), (3, 3),
                                        (2, 2), (1, 1)])
def test_visibility_dims_with_distance(settings, vis, level):
    assert make(Visibility, settings).look(metar(vis=vis)).color == (level, level, level)


def test_visibility_zero_is_off(settings):
    assert make(Visibility, settings).look(metar(vis=0)).color == (0, 0, 0)


def test_visibility_not_reported_is_red(settings):
    assert make(Visibility, settings).look(metar(vis=None)) == Look.solid(C[colors_lib.RED])


def test_visibility_no_report_blinks_red(settings):
    assert make(Visibility, settings).look({}) == Look.blink(C[colors_lib.RED], period=2)


# ---- density altitude ---------------------------------------------------------------------------------------

def test_density_altitude_formula():
    # standard day at sea level: density altitude == field elevation (0)
    assert calculate_density_altitude(29.92, 0, 15) == pytest.approx(0)
    assert calculate_density_altitude(None, 100, 20) is None


@pytest.mark.parametrize("fields", [{"tempC": 0}, {"altimHg": 0}, {"elevation_m": 0}, {"tempC": None}])
def test_density_altitude_needs_all_inputs(settings, fields):
    assert make(DensityAltitude, settings).look(metar(**fields)) == OFF


def test_density_altitude_hot_day_is_red(settings):
    # 10 m field on a 40 °C day with low pressure: DA is about 98 times the field elevation
    look = make(DensityAltitude, settings).look(metar(elevation_m=10, tempC=40, altimHg=29.7))
    assert look.color == tuple(C[colors_lib.RED])


def test_density_altitude_warm_day_blends_toward_red(settings):
    # 100 m field, same day: factor about 11, so gray blending toward red
    look = make(DensityAltitude, settings).look(metar(elevation_m=100, tempC=40, altimHg=29.7))
    assert look.color == mix(colors_lib.DARK_GRAY, colors_lib.RED, 11 / 40)


def test_density_altitude_cold_day_is_green(settings):
    look = make(DensityAltitude, settings).look(metar(elevation_m=10, tempC=-20, altimHg=30.4))
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
    assert make(Precipitation, settings).look(metar(obs=obs)) == expected(settings)


@pytest.mark.xfail(strict=True, reason="known bug: '+RA' is matched by the 'RA' rule first, so heavy rain is "
                                       "solid, not blinking as the legend says")
def test_heavy_rain_blinks(settings):
    assert make(Precipitation, settings).look(metar(obs="+RA")) == Look.blink(W(settings, "rain"))


# ---- whole-strip patterns -----------------------------------------------------------------------------------

def test_rainbow(settings):
    assert make(Rainbow, settings).strip_look() == Look.rainbow(period=5)


def test_chase_walks_every_led(settings):
    settings.led.count = 30
    look = make(Chase, settings).strip_look()
    assert look == Look.chase([0, 0, 255], step=0.1, size=1, spacing=29)
