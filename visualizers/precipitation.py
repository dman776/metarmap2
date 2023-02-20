"""
Module to handle visualizing Precip data
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

def get_color_by_obs(obs: str) -> list:
    """
    Given an observation reading, return a RGB color to show on the map.
    Args:
        obs (string): The observation reading from a metar.
    Returns:
        list: The RGB color to show on the map for the station.
    """

    colors_by_name = colors_lib.get_colors()

    if obs is None or obs == "":
        return colors_by_name[colors_lib.OFF]
    elif "FG" in obs:
        return [15, 15, 15]
    elif "HZ" in obs:
        return [5, 5, 5]
    elif "BR" in obs:
        return colors_by_name[colors_lib.LIGHT_BLUE]
    elif "RS" in obs:
        return colors_by_name[colors_lib.BLUE]
    else:
        safe_logging.safe_log("[v]obs=" + str(obs))
        return colors_by_name[colors_lib.RED]


class Precipitation(Visualizer):
    """
    Object to handle Precip
    Returns a list of Effects on each pixel
    """
    def __init__(self, data, pix, config):
        super().__init__(data, pix, config)

    @property
    def name(self):
        return "Precipitation"

    @property
    def description(self):
        return """
            Display the precipitation.
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
                    pcolor = get_color_by_obs(airport_data['obs'])
                    self.__effect__.append(Solid(self.__pix__[i], color=pcolor))
                else:  # airport key not found in metar data
                    self.__effect__.append(Solid(self.__pix__[i], color=[0, 0, 0]))
            else:  # airport data is empty METAR data
                self.__effect__.append(Solid(self.__pix__[i], color=[0, 0, 0]))
            i += 1

