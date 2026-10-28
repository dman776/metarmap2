"""
Flight Category: colors each airport by its flight category.

When a station doesn't report a category but does report its visibility or sky condition, the category is estimated
from what it reports, with the FAA limits (the worse of the ceiling and the visibility decides), and the LED breathes
slowly instead of shining steadily, so an estimate can't be mistaken for a reported category. With only one of the
two reported, the real category could be worse than the estimate, never better.
"""
from metarmap.decode import estimate_category
from metarmap.models import FlightCategory as Category, Look, Metar
from metarmap.visualizers import style
from metarmap.visualizers.visualizer import legend_item

NAME = "Flight Category"
DESCRIPTION = "Display the flight category (VFR, MVFR, IFR, LIFR). A station that doesn't report one gets an " \
              "estimate from its visibility and ceiling, shown breathing."
EXCLUSIVE = False

ESTIMATE_PERIOD = 4.0  # seconds per breath of an estimated category


def legend(settings):
    cat = settings.color.cat
    items = [
        legend_item("VFR", "Green", cat.vfr),
        legend_item("MVFR", "Blue", cat.mvfr),
        legend_item("IFR", "Red", cat.ifr),
        legend_item("LIFR", "Purple", cat.lifr),
        legend_item("Estimated", "Slow breathing in the category's color: the station didn't report a category, so "
                    "it's estimated from the visibility and ceiling it does report", cat.vfr, effect="pulse",
                    period=ESTIMATE_PERIOD, low=style.LIGHT_LOW),
        style.missing_legend("flight category, visibility or sky condition"),
    ]
    items.append(style.no_report_legend())
    return items


def look(metar: Metar, settings) -> Look:
    if not metar:
        return style.no_report()
    category = metar.get('flightCategory')
    estimated = category is None
    if estimated:
        category = estimate_category(metar)
    color = color_for(category, settings)
    if category is None:  # other data is reported, but nothing to tell the flight category from
        return style.missing()
    if estimated:
        return Look.pulse(color, period=ESTIMATE_PERIOD, low=style.LIGHT_LOW)
    return Look.solid(color)


def color_for(category, settings):
    cat = settings.color.cat
    color_map = {
        Category.VFR: cat.vfr,
        Category.MVFR: cat.mvfr,
        Category.IFR: cat.ifr,
        Category.LIFR: cat.lifr,
    }
    return color_map.get(category, settings.color.clear)
