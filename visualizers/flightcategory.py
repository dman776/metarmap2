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
        for airport in list(self.__stations__):
            # Skip NULL entries
            if "NULL" in airport:
                self.__effect__.append(Solid(self.__pix__[i], color=(0, 0, 0)))
                i += 1
                continue

            airport_data = self.__data__.get(airport, None)

            if airport_data is not None:
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
                    if 'flightCategoryColor' in airport_data:
                        self.__effect__.append(Solid(self.__pix__[i], color=airport_data['flightCategoryColor']))
                    else:
                        self.__effect__.append(Solid(self.__pix__[i], color=(0, 0, 0)))

            #     windy = True if (self.__config__.data().wind.animation and self.windCycle == True and (
            #                  conditions["windSpeed"] > self.__config__.data().wind.threshold or conditions["windGust"] == True)) else False
            #     lightningConditions = True if (self.__config__.data().lightning.animation and self.windCycle == False and conditions[
            #         "lightning"] == True) else False
        #     #         color = self.__config__.data().color.cat.vfr.normal if not (
        #     #                     windy or lightningConditions) else self.__config__.data().color.weather.lightning if lightningConditions else (
        #     #             self.__config__.data().color.cat.vfr.fade if not self.__config__.data().blink.enable else self.__config__.data().color.clear) if windy else self.__config__.data().color.clear
        #     #     elif conditions["flightCategory"] == "MVFR":
        #     #         color = self.__config__.data().color.cat.mvfr.normal if not (
        #     #                     windy or lightningConditions) else self.__config__.data().color.weather.lightning if lightningConditions else (
        #     #             self.__config__.data().color.cat.mvfr.normal if not self.__config__.data().blink.enable else self.__config__.data().color.clear) if windy else self.__config__.data().color.clear
        #     #     elif conditions["flightCategory"] == "IFR":
        #     #         color = self.__config__.data().color.cat.ifr.normal if not (
        #     #                 windy or lightningConditions) else self.__config__.data().color.weather.lightning if lightningConditions else (
        #     #             self.__config__.data().color.cat.ifr.fade if not self.__config__.data().blink.enable else self.__config__.data().color.clear) if windy else self.__config__.data().color.clear
        #     #     elif conditions["flightCategory"] == "LIFR":
        #     #         color = self.__config__.data().color.cat.lifr.normal if not (
        #     #             windy or lightningConditions) else self.__config__.data().color.weather.lightning if lightningConditions else (
        #     #             self.__config__.data().color.cat.lifr.fade if not self.__config__.data().blink.enable else self.__config__.data().color.clear) if windy else self.__config__.data().color.clear
        #     #     else:
        #     #         color = self.__config__.data().color.clear
        #     # safe_logging.safe_log("Setting LED " + str(i) + " for " + airport + " to " + ("lightning " if lightningConditions else "") + ("windy " if windy else "") + (conditions["flightCategory"] if conditions != None else "None") + " " + str(color))
        #
        #     # flight category color for now
        #     self.__pixels__[i] = airport_data['flightCategoryColor']
            else:
                self.__effect__.append(Solid(self.__pix__[i], color=(0, 0, 0)))
            i += 1


