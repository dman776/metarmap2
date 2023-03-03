"""
Module to handle visualizing Precip data
"""

import sys
import time
import datetime
from pprint import pprint
import json

from adafruit_led_animation.animation.pulse import Pulse

import lib.safe_logging as safe_logging
# from lib.config import Config
import lib.utils as utils
import lib.colors as colors_lib
from metar import METAR
from visualizers.visualizer import Visualizer
from adafruit_led_animation.animation.solid import Solid
from adafruit_led_animation.animation.blink import Blink


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
            Display the current observed precipitation.
            <div class="w-100">
            <ul>
                <li>None = OFF</li>
                <li>Haze = DARK GRAY</li>
                <li>Fog = Pulsing 6% WHITE every 4 seconds</li>
                <li>Light Drizzle = <font color='blue'>12% BLUE</font></li>
                <li>Light Rain = Pulsing <font color='blue'>BLUE</font> every 4 seconds</li>
                <li>Rain = Pulsing <font color='blue'>BLUE</font> every 2 seconds</li>
                <li>Heavy Rain = Blinking <font color='blue'>BLUE</font> every second</li>
                <li>Other = Blinking <font color='red'>RED</font> every second</li>
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
                    p_eff = self.get_effect_by_obs(self.__pix__[i], airport_data['obs'])
                    self.__effect__.append(p_eff)
                else:  # airport key not found in metar data
                    self.__effect__.append(Solid(self.__pix__[i], color=[0, 0, 0]))
            else:  # airport data is empty METAR data
                self.__effect__.append(Solid(self.__pix__[i], color=[0, 0, 0]))
            i += 1

    def get_effect_by_obs(self, pixel, obs: str):
        """
        Given an observation reading, return a RGB color to show on the map.
        Args:
            pix (int): the pixel number
            obs (string): The observation reading from a metar.
        Returns:
            pixel effect
        """

        # -RA = light color, slow pulse
        #  RA = regular color, med pulse

        # +RA = blink regular color, rapid pulse

        colors_by_name = colors_lib.get_colors()

        if obs is None or obs == "":
            return Solid(pixel, color=colors_by_name[colors_lib.OFF])
        elif "HZ" in obs:
            return Solid(pixel, color=self.__config__.data.color.weather.haze)
        elif "FG" in obs:
            return Pulse(pixel, speed=0.1, period=4, color=self.__config__.data.color.weather.fog)
        elif "BR" in obs:
            return Solid(pixel, color=self.__config__.data.color.weather.mist.normal)
        elif "-DZ" in obs:
            return Solid(pixel, color=self.__config__.data.color.weather.drizzle.light)
        elif "-RA" in obs:
            return Pulse(pixel, speed=0.1, period=4, color=self.__config__.data.color.weather.rain)
        elif "RA" in obs:
            return Pulse(pixel, speed=0.1, period=2, color=self.__config__.data.color.weather.rain)
        elif "+RA" in obs:
            return Blink(pixel, speed=1, color=self.__config__.data.color.weather.rain)
        elif "VCTS" in obs:
            return Blink(pixel, speed=1, color=self.__config__.data.color.weather.lightning)
        else:
            safe_logging.safe_log("[v]obs=" + str(obs))
            return Blink(pixel, speed=1, color=colors_by_name[colors_lib.RED])
