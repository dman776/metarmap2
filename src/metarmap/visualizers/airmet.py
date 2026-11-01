"""
AIRMET: colors each airport by the G-AIRMET hazard it's inside (metarmap.airmet): IFR, mountain obscuration,
turbulence, low-level wind shear, strong surface wind or icing, below 18,000 ft. An airport in two at once alternates
between their colors; in none, it's dim white.
"""
import metarmap.lib.colors as colors_lib
from metarmap.models import Look, Metar
from metarmap.visualizers import style
from metarmap.visualizers.visualizer import legend_item

NAME = "AIRMET"
DESCRIPTION = "Display the G-AIRMET hazard over each airport, below 18,000 ft: IFR orange, mountain obscuration " \
              "magenta, turbulence yellow, wind shear red, strong surface wind blue, icing cyan. Two at once " \
              "alternate; none is dim white."
EXCLUSIVE = False
AREAS = True  # the Map page draws the G-AIRMET areas

MIXED_PERIOD = 2.0  # seconds per alternation of two hazards

# hazard -> (color, legend label); high and low turbulence look the same
COLORS = {
    "IFR": (colors_lib.ORANGE, "IFR: ceiling below 1,000 ft or visibility below 3 mi", "Orange"),
    "MT_OBSC": (colors_lib.MAGENTA, "Mountain obscuration", "Magenta"),
    "TURB-LO": (colors_lib.YELLOW, "Turbulence (moderate)", "Yellow"),
    "TURB-HI": (colors_lib.YELLOW, "Turbulence (moderate)", "Yellow"),
    "LLWS": (colors_lib.RED, "Low-level wind shear", "Red"),
    "SFC_WND": (colors_lib.BLUE, "Strong surface wind: sustained 30 kt or more", "Blue"),
    "ICE": (colors_lib.CYAN, "Icing (moderate)", "Cyan"),
}
NONE = colors_lib.GRAY


def color(hazard):
    return style.named(COLORS[hazard][0])


def css(hazard):
    """The hazard's color for the Map page's areas."""
    return colors_lib.to_css(color(hazard))


def colors_for(hazards):
    """The colors of an airport's hazards (most important first), without repeats (both turbulences are yellow)."""
    found = []
    for hazard in hazards:
        c = color(hazard)
        if hazard in COLORS and c not in found:
            found.append(c)
    return found


def legend(settings):
    shown, items = set(), []
    for hazard, (name, label, detail) in COLORS.items():
        if label not in shown:
            shown.add(label)
            items.append(legend_item(label, detail, style.named(name)))
    return [
        *items,
        legend_item("Two hazards at once (e.g. IFR and icing)", "Alternating their colors", color("IFR"), color("ICE"),
                    effect="alternate", period=MIXED_PERIOD),
        legend_item("No G-AIRMET below 18,000 ft", "Dim white", style.named(NONE)),
        style.missing_legend("G-AIRMETs yet (or the airport's position)"),
        style.no_report_legend(),
    ]


def look(metar: Metar, settings) -> Look:
    if not metar:
        return style.no_report()
    hazards = metar.get("airmets")
    if hazards is None:
        return style.missing()
    colors = colors_for(hazards)
    if not colors:
        return Look.solid(style.named(NONE))
    if len(colors) == 1:
        return Look.solid(colors[0])
    return Look.blink(colors[0], period=MIXED_PERIOD, background=colors[1])
