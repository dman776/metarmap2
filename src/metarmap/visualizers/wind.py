"""
Module to handle visualizing Wind data
"""
import metarmap.lib.colors as colors_lib
import metarmap.lib.utils as utils
from metarmap.models import Look, Metar
from metarmap.visualizers.visualizer import Visualizer, legend_item

# (upper bound in kts, color at the lower bound, color at the upper bound); colors blend in between
WIND_SCALE = [
    (5, colors_lib.OFF, colors_lib.PURPLE),
    (10, colors_lib.PURPLE, colors_lib.BLUE),
    (15, colors_lib.BLUE, colors_lib.GREEN),
    (20, colors_lib.GREEN, colors_lib.YELLOW),
    (25, colors_lib.YELLOW, colors_lib.ORANGE),
    (30, colors_lib.ORANGE, colors_lib.RED),
]


def get_color_by_wind(wind: float) -> list:
    """
    Given a wind (in kts), return the color
    that should represent that wind on the map.
    Args:
        wind (float): A wind speed in kts.
    Returns:
        list: The color to show on the map.
    """
    colors_by_name = colors_lib.get_colors()
    if wind is None:
        return colors_by_name[colors_lib.OFF]
    if wind == 0:
        return colors_by_name[colors_lib.DARK_GRAY]
    low = 0
    for high, low_color, high_color in WIND_SCALE:
        if wind < high:
            return colors_lib.get_color_mix(colors_by_name[low_color], colors_by_name[high_color],
                                            utils.get_proportion_between_floats(low, wind, high))
        low = high
    return colors_by_name[colors_lib.RED]


class Wind(Visualizer):
    """
    Colors each airport by its wind speed.
    """
    name = "Wind"
    description = "Display the current wind speed."

    @property
    def legend(self):
        c = colors_lib.get_colors()
        scale = [("0", colors_lib.OFF, "off"), ("5", colors_lib.PURPLE, "purple"), ("10", colors_lib.BLUE, "blue"),
                 ("15", colors_lib.GREEN, "green"), ("20", colors_lib.YELLOW, "yellow"),
                 ("25", colors_lib.ORANGE, "orange"), ("30", colors_lib.RED, "red")]
        items = [legend_item("Calm", "Off")]
        for (lo, lo_color, lo_name), (hi, hi_color, hi_name) in zip(scale, scale[1:]):
            items.append(legend_item(f"{lo}-{hi} kts", f"{lo_name.capitalize()} to {hi_name}",
                                     c[lo_color], c[hi_color]))
        items.append(legend_item("Above 30 kts", "Red", c[colors_lib.RED]))
        return items

    def look(self, metar: Metar) -> Look:
        if not metar:
            return Look.off()
        return Look.solid(get_color_by_wind(metar['windSpeed']))
