"""
Temperature: colors each airport by its temperature.
"""
import metarmap.lib.colors as colors_lib
import metarmap.lib.utils as utils
from metarmap.models import Look, Metar
from metarmap.visualizers.visualizer import legend_item

NAME = "Temperature"
DESCRIPTION = "Display the temperature in degrees Fahrenheit."
EXCLUSIVE = False

# (upper bound in °F, color at the lower bound, color at the upper bound); colors blend in between
TEMPERATURE_SCALE = [
    (40, colors_lib.WHITE, colors_lib.PURPLE),
    (60, colors_lib.PURPLE, colors_lib.BLUE),
    (70, colors_lib.BLUE, colors_lib.GREEN),
    (80, colors_lib.GREEN, colors_lib.YELLOW),
    (90, colors_lib.YELLOW, colors_lib.ORANGE),
    (100, colors_lib.ORANGE, colors_lib.RED),
]


def get_color_by_temperature_celsius(temperature_celsius: int) -> list:
    """
    Given a temperature (in Celsius), return the color
    that should represent that temp on the map.

    These colors were decided based on weather temperature maps
    and thermometer markings.
    Args:
        temperature_celsius (int): A temperature in C.
    Returns:
        list: The color to show on the map.
    """
    colors_by_name = colors_lib.get_colors()
    if temperature_celsius is None:
        return colors_by_name[colors_lib.OFF]
    temperature_fahrenheit = utils.celsius_to_fahrenheit(temperature_celsius)
    if temperature_fahrenheit < 0:
        return colors_by_name[colors_lib.WHITE]
    low = 0
    for high, low_color, high_color in TEMPERATURE_SCALE:
        if temperature_fahrenheit < high:
            return colors_lib.get_color_mix(colors_by_name[low_color], colors_by_name[high_color],
                                            utils.get_proportion_between_floats(low, temperature_fahrenheit, high))
        low = high
    return colors_by_name[colors_lib.RED]


def legend(settings):
    c = colors_lib.get_colors()
    scale = [("0°", colors_lib.WHITE, "white"), ("40°", colors_lib.PURPLE, "purple"),
             ("60°", colors_lib.BLUE, "blue"), ("70°", colors_lib.GREEN, "green"),
             ("80°", colors_lib.YELLOW, "yellow"), ("90°", colors_lib.ORANGE, "orange"),
             ("100°", colors_lib.RED, "red")]
    items = [legend_item("Below 0°", "White", c[colors_lib.WHITE])]
    for (lo, lo_color, lo_name), (hi, hi_color, hi_name) in zip(scale, scale[1:]):
        items.append(legend_item(f"{lo} to {hi}", f"{lo_name.capitalize()} to {hi_name}", c[lo_color], c[hi_color]))
    items.append(legend_item("Above 100°", "Red", c[colors_lib.RED]))
    return items


def look(metar: Metar, settings) -> Look:
    if not metar or not isinstance(metar.get('tempC'), int):  # no temperature reported
        return Look.off()
    return Look.solid(get_color_by_temperature_celsius(metar['tempC']))
