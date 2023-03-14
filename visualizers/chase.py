"""
Module to handle a chase pattern (for testing and setup)
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
from visualizers.visualizer import Visualizer
from adafruit_led_animation.animation.chase import Chase


class ChaseTest(Visualizer):
    """
    Object to handle a test pattern
    Returns a list of Effects on each pixel
    """

    def __init__(self, data, pix, config):
        super().__init__(data, pix, config)
        self.__exclusive__ = True

    @property
    def name(self):
        return "Chase"

    @property
    def description(self):
        return """
            Display a simple chase pattern of BLUE LEDS in sequence.
            <div class="w-100">
            This visualizer WILL run for ONE COMPLETE animation cycle. (ie. ALL 50 LEDS), then repeat.
            </div>
        """

    def update_data(self, data):
        self.__effect__.clear()
        self.__effect__.append(Chase(self.__pix__, speed=0.1, size=1, spacing=49, color=[0, 0, 255]))
