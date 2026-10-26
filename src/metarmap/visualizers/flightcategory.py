"""
Flight Category: colors each airport by its flight category.

When a station doesn't report a category but does report its visibility or sky condition, the category is estimated
from what it reports, with the FAA limits (the worse of the ceiling and the visibility decides), and the LED breathes
slowly instead of shining steadily, so an estimate can't be mistaken for a reported category. With only one of the
two reported, the real category could be worse than the estimate, never better.
"""
from metarmap.decode import ceiling_ft
from metarmap.models import FlightCategory as Category, Look, Metar
from metarmap.visualizers import style
from metarmap.visualizers.visualizer import legend_item

NAME = "Flight Category"
DESCRIPTION = "Display the flight category (VFR, MVFR, IFR, LIFR). A station that doesn't report one gets an " \
              "estimate from its visibility and ceiling, shown breathing."
EXCLUSIVE = False

LIGHTNING_STEP = 0.1  # seconds per frame of the lightning pattern
ESTIMATE_PERIOD = 4.0  # seconds per breath of an estimated category

ORDER = (Category.VFR, Category.MVFR, Category.IFR, Category.LIFR)  # best to worst


def lightning_pattern(cat, color):
    """15 frames of the category color, then one lightning flash."""
    return [cat] * 15 + [color]


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
    if settings.lightning.animation:
        items.append(legend_item("Lightning", "Yellow flashes over the flight category color",
                                 cat.vfr, settings.color.weather.lightning, effect="flash"))
    items.append(style.no_report_legend())
    return items


def look(metar: Metar, settings) -> Look:
    if not metar:
        return style.no_report()
    category = metar.get('flightCategory')
    estimated = category is None
    if estimated:
        category = estimate(metar)
    color = color_for(category, settings)
    if settings.lightning.animation and metar.get('lightning', False):
        return Look.cycle(lightning_pattern(color, settings.color.weather.lightning), step=LIGHTNING_STEP)
    if category is None:  # other data is reported, but nothing to tell the flight category from
        return style.missing()
    if estimated:
        return Look.pulse(color, period=ESTIMATE_PERIOD, low=style.LIGHT_LOW)
    return Look.solid(color)


def estimate(metar: Metar):
    """
    The flight category from the visibility and ceiling the report has, or None if it has neither. The worse of the
    two decides; a sky with no broken or overcast layer (or a clear one) has no ceiling.
    """
    found = []
    miles = metar.get('visibilitySM')
    if miles is not None:
        found.append(Category.LIFR if miles < 1 else Category.IFR if miles < 3 else
                     Category.MVFR if miles <= 5 else Category.VFR)
    if metar.get('skyConditions'):
        feet = ceiling_ft(metar['skyConditions'], metar.get('vertVisFt'))
        found.append(Category.VFR if feet is None or feet > 3000 else Category.MVFR if feet >= 1000 else
                     Category.IFR if feet >= 500 else Category.LIFR)
    return max(found, key=ORDER.index) if found else None


def color_for(category, settings):
    cat = settings.color.cat
    color_map = {
        Category.VFR: cat.vfr,
        Category.MVFR: cat.mvfr,
        Category.IFR: cat.ifr,
        Category.LIFR: cat.lifr,
    }
    return color_map.get(category, settings.color.clear)
