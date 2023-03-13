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
import neopixel
import board
from visualizers.visualizer import Visualizer

from adafruit_led_animation.animation.blink import Blink
from adafruit_led_animation.animation.pulse import Pulse
from adafruit_led_animation.animation.solid import Solid
from adafruit_led_animation.animation.comet import Comet
from adafruit_led_animation.animation.customcolorchase import CustomColorChase
from adafruit_led_animation.color import PURPLE, WHITE, AMBER, JADE, MAGENTA, ORANGE, BLUE, AQUA, RED, GREEN, YELLOW


class Chase(Visualizer):
    """
    Object to handle a test pattern
    Returns a list of Effects on each pixel
    """

    def __init__(self, data, pix, config):
        super().__init__(data, pix, config)

    @property
    def name(self):
        return "Chase"

    @property
    def description(self):
        return """
            Display a simple chase pattern of LEDS in sequence.
        """

    def update_data(self, data):
        # super().update_data(data)
        self.__effect__.append(Comet(self.__pix__, speed=0.01, color=BLUE, tail_length=10, bounce=True))
