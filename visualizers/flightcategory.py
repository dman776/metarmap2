"""
Module to handle visualizing Flight Category data
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
from metar import METAR
import neopixel
import board

from adafruit_led_animation.animation.blink import Blink
from adafruit_led_animation.animation.pulse import Pulse
from adafruit_led_animation.animation.solid import Solid
from adafruit_led_animation.animation.colorcycle import ColorCycle
from adafruit_led_animation.color import PURPLE, WHITE, AMBER, JADE, MAGENTA, ORANGE, BLUE, AQUA, RED, GREEN, YELLOW


def lightning_pattern(cat):
    lp = []
    for i in range(1, 16):
        lp.append(cat)
    lp.append(YELLOW)
    return lp


class FlightCategory(object):
    """
    Object to handle FlightCategory
    Returns a list of Effects on each pixel
    """
    def name(self):
        return "Flight Category"

    def get_effects(self):
        return self.__effect__

    def update_data(self, data):
        self.__data__ = data
        self.__effect__ = []        # clear existing effects
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
                    if self.__config__.data().lightning.animation and airport_data['lightning'] is True:
                        self.__effect__.append(ColorCycle(self.__pix__[i], speed=0.1, colors=lightning_pattern(
                            airport_data['flightCategoryColor'])))  # lightning
                    else:
                        self.__effect__.append(Solid(self.__pix__[i], color=airport_data['flightCategoryColor']))
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

