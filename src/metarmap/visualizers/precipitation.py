"""
Precipitation: shows each airport's observed weather. The color says what it is (rain, snow, ice, fog...), the effect
says how much (see style.py): light breathes, moderate is solid, heavy blinks, nearby is dim.

When an airport reports several things, the most significant wins: a thunderstorm (its precipitation, else yellow;
lightning flashes over it, as in every visualizer: see style.with_lightning), then hazards (squalls, funnel
clouds...), freezing precipitation and ice, snow, rain, drizzle, unknown precipitation, then fog, smoke, haze, mist
and dust. Two kinds in one group (e.g. -RASN) alternate.
"""

from typing import Optional

import logging
import metarmap.lib.colors as colors_lib
from metarmap.decode import parse_weather
from metarmap.models import Look, Report
from metarmap.visualizers import style
from metarmap.visualizers.visualizer import Visualizer, legend_item

log = logging.getLogger(__name__)


MIXED_PERIOD = 2.0  # seconds per alternation of two kinds of precipitation
# legend entries' keys: each kind's is its name in KINDS ("rain"), and these
THUNDERSTORM, MIXED, NO_WEATHER = "thunderstorm", "mixed", "no_weather"

RAIN = colors_lib.color(colors_lib.BLUE)
SNOW = colors_lib.color(colors_lib.WHITE)
ICE = colors_lib.color(colors_lib.CYAN)
HAZARD = colors_lib.color(colors_lib.MAGENTA)
UNKNOWN = colors_lib.color(colors_lib.ORANGE)
# the obscurations are shades of gray, and mist a very dim blue
FOG = style.dim(colors_lib.color(colors_lib.GRAY), 0.3)
SMOKE = style.dim(colors_lib.color(colors_lib.GRAY), 1.5)  # brighter than gray
HAZE = style.dim(colors_lib.color(colors_lib.GRAY), 0.1)
MIST = style.dim(RAIN, 0.06)

# kinds of weather, most significant first: (kind, METAR codes, color)
KINDS = [
    ("hazard", {"FC", "SQ", "SS", "DS", "VA", "PO"}, HAZARD),
    ("ice", {"PL", "GR", "GS", "IC"}, ICE),
    ("snow", {"SN", "SG"}, SNOW),
    ("rain", {"RA"}, RAIN),
    ("drizzle", {"DZ"}, style.dim(RAIN, 0.5)),
    ("unknown", {"UP"}, UNKNOWN),
    ("fog", {"FG"}, FOG),
    ("smoke", {"FU"}, SMOKE),
    ("haze", {"HZ", "DU", "SA", "PY"}, HAZE),
    ("mist", {"BR"}, MIST),
]
RANK = {kind: n for n, (kind, _, _) in enumerate(KINDS)}
COLOR = {kind: color for kind, _, color in KINDS}
FREEZES = {"RA", "DZ", "UP"}  # with FZ, these are freezing precipitation: ice


def kinds_in(group):
    """The kinds of weather in one group, most significant first."""
    if group.descriptor == "SH" and not group.phenomena:  # showers of an unreported kind (e.g. VCSH): rain
        return ["rain"]
    found = set()
    for code in group.phenomena:
        if group.descriptor == "FZ" and code in FREEZES:
            found.add("ice")
        else:
            found.update(kind for kind, codes, _ in KINDS if code in codes)
    return sorted(found, key=RANK.get)


def intensity_of(group):
    return style.VICINITY if group.vicinity else group.intensity


def look(metar: Optional[Report], settings) -> Look:
    if not metar:
        return style.no_report()
    return look_for_weather(metar.weather, settings)


def look_for_weather(obs, settings) -> Look:
    """How the LED looks for a METAR's weather codes, e.g. "-RA BR"."""
    if not obs or obs.strip() == "NSW":
        return Look.off().tagged(NO_WEATHER)  # nothing to report ("NSW": no significant weather)
    groups = parse_weather(obs)
    if not groups:
        log.info(f"unknown weather codes: {obs}")
        return style.missing()

    storm = next((g for g in groups if g.descriptor == "TS"), None)
    ranked = sorted(((kinds, g) for g in groups for kinds in [kinds_in(g)] if kinds), key=lambda kg: RANK[kg[0][0]])

    if storm is not None:
        storm_kinds = kinds_in(storm)
        if storm_kinds:  # e.g. +TSRA: heavy rain
            return style.by_intensity(COLOR[storm_kinds[0]], intensity_of(storm), THUNDERSTORM, storm_kinds[0])
        # TS: yellow; VCTS: dim yellow
        return style.by_intensity(style.LIGHTNING, intensity_of(storm), THUNDERSTORM)

    if not ranked:  # e.g. only a descriptor we don't show, like "SH" on its own
        return Look.off().tagged(NO_WEATHER)
    kinds, group = ranked[0]
    if len(kinds) > 1 and RANK[kinds[1]] < RANK["unknown"]:  # two kinds of precipitation at once, e.g. -RASN
        return Look.blink(COLOR[kinds[0]], period=MIXED_PERIOD, background=COLOR[kinds[1]]).tagged(
            MIXED, kinds[0], kinds[1]
        )
    return style.by_intensity(COLOR[kinds[0]], intensity_of(group), kinds[0])


def legend(settings):
    return [
        legend_item("Rain", "Blue", RAIN, key="rain"),
        legend_item("Drizzle", "Dim blue", style.dim(RAIN, 0.5), key="drizzle"),
        legend_item("Snow", "White", SNOW, key="snow"),
        legend_item("Freezing rain or drizzle, ice pellets, hail", "Cyan", ICE, key="ice"),
        legend_item(
            "Thunderstorm",
            "With rain, snow...: their color. Without: yellow (dim if nearby)",
            style.LIGHTNING,
            key=THUNDERSTORM,
        ),
        legend_item("Squalls, funnel cloud, sand or dust storm, volcanic ash", "Magenta", HAZARD, key="hazard"),
        legend_item("Unknown precipitation", "Orange", UNKNOWN, key="unknown"),
        legend_item("Fog", "Gray", FOG, key="fog"),
        legend_item("Smoke", "Gray", SMOKE, key="smoke"),
        legend_item("Haze, dust, sand", "Dark gray", HAZE, key="haze"),
        legend_item("Mist", "Dark blue", MIST, key="mist"),
        *style.intensity_legend(RAIN, "rain"),
        legend_item(
            "Two kinds at once (e.g. rain and snow)",
            "Alternating their colors",
            RAIN,
            SNOW,
            effect="alternate",
            period=MIXED_PERIOD,
            key=MIXED,
        ),
        legend_item("No weather reported", "Off", key=NO_WEATHER),
        style.missing_legend("", label="Weather codes the map doesn't know"),
        style.no_report_legend(),
    ]


VISUALIZER = Visualizer(
    id="precipitation",
    name="Precipitation",
    description="Display the current observed weather: the color is what it is, the effect is how heavy it is.",
    short_name="Precip",
    icon="rain",
    legend=legend,
    look=look,
)
