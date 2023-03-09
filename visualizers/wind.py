"""
Module to handle visualizing Wind data
"""

import sys
import time
import datetime
from pprint import pprint
import json

import lib.safe_logging as safe_logging
# from lib.config import Config
import lib
import lib.utils as utils
import lib.colors as colors_lib
from metar import METAR
import neopixel
import board
from visualizers.visualizer import Visualizer

from adafruit_led_animation.animation.blink import Blink
from adafruit_led_animation.animation.pulse import Pulse
from adafruit_led_animation.animation.solid import Solid
from adafruit_led_animation.animation.colorcycle import ColorCycle
from adafruit_led_animation.color import PURPLE, WHITE, AMBER, JADE, MAGENTA, ORANGE, BLUE, AQUA, RED, GREEN, YELLOW


def get_color_by_wind(wind: float) -> list:
    """
    Given a wind (in kts), return the color
    that should represent that wind on the map.

    Args:
        wind (float): A wind speed in kts.

    Returns:
        list: The RGB color to show on the map.
    """
    colors_by_name = colors_lib.get_colors()

    if wind is None:
        return colors_by_name[colors_lib.OFF]

    if wind == 0:
        return colors_by_name[colors_lib.DARK_GRAY]
    if wind < 5:
        return colors_lib.get_color_mix(
            colors_by_name[colors_lib.OFF], colors_by_name[colors_lib.PURPLE],
            utils.get_proportion_between_floats(0, wind, 5))

    if wind < 10:
        return colors_lib.get_color_mix(
            colors_by_name[colors_lib.PURPLE], colors_by_name[colors_lib.BLUE],
            utils.get_proportion_between_floats(5, wind, 10))

    if wind < 15:
        return colors_lib.get_color_mix(
            colors_by_name[colors_lib.BLUE], colors_by_name[colors_lib.GREEN],
            utils.get_proportion_between_floats(10, wind, 15))

    if wind < 20:
        return colors_lib.get_color_mix(
            colors_by_name[colors_lib.GREEN], colors_by_name[colors_lib.YELLOW],
            utils.get_proportion_between_floats(15, wind, 20))

    if wind < 25:
        return colors_lib.get_color_mix(
            colors_by_name[colors_lib.YELLOW], colors_by_name[colors_lib.ORANGE],
            utils.get_proportion_between_floats(20, wind, 25))

    if wind < 30:
        return colors_lib.get_color_mix(
            colors_by_name[colors_lib.ORANGE], colors_by_name[colors_lib.RED],
            utils.get_proportion_between_floats(25, wind, 30))

    return colors_by_name[colors_lib.RED]


class Wind(Visualizer):
    """
    Object to handle Wind
    Returns a list of Effects on each pixel
    """

    def __init__(self, data, pix, config):
        super().__init__(data, pix, config)

    @property
    def name(self):
        return "Wind"

    @property
    def description(self):
        return """
            Display the current wind speed.
            <div class="w-100">
            <ul>
                <li>Calm=OFF</li>
                <li>Between 0-5 KTS varies between OFF and <font color='Purple'>PURPLE</font></li>
                <li>Between 5-10 KTS varies between <font color='purple'>PURPLE</font> and <font color='blue'>BLUE</font></li>
                <li>Between 10-15 KTS varies between <font color='blue'>BLUE</font> and <font color='green'>GREEN</font></li>
                <li>Between 15-20 KTS varies between <font color='green'>GREEN</font> and <font color='gold'>YELLOW</font></li>
                <li>Between 20-25 KTS varies between <font color='gold'>YELLOW</font> and <font color='orange'>ORANGE</font></li>
                <li>Between 25-30 KTS varies between <font color='orange'>ORANGE</font> and <font color='red'>RED</font></li>
                <li>Greater than 30 KTS is <font color='red'>RED</font></li>
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
                    tcolor = get_color_by_wind(airport_data['windSpeed'])
                    self.__effect__.append(Solid(self.__pix__[i], color=tcolor))
                else:  # airport key not found in metar data
                    self.__effect__.append(Solid(self.__pix__[i], color=[0, 0, 0]))
            else:  # airport data is empty METAR data
                self.__effect__.append(Solid(self.__pix__[i], color=[0, 0, 0]))
            i += 1


