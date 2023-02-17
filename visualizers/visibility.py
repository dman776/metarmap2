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
    elif vis < 0:
        return colors_by_name[colors_lib.OFF]
    elif vis > 10:
        return colors_by_name[colors_lib.WHITE]
    else:
        return colors_lib.get_color_mix(
            colors_by_name[colors_lib.WHITE], colors_by_name[colors_lib.OFF],
            utils.get_proportion_between_floats(0, vis, 10))


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
                    self.__effect__.append(Solid(self.__pix__[i], color=colors_lib.RED))
            else:  # airport data is empty METAR data
                self.__effect__.append(Solid(self.__pix__[i], color=colors_lib.RED))
            i += 1

