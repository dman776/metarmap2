"""
Advisories: colors each airport by the advisory it's inside (metarmap.advisories), below 18,000 ft. A G-AIRMET's
hazard is a steady color (IFR, mountain obscuration, turbulence, low-level wind shear, strong surface wind or icing);
an airport in two at once alternates between their colors, and in none it's dim white. A SIGMET (thunderstorms,
severe turbulence or icing...) is more serious and takes over: a fast bright-and-dim blink in its hazard's color.
"""

from typing import Optional

import metarmap.lib.colors as colors_lib
from metarmap.models import Look, Report
from metarmap.visualizers import style
from metarmap.visualizers.visualizer import Visualizer, legend_item


MIXED_PERIOD = 2.0  # seconds per alternation of two AIRMET hazards
SIGMET_PERIOD = style.HEAVY_PERIOD  # a SIGMET blinks like heavy weather: fast, bright and dim, never dark

# G-AIRMET hazard -> (color, legend label, legend detail); high and low turbulence look the same. The label starts
# with the G-AIRMET it's in: Sierra (IFR, mountains), Tango (turbulence, wind) or Zulu (icing)
COLORS = {
    "IFR": (colors_lib.ORANGE, "Sierra: IFR, ceiling below 1,000 ft or visibility below 3 mi", "Orange"),
    "MT_OBSC": (colors_lib.MAGENTA, "Sierra: mountain obscuration", "Magenta"),
    "TURB-LO": (colors_lib.YELLOW, "Tango: turbulence (moderate)", "Yellow"),
    "TURB-HI": (colors_lib.YELLOW, "Tango: turbulence (moderate)", "Yellow"),
    "LLWS": (colors_lib.RED, "Tango: low-level wind shear", "Red"),
    "SFC_WND": (colors_lib.BLUE, "Tango: strong surface wind, sustained 30 kt or more", "Blue"),
    "ICE": (colors_lib.CYAN, "Zulu: icing (moderate)", "Cyan"),
}
# SIGMET hazard -> (color, legend label); the same color family as the AIRMET of the same kind
SIGMET_COLORS = {
    "CONV": (colors_lib.RED, "SIGMET: thunderstorms (convective) or tropical cyclone"),
    "TS": (colors_lib.RED, "SIGMET: thunderstorms (convective) or tropical cyclone"),
    "TC": (colors_lib.RED, "SIGMET: thunderstorms (convective) or tropical cyclone"),
    "ICE": (colors_lib.CYAN, "SIGMET: severe icing"),
    "TURB": (colors_lib.YELLOW, "SIGMET: severe turbulence or mountain wave"),
    "MTW": (colors_lib.YELLOW, "SIGMET: severe turbulence or mountain wave"),
    "VA": (colors_lib.ORANGE, "SIGMET: volcanic ash, dust or sand storm"),
    "DS": (colors_lib.ORANGE, "SIGMET: volcanic ash, dust or sand storm"),
    "SS": (colors_lib.ORANGE, "SIGMET: volcanic ash, dust or sand storm"),
}
COLOR_NAMES = {colors_lib.RED: "Red", colors_lib.CYAN: "Cyan", colors_lib.YELLOW: "Yellow", colors_lib.ORANGE: "Orange"}
NONE = colors_lib.GRAY
MIXED, NO_ADVISORY = "mixed", "no_advisory"  # legend entries' keys; the others' are their labels


def color(hazard, kind="AIRMET"):
    return style.named((SIGMET_COLORS if kind == "SIGMET" else COLORS)[hazard][0])


def css(hazard, kind="AIRMET"):
    """The hazard's color for the Map page's areas."""
    return colors_lib.to_css(color(hazard, kind))


def colors_for(hazards):
    """The colors of an airport's AIRMET hazards (most important first), each once (both turbulences are yellow)."""
    found = []
    for hazard in hazards:
        c = color(hazard)
        if c not in found:
            found.append(c)
    return found


def labels_for(hazards):
    """The legend entries (labels) of an airport's AIRMET hazards, in the order of colors_for()."""
    return list(dict.fromkeys(COLORS[hazard][1] for hazard in hazards))


def sigmet_look(c) -> Look:
    return Look.blink(c, period=SIGMET_PERIOD, background=style.dim(c))


def legend(settings):
    items, shown = [], set()
    for name, label in SIGMET_COLORS.values():
        if label not in shown:
            shown.add(label)
            c = style.named(name)
            items.append(
                legend_item(
                    label,
                    f"{COLOR_NAMES[name]}, fast blink, bright and dim",
                    c,
                    style.dim(c),
                    effect="alternate",
                    period=SIGMET_PERIOD,
                )
            )
    for name, label, detail in COLORS.values():
        if label not in shown:
            shown.add(label)
            items.append(legend_item(label, detail, style.named(name)))
    return [
        *items,
        legend_item(
            "Two G-AIRMETs at once (e.g. IFR and icing)",
            "Alternating their colors",
            color("IFR"),
            color("ICE"),
            effect="alternate",
            period=MIXED_PERIOD,
            key=MIXED,
        ),
        legend_item("No advisory below 18,000 ft", "Dim white", style.named(NONE), key=NO_ADVISORY),
        style.missing_legend("", label="No G-AIRMETs yet, or the airport's position isn't known"),
        style.no_report_legend(),
    ]


def look(metar: Optional[Report], settings) -> Look:
    if not metar:
        return style.no_report()
    sigmets = metar.sigmets or []
    if sigmets:  # the most serious one
        return sigmet_look(color(sigmets[0], "SIGMET")).tagged(SIGMET_COLORS[sigmets[0]][1])
    hazards = metar.airmets
    if hazards is None:
        return style.missing()
    colors, labels = colors_for(hazards), labels_for(hazards)
    if not colors:
        return Look.solid(style.named(NONE)).tagged(NO_ADVISORY)
    if len(colors) == 1:
        return Look.solid(colors[0]).tagged(*labels)
    # the two colors shown alternate; with more hazards, only the first two are on the LED
    shown = dict.fromkeys(COLORS[hazard][1] for hazard in hazards if color(hazard) in colors[:2])
    return Look.blink(colors[0], period=MIXED_PERIOD, background=colors[1]).tagged(MIXED, *shown)


VISUALIZER = Visualizer(
    id="advisories",
    name="Advisories",
    description="Display the advisory over each airport, below 18,000 ft. G-AIRMETs in steady colors: IFR orange, "
    "mountain obscuration magenta, turbulence yellow, wind shear red, strong surface wind blue, icing "
    "cyan; two at once alternate, none is dim white. A SIGMET takes over, blinking in its hazard's color.",
    legend=legend,
    look=look,
    areas="advisories",  # the Map page draws the G-AIRMET and SIGMET areas (/api/advisories)
)
