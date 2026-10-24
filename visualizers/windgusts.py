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
import lib.colors as colors_lib
from metar import METAR
from visualizers.visualizer import Visualizer, legend_item

from adafruit_led_animation.animation.blink import Blink
from adafruit_led_animation.animation.pulse import Pulse
from adafruit_led_animation.animation.solid import Solid
from adafruit_led_animation.animation.colorcycle import ColorCycle
from adafruit_led_animation.color import PURPLE, WHITE, AMBER, JADE, MAGENTA, ORANGE, BLUE, AQUA, RED, GREEN, YELLOW
import visualizers.wind


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
        return "Display the wind gusts by pulsing the wind colors (from the Wind visualizer) at different rates."

    @property
    def legend(self):
        c = colors_lib.get_colors()
        rates = [("0-10 kts", 10), ("11-15 kts", 8), ("16-20 kts", 6), ("21-25 kts", 4), ("26-30 kts", 1),
                 ("over 30 kts", 0.5)]
        items = [legend_item(f"Gusts {kts}", f"Wind color, pulsing every {period} s", c[colors_lib.GREEN],
                             effect="pulse", period=period) for kts, period in rates]
        items.append(legend_item("No gusts reported", "No pulse; solid flight category color", c[colors_lib.GREEN]))
        return items

    def update_data(self, data):
        super().update_data(data)

        # loop over all stations
        i = 0
        wcolor = None
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
                    wcolor = visualizers.wind.get_color_by_wind(airport_data['windSpeed'])
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
                            Pulse(self.__pix__[i], speed=0.1, period=p, color=wcolor))
                    else:
                        self.__effect__.append(Solid(self.__pix__[i], color=wcolor))
                else:  # airport key not found in metar data
                    self.__effect__.append(Solid(self.__pix__[i], color=[0, 0, 0]))
            else:  # airport data is empty METAR data
                self.__effect__.append(Solid(self.__pix__[i], color=[0, 0, 0]))
            i += 1

