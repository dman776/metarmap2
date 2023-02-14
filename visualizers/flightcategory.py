"""
Module to handle visualizing Flight Category data
"""

import sys
import time
import datetime
from pprint import pprint
import json
import lib.safe_logging as safe_logging
from lib.config import Config
import lib.utils as utils

import neopixel
import board

from adafruit_led_animation.animation.blink import Blink
from adafruit_led_animation.animation.pulse import Pulse
from adafruit_led_animation.animation.solid import Solid
from adafruit_led_animation.animation.colorcycle import ColorCycle
from adafruit_led_animation.color import PURPLE, WHITE, AMBER, JADE, MAGENTA, ORANGE, BLUE, AQUA, RED, GREEN, YELLOW


class FlightCategory(object):
    """
    Object to handle FlightCategory
    Returns a list of Effects on each pixel
    """
    def name(self):
        return "FlightCategory"

    def get_effects(self):
        return self.__effect__

    def __init__(self, stations, data, pix, config):
        # visualizer = FlightCategoryVisualizer(self.__stations__, self.__data__, self.__pix__)
        self.__stations__ = stations
        self.__data__ = data
        self.__pix__ = pix
        self.__config__ = config
        self.__effect__ = []

        # loop over all stations
        i = 0
        # for airport in list(self.__stations__):

        pprint(self.__data__.keys())
        sys.exit()

        for airport in list(self.__data__.keys()):
            # Skip NULL entries
            if "NULL" in airport:
                self.__effect__.append(Solid(self.__pix__[i], color=(0, 0, 0)))
                i += 1
                continue

            airport_data = self.__data__.get(airport, None)

            if airport=="KLJV":
                pprint(airport_data)
                sys.exit()

            if airport_data is not None and len(airport_data.keys()) > 0:
                if self.__config__.data().lightning.animation and airport_data['lightning'] is True:
                    self.__effect__.append(ColorCycle(self.__pix__[i], speed=0.5,
                            colors=[airport_data['flightCategoryColor'], YELLOW]))  # lightning
                elif self.__config__.data().wind.animation and airport_data['windGust'] is True:
                    p = 0
                    if 0 < airport_data['windGustSpeed'] <= 5:
                        p = 4       # gusts 1-5
                    elif 6 < airport_data['windGustSpeed'] <= 10:
                        p = 3       # gusts 6-10
                    elif 11 < airport_data['windGustSpeed'] <= 15:
                        p = 2       # gusts 11-15
                    elif 16 < airport_data['windGustSpeed'] <= 20:
                        p = 1       # gusts 16-20
                    elif airport_data['windGustSpeed'] >= 21:
                        p = 0.5     # gusts 21+
                    self.__effect__.append(Pulse(self.__pix__[i], speed=0.1, period=p, color=airport_data['flightCategoryColor']))
                else:
                    self.__effect__.append(Solid(self.__pix__[i], color=airport_data['flightCategoryColor']))
            else:       # airport not found in METAR data
                self.__effect__.append(Solid(self.__pix__[i], color=(0, 0, 0)))
            i += 1


