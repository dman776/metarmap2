"""
Color rules for every visualizer: METAR in, Look out. No LEDs involved.
Colors are in the strip's GRB order (see lib/colors.py).
"""

import importlib

import pytest

import metarmap.lib.colors as colors_lib
from metarmap.models import Look, Report, SkyLayer
from metarmap.visualizers.visualizer import Visualizer
from metarmap.settings import LIGHTNING_COLORS, Settings
from metarmap import decode, visualizers
from metarmap.visualizers import (
    advisories,
    ceiling,
    chase,
    density_altitude,
    flightcategory,
    precipitation,
    pressure,
    rainbow,
    spread,
    style,
    temperature,
    tfr,
    visibility,
    visualizer,
    wind,
    wind_direction,
    windgusts,
)
from metarmap.visualizers.density_altitude import calculate_density_altitude

C = colors_lib.get_colors()
OFF = Look.off()
ALL = visualizers.ALL


@pytest.fixture
def settings():
    return Settings()


def metar(**fields):
    """A report: a VFR day with calm wind, unless `fields` say otherwise."""
    base = dict(
        flight_category="VFR",
        wind_dir="100",
        temp_c=20,
        dewpoint_c=10,
        altimeter_inhg=29.92,
        elevation_m=100,
    )
    return Report(**{**base, **fields})


# ---- every visualizer ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("v", ALL)
def test_metadata(v, settings):
    assert v.id and v.name and v.description
    assert (v.look is None) != (v.strip_look is None), "one look per airport, or one for the whole strip"
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
    assert {v.name for v in ALL if v.exclusive} == {"Rainbow", "Chase"}


def test_info(settings):
    assert visualizer.info(wind.VISUALIZER, settings) == {
        "id": "wind",
        "name": "Wind",
        "description": wind.VISUALIZER.description,
        "exclusive": False,
        "legend": visualizer.legend(wind.VISUALIZER, settings),
    }


def off_look(metar, settings):
    return Look.off()


def off_strip(settings):
    return Look.off()


# ---- the contract (Visualizer) ------------------------------------------------------------------------------------


def make_visualizer(**fields):
    return Visualizer(**{"id": "test", "name": "Test", "description": "A test.", "legend": lambda s: [], **fields})


@pytest.mark.parametrize(
    "fields, error",
    [
        ({}, "needs either look or strip_look"),
        ({"look": off_look, "strip_look": off_strip}, "needs either look or strip_look"),
        ({"look": off_look, "covers_virtual": True}, "covers_virtual is for a strip look"),
        ({"look": off_look, "areas": "clouds"}, "areas 'clouds' is not one of advisories, tfrs"),
        ({"look": off_look, "id": "Wind Gusts"}, "lower case letters, digits and _"),
        ({"look": off_look, "id": "2wind"}, "lower case letters, digits and _"),
    ],
)
def test_a_visualizer_that_breaks_the_contract_is_refused(fields, error):
    with pytest.raises(ValueError, match=error):
        make_visualizer(**fields)


def test_exclusive_means_a_strip_look():
    assert not make_visualizer(look=off_look).exclusive
    assert make_visualizer(strip_look=off_strip).exclusive


def test_ids_are_unique_and_index_of_finds_them():
    assert len({v.id for v in ALL}) == len(ALL) == len(visualizers.BY_ID)
    for number, v in enumerate(ALL):
        assert visualizers.index_of(v.id) == visualizers.index_of(number) == visualizers.index_of(str(number)) == number
    for unknown in ("nope", "Wind", len(ALL), str(len(ALL)), -1):
        with pytest.raises(LookupError):
            visualizers.index_of(unknown)


def test_every_module_declares_its_visualizer():
    for v in ALL:
        module = importlib.import_module(v.look.__module__ if v.look else v.strip_look.__module__)
        assert module.VISUALIZER is v


# ---- which legend entries a look shows (Look.legend) -------------------------------------------------------------


def sample_reports():
    """Reports that take every visualizer down each of its paths: values in every band, every kind of weather..."""

    def sky(*layers):
        return tuple(SkyLayer(cover, base) for cover, base in layers)

    reports = [None, Report()]  # no report; a report with nothing in it
    reports += [metar(flight_category=category) for category in ("VFR", "MVFR", "IFR", "LIFR", None)]
    reports += [
        metar(flight_category=None, visibility_sm=10.0, sky_conditions=sky(("CLR", 0))),  # estimated VFR
        metar(flight_category=None, visibility_sm=0.5, sky_conditions=sky(("OVC", 200))),  # estimated LIFR
    ]
    reports += [
        metar(wind_speed=kt, wind_gust_speed=(kt or 0) + gust)
        for kt in (0, 5, 12, 20, 30, None)
        for gust in (0, 8, 15, 25)
    ]
    reports += [
        metar(wind_dir=d, wind_speed=8) for d in ("0", "45", "90", "135", "180", "225", "270", "315", "VRB", "")
    ]
    reports += [
        metar(temp_c=t, dewpoint_c=None if t is None else t - spread)
        for t in (-20, 0, 15, 30, 40, None)
        for spread in (0, 2, 5, 12)
    ]
    reports += [metar(altimeter_inhg=inhg) for inhg in (28.5, 29.5, 29.92, 30.4, 31.0, None, 0)]
    reports += [metar(visibility_sm=miles) for miles in (0.25, 1, 2, 4, 7, 10, None)]
    reports += [metar(elevation_m=m, temp_c=t) for m in (0, 1500, 3000) for t in (0, 30, 45)]
    reports += [
        metar(sky_conditions=sky(*layers), vert_vis_ft=vv)
        for layers in (
            (("OVC", 200),),
            (("BKN", 800),),
            (("BKN", 2000),),
            (("OVC", 5000),),
            (("SCT", 3000),),
            (("OVX", 0),),
            (),
        )
        for vv in (300, None)
    ]
    weather = [
        "",
        "NSW",
        "-RA",
        "RA",
        "+RA",
        "VCSH",
        "-DZ",
        "-SN",
        "SN",
        "+SN",
        "FZRA",
        "PL",
        "+TSRA",
        "TS",
        "VCTS",
        "SQ",
        "UP",
        "FG",
        "FU",
        "HZ",
        "BR",
        "-RASN",
        "ZZZZ",
        "SH",
        "-RA BR",
    ]
    reports += [metar(weather=wx) for wx in weather]
    reports += [metar(weather=wx, lightning=True) for wx in ("", "-RA", "TS")]
    reports += [
        metar(tfrs=[{"type": kind, "inside": inside, "upcoming": upcoming}])
        for kind in tfr.COLORS
        for inside, upcoming in ((True, False), (False, False), (True, True))
    ]
    reports += [metar(tfrs=[]), metar(tfrs=None)]
    reports += [metar(airmets=[hazard]) for hazard in advisories.COLORS]
    reports += [metar(airmets=list(h)) for h in (("IFR", "ICE"), ("IFR", "ICE", "LLWS"), ("TURB-LO", "TURB-HI"), ())]
    reports += [metar(airmets=None), *(metar(airmets=[], sigmets=[s]) for s in advisories.SIGMET_COLORS)]
    return reports


@pytest.mark.parametrize("v", [v for v in ALL if v.look is not None], ids=lambda v: v.id)
@pytest.mark.parametrize("missing_blink, lightning, breathing", [(True, True, True), (False, False, False)])
def test_every_look_names_its_legend_entries(v, missing_blink, lightning, breathing):
    """Every look says which legend entries it shows, and they're all in the visualizer's legend."""
    settings = Settings()
    settings.visualizer.missing_data_blink = missing_blink
    settings.lightning.animation = lightning
    settings.visualizer.estimated_category_breathing = breathing
    keys = [item["key"] for item in visualizer.legend(v, settings)]
    assert len(keys) == len(set(keys)), "each legend entry has its own key"
    for report in sample_reports():
        look = visualizer.look(v, report, settings)
        assert look.legend, f"{v.id}: no legend entry for {report}"
        assert set(look.legend) <= set(keys), f"{v.id}: {look.legend} not all in the legend, for {report}"


@pytest.mark.parametrize(
    "v, fields, keys",
    [
        (flightcategory, {"flight_category": "MVFR"}, ("MVFR",)),
        (flightcategory, {"flight_category": None, "visibility_sm": 4.0}, ("MVFR", "estimated")),
        (flightcategory, {"flight_category": None}, ("missing",)),
        (precipitation, {"weather": "-SN"}, ("snow", "light")),
        (precipitation, {"weather": "+TSRA"}, ("thunderstorm", "rain", "heavy", "lightning")),
        (precipitation, {"weather": "-RASN"}, ("mixed", "snow", "rain")),  # snow outranks rain
        (precipitation, {"weather": "VCTS"}, ("thunderstorm", "vicinity", "lightning")),
        (precipitation, {"weather": "NSW"}, ("no_weather",)),
        (precipitation, {"weather": "ZZZZ"}, ("missing",)),
        (precipitation, {"weather": "-RA", "lightning": True}, ("rain", "light", "lightning")),
        (wind, {"wind_speed": 12}, ("10-14 kt",)),
        (wind_direction, {"wind_dir": "VRB", "wind_speed": 4}, ("Variable",)),
        (wind_direction, {"wind_dir": "270", "wind_speed": 4}, ("West",)),
        (tfr, {"tfrs": [{"type": "VIP", "inside": False, "upcoming": False}]}, (tfr.COLORS["VIP"][1], "nearby")),
        (tfr, {"tfrs": [{"type": "VIP", "inside": True, "upcoming": True}]}, (tfr.COLORS["VIP"][1], "upcoming")),
        (advisories, {"airmets": ["IFR", "ICE"]}, ("mixed", advisories.COLORS["IFR"][1], advisories.COLORS["ICE"][1])),
        (advisories, {"airmets": [], "sigmets": ["CONV"]}, (advisories.SIGMET_COLORS["CONV"][1],)),
    ],
)
def test_a_look_names_what_it_shows(v, fields, keys, settings):
    assert visualizer.look(v.VISUALIZER, metar(**fields), settings).legend == keys


def test_no_report_is_its_entry(settings):
    assert visualizer.look(flightcategory.VISUALIZER, None, settings).legend == ("no_report",)


def test_missing_data_turned_off_is_still_its_entry(settings):
    settings.visualizer.missing_data_blink = False
    look = visualizer.look(wind.VISUALIZER, metar(wind_speed=None), settings)
    assert look.effect == "off" and look.legend == ("missing",)
    (item,) = [i for i in visualizer.legend(wind.VISUALIZER, settings) if i["key"] == "missing"]
    assert item["detail"] == "Off"


def test_in_use_is_in_the_legends_order(settings):
    looks = [
        visualizer.look(flightcategory.VISUALIZER, metar(flight_category=c), settings) for c in ("IFR", "VFR", "IFR")
    ]
    assert visualizer.in_use(flightcategory.VISUALIZER, looks, settings) == ["VFR", "IFR"]
    assert visualizer.in_use(rainbow.VISUALIZER, [], settings) is None  # a whole-strip look: all of it


# ---- flight category ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("category, attr", [("VFR", "vfr"), ("MVFR", "mvfr"), ("IFR", "ifr"), ("LIFR", "lifr")])
def test_flight_category_colors(settings, category, attr):
    look = flightcategory.look(metar(flight_category=category), settings)
    assert look == Look.solid(flightcategory.COLORS[attr.upper()])


def test_flight_category_missing_blinks_red(settings):
    look = flightcategory.look(metar(flight_category=None), settings)
    assert look == Look.blink(C[colors_lib.RED], period=2)


def test_missing_data_blink_off_leaves_the_led_dark(settings):
    settings.visualizer.missing_data_blink = False
    assert visualizer.look(flightcategory.VISUALIZER, metar(flight_category=None), settings) == OFF
    assert visualizer.look(wind.VISUALIZER, metar(wind_speed=None), settings) == OFF
    assert (
        visualizer.look(precipitation.VISUALIZER, metar(weather="ZZ"), settings) == OFF
    )  # weather codes the map doesn't know
    # everything else is unchanged: a category, an estimate
    assert visualizer.look(flightcategory.VISUALIZER, metar(flight_category="IFR"), settings) == Look.solid(
        C[colors_lib.RED]
    )
    assert (
        visualizer.look(flightcategory.VISUALIZER, metar(flight_category=None, visibility_sm=10.0), settings).effect
        == "pulse"
    )


def test_missing_data_blink_on_by_default(settings):
    assert settings.visualizer.missing_data_blink is True
    assert visualizer.look(flightcategory.VISUALIZER, metar(flight_category=None), settings) == style.missing()


def test_lightning_flickers_over_dark_missing_data(settings):
    settings.visualizer.missing_data_blink = False
    frames = visualizer.look(flightcategory.VISUALIZER, metar(flight_category=None, lightning=True), settings).colors
    assert frames[:3] == (style.LIGHTNING,) * 3 and frames[3] == (0, 0, 0)


@pytest.mark.parametrize("v", visualizers.WEATHER)
def test_missing_data_blink_off_in_every_legend(v, settings):
    on = visualizer.legend(v, settings)
    assert any(style.is_missing_legend(i) for i in on)
    settings.visualizer.missing_data_blink = False
    off = visualizer.legend(v, settings)
    assert not any(style.is_missing_legend(i) for i in off)
    assert [i["label"] for i in off] == [i["label"] for i in on]  # the same entries, now "Off"
    changed = [i for i, j in zip(off, on) if i != j]
    assert changed and all(i["detail"] == "Off" and i["effect"] == "off" for i in changed)


def test_flight_category_no_report_is_off(settings):
    assert flightcategory.look(None, settings) == OFF


def estimated(metar_fields, settings):
    """The look of an airport that doesn't report a category."""
    return flightcategory.look(metar(flight_category=None, **metar_fields), settings)


def breathing(color):
    return Look.pulse(color, period=flightcategory.ESTIMATE_PERIOD, low=style.LIGHT_LOW)


@pytest.mark.parametrize(
    "fields, attr",
    [
        # visibility only (an automated station without a ceilometer reading)
        ({"visibility_sm": 10.0}, "vfr"),
        ({"visibility_sm": 6.0}, "vfr"),
        ({"visibility_sm": 5.0}, "mvfr"),
        ({"visibility_sm": 3.0}, "mvfr"),
        ({"visibility_sm": 2.5}, "ifr"),
        ({"visibility_sm": 1.0}, "ifr"),
        ({"visibility_sm": 0.75}, "lifr"),
        # sky condition only
        ({"sky_conditions": [SkyLayer("FEW", 3900)]}, "vfr"),
        ({"sky_conditions": [SkyLayer("CLR", 0)]}, "vfr"),
        ({"sky_conditions": [SkyLayer("BKN", 3100)]}, "vfr"),
        ({"sky_conditions": [SkyLayer("BKN", 3000)]}, "mvfr"),
        ({"sky_conditions": [SkyLayer("OVC", 1000)]}, "mvfr"),
        ({"sky_conditions": [SkyLayer("BKN", 800)]}, "ifr"),
        ({"sky_conditions": [SkyLayer("OVC", 500)]}, "ifr"),
        ({"sky_conditions": [SkyLayer("OVC", 400)]}, "lifr"),
        ({"sky_conditions": [SkyLayer("OVX", 0)], "vert_vis_ft": 200}, "lifr"),
        # both: the worse decides
        ({"visibility_sm": 10.0, "sky_conditions": [SkyLayer("OVC", 400)]}, "lifr"),
        ({"visibility_sm": 2.0, "sky_conditions": [SkyLayer("CLR", 0)]}, "ifr"),
        ({"visibility_sm": 4.0, "sky_conditions": [SkyLayer("BKN", 800)]}, "ifr"),
    ],
)
def test_a_missing_category_is_estimated_and_breathes(settings, fields, attr):
    assert estimated(fields, settings) == breathing(flightcategory.COLORS[attr.upper()])


def test_nothing_to_estimate_from_blinks_red(settings):
    assert estimated({}, settings) == RED_BLINK
    assert estimated({"visibility_sm": None, "sky_conditions": []}, settings) == RED_BLINK


def test_a_reported_category_is_never_estimated(settings):
    """aviationweather.gov's category wins, even if the visibility and ceiling would say otherwise."""
    look = flightcategory.look(metar(flight_category="VFR", visibility_sm=0.5), settings)
    assert look == Look.solid(flightcategory.COLORS["VFR"])


def test_the_legend_explains_estimates(settings):
    item = next(i for i in flightcategory.legend(settings) if i["label"] == "Estimated")
    assert item["effect"] == "pulse" and item["period"] == flightcategory.ESTIMATE_PERIOD


def test_estimating_from_real_reports():
    """Reports like these come in without a category from aviationweather.gov (sampled 2026-10-26)."""
    from metarmap.metar import parse_report

    vis_only = parse_report(
        {"rawOb": "METAR KSOW 261735Z AUTO VRB04KT 10SM 14/04 A3028 RMK AO2", "visib": "10+", "fltCat": None}
    )
    sky_only = parse_report(
        {
            "rawOb": "METAR K18H 261730Z AUTO 09011G18KT FEW039 31/17 A3013 RMK A01",
            "clouds": [{"cover": "FEW", "base": 3900}],
            "fltCat": None,
        }
    )
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
    look = lit(flightcategory.VISUALIZER, settings, flight_category="IFR", lightning=True)
    ifr, yellow = flightcategory.COLORS["IFR"], style.LIGHTNING
    assert look.effect == "cycle" and look.step == style.LIGHTNING_STEP
    assert list(look.colors) == flicker(ifr, yellow) * 2  # every 2 s, for 4 s


@pytest.mark.parametrize("v", visualizers.WEATHER)
def test_every_weather_visualizer_shows_lightning(v, settings):
    look = lit(v, settings, lightning=True)
    yellow = style.LIGHTNING
    assert look.effect == "cycle" and look.colors[:3] == (yellow,) * 3 and look.colors[40:43] == (yellow,) * 3
    assert any(i["label"] == "Lightning or a thunderstorm" for i in visualizer.legend(v, settings))


@pytest.mark.parametrize("v", visualizers.WEATHER)
def test_lightning_animation_off_is_honored_everywhere(v, settings):
    settings.lightning.animation = False
    m = metar(lightning=True, weather="TSRA")
    assert visualizer.look(v, m, settings) == v.look(m, settings)
    assert all(i["label"] != "Lightning or a thunderstorm" for i in visualizer.legend(v, settings))


@pytest.mark.parametrize(
    "fields, has",
    [
        ({"lightning": True}, True),
        ({"weather": "TSRA"}, True),
        ({"weather": "+TSRA BR"}, True),
        ({"weather": "VCTS"}, True),
        ({"weather": "-RA"}, False),
        ({}, False),
    ],
)
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
    yellow = style.LIGHTNING
    frames = lit(precipitation.VISUALIZER, settings, weather="TS").colors
    assert frames[:3] == (yellow,) * 3 and frames[3] == style.dim(yellow)


def test_lightning_color_white(settings):
    settings.lightning.color = "white"
    white = C[colors_lib.WHITE]
    look = lit(flightcategory.VISUALIZER, settings, flight_category="IFR", lightning=True)
    assert list(look.colors) == flicker(flightcategory.COLORS["IFR"], white) * 2
    item = next(
        i for i in visualizer.legend(flightcategory.VISUALIZER, settings) if i["label"] == "Lightning or a thunderstorm"
    )
    assert "white flashes" in item["detail"] and item["colors"][1] == colors_lib.to_css(white)


def test_lightning_color_white_on_white_is_dimmed_between_flashes(settings):
    settings.lightning.color = "white"
    white = C[colors_lib.WHITE]
    frames = lit(precipitation.VISUALIZER, settings, weather="SN", lightning=True).colors  # snow is white
    assert frames[:3] == (white,) * 3 and frames[3] == style.dim(white)


def test_precipitation_thunderstorm_stays_yellow_with_white_lightning(settings):
    """Snow is white in Precipitation, so a thunderstorm keeps its yellow; only the flashes are white."""
    settings.lightning.color = "white"
    assert precipitation.look(metar(weather="TS"), settings) == Look.solid(style.LIGHTNING)
    frames = lit(precipitation.VISUALIZER, settings, weather="TS").colors
    assert frames[:3] == (C[colors_lib.WHITE],) * 3 and frames[3] == style.LIGHTNING


def test_unknown_lightning_color_in_config_json_is_yellow():
    data = Settings().to_dict()
    data["lightning"]["color"] = "purple"  # hand-edited config.json: reset when it loads
    settings = Settings.from_dict(data)
    assert lit(flightcategory.VISUALIZER, settings, flight_category="VFR", lightning=True).colors[0] == style.LIGHTNING
    assert "yellow flashes" in style.lightning_legend(settings)["detail"]


def test_every_lightning_color_has_an_led_color():
    assert set(style.LIGHTNING_COLORS) == set(LIGHTNING_COLORS)


def test_lightning_isnt_added_to_whole_strip_patterns(settings):
    assert not visualizer.shows_lightning(rainbow.VISUALIZER, settings)
    assert all(i["label"] != "Lightning or a thunderstorm" for i in visualizer.legend(rainbow.VISUALIZER, settings))


# ---- the shared conventions (style.py) ---------------------------------------------------------------------

PER_AIRPORT = [v for v in ALL if v.look is not None]
RED_BLINK = Look.blink(C[colors_lib.RED], period=2)


@pytest.mark.parametrize("v", PER_AIRPORT)
def test_no_report_is_off_everywhere(v, settings):
    assert v.look(None, settings) == OFF


@pytest.mark.parametrize(
    "v, field",
    [
        (wind, "wind_speed"),
        (windgusts, "wind_speed"),
        (temperature, "temp_c"),
        (pressure, "altimeter_inhg"),
        (visibility, "visibility_sm"),
        (density_altitude, "temp_c"),
        (flightcategory, "flight_category"),
    ],
)
def test_a_missing_value_is_a_slow_red_blink_everywhere(v, field, settings):
    data = metar(**{field: None})
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


@pytest.mark.parametrize(
    "speed, name",
    [
        (0, colors_lib.GRAY),
        (1, colors_lib.BLUE),
        (9, colors_lib.BLUE),
        (10, colors_lib.YELLOW),
        (14, colors_lib.YELLOW),
        (15, colors_lib.ORANGE),
        (24, colors_lib.ORANGE),
        (25, colors_lib.RED),
        (60, colors_lib.RED),
    ],
)
def test_wind_bands(settings, speed, name):
    assert wind.look(metar(wind_speed=speed), settings) == Look.solid(C[name])


def test_calm_is_not_off(settings):
    """Off means no report; calm is a dim white so the two can't be confused."""
    assert wind.look(metar(wind_speed=0), settings) != OFF


@pytest.mark.parametrize(
    "speed, gust, name",
    [
        (12, 0, colors_lib.GRAY),  # not gusting
        (12, 13, colors_lib.BLUE),
        (12, 21, colors_lib.BLUE),  # 1 and 9 kt above
        (12, 22, colors_lib.YELLOW),
        (12, 26, colors_lib.YELLOW),  # 10 and 14
        (12, 27, colors_lib.ORANGE),
        (12, 31, colors_lib.ORANGE),  # 15 and 19
        (12, 32, colors_lib.RED),
        (5, 45, colors_lib.RED),  # 20 and 40
    ],
)
def test_gust_spread_bands(settings, speed, gust, name):
    data = metar(wind_speed=speed, wind_gust_speed=gust)
    assert windgusts.look(data, settings) == Look.solid(C[name])


def test_gusts_are_about_the_spread_not_the_speed(settings):
    """A strong steady wind isn't gusty, and a light one can be."""
    steady = metar(wind_speed=30, wind_gust_speed=0)
    gusty = metar(wind_speed=6, wind_gust_speed=24)
    assert windgusts.look(steady, settings) == Look.solid(C[colors_lib.GRAY])
    assert windgusts.look(gusty, settings) == Look.solid(C[colors_lib.ORANGE])
    assert wind.look(steady, settings) != wind.look(gusty, settings)


def test_a_gust_that_is_not_above_the_wind_is_no_gust(settings):
    assert windgusts.look(metar(wind_speed=12, wind_gust_speed=12), settings) == Look.solid(C[colors_lib.GRAY])
    assert windgusts.look(metar(wind_speed=12, wind_gust_speed=0), settings) == Look.solid(C[colors_lib.GRAY])


# ---- temperature, pressure, visibility, density altitude ----------------------------------------------------


@pytest.mark.parametrize(
    "celsius, name",
    [
        (-10, colors_lib.WHITE),
        (-1, colors_lib.WHITE),
        (0, colors_lib.PURPLE),
        (12, colors_lib.BLUE),
        (20, colors_lib.LIGHT_BLUE),
        (28, colors_lib.YELLOW),
        (35, colors_lib.ORANGE),
        (40, colors_lib.RED),
    ],
)
def test_temperature_bands(settings, celsius, name):
    """In °F: below 32 (freezing) white, 32-49 purple, 50-64 blue, 65-79 cyan, 80-89 yellow, 90-99 orange."""
    assert temperature.look(metar(temp_c=celsius), settings) == Look.solid(C[name])


@pytest.mark.parametrize(
    "inhg, name",
    [
        (29.5, colors_lib.RED),
        (29.85, colors_lib.LIGHT_RED),
        (29.92, colors_lib.LIGHT_BLUE),
        (30.1, colors_lib.LIGHT_BLUE),
        (30.2, colors_lib.BLUE),
        (30.6, colors_lib.BLUE),
    ],
)
def test_pressure_bands(settings, inhg, name):
    assert pressure.look(metar(altimeter_inhg=inhg), settings) == Look.solid(C[name])


@pytest.mark.parametrize(
    "miles, name",
    [
        (0.25, colors_lib.RED),
        (0.75, colors_lib.RED),
        (1, colors_lib.ORANGE),
        (2.5, colors_lib.ORANGE),
        (3, colors_lib.YELLOW),
        (5, colors_lib.YELLOW),
        (5.5, colors_lib.WHITE),
        (10, colors_lib.WHITE),
    ],
)
def test_visibility_bands(settings, miles, name):
    """At the flight category limits: over 5 miles, 3-5, 1 to under 3, under 1."""
    assert visibility.look(metar(visibility_sm=miles), settings) == Look.solid(C[name])


def test_density_altitude_formula():
    # standard day at sea level: density altitude = field elevation
    assert calculate_density_altitude(29.92, 0, 15) == pytest.approx(0)
    assert calculate_density_altitude(29.92, 1000, 25) > 1000 * 3.28084


@pytest.mark.parametrize(
    "fields, name",
    [
        ({"elevation_m": 0, "temp_c": 15, "altimeter_inhg": 29.92}, colors_lib.LIGHT_BLUE),  # standard day
        # 0°C at a sea-level field is real
        ({"elevation_m": 0, "temp_c": 0, "altimeter_inhg": 29.92}, colors_lib.LIGHT_BLUE),
        ({"elevation_m": 0, "temp_c": 28, "altimeter_inhg": 29.92}, colors_lib.YELLOW),
        ({"elevation_m": 0, "temp_c": 35, "altimeter_inhg": 29.92}, colors_lib.ORANGE),
        ({"elevation_m": 1500, "temp_c": 38, "altimeter_inhg": 29.7}, colors_lib.RED),
    ],
)
def test_density_altitude_bands(settings, fields, name):
    assert density_altitude.look(metar(**fields), settings) == Look.solid(C[name])


@pytest.mark.parametrize("fields", [{"temp_c": None}, {"altimeter_inhg": 0}, {"elevation_m": None}])
def test_density_altitude_needs_all_inputs(settings, fields):
    assert density_altitude.look(metar(**fields), settings) == RED_BLINK


# ---- precipitation ------------------------------------------------------------------------------------------


def W(settings, name):
    return style.LIGHTNING if name == "lightning" else precipitation.COLOR[name]


def P(obs, settings):
    return precipitation.look(metar(weather=obs), settings)


@pytest.mark.parametrize(
    "obs, kind",
    [
        ("RA", "rain"),
        ("SHRA", "rain"),
        ("SN", "snow"),
        ("SG", "snow"),
        ("FZRA", "ice"),
        ("FZDZ", "ice"),
        ("PL", "ice"),
        ("GR", "ice"),
        ("GS", "ice"),
        ("IC", "ice"),
        ("SQ", "hazard"),
        ("FC", "hazard"),
        ("VA", "hazard"),
        ("UP", "unknown"),
        ("FG", "fog"),
        ("FZFG", "fog"),
        ("FU", "smoke"),
        ("HZ", "haze"),
        ("DU", "haze"),
        ("BR", "mist"),
    ],
)
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
    return [SkyLayer(cover, base) for cover, base in layers]


@pytest.mark.parametrize(
    "layers, name",
    [
        (sky(("BKN", 400)), colors_lib.RED),
        (sky(("OVC", 500)), colors_lib.ORANGE),
        (sky(("BKN", 999)), colors_lib.ORANGE),
        (sky(("BKN", 1000)), colors_lib.YELLOW),
        (sky(("OVC", 3000)), colors_lib.YELLOW),  # 3,000 ft is still MVFR
        (sky(("BKN", 3100)), colors_lib.WHITE),
        (sky(("FEW", 800), ("SCT", 1500), ("BKN", 2500), ("OVC", 400)), colors_lib.YELLOW),  # the lowest BKN/OVC
    ],
)
def test_ceiling_bands(settings, layers, name):
    assert ceiling.look(metar(sky_conditions=layers), settings) == Look.solid(C[name])


@pytest.mark.parametrize("layers", [sky(("CLR", 0)), sky(("SKC", 0)), sky(("FEW", 800), ("SCT", 2000))])
def test_no_ceiling_is_dim_white(settings, layers):
    assert ceiling.look(metar(sky_conditions=layers), settings) == Look.solid(style.dim(C[colors_lib.WHITE]))


def test_an_obscured_sky_is_a_ceiling_at_the_vertical_visibility(settings):
    obscured = sky(("OVX", 0))
    assert ceiling.look(metar(sky_conditions=obscured, vert_vis_ft=200), settings) == Look.solid(C[colors_lib.RED])
    assert ceiling.look(metar(sky_conditions=sky(("OVX", 0)), vert_vis_ft=None), settings) == Look.solid(
        C[colors_lib.RED]
    )  # obscured, height unknown: as low as it gets


def test_ceiling_missing_and_no_report(settings):
    assert ceiling.look(metar(), settings) == style.missing()  # no sky condition in the report
    assert ceiling.look(metar(sky_conditions=[]), settings) == style.missing()
    assert ceiling.look(None, settings) == OFF


# ---- dewpoint spread ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "temp, dewpoint, name",
    [
        (10, 10, colors_lib.RED),
        (10, 9, colors_lib.RED),
        (10, 8, colors_lib.ORANGE),
        (10, 7, colors_lib.YELLOW),
        (10, 6, colors_lib.YELLOW),
        (10, 5, colors_lib.WHITE),
        (-3, -4, colors_lib.RED),
        (30, 5, colors_lib.WHITE),
    ],
)
def test_spread_bands(settings, temp, dewpoint, name):
    assert spread.look(metar(temp_c=temp, dewpoint_c=dewpoint), settings) == Look.solid(C[name])


def test_spread_missing_and_no_report(settings):
    assert spread.look(metar(dewpoint_c=None), settings) == style.missing()
    assert spread.look(metar(temp_c=None), settings) == style.missing()
    assert spread.look(None, settings) == OFF


# ---- wind direction -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "direction, name",
    [
        ("360", colors_lib.RED),
        ("10", colors_lib.RED),
        ("22", colors_lib.RED),
        ("338", colors_lib.RED),
        ("23", colors_lib.ORANGE),
        ("67", colors_lib.ORANGE),
        ("68", colors_lib.YELLOW),
        ("90", colors_lib.YELLOW),
        ("135", colors_lib.GREEN),
        ("180", colors_lib.CYAN),
        ("225", colors_lib.BLUE),
        ("270", colors_lib.PURPLE),
        ("315", colors_lib.MAGENTA),
        ("337", colors_lib.MAGENTA),
    ],
)
def test_wind_direction_sectors(settings, direction, name):
    assert wind_direction.look(metar(wind_dir=direction, wind_speed=8), settings) == Look.solid(C[name])


def test_wind_direction_calm_variable_and_missing(settings):
    calm = Look.solid(C[colors_lib.GRAY])
    assert wind_direction.look(metar(wind_dir="0", wind_speed=0), settings) == calm
    assert wind_direction.look(metar(wind_dir="270", wind_speed=0), settings) == calm
    assert wind_direction.look(metar(wind_dir="0", wind_speed=None), settings) == calm
    assert wind_direction.look(metar(wind_dir="VRB", wind_speed=3), settings) == Look.pulse(
        C[colors_lib.WHITE], period=style.LIGHT_PERIOD, low=style.LIGHT_LOW
    )
    assert wind_direction.look(metar(wind_dir="", wind_speed=None), settings) == style.missing()
    assert wind_direction.look(metar(wind_dir="", wind_speed=5), settings) == style.missing()
    assert wind_direction.look(None, settings) == OFF


def test_wind_direction_legend(settings):
    labels = [item["label"] for item in wind_direction.legend(settings)]
    assert labels[:3] == ["From the north (338-22°)", "From the northeast (23-67°)", "From the east (68-112°)"]
    assert labels[7] == "From the northwest (293-337°)"
    assert {"Calm", "Variable"} <= set(labels)


def test_wind_direction_flickers_with_lightning(settings):
    storm = metar(wind_dir="180", wind_speed=10, lightning=True)
    assert visualizer.look(wind_direction.VISUALIZER, storm, settings) == style.with_lightning(
        Look.solid(C[colors_lib.CYAN]), settings
    )


def test_the_patterns_are_last():
    """Rainbow and Chase (one look for the whole strip) come after the weather visualizers, in the web UI."""
    assert [v.name for v in ALL] == [
        "Flight Category",
        "Wind",
        "Wind Gusts",
        "Wind Direction",
        "Pressure",
        "Precipitation",
        "Temperature",
        "Visibility",
        "Density Altitude",
        "Ceiling",
        "Dewpoint Spread",
        "Advisories",
        "TFR",
        "Rainbow",
        "Chase",
    ]
    patterns = [visualizer.strip_look(v, Settings()) is not None for v in ALL]
    assert patterns == sorted(patterns), "a whole-strip visualizer comes before a weather one"
