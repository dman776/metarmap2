"""
Module to handle visualizing Pressure data
"""

import sys
import time
import datetime
from pprint import pprint
import json
from typing import Union
import lib.safe_logging as safe_logging
from config import Config
import lib.utils as utils
import lib.colors as colors_lib
from metar import METAR
from visualizers.visualizer import Visualizer, legend_item
from adafruit_led_animation.animation.solid import Solid

STANDARD_PRESSURE = 29.92


def get_color_by_da(da: float, elevation_f: float) -> list:
    """
    Given a DA reading, return a RGB color to show on the map.
    Args:
        da (float): The DA reading from a metar in feet.
        elevation_f (int): The elevation of the station in feet.
    Returns:
        list: The RGB color to show on the map for the station.
    """
    colors_by_name = colors_lib.get_colors()

    da_factor = round(da / elevation_f)

    if da_factor < -20:
        return colors_by_name[colors_lib.GREEN]

    if -20 <= da_factor < -10:
        proportion = utils.get_proportion_between_floats(-20, da_factor, -10)
        return colors_lib.get_color_mix(
            colors_by_name[colors_lib.GREEN], colors_by_name[colors_lib.BLUE], proportion)

    if -10 <= da_factor < -5:
        proportion = utils.get_proportion_between_floats(-10, da_factor, -5)
        return colors_lib.get_color_mix(
            colors_by_name[colors_lib.BLUE], colors_by_name[colors_lib.LIGHT_BLUE], proportion)

    if -5 <= da_factor < 0:
        proportion = utils.get_proportion_between_floats(-5, da_factor, 0)
        return colors_lib.get_color_mix(
            colors_by_name[colors_lib.LIGHT_BLUE], colors_by_name[colors_lib.DARK_GRAY], proportion)

    if 0 <= da_factor < 40:
        proportion = utils.get_proportion_between_floats(0, da_factor, 40)
        return colors_lib.get_color_mix(
            colors_by_name[colors_lib.DARK_GRAY], colors_by_name[colors_lib.RED], proportion)

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
    da = pa + 118.8 * (oat - isa)
    return da


class DensityAltitude(Visualizer):
    """
    Object to handle DA
    Returns a list of Effects on each pixel
    """
    def __init__(self, data, pix, config):
        super().__init__(data, pix, config)

    @property
    def name(self):
        return "Density Altitude"

    @property
    def description(self):
        return "Display the density altitude (DA) relative to field elevation (FE), aka. the density altitude factor (DAF)."

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

    def update_data(self, data):
        super().update_data(data)

        for i, airport in enumerate(self.__data__):
            if "NULL" in airport:
                self.__effect__.append(Solid(self.__pix__[i], color=[0, 0, 0]))
                continue

            airport_data = self.__data__[airport]

            if not airport_data:
                self.__effect__.append(Solid(self.__pix__[i], color=[0, 0, 0]))
                continue

            if not all([airport_data['altimHg'], airport_data['elevation_m'], airport_data['tempC']]):
                self.__effect__.append(Solid(self.__pix__[i], color=[0, 0, 0]))
                continue

            density_altitude = calculate_density_altitude(
                airport_data['altimHg'],
                airport_data['elevation_m'],
                airport_data['tempC']
            )
            density_altitude_factor = round(density_altitude / meters_to_feet(airport_data['elevation_m']))
            color = get_color_by_da(density_altitude, meters_to_feet(airport_data['elevation_m']))
            self.__effect__.append(Solid(self.__pix__[i], color=color))
