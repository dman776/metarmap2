"""
Color rules for every visualizer: METAR in, Look out. No LEDs involved.
Colors are in the strip's GRB order (see lib/colors.py).
"""
import pytest

import metarmap.lib.colors as colors_lib
from metarmap.models import Look
from metarmap.settings import Settings
from metarmap import decode, visualizers
from metarmap.visualizers import (ceiling, chase, density_altitude, flightcategory, precipitation, pressure, rainbow,
                                  spread, style, temperature, visibility, visualizer, wind, wind_direction,
                                  windgusts)
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
    assert {v.NAME for v in ALL if v.EXCLUSIVE} == {"Rainbow", "Chase"}


def test_info(settings):
    assert visualizer.info(wind, settings) == {"name": "Wind", "description": wind.DESCRIPTION, "exclusive": False,
                                               "legend": visualizer.legend(wind, settings)}


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


def estimated(metar_fields, settings):
    """The look of an airport that doesn't report a category."""
    return flightcategory.look(metar(flightCategory=None, **metar_fields), settings)


def breathing(color):
    return Look.pulse(color, period=flightcategory.ESTIMATE_PERIOD, low=style.LIGHT_LOW)


@pytest.mark.parametrize("fields, attr", [
    # visibility only (an automated station without a ceilometer reading)
    ({"visibilitySM": 10.0}, "vfr"), ({"visibilitySM": 6.0}, "vfr"), ({"visibilitySM": 5.0}, "mvfr"),
    ({"visibilitySM": 3.0}, "mvfr"), ({"visibilitySM": 2.5}, "ifr"), ({"visibilitySM": 1.0}, "ifr"),
    ({"visibilitySM": 0.75}, "lifr"),
    # sky condition only
    ({"skyConditions": [{"cover": "FEW", "cloudBaseFt": 3900}]}, "vfr"),
    ({"skyConditions": [{"cover": "CLR", "cloudBaseFt": 0}]}, "vfr"),
    ({"skyConditions": [{"cover": "BKN", "cloudBaseFt": 3100}]}, "vfr"),
    ({"skyConditions": [{"cover": "BKN", "cloudBaseFt": 3000}]}, "mvfr"),
    ({"skyConditions": [{"cover": "OVC", "cloudBaseFt": 1000}]}, "mvfr"),
    ({"skyConditions": [{"cover": "BKN", "cloudBaseFt": 800}]}, "ifr"),
    ({"skyConditions": [{"cover": "OVC", "cloudBaseFt": 500}]}, "ifr"),
    ({"skyConditions": [{"cover": "OVC", "cloudBaseFt": 400}]}, "lifr"),
    ({"skyConditions": [{"cover": "OVX", "cloudBaseFt": 0}], "vertVisFt": 200}, "lifr"),
    # both: the worse decides
    ({"visibilitySM": 10.0, "skyConditions": [{"cover": "OVC", "cloudBaseFt": 400}]}, "lifr"),
    ({"visibilitySM": 2.0, "skyConditions": [{"cover": "CLR", "cloudBaseFt": 0}]}, "ifr"),
    ({"visibilitySM": 4.0, "skyConditions": [{"cover": "BKN", "cloudBaseFt": 800}]}, "ifr"),
])
def test_a_missing_category_is_estimated_and_breathes(settings, fields, attr):
    assert estimated(fields, settings) == breathing(getattr(settings.color.cat, attr))


def test_nothing_to_estimate_from_blinks_red(settings):
    assert estimated({}, settings) == RED_BLINK
    assert estimated({"visibilitySM": None, "skyConditions": []}, settings) == RED_BLINK


def test_a_reported_category_is_never_estimated(settings):
    """aviationweather.gov's category wins, even if the visibility and ceiling would say otherwise."""
    look = flightcategory.look(metar(flightCategory="VFR", visibilitySM=0.5), settings)
    assert look == Look.solid(settings.color.cat.vfr)


def test_the_legend_explains_estimates(settings):
    item = next(i for i in flightcategory.legend(settings) if i["label"] == "Estimated")
    assert item["effect"] == "pulse" and item["period"] == flightcategory.ESTIMATE_PERIOD


def test_estimating_from_real_reports():
    """Reports like these come in without a category from aviationweather.gov (sampled 2026-10-26)."""
    from metarmap.metar import parse_report
    vis_only = parse_report({"rawOb": "METAR KSOW 261735Z AUTO VRB04KT 10SM 14/04 A3028 RMK AO2", "visib": "10+",
                             "fltCat": None})
    sky_only = parse_report({"rawOb": "METAR K18H 261730Z AUTO 09011G18KT FEW039 31/17 A3013 RMK A01",
                             "clouds": [{"cover": "FEW", "base": 3900}], "fltCat": None})
    neither = parse_report({"rawOb": "METAR CWEH 261700Z AUTO 12020KT M01/M01 RMK AO1", "fltCat": None})
    assert decode.estimate_category(vis_only) == "VFR"
    assert decode.estimate_category(sky_only) == "VFR"
    assert decode.estimate_category(neither) is None


# ---- lightning: the same double flicker over every weather visualizer ----------------------------------------

def lit(v, settings, **fields):
    return visualizer.look(v, metar(**fields), settings)


def flicker(base, flash):
    """The frames of 2 s: flash, back, flash, then the base color."""
    return [flash] * 3 + [base] * 2 + [flash] * 3 + [base] * 32


def test_lightning_flickers_over_the_category(settings):
    look = lit(flightcategory, settings, flightCategory="IFR", lightning=True)
    ifr, yellow = tuple(settings.color.cat.ifr), tuple(settings.color.weather.lightning)
    assert look.effect == "cycle" and look.step == style.LIGHTNING_STEP
    assert list(look.colors) == flicker(ifr, yellow) * 2  # every 2 s, for 4 s


@pytest.mark.parametrize("v", visualizers.WEATHER)
def test_every_weather_visualizer_shows_lightning(v, settings):
    look = lit(v, settings, lightning=True)
    yellow = tuple(settings.color.weather.lightning)
    assert look.effect == "cycle" and look.colors[:3] == (yellow,) * 3 and look.colors[40:43] == (yellow,) * 3
    assert any(i["label"] == "Lightning or a thunderstorm" for i in visualizer.legend(v, settings))


@pytest.mark.parametrize("v", visualizers.WEATHER)
def test_lightning_animation_off_is_honored_everywhere(v, settings):
    settings.lightning.animation = False
    m = metar(lightning=True, obs="TSRA")
    assert visualizer.look(v, m, settings) == v.look(m, settings)
    assert all(i["label"] != "Lightning or a thunderstorm" for i in visualizer.legend(v, settings))


@pytest.mark.parametrize("fields, has", [({"lightning": True}, True), ({"obs": "TSRA"}, True),
                                         ({"obs": "+TSRA BR"}, True), ({"obs": "VCTS"}, True),
                                         ({"obs": "-RA"}, False), ({}, False)])
def test_what_counts_as_lightning(fields, has):
    assert style.has_lightning(metar(**fields)) is has
    assert style.has_lightning({}) is False  # no report


def test_lightning_keeps_the_look_moving_between_flashes(settings):
    """A heavy blink (or a breath) carries on between the flickers."""
    base = Look.blink((200, 0, 0), period=1, background=(60, 0, 0))
    frames = style.with_lightning(base, settings).colors
    assert frames[8] == (200, 0, 0) and frames[10] == (60, 0, 0)  # 0.4 s: bright half; 0.5 s: dim half
    breath = style.with_lightning(Look.pulse((100, 100, 100), period=4, low=0.3), settings).colors
    assert breath[8] != breath[20]


def test_lightning_on_yellow_is_dimmed_between_flashes(settings):
    yellow = tuple(settings.color.weather.lightning)
    frames = lit(precipitation, settings, obs="TS").colors
    assert frames[:3] == (yellow,) * 3 and frames[3] == style.dim(yellow)


def test_lightning_isnt_added_to_whole_strip_patterns(settings):
    assert not visualizer.shows_lightning(rainbow, settings)
    assert all(i["label"] != "Lightning or a thunderstorm" for i in visualizer.legend(rainbow, settings))


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


@pytest.mark.parametrize("v", [wind, windgusts, temperature, pressure, visibility, density_altitude])
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


@pytest.mark.parametrize("speed, gust, name", [
    (12, 0, colors_lib.GRAY),  # not gusting
    (12, 13, colors_lib.BLUE), (12, 21, colors_lib.BLUE),  # 1 and 9 kt above
    (12, 22, colors_lib.YELLOW), (12, 26, colors_lib.YELLOW),  # 10 and 14
    (12, 27, colors_lib.ORANGE), (12, 31, colors_lib.ORANGE),  # 15 and 19
    (12, 32, colors_lib.RED), (5, 45, colors_lib.RED),  # 20 and 40
])
def test_gust_spread_bands(settings, speed, gust, name):
    data = metar(windSpeed=speed, windGust=gust > 0, windGustSpeed=gust)
    assert windgusts.look(data, settings) == Look.solid(C[name])


def test_gusts_are_about_the_spread_not_the_speed(settings):
    """A strong steady wind isn't gusty, and a light one can be."""
    steady = metar(windSpeed=30, windGust=False, windGustSpeed=0)
    gusty = metar(windSpeed=6, windGust=True, windGustSpeed=24)
    assert windgusts.look(steady, settings) == Look.solid(C[colors_lib.GRAY])
    assert windgusts.look(gusty, settings) == Look.solid(C[colors_lib.ORANGE])
    assert wind.look(steady, settings) != wind.look(gusty, settings)


def test_a_gust_that_is_not_above_the_wind_is_no_gust(settings):
    assert windgusts.look(metar(windSpeed=12, windGust=True, windGustSpeed=12), settings) == Look.solid(
        C[colors_lib.GRAY])
    assert windgusts.look(metar(windSpeed=12, windGust=True, windGustSpeed=0), settings) == Look.solid(
        C[colors_lib.GRAY])


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
    """Without lightning (look_for_weather is the base look): the storm's precipitation, else yellow."""
    yellow = W(settings, "lightning")
    assert P("TS", settings) == Look.solid(yellow)
    assert P("TSRA", settings) == Look.solid(W(settings, "rain"))
    assert P("+TSRA", settings) == style.by_intensity(W(settings, "rain"), "+")
    assert P("VCTS", settings) == Look.solid(style.dim(yellow))
    assert P("BR TS", settings) == Look.solid(yellow)  # a thunderstorm anywhere wins


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


# ---- ceiling ------------------------------------------------------------------------------------------------

def sky(*layers):
    return [{"cover": cover, "cloudBaseFt": base} for cover, base in layers]


@pytest.mark.parametrize("layers, name", [
    (sky(("BKN", 400)), colors_lib.RED),
    (sky(("OVC", 500)), colors_lib.ORANGE),
    (sky(("BKN", 999)), colors_lib.ORANGE),
    (sky(("BKN", 1000)), colors_lib.YELLOW),
    (sky(("OVC", 3000)), colors_lib.YELLOW),  # 3,000 ft is still MVFR
    (sky(("BKN", 3100)), colors_lib.WHITE),
    (sky(("FEW", 800), ("SCT", 1500), ("BKN", 2500), ("OVC", 400)), colors_lib.YELLOW),  # the lowest BKN/OVC
])
def test_ceiling_bands(settings, layers, name):
    assert ceiling.look(metar(skyConditions=layers), settings) == Look.solid(C[name])


@pytest.mark.parametrize("layers", [sky(("CLR", 0)), sky(("SKC", 0)), sky(("FEW", 800), ("SCT", 2000))])
def test_no_ceiling_is_dim_white(settings, layers):
    assert ceiling.look(metar(skyConditions=layers), settings) == Look.solid(style.dim(C[colors_lib.WHITE]))


def test_an_obscured_sky_is_a_ceiling_at_the_vertical_visibility(settings):
    assert ceiling.look(metar(skyConditions=sky(("OVX", 0)), vertVisFt=200), settings) == Look.solid(
        C[colors_lib.RED])
    assert ceiling.look(metar(skyConditions=sky(("OVX", 0)), vertVisFt=None), settings) == Look.solid(
        C[colors_lib.RED])  # obscured, height unknown: as low as it gets


def test_ceiling_missing_and_no_report(settings):
    assert ceiling.look(metar(), settings) == style.missing()  # no sky condition in the report
    assert ceiling.look(metar(skyConditions=[]), settings) == style.missing()
    assert ceiling.look({}, settings) == OFF


# ---- dewpoint spread ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("temp, dewpoint, name", [
    (10, 10, colors_lib.RED), (10, 9, colors_lib.RED), (10, 8, colors_lib.ORANGE), (10, 7, colors_lib.YELLOW),
    (10, 6, colors_lib.YELLOW), (10, 5, colors_lib.WHITE), (-3, -4, colors_lib.RED), (30, 5, colors_lib.WHITE),
])
def test_spread_bands(settings, temp, dewpoint, name):
    assert spread.look(metar(tempC=temp, dewpointC=dewpoint), settings) == Look.solid(C[name])


def test_spread_missing_and_no_report(settings):
    assert spread.look(metar(dewpointC=None), settings) == style.missing()
    assert spread.look(metar(tempC=None), settings) == style.missing()
    assert spread.look({}, settings) == OFF


# ---- wind direction -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("direction, name", [
    ("360", colors_lib.RED), ("10", colors_lib.RED), ("22", colors_lib.RED), ("338", colors_lib.RED),
    ("23", colors_lib.ORANGE), ("67", colors_lib.ORANGE), ("68", colors_lib.YELLOW), ("90", colors_lib.YELLOW),
    ("135", colors_lib.GREEN), ("180", colors_lib.CYAN), ("225", colors_lib.BLUE), ("270", colors_lib.PURPLE),
    ("315", colors_lib.MAGENTA), ("337", colors_lib.MAGENTA),
])
def test_wind_direction_sectors(settings, direction, name):
    assert wind_direction.look(metar(windDir=direction, windSpeed=8), settings) == Look.solid(C[name])


def test_wind_direction_calm_variable_and_missing(settings):
    calm = Look.solid(C[colors_lib.GRAY])
    assert wind_direction.look(metar(windDir="0", windSpeed=0), settings) == calm
    assert wind_direction.look(metar(windDir="270", windSpeed=0), settings) == calm
    assert wind_direction.look(metar(windDir="0", windSpeed=None), settings) == calm
    assert wind_direction.look(metar(windDir="VRB", windSpeed=3), settings) == \
        Look.pulse(C[colors_lib.WHITE], period=style.LIGHT_PERIOD, low=style.LIGHT_LOW)
    assert wind_direction.look(metar(windDir="", windSpeed=None), settings) == style.missing()
    assert wind_direction.look(metar(windDir="", windSpeed=5), settings) == style.missing()
    assert wind_direction.look({}, settings) == OFF


def test_wind_direction_legend(settings):
    labels = [item["label"] for item in wind_direction.legend(settings)]
    assert labels[:3] == ["From the north (338-22°)", "From the northeast (23-67°)", "From the east (68-112°)"]
    assert labels[7] == "From the northwest (293-337°)"
    assert {"Calm", "Variable"} <= set(labels)


def test_wind_direction_flickers_with_lightning(settings):
    storm = metar(windDir="180", windSpeed=10, lightning=True)
    assert visualizer.look(wind_direction, storm, settings) == style.with_lightning(Look.solid(C[colors_lib.CYAN]),
                                                                                 settings)


def test_the_patterns_are_last():
    """Rainbow and Chase (one look for the whole strip) always come after the weather visualizers."""
    assert [v.NAME for v in ALL] == ["Flight Category", "Wind", "Wind Gusts", "Wind Direction", "Pressure",
                                     "Precipitation", "Temperature", "Visibility", "Density Altitude", "Ceiling",
                                     "Dewpoint Spread", "Rainbow", "Chase"]
    patterns = [visualizer.strip_look(v, Settings()) is not None for v in ALL]
    assert patterns == sorted(patterns), "a whole-strip visualizer comes before a weather one"
