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
from visualizers.visualizer import Visualizer, legend_item

from adafruit_led_animation.animation.blink import Blink
from adafruit_led_animation.animation.pulse import Pulse
from adafruit_led_animation.animation.solid import Solid
from adafruit_led_animation.animation.colorcycle import ColorCycle
from adafruit_led_animation.color import PURPLE, WHITE, AMBER, JADE, MAGENTA, ORANGE, BLUE, AQUA, RED, GREEN, YELLOW


def get_color_by_temperature_celsius(temperature_celsius: int) -> list:
    """
    Given a temperature (in Celsius), return the color
    that should represent that temp on the map.

    These colors were decided based on weather temperature maps
    and thermometer markings.

    Args:
        temperature_celsius (int): A temperature in C.

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
        return "Display the temperature in degrees Fahrenheit."

    @property
    def legend(self):
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
                    if type(airport_data['tempC']) == int:
                        tcolor = get_color_by_temperature_celsius(airport_data['tempC'])
                        self.__effect__.append(Solid(self.__pix__[i], color=tcolor))
                    else:   # no temp reported
                        self.__effect__.append(Solid(self.__pix__[i], color=[0, 0, 0]))
                else:  # airport key not found in metar data
                    self.__effect__.append(Solid(self.__pix__[i], color=[0, 0, 0]))
            else:  # airport data is empty METAR data
                self.__effect__.append(Solid(self.__pix__[i], color=[0, 0, 0]))
            i += 1


