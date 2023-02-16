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


class FlightCategory(object):
    """
    Object to handle FlightCategory
    Returns a list of Effects on each pixel
    """
    def name(self):
        return "FlightCategory"

    def get_effects(self):
        return self.__effect__

    def __init__(self, data, pix, config):
        self.__stations__ = data.keys()
        self.__data__ = data
        self.__pix__ = pix
        self.__config__ = config
        self.__effect__ = []

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
                        self.__effect__.append(ColorCycle(self.__pix__[i], speed=0.5, colors=[airport_data['flightCategoryColor'], YELLOW]))  # lightning
                    elif self.__config__.data().wind.animation and airport_data['windGust'] is True:
                        p = 10
                        if airport_data['windGustSpeed'] in range(0, 6):
                            p = 5       # gusts 1-5
                        elif airport_data['windGustSpeed'] in range(6, 11):
                            p = 4       # gusts 6-10
                        elif airport_data['windGustSpeed'] in range(11, 16):
                            p = 3       # gusts 11-15
                        elif airport_data['windGustSpeed'] in range(16, 21):
                            p = 2       # gusts 16-20
                        elif airport_data['windGustSpeed'] > 20:
                            p = 1     # gusts 21+
                        # pprint(airport + ": " + str(airport_data['windGustSpeed']) + " P=" + str(p))
                        self.__effect__.append(Pulse(self.__pix__[i], speed=0.1, period=p, color=airport_data['flightCategoryColor']))
                    else:
                        self.__effect__.append(Solid(self.__pix__[i], color=airport_data['flightCategoryColor']))
                else:       # airport key not found in metar data
                    self.__effect__.append(Solid(self.__pix__[i], color=[0, 0, 0]))
            else:       # airport data is empty METAR data
                self.__effect__.append(Solid(self.__pix__[i], color=[0, 0, 0]))
            i += 1


if __name__ == '__main__':
    pass
    # airportstr = '{"KDWH": {"text": "Hooks", "display": false, "visits": 0},'\
    #             '"KIAH": {"text": "IAH", "display": false, "visits": 0},'\
    #             '"KLVJ": {"text": "", "display": false, "visits": 0}}'
    # airports = json.loads(airportstr)

    # with open('airports.json') as f:
    #     data = f.read()
    # airports = json.loads(data)
    #
    # CONFIG = lib. Config("../config.json")
    # metars = METAR(airports, CONFIG, fetch=True)
    # pixels = neopixel.NeoPixel(CONFIG.LED_PIN, CONFIG.data().led.count, brightness=CONFIG.data().led.brightness if (
    #         CONFIG.data().dimming.dynamic_base.enabled and bright == False) else CONFIG.data().led.brightness,
    #                            pixel_order=CONFIG.LED_ORDER,
    #                            auto_write=False)
    # pix = controller.init_pixel_subsets(pixels)
    # v = FlightCategory(metars, pix, CONFIG)
