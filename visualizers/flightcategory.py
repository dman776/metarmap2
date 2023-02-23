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
# import lib.utils as utils
# from metar import METAR
from visualizers.visualizer import Visualizer

from adafruit_led_animation.animation.solid import Solid
from adafruit_led_animation.animation.colorcycle import ColorCycle
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
            </ul>
            </div>
            <div class="w-100">
            Lightning will be indicated by flashing <font color='gold'>YELLOW</font>.
            </div>
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
                    if self.__config__.data.lightning.animation and airport_data['lightning'] is True:
                        self.__effect__.append(ColorCycle(self.__pix__[i], speed=0.1, colors=lightning_pattern(
                            airport_data['flightCategoryColor'], self.__config__.data.color.weather.lightning)))
                    else:
                        self.__effect__.append(Solid(self.__pix__[i], color=airport_data['flightCategoryColor']))
                else:  # airport key not found in metar data
                    self.__effect__.append(Solid(self.__pix__[i], color=[0, 0, 0]))
            else:  # airport data is empty METAR data
                self.__effect__.append(Solid(self.__pix__[i], color=[0, 0, 0]))
            i += 1


