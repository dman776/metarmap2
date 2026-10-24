"""
Module to handle visualizing Pressure data
"""
import lib.colors as colors_lib
import lib.utils as utils
from metarmap.models import Look, Metar
from visualizers.visualizer import Visualizer, legend_item

HIGH_PRESSURE = 30.2
STANDARD_PRESSURE = 29.92
LOW_PRESSURE = 29.8


def get_color_by_pressure(inches_of_mercury: float) -> list:
    """
    Given a barometer reading, return a color to show on the map.
    Args:
        inches_of_mercury (float): The barometer reading from a metar in inHg.
    Returns:
        list: The color to show on the map for the station.
    """
    colors_by_name = colors_lib.get_colors()
    if inches_of_mercury is None:
        return colors_by_name[colors_lib.OFF]
    if inches_of_mercury < LOW_PRESSURE:
        return colors_by_name[colors_lib.RED]
    if inches_of_mercury > HIGH_PRESSURE:
        return colors_by_name[colors_lib.BLUE]
    if inches_of_mercury > STANDARD_PRESSURE:
        return colors_lib.get_color_mix(
            colors_by_name[colors_lib.LIGHT_BLUE], colors_by_name[colors_lib.BLUE],
            utils.get_proportion_between_floats(STANDARD_PRESSURE, inches_of_mercury, HIGH_PRESSURE))
    return colors_lib.get_color_mix(
        colors_by_name[colors_lib.RED], colors_by_name[colors_lib.LIGHT_RED],
        utils.get_proportion_between_floats(LOW_PRESSURE, inches_of_mercury, STANDARD_PRESSURE))


class Pressure(Visualizer):
    """
    Colors each airport by its altimeter setting.
    """
    name = "Pressure"
    description = "Display the atmospheric pressure (inHg)."

    @property
    def legend(self):
        c = colors_lib.get_colors()
        return [
            legend_item("Below 29.80", "Red", c[colors_lib.RED]),
            legend_item("29.80 to 29.92", "Red to light red", c[colors_lib.RED], c[colors_lib.LIGHT_RED]),
            legend_item("29.92 to 30.20", "Light blue to blue", c[colors_lib.LIGHT_BLUE], c[colors_lib.BLUE]),
            legend_item("Above 30.20", "Blue", c[colors_lib.BLUE]),
        ]

    def look(self, metar: Metar) -> Look:
        if not metar:
            return Look.off()
        return Look.solid(get_color_by_pressure(metar['altimHg']))
