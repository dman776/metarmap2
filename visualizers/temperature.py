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

from adafruit_led_animation.animation.blink import Blink
from adafruit_led_animation.animation.pulse import Pulse
from adafruit_led_animation.animation.solid import Solid
from adafruit_led_animation.animation.colorcycle import ColorCycle
from adafruit_led_animation.color import PURPLE, WHITE, AMBER, JADE, MAGENTA, ORANGE, BLUE, AQUA, RED, GREEN, YELLOW


def celsius_to_fahrenheit(temperature_celsius: float):
    """
    Converts a temperature in celsius to fahrenheit.
    Args:
        temperature_celsius (float): A temperature in C
    Returns:
        [type]: The temperature converted to F
    """
    if temperature_celsius is None:
        return 0

    return (temperature_celsius * (9.0 / 5.0)) + 32.0


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

    temperature_fahrenheit = celsius_to_fahrenheit(temperature_celsius)

    if temperature_fahrenheit < 0:
        return colors_by_name[colors_lib.PURPLE]

    if temperature_fahrenheit < 20:
        return colors_lib.get_color_mix(
            colors_by_name[colors_lib.PURPLE],
            colors_by_name[colors_lib.BLUE],
            utils.get_proportion_between_floats(
                0,
                temperature_fahrenheit,
                20))

    if temperature_fahrenheit < 40:
        return colors_lib.get_color_mix(
            colors_by_name[colors_lib.BLUE],
            colors_by_name[colors_lib.GREEN],
            utils.get_proportion_between_floats(
                20,
                temperature_fahrenheit,
                40))

    if temperature_fahrenheit < 60:
        return colors_lib.get_color_mix(
            colors_by_name[colors_lib.GREEN],
            colors_by_name[colors_lib.YELLOW],
            utils.get_proportion_between_floats(
                40,
                temperature_fahrenheit,
                60))

    if temperature_fahrenheit < 80:
        return colors_lib.get_color_mix(
            colors_by_name[colors_lib.YELLOW],
            colors_by_name[colors_lib.ORANGE],
            utils.get_proportion_between_floats(
                60,
                temperature_fahrenheit,
                80))

    if temperature_fahrenheit < 100:
        return colors_lib.get_color_mix(
            colors_by_name[colors_lib.ORANGE],
            colors_by_name[colors_lib.RED],
            utils.get_proportion_between_floats(
                80,
                temperature_fahrenheit,
                100))

    return colors_by_name[colors_lib.RED]


class Temperature(object):
    """
    Object to handle Temp
    Returns a list of Effects on each pixel
    """
    def name(self):
        return "Temperature"

    def get_effects(self):
        return self.__effect__

    def update_data(self, data):
        safe_logging.safe_log("[v]" + "updating data in the visualizer")
        self.__data__ = data
        self.__effect__ = []  # clear existing effects
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

    def __init__(self, data, pix, config):
        self.__stations__ = data.keys()
        self.__data__ = data
        self.__pix__ = pix
        self.__config__ = config
        self.__effect__ = []
        self.update_data(data)
