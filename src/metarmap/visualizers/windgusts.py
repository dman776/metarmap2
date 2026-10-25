"""
Wind Gusts: pulses each airport's wind color, faster for stronger gusts.
"""
import metarmap.lib.colors as colors_lib
from metarmap.models import Look, Metar
from metarmap.visualizers.visualizer import legend_item
from metarmap.visualizers.wind import get_color_by_wind

NAME = "Wind Gusts"
DESCRIPTION = "Display the wind gusts by pulsing the wind colors (from the Wind visualizer) at different rates."
EXCLUSIVE = False

# (highest gust in kts, pulse period in seconds); stronger gusts pulse faster
GUST_PULSE = [(10, 10), (15, 8), (20, 6), (25, 4), (30, 1)]
STRONGEST_GUST_PULSE = 0.5


def pulse_period(gust_kts: int) -> float:
    for highest, period in GUST_PULSE:
        if gust_kts <= highest:
            return period
    return STRONGEST_GUST_PULSE


def legend(settings):
    c = colors_lib.get_colors()
    rates = [("0-10 kts", 10), ("11-15 kts", 8), ("16-20 kts", 6), ("21-25 kts", 4), ("26-30 kts", 1),
             ("over 30 kts", 0.5)]
    items = [legend_item(f"Gusts {kts}", f"Wind color, pulsing every {period} s", c[colors_lib.GREEN],
                         effect="pulse", period=period) for kts, period in rates]
    items.append(legend_item("No gusts reported", "No pulse; solid flight category color", c[colors_lib.GREEN]))
    return items


def look(metar: Metar, settings) -> Look:
    if not metar:
        return Look.off()
    color = get_color_by_wind(metar['windSpeed'])
    if metar['windGust'] is True:
        return Look.pulse(color, period=pulse_period(metar['windGustSpeed']))
    return Look.solid(color)
