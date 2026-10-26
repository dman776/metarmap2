"""
Precipitation: shows each airport's observed weather. The color says what it is (rain, snow, ice, fog...), the effect
says how much (see style.py): light breathes, moderate is solid, heavy blinks, nearby is dim.

When an airport reports several things, the most significant wins: a thunderstorm, then hazards (squalls, funnel
clouds...), freezing precipitation and ice, snow, rain, drizzle, unknown precipitation, then fog, smoke, haze, mist
and dust. Two kinds in one group (e.g. -RASN) alternate.
"""
import metarmap.lib.colors as colors_lib
import metarmap.lib.safe_logging as safe_logging
from metarmap.decode import parse_weather
from metarmap.models import Look, Metar
from metarmap.visualizers import style
from metarmap.visualizers.visualizer import legend_item

NAME = "Precipitation"
DESCRIPTION = "Display the current observed weather: the color is what it is, the effect is how heavy it is."
EXCLUSIVE = False

MIXED_PERIOD = 2.0  # seconds per alternation of two kinds of precipitation

# kinds of weather, most significant first: (kind, METAR codes, color)
KINDS = [
    ("hazard", {"FC", "SQ", "SS", "DS", "VA", "PO"}, lambda w: w.hazard),
    ("ice", {"PL", "GR", "GS", "IC"}, lambda w: w.ice),
    ("snow", {"SN", "SG"}, lambda w: w.snow),
    ("rain", {"RA"}, lambda w: w.rain),
    ("drizzle", {"DZ"}, lambda w: style.dim(w.rain, 0.5)),
    ("unknown", {"UP"}, lambda w: w.unknown),
    ("fog", {"FG"}, lambda w: w.fog),
    ("smoke", {"FU"}, lambda w: w.smoke),
    ("haze", {"HZ", "DU", "SA", "PY"}, lambda w: w.haze),
    ("mist", {"BR"}, lambda w: w.mist),
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


def look(metar: Metar, settings) -> Look:
    if not metar:
        return style.no_report()
    return look_for_weather(metar.get("obs"), settings)


def look_for_weather(obs, settings) -> Look:
    """How the LED looks for a METAR's weather codes, e.g. "-RA BR"."""
    w = settings.color.weather
    if not obs or obs.strip() == "NSW":
        return Look.off()  # nothing to report ("NSW": no significant weather)
    groups = parse_weather(obs)
    if not groups:
        safe_logging.safe_log(f"[v]unknown weather codes: {obs}")
        return style.missing()

    storm = next((g for g in groups if g.descriptor == "TS"), None)
    ranked = sorted(((kinds, g) for g in groups for kinds in [kinds_in(g)] if kinds), key=lambda kg: RANK[kg[0][0]])

    if storm is not None:
        storm_kinds = kinds_in(storm)
        if storm_kinds:  # e.g. TSRA: the precipitation's color, alternating with the thunderstorm's yellow
            return Look.blink(COLOR[storm_kinds[0]](w), period=style.HEAVY_PERIOD, background=w.lightning)
        if storm.vicinity:  # VCTS
            return style.by_intensity(w.lightning, style.VICINITY)
        return Look.blink(w.lightning, period=style.HEAVY_PERIOD, background=style.dim(w.lightning))

    if not ranked:  # e.g. only a descriptor we don't show, like "SH" on its own
        return Look.off()
    kinds, group = ranked[0]
    if len(kinds) > 1 and RANK[kinds[1]] < RANK["unknown"]:  # two kinds of precipitation at once, e.g. -RASN
        return Look.blink(COLOR[kinds[0]](w), period=MIXED_PERIOD, background=COLOR[kinds[1]](w))
    return style.by_intensity(COLOR[kinds[0]](w), intensity_of(group))


def legend(settings):
    w = settings.color.weather
    rain = w.rain
    return [
        legend_item("Rain", "Blue", rain),
        legend_item("Drizzle", "Dim blue", style.dim(rain, 0.5)),
        legend_item("Snow", "White", w.snow),
        legend_item("Freezing rain or drizzle, ice pellets, hail", "Cyan", w.ice),
        legend_item("Thunderstorm", "Yellow, blinking; with rain, snow... alternating with their color",
                    w.lightning, rain, effect="alternate", period=style.HEAVY_PERIOD),
        legend_item("Squalls, funnel cloud, sand or dust storm, volcanic ash", "Magenta", w.hazard),
        legend_item("Unknown precipitation", "Orange", w.unknown),
        legend_item("Fog", "Gray", w.fog),
        legend_item("Smoke", "Gray", w.smoke),
        legend_item("Haze, dust, sand", "Dark gray", w.haze),
        legend_item("Mist", "Dark blue", w.mist),
        *style.intensity_legend(rain, "rain"),
        legend_item("Two kinds at once (e.g. rain and snow)", "Alternating their colors", rain, w.snow,
                    effect="alternate", period=MIXED_PERIOD),
        legend_item("No weather reported", "Off"),
        legend_item("Weather codes the map doesn't know", "Slow red blink", colors_lib.get_colors()[colors_lib.RED],
                    effect="blink", period=style.MISSING_PERIOD),
    ]
