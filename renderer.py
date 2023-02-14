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
from lib.config import Config
from lib.utils import wheel

from adafruit_led_animation.helper import PixelSubset

from adafruit_led_animation.sequence import AnimationSequence, AnimateOnce
from adafruit_led_animation.group import AnimationGroup

from visualizers.flightcategory import FlightCategory as FlightCategoryVisualizer

class Renderer(object):
    """
    Object to control and handle a rendering Neopixels
    """

    def render(self):
        i = 0
        # visualizer = FlightCategoryVisualizer(self.__stations__, self.__data__, self.__pix__, self.__config__)
        animations = AnimateOnce(
            AnimationGroup(
                *self.__vis__.get_effects()
            ),
            # advance_interval=5,
            auto_clear=False,
        )
        while animations.animate():
            pass

    def update_data(self, metars: metar.METAR):
        safe_logging.safe_log("updating data in the renderer")
        self.__data__ = metars.data
        return

    def clear(self):
        self.__pixels__.fill(self.__config__.data().color.clear)
        self.__pixels__.show()
        return

    def animate_once(self, effect, clear=True):
        # rc = RainbowChase(self.__pixels__, speed=0.1, size=4, spacing=2, step=8)
        animations = AnimateOnce(effect)
        while animations.animate():
            pass
        if clear: self.clear()

    @property
    def visualizer(self):
        return self.__vis__

    @visualizer.setter
    def visualizer(self, vis):
        self.__vis__ = vis

    def pixels(self):
        return self.__pixels__

    def __init__(self, pixels, metars: metar.METAR, config: Config):
        """
        Creates a new renderer
        """

        self.__pixels__ = pixels
        self.__stations__ = metars.stations()   # list of station ids
        self.__data__ = metars.data             # all METAR data
        self.__config__ = config
        # self.windCycle = False
        self.numAirports = len(self.__stations__)
        self.__pix__ = []                       # individual pixel submap - used to address one pixel for effects
        # self.__effect__ = []                    # individual pixel effects - actual effects to be applied to a pixel
        self.__vis__ = None
        # self.flight_category_colors = []
        self.clear()
        # displayTime = 0.0
        # displayAirportCounter = 0


if __name__ == '__main__':
    print("Renderer")
