"""
Flight Category: colors each airport by its flight category.

When a station doesn't report a category but does report its visibility or sky condition, the category is estimated
from what it reports, with the FAA limits (the worse of the ceiling and the visibility decides). By default an
estimate breathes slowly instead of shining steadily, so it can't be mistaken for a reported category. With only one
of the two reported, the real category could be worse than the estimate, never better.
"""

from typing import Optional

import metarmap.lib.colors as colors_lib
from metarmap.decode import estimate_category
from metarmap.models import FlightCategory as Category, Look, Report
from metarmap.visualizers import style
from metarmap.visualizers.visualizer import Visualizer, legend_item


ESTIMATE_PERIOD = 4.0  # seconds per breath of an estimated category

COLORS = {
    Category.VFR: colors_lib.color(colors_lib.GREEN),
    Category.MVFR: colors_lib.color(colors_lib.BLUE),
    Category.IFR: colors_lib.color(colors_lib.RED),
    Category.LIFR: colors_lib.color(colors_lib.DARK_MAGENTA),  # purple
}
OFF = colors_lib.color(colors_lib.OFF)


def legend(settings):
    breathing = settings.visualizer.estimated_category_breathing
    items = [
        legend_item("VFR", "Green", COLORS[Category.VFR]),
        legend_item("MVFR", "Blue", COLORS[Category.MVFR]),
        legend_item("IFR", "Red", COLORS[Category.IFR]),
        legend_item("LIFR", "Purple", COLORS[Category.LIFR]),
        legend_item(
            "Estimated",
            f"{'Slow breathing' if breathing else 'Solid'} in the category's color: the station didn't report a "
            "category, so it's estimated from the visibility and ceiling it does report",
            COLORS[Category.VFR],
            effect="pulse" if breathing else "solid",
            period=ESTIMATE_PERIOD if breathing else None,
            low=style.LIGHT_LOW if breathing else None,
        ),
        style.missing_legend("flight category, visibility or sky condition"),
    ]
    items.append(style.no_report_legend())
    return items


def look(metar: Optional[Report], settings) -> Look:
    if not metar:
        return style.no_report()
    category = metar.flight_category
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


VISUALIZER = Visualizer(
    id="flight_category",
    name="Flight Category",
    description="Display the flight category (VFR, MVFR, IFR, LIFR). A station that doesn't report one gets an "
    "estimate from its visibility and ceiling, shown breathing (or solid, if that's turned off in Config).",
    legend=legend,
    look=look,
)
