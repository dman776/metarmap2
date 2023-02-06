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

            color = self.__config__.data().color.fog
            conditions = self.__data__.get(airport, None)

            windy = False
            lightningConditions = False
            if conditions != None:
                # windy = True if (self.__config__.data().wind.animation and self.windCycle == True and (
                #             conditions["windSpeed"] > self.__config__.data().wind.threshold or conditions["windGust"] == True)) else False
                # lightningConditions = True if (self.__config__.data().lightning.animation and self.windCycle == False and conditions[
                #     "lightning"] == True) else False
                if conditions["flightCategory"] == "VFR":
                    color = self.__config__.data().color.cat.vfr.normal # if not (
                        #         windy or lightningConditions) else self.__config__.data().color.weather.lightning if lightningConditions else (
                        # self.__config__.data().color.cat.vfr.fade if FADE_INSTEAD_OF_BLINK else self.__config__.data().color.clear) if windy else self.__config__.data().color.clear
                elif conditions["flightCategory"] == "MVFR":
                    color = self.__config__.data().color.cat.mvfr.normal # if not (
                        #         windy or lightningConditions) else self.__config__.data().color.weather.lightning if lightningConditions else (
                        # self.__config__.data().color.cat.mvfr.normal if FADE_INSTEAD_OF_BLINK else self.__config__.data().color.clear) if windy else self.__config__.data().color.clear
                elif conditions["flightCategory"] == "IFR":
                    color = self.__config__.data().color.cat.ifr.normal # if not (
                        #         windy or lightningConditions) else COLOR_LIGHTNING if lightningConditions else (
                        # self.__config__.data().color.cat.ifr.fade if FADE_INSTEAD_OF_BLINK else self.__config__.data().color.clear) if windy else self.__config__.data().color.clear
                elif conditions["flightCategory"] == "LIFR":
                    color = self.__config__.data().color.cat.lifr.normal # if not (
                        #         windy or lightningConditions) else COLOR_LIGHTNING if lightningConditions else (
                        # self.__config__.data().color.cat.lifr.fade if FADE_INSTEAD_OF_BLINK else self.__config__.data().color.clear) if windy else self.__config__.data().color.clear
                else:
                    color = self.__config__.data().color.clear

            # print("Setting LED " + str(i) + " for " + airport + " to " + ("lightning " if lightningConditions else "") + ("windy " if windy else "") + (conditions["flightCategory"] if conditions != None else "None") + " " + str(color))
            safe_logging.safe_log("Setting LED " + str(i) + " for " + airport + " to " + ("lightning " if lightningConditions else "") + ("windy " if windy else "") + (conditions["flightCategory"] if conditions != None else "None") + " " + str(color))
            self.__pixels__[i] = color
            i += 1
        # Update actual LEDs all at once
        self.__pixels__.show()

        # To get all airport codes in the displayList. I thought I needed this, but didn't. So into the magic comment garden it goes until needed:
        # for airport in [seq[0] for seq in displayList]:

        # Switching between animation cycles
        time.sleep(self.__config__.data().blink.rate)
        # windCycle = False if windCycle else True

    def clear(self):
        self.__pixels__.fill(self.__config__.data().color.clear)
        self.__pixels__.show()
        return

    def update(self, data):
        return

    def test(self):
        self.__pixels__.fill(self.__config__.data().color.cat.vfr.normal)
        self.__pixels__.show()
        time.sleep(2.0)
        self.__pixels__.fill(self.__config__.data().color.clear)
        self.__pixels__.show()
        time.sleep(1.0)
        return

    def rainbow_test(self):
        pixel_count = 50

        for j in range(255):  # one cycle of all 256 colors in the wheel
            for i in range(pixel_count):
                pixel_index = (i * 256 // pixel_count) + j
                color = wheel(pixel_index & 255)
                self.__pixels__[i] = color
            self.__pixels__.show()
        self.clear()

    def __init__(self, pixels, metars: metar.METAR, config: Config):
        """
        Creates a new renderer
        """
        # neopixel obj
        # stations
        # data obj
        self.__pixels__ = pixels
        self.__stations__ = metars.stations()
        self.__data__ = metars.data
        self.__config__ = config
        self.windCycle = False
        self.numAirports = len(self.__stations__)
        # displayTime = 0.0
        # displayAirportCounter = 0


if __name__ == '__main__':
    print("Renderer")