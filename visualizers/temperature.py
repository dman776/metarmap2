"""
Module to handle visualizing Temp data
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


def get_color_by_temperature_celsius(temperature_celsius: float) -> list:
    """
    Given a temperature (in Celsius), return the color
    that should represent that temp on the map.

    These colors were decided based on weather temperature maps
    and thermometer markings.

    Args:
        temperature_celsius (float): A temperature in metric.

    Returns:
        list: The RGB color to show on the map.
    """
    colors_by_name = colors_lib.get_colors()

    if temperature_celsius is None:
        return colors_by_name[colors_lib.OFF]

    temperature_fahrenheit = utils.celsius_to_fahrenheit(temperature_celsius)

    if temperature_fahrenheit < 0:
        return colors_by_name[colors_lib.WHITE]

    if temperature_fahrenheit < 40:
        return colors_lib.get_color_mix(
            colors_by_name[colors_lib.WHITE], colors_by_name[colors_lib.PURPLE],
            utils.get_proportion_between_floats(0, temperature_fahrenheit, 40))

    if temperature_fahrenheit < 60:
        return colors_lib.get_color_mix(
            colors_by_name[colors_lib.PURPLE], colors_by_name[colors_lib.BLUE],
            utils.get_proportion_between_floats(40, temperature_fahrenheit, 60))

    if temperature_fahrenheit < 70:
        return colors_lib.get_color_mix(
            colors_by_name[colors_lib.BLUE], colors_by_name[colors_lib.GREEN],
            utils.get_proportion_between_floats(60, temperature_fahrenheit, 70))

    if temperature_fahrenheit < 80:
        return colors_lib.get_color_mix(
            colors_by_name[colors_lib.GREEN], colors_by_name[colors_lib.YELLOW],
            utils.get_proportion_between_floats(70, temperature_fahrenheit, 80))

    if temperature_fahrenheit < 90:
        return colors_lib.get_color_mix(
            colors_by_name[colors_lib.YELLOW], colors_by_name[colors_lib.ORANGE],
            utils.get_proportion_between_floats(80, temperature_fahrenheit, 90))

    if temperature_fahrenheit < 100:
        return colors_lib.get_color_mix(
            colors_by_name[colors_lib.ORANGE], colors_by_name[colors_lib.RED],
            utils.get_proportion_between_floats(90, temperature_fahrenheit, 100))

    return colors_by_name[colors_lib.RED]


class Temperature(Visualizer):
    """
    Object to handle Temp
    Returns a list of Effects on each pixel
    """

    def __init__(self, data, pix, config):
        super().__init__(data, pix, config)

    @property
    def name(self):
        return "Temperature"

    @property
    def description(self):
        return """
            Display the temperature in degrees Fahrenheit.
            <div class="w-100">
            <ul>
                <li>Less than 0&deg;=WHITE</li>
                <li>Between 0&deg; and 40&deg; varies between WHITE and <font color='purple'>PURPLE</font></li>
                <li>Between 40&deg; and 60&deg; varies between <font color='purple'>PURPLE</font> and <font color='blue'>BLUE</font></li>
                <li>Between 60&deg; and 70&deg; varies between <font color='blue'>BLUE</font> and <font color='green'>GREEN</font></li>
                <li>Between 70&deg; and 80&deg; varies between <font color='green'>GREEN</font> and <font color='gold'>YELLOW</font></li>
                <li>Between 80&deg; and 90&deg; varies between <font color='gold'>YELLOW</font> and <font color='orange'>ORANGE</font></li>
                <li>Between 90&deg; and 100&deg; varies between <font color='orange'>ORANGE</font> and <font color='red'>RED</font></li>
                <li>Greater than 100&deg;=RED</li>
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
                    tcolor = get_color_by_temperature_celsius(airport_data['tempC'])
                    self.__effect__.append(Solid(self.__pix__[i], color=tcolor))
                else:  # airport key not found in metar data
                    self.__effect__.append(Solid(self.__pix__[i], color=[0, 0, 0]))
            else:  # airport data is empty METAR data
                self.__effect__.append(Solid(self.__pix__[i], color=[0, 0, 0]))
            i += 1


