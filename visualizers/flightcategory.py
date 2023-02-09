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
from adafruit_led_animation.helper import PixelSubset
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

    def get_effects(self):
        return self.__effect__

    def __init__(self, stations, data, pix):
        # visualizer = FlightCategoryVisualizer(self.__stations__, self.__data__, self.__pix__)
        self.__stations__ = stations
        self.__data__ = data
        self.__pix__ = pix
        self.__effect__ = []

        # loop over all stations
        # determine effect based on data
        self.__effect__.append(Pulse(self.__pix__[0], speed=0.1, period=4, color=GREEN))  # VFR + gusts under 5
        self.__effect__.append(Pulse(self.__pix__[1], speed=0.1, period=3, color=GREEN))  # VFR + gusts 6-10
        self.__effect__.append(Pulse(self.__pix__[2], speed=0.1, period=2, color=GREEN))  # VFR + gusts 11-15
        self.__effect__.append(Pulse(self.__pix__[3], speed=0.1, period=1, color=GREEN))  # VFR + gusts 16-20
        self.__effect__.append(Pulse(self.__pix__[4], speed=0.1, period=0.5, color=GREEN))  # VFR + gusts 21+
        self.__effect__.append(Solid(self.__pix__[5], color=GREEN))  # VFR
        self.__effect__.append(Solid(self.__pix__[6], color=BLUE))  # MVFR
        self.__effect__.append(Solid(self.__pix__[7], color=RED))  # IFR
        self.__effect__.append(Solid(self.__pix__[8], color=PURPLE))  # LIFR
        self.__effect__.append(ColorCycle(self.__pix__[9], speed=0.5, colors=[BLUE, YELLOW]))  # MVFR + lightning
        self.__effect__.append(Pulse(self.__pix__[10], speed=0.1, period=4, color=BLUE))  # MVFR + gusts under 5
        self.__effect__.append(Pulse(self.__pix__[11], speed=0.1, period=3, color=BLUE))  # MVFR + gusts 6-10
        self.__effect__.append(Pulse(self.__pix__[12], speed=0.1, period=2, color=BLUE))  # MVFR + gusts 11-15
        self.__effect__.append(Pulse(self.__pix__[13], speed=0.1, period=1, color=BLUE))  # MVFR + gusts 16-20
        self.__effect__.append(Pulse(self.__pix__[14], speed=0.1, period=0.5, color=BLUE))  # MVFR + gusts 21+
        self.__effect__.append(Pulse(self.__pix__[15], speed=0.1, period=4, color=RED))  # IFR + gusts under 5
        self.__effect__.append(Pulse(self.__pix__[16], speed=0.1, period=3, color=RED))  # IFR + gusts 6-10
        self.__effect__.append(Pulse(self.__pix__[17], speed=0.1, period=2, color=RED))  # IFR + gusts 11-15
        self.__effect__.append(Pulse(self.__pix__[18], speed=0.1, period=1, color=RED))  # IFR + gusts 16-20
        self.__effect__.append(Pulse(self.__pix__[19], speed=0.1, period=0.5, color=RED))  # IFR + gusts 21+


        # DO STUFF
        # # Set light color and status for all entries in airports.json list
        # for airport in list(self.__stations__):
        #     # Skip NULL entries
        #     if "NULL" in airport:
        #         i += 1
        #         continue
        #
        #     airport_data = self.__data__.get(airport, None)
        #
        #
        #     # if conditions is not None:
        #     #     windy = True if (self.__config__.data().wind.animation and self.windCycle == True and (
        #     #                  conditions["windSpeed"] > self.__config__.data().wind.threshold or conditions["windGust"] == True)) else False
        #     #     lightningConditions = True if (self.__config__.data().lightning.animation and self.windCycle == False and conditions[
        #     #         "lightning"] == True) else False
        #     #     if conditions["flightCategory"] == "VFR":
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
        #     i += 1
        # # Update actual LEDs all at once
        # self.__pixels__.show()
        #
        # # To get all airport codes in the displayList. I thought I needed this, but didn't. So into the magic comment garden it goes until needed:
        # # for airport in [seq[0] for seq in displayList]:
        #
        # # Switching between animation cycles
        # time.sleep(self.__config__.data().blink.rate)

