"""
Flight Category: colors each airport by its flight category.
"""
from metarmap.models import FlightCategory as Category, Look, Metar
from metarmap.visualizers import style
from metarmap.visualizers.visualizer import legend_item

NAME = "Flight Category"
DESCRIPTION = "Display the flight category (ie. VFR, MVFR, IFR, LIFR)."
EXCLUSIVE = False

LIGHTNING_STEP = 0.1  # seconds per frame of the lightning pattern


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
        style.missing_legend("flight category"),
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
    color = color_for(category, settings)
    if settings.lightning.animation and metar.get('lightning', False):
        return Look.cycle(lightning_pattern(color, settings.color.weather.lightning), step=LIGHTNING_STEP)
    if category is None:  # other data is reported, but not the flight category
        return style.missing()
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
