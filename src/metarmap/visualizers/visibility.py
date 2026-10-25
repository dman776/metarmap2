"""
Visibility: lights each airport white, brighter for better visibility.
"""
import metarmap.lib.colors as colors_lib
from metarmap.models import Look, Metar
from metarmap.visualizers.visualizer import legend_item

NAME = "Visibility"
DESCRIPTION = ("Display the visibility level (ie. 10SM, 6SM, 1/2SM, etc.). "
               "The brighter the LED, the better the visibility.")
EXCLUSIVE = False

# whole statute miles -> brightness of white; less visibility is dimmer
VISIBILITY_WHITE = {9: 80, 8: 40, 7: 20, 6: 10, 5: 5, 4: 4, 3: 3, 2: 2, 1: 1}


def get_color_by_visibility(vis: float) -> list:
    """
    Given a visibility reading, return a color to show on the map.
    Args:
        vis (float): The vis reading from a metar in SM
    Returns:
        list: The color to show on the map for the station.
    """
    colors_by_name = colors_lib.get_colors()
    if vis is None:
        return colors_by_name[colors_lib.RED]
    if vis <= 0:
        return colors_by_name[colors_lib.OFF]
    if vis >= 10:
        return colors_by_name[colors_lib.WHITE]
    level = VISIBILITY_WHITE.get(int(vis), 0)
    return [level, level, level]


def legend(settings):
    c = colors_lib.get_colors()
    return [
        legend_item("9 to 10 miles", "White (30%)", (255, 255, 255)),
        legend_item("5 to 9 miles", "Dim white (5-15%)", (150, 150, 150)),
        legend_item("1 to 5 miles", "Very dim white (1-4%)", (95, 95, 95)),
        legend_item("Less than 1 mile", "Off"),
        legend_item("No visibility reported", "Red", c[colors_lib.RED]),
    ]


def look(metar: Metar, settings) -> Look:
    if not metar:  # no report at all
        return Look.blink(colors_lib.get_colors()[colors_lib.RED], period=2)
    return Look.solid(get_color_by_visibility(metar['vis']))
