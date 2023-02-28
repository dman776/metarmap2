"""
Module to handle visualizing Visibility data
"""

import sys
import time
import datetime
from pprint import pprint
import json

import lib.safe_logging as safe_logging
# from lib.config import Config
import lib.utils as utils
import lib.colors as colors_lib
from metar import METAR
from visualizers.visualizer import Visualizer
from adafruit_led_animation.animation.solid import Solid
from adafruit_led_animation.animation.blink import Blink

def get_color_by_visibility(vis: float) -> list:
    """
    Given a visibility reading, return a RGB color to show on the map.
    Args:
        vis (float): The vis reading from a metar in SM
    Returns:
        list: The RGB color to show on the map for the station.
    """

    colors_by_name = colors_lib.get_colors()

    if vis is None:
        return colors_by_name[colors_lib.RED]
    elif vis <= 0:
        return colors_by_name[colors_lib.OFF]
    elif vis >= 10:
        return colors_by_name[colors_lib.WHITE]
    else:
        # return colors_lib.get_color_mix(
        #     colors_by_name[colors_lib.OFF], colors_by_name[colors_lib.WHITE],
        #     utils.get_proportion_between_floats(0, vis, 10))
        if vis in range(9, 10):
            return [80, 80, 80]
        elif vis in range(8, 9):
            return [40, 40, 40]
        elif vis in range(7, 8):
            return [20, 20, 20]
        elif vis in range(6, 7):
            return [10, 10, 10]
        elif vis in range(5, 6):
            return [5, 5, 5]
        elif vis in range(4, 5):
            return [4, 4, 4]
        elif vis in range(3, 4):
            return [3, 3, 3]
        elif vis in range(2, 3):
            return [2, 2, 2]
        elif vis in range(1, 2):
            return [1, 1, 1]
        elif vis in range(0, 1):
            return [0, 0, 0]



class Visibility(Visualizer):
    """
    Object to handle Visibility
    Returns a list of Effects on each pixel
    """
    def __init__(self, data, pix, config):
        super().__init__(data, pix, config)

    @property
    def name(self):
        return "Visibility"

    @property
    def description(self):
        return """
            Display the visibility level (ie. 10SM, 6SM, 1/2SM, etc.)
            <div class="w-100">
            <ul>
                <li>Between 9 and 10 Miles = 30% WHITE</li>
                <li>Between 8 and 9 Miles = 15% WHITE</li>
                <li>Between 7 and 8 Miles = 8% WHITE</li>
                <li>Between 6 and 7 Miles = 6% WHITE</li>
                <li>Between 5 and 6 Miles = 5% WHITE</li>
                <li>Between 4 and 5 Miles = 4% WHITE</li>
                <li>Between 3 and 4 Miles = 3% WHITE</li>
                <li>Between 2 and 3 Miles = 2% WHITE</li>
                <li>Between 1 and 2 Miles = 1% WHITE</li>
                <li>Between 0 and 1 Miles = OFF</li>
                <li>No visibility reported = <font color='red'>RED</font></li>
            </ul>
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
                    pcolor = get_color_by_visibility(airport_data['vis'])
                    self.__effect__.append(Solid(self.__pix__[i], color=pcolor))
                else:  # airport key not found in metar data
                    self.__effect__.append(Solid(self.__pix__[i], color=colors_lib.get_colors()['RED']))
            else:  # airport data is empty METAR data
                self.__effect__.append(Blink(self.__pix__[i], speed=1, color=colors_lib.get_colors()['RED']))
            i += 1

