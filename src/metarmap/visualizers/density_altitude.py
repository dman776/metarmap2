"""
Module to handle visualizing Density Altitude data
"""
from typing import Union

import metarmap.lib.colors as colors_lib
import metarmap.lib.utils as utils
from metarmap.models import Look, Metar
from metarmap.visualizers.visualizer import Visualizer, legend_item

STANDARD_PRESSURE = 29.92

# (upper bound of the density altitude factor, color at the lower bound, color at the upper bound)
DA_FACTOR_SCALE = [
    (-20, -10, colors_lib.GREEN, colors_lib.BLUE),
    (-10, -5, colors_lib.BLUE, colors_lib.LIGHT_BLUE),
    (-5, 0, colors_lib.LIGHT_BLUE, colors_lib.DARK_GRAY),
    (0, 40, colors_lib.DARK_GRAY, colors_lib.RED),
]


def get_color_by_da(da: float, elevation_f: float) -> list:
    """
    Given a DA reading, return a color to show on the map.
    Args:
        da (float): The DA reading from a metar in feet.
        elevation_f (int): The elevation of the station in feet.
    Returns:
        list: The color to show on the map for the station.
    """
    colors_by_name = colors_lib.get_colors()
    da_factor = round(da / elevation_f)
    if da_factor < -20:
        return colors_by_name[colors_lib.GREEN]
    for low, high, low_color, high_color in DA_FACTOR_SCALE:
        if low <= da_factor < high:
            return colors_lib.get_color_mix(colors_by_name[low_color], colors_by_name[high_color],
                                            utils.get_proportion_between_floats(low, da_factor, high))
    return colors_by_name[colors_lib.RED]


def meters_to_feet(m: float) -> float:
    return m * 3.28084


def calculate_density_altitude(pressure: float, field_elevation_m: float, oat: float) -> Union[None, float]:
    """
    Calculates the density altitude given the pressure (in inHg), field elevation (in meters),
    and the outside air temperature (in Celsius).
    Args:
        pressure (float): The pressure reading in inHg.
        field_elevation_m (float): The field elevation in meters.
        oat (float): The outside air temperature in Celsius.
    Returns:
        Union[None, float]: The density altitude in feet or None if any of the input parameters is None.
    """
    if None in [pressure, field_elevation_m, oat]:
        return None
    fef = meters_to_feet(field_elevation_m)
    pa = (STANDARD_PRESSURE - pressure) * 1000 + fef
    isa = 15 - 1.98 * fef / 1000
    return pa + 118.8 * (oat - isa)


class DensityAltitude(Visualizer):
    """
    Colors each airport by its density altitude relative to field elevation.
    """
    name = "Density Altitude"
    description = ("Display the density altitude (DA) relative to field elevation (FE), "
                   "aka. the density altitude factor (DAF).")

    @property
    def legend(self):
        c = colors_lib.get_colors()
        return [
            legend_item("DAF below -20", "Green", c[colors_lib.GREEN]),
            legend_item("DAF -20 to -10", "Green to blue", c[colors_lib.GREEN], c[colors_lib.BLUE]),
            legend_item("DAF -10 to -5", "Blue to light blue", c[colors_lib.BLUE], c[colors_lib.LIGHT_BLUE]),
            legend_item("DAF -5 to 0", "Light blue to gray", c[colors_lib.LIGHT_BLUE], c[colors_lib.GRAY]),
            legend_item("DAF 0 to 40", "Gray to red", c[colors_lib.GRAY], c[colors_lib.RED]),
            legend_item("DAF above 40", "Red", c[colors_lib.RED]),
        ]

    def look(self, metar: Metar) -> Look:
        # needs pressure, a non-zero field elevation, and a temperature (a zero reading counts as missing)
        if not metar or not all([metar.get('altimHg'), metar.get('elevation_m'), metar.get('tempC')]):
            return Look.off()
        density_altitude = calculate_density_altitude(metar['altimHg'], metar['elevation_m'], metar['tempC'])
        return Look.solid(get_color_by_da(density_altitude, meters_to_feet(metar['elevation_m'])))
