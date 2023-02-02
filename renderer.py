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
import lib.colors as colors


class Renderer(object):
    """
    Object to control and handle a rendering Neopixels
    """


    windCycle = False
    displayTime = 0.0
    displayAirportCounter = 0
    # numAirports = len(displayList)
    numAirports = 50
    pixels=[]

    def render(self):
        while looplimit > 0:
            i = 0

            # Set light color and status for all entries in airports.json list
            for airport in list(self.__stations__):
                # Skip NULL entries
                if "NULL" in airport:
                    i += 1
                    continue

                color = colors.CLEAR
                conditions = self.__data__.get(airport, None)
                windy = False
                lightningConditions = False
                if conditions != None:
                    windy = True if (ACTIVATE_WINDCONDITION_ANIMATION and windCycle == True and (
                                conditions["windSpeed"] > WIND_BLINK_THRESHOLD or conditions["windGust"] == True)) else False
                    lightningConditions = True if (ACTIVATE_LIGHTNING_ANIMATION and windCycle == False and conditions[
                        "lightning"] == True) else False
                    if conditions["flightCategory"] == "VFR":
                        color = colors.VFR if not (
                                    windy or lightningConditions) else COLOR_LIGHTNING if lightningConditions else (
                            COLOR_VFR_FADE if FADE_INSTEAD_OF_BLINK else COLOR_CLEAR) if windy else COLOR_CLEAR
                    elif conditions["flightCategory"] == "MVFR":
                        color = colors.MVFR if not (
                                    windy or lightningConditions) else COLOR_LIGHTNING if lightningConditions else (
                            COLOR_MVFR_FADE if FADE_INSTEAD_OF_BLINK else COLOR_CLEAR) if windy else COLOR_CLEAR
                    elif conditions["flightCategory"] == "IFR":
                        color = colors.IFR if not (
                                    windy or lightningConditions) else COLOR_LIGHTNING if lightningConditions else (
                            COLOR_IFR_FADE if FADE_INSTEAD_OF_BLINK else COLOR_CLEAR) if windy else COLOR_CLEAR
                    elif conditions["flightCategory"] == "LIFR":
                        color = colors.LIFR if not (
                                    windy or lightningConditions) else COLOR_LIGHTNING if lightningConditions else (
                            COLOR_LIFR_FADE if FADE_INSTEAD_OF_BLINK else COLOR_CLEAR) if windy else COLOR_CLEAR
                    else:
                        color = colors.CLEAR

                # print("Setting LED " + str(i) + " for " + airport + " to " + ("lightning " if lightningConditions else "") + ("windy " if windy else "") + (conditions["flightCategory"] if conditions != None else "None") + " " + str(color))
                pixels[i] = color
                i += 1
            # Update actual LEDs all at once
            # pixels.show()

            # To get all airport codes in the displayList. I thought I needed this, but didn't. So into the magic comment garden it goes until needed:
            # for airport in [seq[0] for seq in displayList]:

            # Switching between animation cycles
            time.sleep(BLINK_SPEED)
            windCycle = False if windCycle else True
            looplimit -= 1

    def clear(self):
        return

    def update(self, data):
        return

    def test(self):
        self.__pixels__.set_all(colors.VFR)
        self.__pixels__.show()
        time.sleep(2.0)
        self.__pixels__.set_all(colors.CLEAR)
        self.__pixels__.show()
        return

    def rainbow_test(self):
        pixel_count = 50

        for j in range(255):  # one cycle of all 256 colors in the wheel
            for i in range(pixel_count):
                pixel_index = (i * 256 // pixel_count) + j
                color = wheel(pixel_index & 255)
                self.__pixels__.set_led(i, color)
            self.__renderer__.show()

    def __wheel__(pos):
        # Input a value 0 to 255 to get a color value.
        # The colours are a transition r - g - b - back to r.
        if pos < 0 or pos > 255:
            r = g = b = 0
        elif pos < 85:
            r = int(pos * 3)
            g = int(255 - pos * 3)
            b = 0
        elif pos < 170:
            pos -= 85
            r = int(255 - pos * 3)
            g = 0
            b = int(pos * 3)
        else:
            pos -= 170
            r = 0
            g = int(pos * 3)
            b = int(255 - pos * 3)
        return r, g, b

    def __init__(self, pixels, metars: metar.METAR):
        """
        Creates a new renderer
        """
        # neopixel obj
        # stations
        # data obj
        self.__pixels__ = pixels
        self.__stations__ = metars.stations()
        self.__data__ = metars.data

if __name__ == '__main__':
    print("Renderer")