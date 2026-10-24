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
from visualizers.visualizer import Visualizer, legend_item
from adafruit_led_animation.animation.pulse import Pulse
from adafruit_led_animation.animation.solid import Solid
from adafruit_led_animation.animation.blink import Blink
from adafruit_led_animation.animation.sparkle import Sparkle


class Precipitation(Visualizer):
    """
    Object to handle Precip
    Returns a list of Effects on each pixel
    """
    def __init__(self, data, pix, config):
        super().__init__(data, pix, config)
        self.__exclusive__ = True

    @property
    def name(self):
        return "Precipitation"

    @property
    def description(self):
        return "Display the current observed precipitation."

    @property
    def legend(self):
        c = colors_lib.get_colors()
        w = self.__config__.data.color.weather
        return [
            legend_item("None", "Off"),
            legend_item("Haze", "Dark gray", w.haze),
            legend_item("Fog", "Dim white, pulsing every 4 seconds", w.fog, effect="pulse", period=4),
            legend_item("Light drizzle", "Green, pulsing every 4 seconds", w.drizzle, effect="pulse", period=4),
            legend_item("Drizzle", "Solid green", w.drizzle),
            legend_item("Light freezing drizzle", "Green, fast pulse", w.drizzle, effect="pulse", period=0.5),
            legend_item("Mist", "Dark blue", w.mist),
            legend_item("Light rain", "Blue, pulsing every 4 seconds", w.rain, effect="pulse", period=4),
            legend_item("Rain", "Solid blue", w.rain),
            legend_item("Light freezing rain", "Blue, pulsing every 2 seconds", w.rain, effect="pulse", period=2),
            legend_item("Heavy rain", "Blinking blue", w.rain, effect="blink", period=2),
            legend_item("Thunderstorms", "Blinking yellow", w.lightning, effect="blink", period=2),
            legend_item("Light snow", "White, pulsing every 2 seconds", c[colors_lib.WHITE], effect="pulse", period=2),
            legend_item("Snow", "White, pulsing every second", c[colors_lib.WHITE], effect="pulse", period=1),
            legend_item("Light unknown precipitation", "Blinking light red", c[colors_lib.LIGHT_RED],
                        effect="blink", period=2),
            legend_item("Other / unknown", "Blinking red", c[colors_lib.RED], effect="blink", period=2),
        ]

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

        # -RA = slow pulse 4 sec
        #  RA = solid color
        # +RA = blink color 1 sec

        colors_by_name = colors_lib.get_colors()

        if obs is None or obs == "":
            return Solid(pixel, color=colors_by_name[colors_lib.OFF])
        elif "VCTS" in obs:
            return Blink(pixel, speed=1, color=self.__config__.data.color.weather.lightning)
        elif "TS" in obs:
            return Blink(pixel, speed=1, color=self.__config__.data.color.weather.lightning)
        elif "-FZDZ" in obs:
            return Pulse(pixel, speed=0.1, period=0.5, color=self.__config__.data.color.weather.drizzle)
        elif "-FZRA" in obs:
            return Pulse(pixel, speed=0.1, period=2, color=self.__config__.data.color.weather.rain)
        elif "-SN" in obs:
            return Pulse(pixel, speed=0.1, period=2, color=colors_by_name[colors_lib.WHITE])
        elif "SN" in obs:
            return Pulse(pixel, speed=0.1, period=1, color=colors_by_name[colors_lib.WHITE])
        elif "-RA" in obs:
            return Pulse(pixel, speed=0.1, period=4, color=self.__config__.data.color.weather.rain)
        elif "RA" in obs:
            return Solid(pixel, color=self.__config__.data.color.weather.rain)
        elif "+RA" in obs:
            return Blink(pixel, speed=1, color=self.__config__.data.color.weather.rain)
        elif "-DZ" in obs:
            return Pulse(pixel, speed=0.1, period=4, color=self.__config__.data.color.weather.drizzle)
        elif "DZ" in obs:
            return Solid(pixel, color=self.__config__.data.color.weather.drizzle)
        elif "FG" in obs:
            return Pulse(pixel, speed=0.1, period=4, color=self.__config__.data.color.weather.fog)
        elif "HZ" in obs:
            return Solid(pixel, color=self.__config__.data.color.weather.haze)
        elif "BR" in obs:
            return Solid(pixel, color=self.__config__.data.color.weather.mist)
        elif "-UP" in obs:
            return Blink(pixel, speed=1, color=colors_by_name[colors_lib.LIGHT_RED])
        elif "UP" in obs:
            return Blink(pixel, speed=1, color=colors_by_name[colors_lib.RED])
        else:
            safe_logging.safe_log("[v]missing observation code=" + str(obs))
            return Blink(pixel, speed=1, color=colors_by_name[colors_lib.RED])
