"""
Module to handle a rainbow pattern
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
from adafruit_led_animation.animation.rainbow import Rainbow


class Rainbow1(Visualizer):
    """
    Object to handle a test pattern
    Returns a list of Effects on each pixel
    """

    def __init__(self, data, pix, config):
        super().__init__(data, pix, config)
        self.__exclusive__ = True

    @property
    def name(self):
        return "Rainbow"

    @property
    def description(self):
        return "Display a rainbow pattern across all of the LEDS."

    @property
    def legend(self):
        c = colors_lib.get_colors()
        return [
            legend_item("All LEDs", "Cycle through the colors of the rainbow",
                        *(c[n] for n in (colors_lib.RED, colors_lib.ORANGE, colors_lib.YELLOW,
                                         colors_lib.GREEN, colors_lib.BLUE, colors_lib.PURPLE))),
        ]

    def update_data(self, data):
        # super().update_data(data)
        self.__effect__.clear()
        self.__effect__.append(Rainbow(self.__pix__, period=5, speed=0.1, precompute_rainbow=True))
