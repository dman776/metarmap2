"""
TFR: colors each airport by the TFR (temporary flight restriction) it's in or near (metarmap.tfr), in its type's color:
solid inside one, dim within tfr.nearby_nm of one, breathing for one that starts within 24 hours. In or near none,
it's dim white.
"""

from typing import Optional

import metarmap.lib.colors as colors_lib
from metarmap.models import Look, Report
from metarmap.visualizers import style
from metarmap.visualizers.visualizer import Visualizer, legend_item


# type -> (color, legend label); in the order of metarmap.tfr.TYPES
COLORS = {
    "VIP": (colors_lib.RED, "VIP: presidential and other VIP movements"),
    "HAZARDS": (colors_lib.ORANGE, "Hazards: wildfires, disasters, rocket launches"),
    "SECURITY": (colors_lib.MAGENTA, "Security"),
    "SPECIAL": (colors_lib.BLUE, "Special"),
    "AIR SHOWS/SPORTS": (colors_lib.YELLOW, "Air shows and sports events"),
    "UAS PUBLIC GATHERING": (colors_lib.CYAN, "Drone (UAS) restrictions over public gatherings"),
}
DETAILS = {
    colors_lib.RED: "Red",
    colors_lib.ORANGE: "Orange",
    colors_lib.MAGENTA: "Magenta",
    colors_lib.BLUE: "Blue",
    colors_lib.YELLOW: "Yellow",
    colors_lib.CYAN: "Cyan",
}
NONE = colors_lib.GRAY
# legend entries' keys, beside each type's (its label): their labels change with tfr.nearby_nm
NEARBY, UPCOMING, NO_TFR = "nearby", "upcoming", "no_tfr"


def color(tfr_type):
    return style.named(COLORS[tfr_type][0])


def css(tfr_type):
    """The type's color for the Map page's outlines."""
    return colors_lib.to_css(color(tfr_type))


def nearby_nm(settings):
    return getattr(getattr(settings, "tfr", None), "nearby_nm", 0) or 0


def legend(settings):
    reach = nearby_nm(settings)
    red = color("VIP")
    nearby = (
        [legend_item(f"Within {reach:g} NM of a TFR", "Dim, in its type's color", style.dim(red), key=NEARBY)]
        if reach
        else []
    )
    return [
        *[legend_item(label, DETAILS[name], style.named(name)) for name, label in COLORS.values()],
        *nearby,
        legend_item(
            "A TFR starting within 24 hours",
            "Breathing, in its type's color",
            red,
            effect="pulse",
            period=style.LIGHT_PERIOD,
            low=style.LIGHT_LOW,
            key=UPCOMING,
        ),
        legend_item(f"No TFR within {reach:g} NM" if reach else "No TFR", "Dim white", style.named(NONE), key=NO_TFR),
        style.missing_legend("", label="No TFR list yet, or the airport's position isn't known"),
        style.no_report_legend(),
    ]


def look(metar: Optional[Report], settings) -> Look:
    if not metar:
        return style.no_report()
    tfrs = metar.tfrs
    if tfrs is None:
        return style.missing()
    if not tfrs:
        return Look.solid(style.named(NONE)).tagged(NO_TFR)
    first = tfrs[0]  # the most important: in effect before upcoming, inside before nearby, then by type
    c = color(first["type"])
    kind = COLORS[first["type"]][1]  # its type's legend entry
    if first["upcoming"]:
        return Look.pulse(c, period=style.LIGHT_PERIOD, low=style.LIGHT_LOW).tagged(kind, UPCOMING)
    if first["inside"]:
        return Look.solid(c).tagged(kind)
    return Look.solid(style.dim(c)).tagged(kind, NEARBY)


VISUALIZER = Visualizer(
    id="tfr",
    name="TFR",
    description="Display the TFR each airport is in or near: VIP red, hazards orange, security magenta, special blue, "
    "air shows and sports yellow, drone gatherings cyan. Solid inside, dim nearby, breathing when it "
    "starts within 24 hours; none is dim white.",
    short_name="TFR",
    icon="ban",
    legend=legend,
    look=look,
    areas="tfrs",  # the Map page draws the TFRs (/api/tfrs)
)
