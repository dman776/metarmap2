"""
Module to handle visualizing Flight Category data
"""

# import sys
# import time
# import datetime
# from pprint import pprint
# import json
#
# import lib.safe_logging as safe_logging
# from lib.config import Config
# import lib
import lib.utils as utils
import lib.colors as colors_lib
# from metar import METAR
from visualizers.visualizer import Visualizer

from adafruit_led_animation.animation.solid import Solid
from adafruit_led_animation.animation.colorcycle import ColorCycle
from adafruit_led_animation.animation.blink import Blink


# from adafruit_led_animation.color import YELLOW


def lightning_pattern(cat, color):
    lp = []
    for i in range(1, 16):
        lp.append(cat)
    lp.append(color)
    return lp


class FlightCategory(Visualizer):
    """
    Object to handle FlightCategory
    Returns a list of Effects on each pixel
    """
    def __init__(self, data, pix, config):
        super().__init__(data, pix, config)

    @property
    def name(self):
        return "Flight Category"

    @property
    def description(self):
        return """
            Display the flight category (ie. VFR, MVFR, IFR, LIFR).
            <div class="w-100">
            <ul>
                <li>VFR = <font color='green'>GREEN</font></li>
                <li>MVFR = <font color='blue'>BLUE</font></li>
                <li>IFR = <font color='red'>RED</font></li>
                <li>LIFR = <font color='purple'>PURPLE</font></li>
                <li>Flight category is missing (but other data is available) = Blinking <font color='red'>RED</font></li>
                <li>Metar not available = OFF</li>
            </ul>
            </div>
            <div class="w-100">
            Lightning will be indicated by flashing <font color='gold'>YELLOW</font> (if configured).
            </div>
        """

    def update_data(self, data):
        super().update_data(data)
        # loop over all stations
        for i, airport in enumerate(list(self.__data__.keys())):
            if "NULL" in airport or not self.__data__[airport]:  # NULL or no metar data at all
                self.__effect__.append(Solid(self.__pix__[i], color=colors_lib.get_colors()[colors_lib.OFF]))
                continue
            airport_data = self.__data__.get(airport, {})
            flight_category = airport_data.get('flightCategory')
            flight_category_color = self.__colors_by_category__(flight_category)

            if self.__config__.data.lightning.animation and airport_data.get('lightning', False):
                self.__effect__.append(ColorCycle(self.__pix__[i], speed=0.1, colors=lightning_pattern(
                    flight_category_color, self.__config__.data.color.weather.lightning)))
            elif flight_category is None:  # ie. not reporting flight_cat
                self.__effect__.append(Blink(self.__pix__[i], speed=1, color=colors_lib.get_colors()[colors_lib.RED]))
            else:
                self.__effect__.append(Solid(self.__pix__[i], color=flight_category_color))

    def __colors_by_category__(self, category):
        color_map = {
            "VFR": self.__config__.data.color.cat.vfr,
            "MVFR": self.__config__.data.color.cat.mvfr,
            "IFR": self.__config__.data.color.cat.ifr,
            "LIFR": self.__config__.data.color.cat.lifr,
        }
        return color_map.get(category, self.__config__.data.color.clear)
