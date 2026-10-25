"""
Flight Category: colors each airport by its flight category.
"""
import metarmap.lib.colors as colors_lib
from metarmap.models import FlightCategory as Category, Look, Metar
from metarmap.visualizers.visualizer import legend_item

NAME = "Flight Category"
DESCRIPTION = "Display the flight category (ie. VFR, MVFR, IFR, LIFR)."
EXCLUSIVE = False

LIGHTNING_STEP = 0.1  # seconds per frame of the lightning pattern


def lightning_pattern(cat, color):
    """15 frames of the category color, then one lightning flash."""
    return [cat] * 15 + [color]


def legend(settings):
    c = colors_lib.get_colors()
    cat = settings.color.cat
    items = [
        legend_item("VFR", "Green", cat.vfr),
        legend_item("MVFR", "Blue", cat.mvfr),
        legend_item("IFR", "Red", cat.ifr),
        legend_item("LIFR", "Purple", cat.lifr),
        legend_item("Flight category missing", "Blinking red (other METAR data is available)",
                    c[colors_lib.RED], effect="blink", period=2),
    ]
    if settings.lightning.animation:
        items.append(legend_item("Lightning", "Yellow flashes over the flight category color",
                                 cat.vfr, settings.color.weather.lightning, effect="flash"))
    items.append(legend_item("METAR not available", "Off"))
    return items


def look(metar: Metar, settings) -> Look:
    if not metar:
        return Look.off()
    category = metar.get('flightCategory')
    color = color_for(category, settings)
    if settings.lightning.animation and metar.get('lightning', False):
        return Look.cycle(lightning_pattern(color, settings.color.weather.lightning), step=LIGHTNING_STEP)
    if category is None:  # other data is reported, but not the flight category
        return Look.blink(colors_lib.get_colors()[colors_lib.RED], period=2)
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
