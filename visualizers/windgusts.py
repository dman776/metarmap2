"""
Module to handle visualizing WindGust data
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
from visualizers.visualizer import Visualizer

from adafruit_led_animation.animation.blink import Blink
from adafruit_led_animation.animation.pulse import Pulse
from adafruit_led_animation.animation.solid import Solid
from adafruit_led_animation.animation.colorcycle import ColorCycle
from adafruit_led_animation.color import PURPLE, WHITE, AMBER, JADE, MAGENTA, ORANGE, BLUE, AQUA, RED, GREEN, YELLOW


class WindGusts(Visualizer):
    """
    Object to handle Wind
    Returns a list of Effects on each pixel
    """
    def __init__(self, data, pix, config):
        super().__init__(data, pix, config)

    @property
    def name(self):
        return "Wind Gusts"

    @property
    def description(self):
        return """
            Display the wind gusts.
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
                    if airport_data['windGust'] is True:
                        p = 10
                        if airport_data['windGustSpeed'] in range(0, 11):
                            p = 10  # gusts 1-5
                        elif airport_data['windGustSpeed'] in range(11, 16):
                            p = 8  # gusts 6-10
                        elif airport_data['windGustSpeed'] in range(16, 21):
                            p = 6  # gusts 11-15
                        elif airport_data['windGustSpeed'] in range(21, 26):
                            p = 4  # gusts 16-20
                        elif airport_data['windGustSpeed'] in range(26, 31):
                            p = 1  # gusts 21+
                        elif airport_data['windGustSpeed'] > 30:
                            p = 0.5
                        self.__effect__.append(
                            Pulse(self.__pix__[i], speed=0.1, period=p, color=airport_data['flightCategoryColor']))
                    else:
                        self.__effect__.append(Solid(self.__pix__[i], color=airport_data['flightCategoryColor']))
                else:  # airport key not found in metar data
                    self.__effect__.append(Solid(self.__pix__[i], color=[0, 0, 0]))
            else:  # airport data is empty METAR data
                self.__effect__.append(Solid(self.__pix__[i], color=[0, 0, 0]))
            i += 1

