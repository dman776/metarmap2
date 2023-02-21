"""
Module to handle visualizing Pressure data
"""

import sys
import time
import datetime
from pprint import pprint
import json

import lib.safe_logging as safe_logging
# from lib.config import Config
import lib.utils as utils
import lib.colors as colors_lib
from metar import METAR
from visualizers.visualizer import Visualizer
from adafruit_led_animation.animation.solid import Solid


HIGH_PRESSURE = 30.2
STANDARD_PRESSURE = 29.92
LOW_PRESSURE = 29.8


def get_color_by_pressure(inches_of_mercury: float) -> list:
    """
    Given a barometer reading, return a RGB color to show on the map.
    Args:
        inches_of_mercury (float): The barometer reading from a metar in inHg.
    Returns:
        list: The RGB color to show on the map for the station.
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
            colors_by_name[colors_lib.LIGHT_BLUE],
            colors_by_name[colors_lib.BLUE],
            utils.get_proportion_between_floats(
                STANDARD_PRESSURE,
                inches_of_mercury,
                HIGH_PRESSURE))

    return colors_lib.get_color_mix(
        colors_by_name[colors_lib.RED],
        colors_by_name[colors_lib.LIGHT_RED],
        utils.get_proportion_between_floats(
            LOW_PRESSURE,
            inches_of_mercury,
            STANDARD_PRESSURE))


class Pressure(Visualizer):
    """
    Object to handle Wind
    Returns a list of Effects on each pixel
    """
    def __init__(self, data, pix, config):
        super().__init__(data, pix, config)

    @property
    def name(self):
        return "Pressure"

    @property
    def description(self):
        return """
            Display the atmospheric pressure.
            <div class="w-100">
            HIGH_PRESSURE = 30.2
STANDARD_PRESSURE = 29.92
LOW_PRESSURE = 29.8
            <ul>
                <li>Less than 29.80=<font color='red'>RED</font></li>
                <li>Greater than 30.20=<font color='blue'>BLUE</font></li>
                <li>Between 29.92 and 30.20 varies between <font color='LightSkyBlue'>LIGHT BLUE</font> and <font color='blue'>BLUE</font></li>
                <li>Between 29.80 and 29.92 varies between <font color='red'>RED</font> and <font color='LightCoral'>LIGHT RED</font></li>
            </ul>
            </div>
            <div class="w-100">
            Lighting will be indicated by flashing <font color='gold'>YELLOW</font>.
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
                    pcolor = get_color_by_pressure(airport_data['altimHg'])
                    self.__effect__.append(Solid(self.__pix__[i], color=pcolor))
                else:  # airport key not found in metar data
                    self.__effect__.append(Solid(self.__pix__[i], color=[0, 0, 0]))
            else:  # airport data is empty METAR data
                self.__effect__.append(Solid(self.__pix__[i], color=[0, 0, 0]))
            i += 1

