"""
Flight Category: colors each airport by its flight category.

When a station doesn't report a category but does report its visibility or sky condition, the category is estimated
from what it reports, with the FAA limits (the worse of the ceiling and the visibility decides). By default an
estimate breathes slowly instead of shining steadily, so it can't be mistaken for a reported category. With only one
of the two reported, the real category could be worse than the estimate, never better.
"""

from metarmap.decode import estimate_category
from metarmap.models import FlightCategory as Category, Look, Metar
from metarmap.visualizers import style
from metarmap.visualizers.visualizer import legend_item

NAME = "Flight Category"
DESCRIPTION = (
    "Display the flight category (VFR, MVFR, IFR, LIFR). A station that doesn't report one gets an "
    "estimate from its visibility and ceiling; the estimated color can breathe or stay solid."
)
EXCLUSIVE = False

ESTIMATE_PERIOD = 4.0  # seconds per breath of an estimated category

# in the strip's GRB order (see lib/colors.py)
COLORS = {
    Category.VFR: (255, 0, 0),  # green
    Category.MVFR: (0, 0, 255),  # blue
    Category.IFR: (0, 255, 0),  # red
    Category.LIFR: (0, 125, 125),  # purple
}
OFF = (0, 0, 0)


def legend(settings):
    items = [
        legend_item("VFR", "Green", COLORS[Category.VFR]),
        legend_item("MVFR", "Blue", COLORS[Category.MVFR]),
        legend_item("IFR", "Red", COLORS[Category.IFR]),
        legend_item("LIFR", "Purple", COLORS[Category.LIFR]),
        legend_item(
            "Estimated",
            "Slow breathing in the inferred category's color"
            if settings.visualizer.estimated_category_breathing
            else "Solid inferred category color",
            COLORS[Category.VFR],
            effect="pulse" if settings.visualizer.estimated_category_breathing else "solid",
            period=ESTIMATE_PERIOD if settings.visualizer.estimated_category_breathing else None,
            low=style.LIGHT_LOW if settings.visualizer.estimated_category_breathing else None,
        ),
        style.missing_legend("flight category, visibility or sky condition"),
    ]
    items.append(style.no_report_legend())
    return items


def look(metar: Metar, settings) -> Look:
    if not metar:
        return style.no_report()
    category = metar.get("flightCategory")
    estimated = category is None
    if estimated:
        category = estimate_category(metar)
    color = color_for(category)
    if category is None:  # other data is reported, but nothing to tell the flight category from
        return style.missing()
    if estimated and settings.visualizer.estimated_category_breathing:
        return Look.pulse(color, period=ESTIMATE_PERIOD, low=style.LIGHT_LOW)
    return Look.solid(color)


def color_for(category):
    return COLORS.get(category, OFF)
