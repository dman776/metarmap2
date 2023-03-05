"""
Module to handle visualizing Pressure data
"""

import sys
import time
import datetime
from pprint import pprint
import json

# import lib.safe_logging as safe_logging
from config import Config
import lib.utils as utils
import lib.colors as colors_lib
from metar import METAR
from visualizers.visualizer import Visualizer
from adafruit_led_animation.animation.solid import Solid

def get_color_by_da(da: int, elevation_f: int) -> list:
    """
    Given a DA reading, return a RGB color to show on the map.
    Args:
        density altitude (int): The DA reading from a metar in feet.
    Returns:
        list: The RGB color to show on the map for the station.
    """

    colors_by_name = colors_lib.get_colors()

    if da is None:
        return colors_by_name[colors_lib.OFF]

    if da == elevation_f:
        return colors_by_name[colors_lib.WHITE]

    if da < elevation_f:
        return colors_lib.get_color_mix(
            colors_by_name[colors_lib.WHITE],
            colors_by_name[colors_lib.BLUE],
            utils.get_proportion_between_floats(
                elevation_f,
                da,
                elevation_f * -50))
    else:
        return colors_lib.get_color_mix(
            colors_by_name[colors_lib.WHITE],
            colors_by_name[colors_lib.RED],
            utils.get_proportion_between_floats(
                elevation_f,
                da,
                elevation_f * 50))


def meters_to_feet(m):
    return m * 3.28084


def calculate_density_altitude(pressure, field_elevation, oat):
    fef = meters_to_feet(field_elevation)
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
        return """
            Display the density altitude relative to field elevation.
            <div class="w-100">
            <ul>
                <li>Less than 29.80=<font color='red'>RED</font></li>
                <li>Between 29.80 and 29.92 varies between <font color='red'>RED</font> and <font color='LightCoral'>LIGHT RED</font></li>
                <li>Between 29.92 and 30.20 varies between <font color='LightSkyBlue'>LIGHT BLUE</font> and <font color='blue'>BLUE</font></li>
                <li>Greater than 30.20=<font color='blue'>BLUE</font></li>
            </ul>
            </div>
        """

    def update_data(self, data):
        super().update_data(data)

        # loop over all stations
        i = 0
        # for airport in list(self.__stations__):
        for airport in list(self.__data__.keys()):
            # Skip NULL entries
            if "NULL" in airport:
                self.__effect__.append(Solid(self.__pix__[i], color=[0, 0, 0]))
                i += 1
                continue
            airport_data = self.__data__.get(airport, None)

            if len(airport_data.keys()) > 0:
                if airport_data is not None:
                    da = calculate_density_altitude(airport_data['altimHg'])
                    pcolor = get_color_by_da(da, meters_to_feet(airport_data['elevation_m'])
                    self.__effect__.append(Solid(self.__pix__[i], color=pcolor))
                else:  # airport key not found in metar data
                    self.__effect__.append(Solid(self.__pix__[i], color=[0, 0, 0]))
            else:  # airport data is empty METAR data
                self.__effect__.append(Solid(self.__pix__[i], color=[0, 0, 0]))
            i += 1


