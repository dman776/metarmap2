"""
Module to handle METAR fetching and processing
"""

import sys
import time
import datetime
from pprint import pprint
import json
import lib.safe_logging as safe_logging
import metar
from lib.config import Config
from lib.utils import wheel

from adafruit_led_animation.helper import PixelSubset
from adafruit_led_animation.animation.blink import Blink
from adafruit_led_animation.animation.pulse import Pulse
from adafruit_led_animation.animation.solid import Solid
from adafruit_led_animation.animation.colorcycle import ColorCycle
from adafruit_led_animation.animation.rainbowchase import RainbowChase
from adafruit_led_animation.sequence import AnimationSequence, AnimateOnce
from adafruit_led_animation.group import AnimationGroup

class Renderer(object):
    """
    Object to control and handle a rendering Neopixels
    """

    def render(self):
        i = 0

        # Set light color and status for all entries in airports.json list
        for airport in list(self.__stations__):
            # Skip NULL entries
            if "NULL" in airport:
                i += 1
                continue

            color = self.__config__.data().color.clear
            conditions = self.__data__.get(airport, None)

            windy = False
            lightningConditions = False
            if conditions is not None:
                windy = True if (self.__config__.data().wind.animation and self.windCycle == True and (
                             conditions["windSpeed"] > self.__config__.data().wind.threshold or conditions["windGust"] == True)) else False
                lightningConditions = True if (self.__config__.data().lightning.animation and self.windCycle == False and conditions[
                    "lightning"] == True) else False
                if conditions["flightCategory"] == "VFR":
                    color = self.__config__.data().color.cat.vfr.normal if not (
                                windy or lightningConditions) else self.__config__.data().color.weather.lightning if lightningConditions else (
                        self.__config__.data().color.cat.vfr.fade if not self.__config__.data().blink.enable else self.__config__.data().color.clear) if windy else self.__config__.data().color.clear
                elif conditions["flightCategory"] == "MVFR":
                    color = self.__config__.data().color.cat.mvfr.normal if not (
                                windy or lightningConditions) else self.__config__.data().color.weather.lightning if lightningConditions else (
                        self.__config__.data().color.cat.mvfr.normal if not self.__config__.data().blink.enable else self.__config__.data().color.clear) if windy else self.__config__.data().color.clear
                elif conditions["flightCategory"] == "IFR":
                    color = self.__config__.data().color.cat.ifr.normal if not (
                            windy or lightningConditions) else self.__config__.data().color.weather.lightning if lightningConditions else (
                        self.__config__.data().color.cat.ifr.fade if not self.__config__.data().blink.enable else self.__config__.data().color.clear) if windy else self.__config__.data().color.clear
                elif conditions["flightCategory"] == "LIFR":
                    color = self.__config__.data().color.cat.lifr.normal if not (
                        windy or lightningConditions) else self.__config__.data().color.weather.lightning if lightningConditions else (
                        self.__config__.data().color.cat.lifr.fade if not self.__config__.data().blink.enable else self.__config__.data().color.clear) if windy else self.__config__.data().color.clear
                else:
                    color = self.__config__.data().color.clear

            # print("Setting LED " + str(i) + " for " + airport + " to " + ("lightning " if lightningConditions else "") + ("windy " if windy else "") + (conditions["flightCategory"] if conditions != None else "None") + " " + str(color))
            # safe_logging.safe_log("Setting LED " + str(i) + " for " + airport + " to " + ("lightning " if lightningConditions else "") + ("windy " if windy else "") + (conditions["flightCategory"] if conditions != None else "None") + " " + str(color))
            self.__pixels__[i] = color
            i += 1
        # Update actual LEDs all at once
        self.__pixels__.show()

        # To get all airport codes in the displayList. I thought I needed this, but didn't. So into the magic comment garden it goes until needed:
        # for airport in [seq[0] for seq in displayList]:

        # Switching between animation cycles
        time.sleep(self.__config__.data().blink.rate)
        self.windCycle = False if self.windCycle else True

    def clear(self):
        self.__pixels__.fill(self.__config__.data().color.clear)
        self.__pixels__.show()
        return

    def update(self, data):
        return


    def color_by_category(self, station):
        return


    def test(self):
        pixel_count = self.__config__.data().led.count

        rc = RainbowChase(self.__pixels__, speed=0.1, size=4, spacing=2, step=8)
        animations = AnimateOnce(rc)
        while animations.animate():
            pass
        self.clear()

    def init_pixel_subsets(self):
        for i in range(0, 49):
            self.__pix__.append(PixelSubset(self.__pixels__, i, i + 1))

    def __init__(self, pixels, metars: metar.METAR, config: Config):
        """
        Creates a new renderer
        """

        self.__pixels__ = pixels
        self.__stations__ = metars.stations()   # list of station ids
        self.__data__ = metars.data             # all METAR data
        self.__config__ = config
        self.windCycle = False
        self.numAirports = len(self.__stations__)
        self.__pix__ = []                       # individual pixel submap - used to address one pixel for effects
        self.__effect__ = []                    # individual pixel effects - actual effects to be applied to a pixel

        self.init_pixel_subsets()
        self.clear()
        # displayTime = 0.0
        # displayAirportCounter = 0


if __name__ == '__main__':
    print("Renderer")
