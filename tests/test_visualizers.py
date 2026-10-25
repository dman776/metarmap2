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
                                  style, temperature, visibility, visualizer, wind, windgusts)
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


# ---- every visualizer ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("v", ALL)
def test_metadata(v, settings):
    assert v.NAME and v.DESCRIPTION and v.EXCLUSIVE in (True, False)
    assert hasattr(v, "look") != hasattr(v, "strip_look"), "one look per airport, or one for the whole strip"
    assert v.legend(settings), "every visualizer explains its colors"
    for item in v.legend(settings):
        assert item["label"] and item["detail"]
        assert item["effect"] in {"solid", "blink", "pulse", "flash", "alternate", "chase", "off"}


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


# ---- the shared conventions (style.py) ---------------------------------------------------------------------

PER_AIRPORT = [v for v in ALL if hasattr(v, "look")]
RED_BLINK = Look.blink(C[colors_lib.RED], period=2)


@pytest.mark.parametrize("v", PER_AIRPORT)
def test_no_report_is_off_everywhere(v, settings):
    assert v.look({}, settings) == OFF


@pytest.mark.parametrize("v, field", [(wind, "windSpeed"), (windgusts, "windSpeed"), (temperature, "tempC"),
                                      (pressure, "altimHg"), (visibility, "visibilitySM"),
                                      (density_altitude, "tempC"), (flightcategory, "flightCategory")])
def test_a_missing_value_is_a_slow_red_blink_everywhere(v, field, settings):
    data = metar(**{field: None})
    if field == "visibilitySM":
        del data["vis"]  # older data's rounded visibility, used when visibilitySM is absent
    assert v.look(data, settings) == RED_BLINK


def test_intensity():
    blue = (0, 0, 255)
    assert style.by_intensity(blue, "-") == Look.pulse(blue, period=4, low=0.3)  # breathing, never dark
    assert style.by_intensity(blue, "") == Look.solid(blue)
    assert style.by_intensity(blue, "+") == Look.blink(blue, period=1, background=(0, 0, 76))  # bright and dim
    assert style.by_intensity(blue, "VC") == Look.solid((0, 0, 76))


@pytest.mark.parametrize("v", [wind, temperature, pressure, visibility, density_altitude])
def test_legends_come_from_the_band_tables(v, settings):
    rows = v.legend(settings)
    for band, row in zip(v.BANDS, rows):
        assert row["label"] == band.label and row["colors"] == [colors_lib.to_css(band.color_for(settings))]


# ---- wind and gusts -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("speed, name", [(0, colors_lib.GRAY), (1, colors_lib.BLUE), (9, colors_lib.BLUE),
                                         (10, colors_lib.YELLOW), (14, colors_lib.YELLOW), (15, colors_lib.ORANGE),
                                         (24, colors_lib.ORANGE), (25, colors_lib.RED), (60, colors_lib.RED)])
def test_wind_bands(settings, speed, name):
    assert wind.look(metar(windSpeed=speed), settings) == Look.solid(C[name])


def test_calm_is_not_off(settings):
    """Off means no report; calm is a dim white so the two can't be confused."""
    assert wind.look(metar(windSpeed=0), settings) != OFF


def test_gusts_alternate_wind_and_gust_colors(settings):
    look = windgusts.look(metar(windSpeed=12, windGust=True, windGustSpeed=27), settings)
    assert look == Look.blink(C[colors_lib.YELLOW], period=2, background=C[colors_lib.RED])


def test_gusts_in_the_same_band_breathe(settings):
    look = windgusts.look(metar(windSpeed=10, windGust=True, windGustSpeed=14), settings)
    assert look == Look.pulse(C[colors_lib.YELLOW], period=2, low=0.3)


def test_no_gusts_is_the_wind_color(settings):
    assert windgusts.look(metar(windSpeed=12), settings) == wind.look(metar(windSpeed=12), settings)


# ---- temperature, pressure, visibility, density altitude ----------------------------------------------------

@pytest.mark.parametrize("celsius, name", [(-10, colors_lib.WHITE), (-1, colors_lib.WHITE), (0, colors_lib.PURPLE),
                                           (12, colors_lib.BLUE), (20, colors_lib.LIGHT_BLUE), (28, colors_lib.YELLOW),
                                           (35, colors_lib.ORANGE), (40, colors_lib.RED)])
def test_temperature_bands(settings, celsius, name):
    """In °F: below 32 (freezing) white, 32-49 purple, 50-64 blue, 65-79 cyan, 80-89 yellow, 90-99 orange."""
    assert temperature.look(metar(tempC=celsius), settings) == Look.solid(C[name])


@pytest.mark.parametrize("inhg, name", [(29.5, colors_lib.RED), (29.85, colors_lib.LIGHT_RED),
                                        (29.92, colors_lib.LIGHT_BLUE), (30.1, colors_lib.LIGHT_BLUE),
                                        (30.2, colors_lib.BLUE), (30.6, colors_lib.BLUE)])
def test_pressure_bands(settings, inhg, name):
    assert pressure.look(metar(altimHg=inhg), settings) == Look.solid(C[name])


@pytest.mark.parametrize("miles, name", [(0.25, colors_lib.RED), (0.75, colors_lib.RED), (1, colors_lib.ORANGE),
                                         (2.5, colors_lib.ORANGE), (3, colors_lib.YELLOW), (5, colors_lib.YELLOW),
                                         (5.5, colors_lib.WHITE), (10, colors_lib.WHITE)])
def test_visibility_bands(settings, miles, name):
    """At the flight category limits: over 5 miles, 3-5, 1 to under 3, under 1."""
    assert visibility.look(metar(visibilitySM=miles), settings) == Look.solid(C[name])


def test_visibility_from_older_data(settings):
    assert visibility.look(metar(vis=2), settings) == Look.solid(C[colors_lib.ORANGE])  # no visibilitySM


def test_density_altitude_formula():
    # standard day at sea level: density altitude = field elevation
    assert calculate_density_altitude(29.92, 0, 15) == pytest.approx(0)
    assert calculate_density_altitude(29.92, 1000, 25) > 1000 * 3.28084


@pytest.mark.parametrize("fields, name", [
    ({"elevation_m": 0, "tempC": 15, "altimHg": 29.92}, colors_lib.LIGHT_BLUE),  # standard day
    ({"elevation_m": 0, "tempC": 0, "altimHg": 29.92}, colors_lib.LIGHT_BLUE),  # 0°C at a sea-level field is real
    ({"elevation_m": 0, "tempC": 28, "altimHg": 29.92}, colors_lib.YELLOW),
    ({"elevation_m": 0, "tempC": 35, "altimHg": 29.92}, colors_lib.ORANGE),
    ({"elevation_m": 1500, "tempC": 38, "altimHg": 29.7}, colors_lib.RED),
])
def test_density_altitude_bands(settings, fields, name):
    assert density_altitude.look(metar(**fields), settings) == Look.solid(C[name])


@pytest.mark.parametrize("fields", [{"tempC": None}, {"altimHg": 0}, {"elevation_m": None}])
def test_density_altitude_needs_all_inputs(settings, fields):
    assert density_altitude.look(metar(**fields), settings) == RED_BLINK


# ---- precipitation ------------------------------------------------------------------------------------------

def W(settings, name):
    return tuple(getattr(settings.color.weather, name))


def P(obs, settings):
    return precipitation.look(metar(obs=obs), settings)


@pytest.mark.parametrize("obs, kind", [("RA", "rain"), ("SHRA", "rain"), ("SN", "snow"), ("SG", "snow"),
                                       ("FZRA", "ice"), ("FZDZ", "ice"), ("PL", "ice"), ("GR", "ice"), ("GS", "ice"),
                                       ("IC", "ice"), ("SQ", "hazard"), ("FC", "hazard"), ("VA", "hazard"),
                                       ("UP", "unknown"), ("FG", "fog"), ("FZFG", "fog"), ("FU", "smoke"),
                                       ("HZ", "haze"), ("DU", "haze"), ("BR", "mist")])
def test_precipitation_color_is_the_kind(settings, obs, kind):
    assert P(obs, settings) == Look.solid(W(settings, kind))


def test_drizzle_is_a_dimmer_rain(settings):
    assert P("DZ", settings) == Look.solid(style.dim(W(settings, "rain"), 0.5))


@pytest.mark.parametrize("prefix, expected", [("-", "light"), ("", "moderate"), ("+", "heavy"), ("VC", "vicinity")])
@pytest.mark.parametrize("code, kind", [("RA", "rain"), ("SN", "snow"), ("FZRA", "ice")])
def test_precipitation_effect_is_the_intensity(settings, prefix, expected, code, kind):
    """The same effect for the same intensity, whatever falls: -SN looks like -RA, only white."""
    intensity = {"light": "-", "moderate": "", "heavy": "+", "vicinity": "VC"}[expected]
    assert P(prefix + code, settings) == style.by_intensity(W(settings, kind), intensity)


def test_heavy_rain_blinks(settings):
    """The old bug: '+RA' was matched by the 'RA' rule first, so heavy rain was solid."""
    assert P("+RA", settings).effect == "blink"


def test_most_significant_wins(settings):
    assert P("-RA BR", settings) == style.by_intensity(W(settings, "rain"), "-")  # rain over mist
    assert P("BR -SN", settings) == style.by_intensity(W(settings, "snow"), "-")  # whatever the order
    assert P("RA FZDZ", settings).colors[0] == W(settings, "ice")  # ice over rain
    assert P("SN SQ", settings).colors[0] == W(settings, "hazard")


def test_thunderstorms(settings):
    yellow = W(settings, "lightning")
    assert P("TS", settings) == Look.blink(yellow, period=1, background=style.dim(yellow))
    assert P("TSRA", settings) == Look.blink(W(settings, "rain"), period=1, background=yellow)
    assert P("VCTS", settings) == Look.solid(style.dim(yellow))
    assert P("-RA TS", settings).effect == "blink"  # a thunderstorm anywhere wins


def test_two_kinds_at_once_alternate(settings):
    assert P("-RASN", settings) == Look.blink(W(settings, "snow"), period=2, background=W(settings, "rain"))


def test_showers_of_an_unknown_kind_are_rain(settings):
    assert P("VCSH", settings) == Look.solid(style.dim(W(settings, "rain")))


@pytest.mark.parametrize("obs", ["", None, "NSW"])
def test_no_weather_is_off(settings, obs):
    assert P(obs, settings) == OFF


def test_unknown_codes_are_a_slow_red_blink(settings):
    assert P("XX", settings) == RED_BLINK


# ---- whole-strip patterns -----------------------------------------------------------------------------------

def test_rainbow(settings):
    assert rainbow.strip_look(settings) == Look.rainbow(period=5)


def test_chase_walks_every_led(settings):
    settings.led.count = 30
    look = chase.strip_look(settings)
    assert look == Look.chase([0, 0, 255], step=0.1, size=1, spacing=29)
