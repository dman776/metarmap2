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
from adafruit_led_animation.animation.blink import Blink
from adafruit_led_animation.animation.pulse import Pulse
from adafruit_led_animation.animation.solid import Solid
from adafruit_led_animation.animation.colorcycle import ColorCycle
from adafruit_led_animation.animation.rainbowchase import RainbowChase
from adafruit_led_animation.animation.rainbowcomet import RainbowComet
from adafruit_led_animation.sequence import AnimationSequence, AnimateOnce
from adafruit_led_animation.group import AnimationGroup

from visualizers.flightcategory import FlightCategory as FlightCategoryVisualizer

class Renderer(object):
    """
    Object to control and handle a rendering Neopixels
    """

    def render(self):
        i = 0
        visualizer = FlightCategoryVisualizer(self.__stations__, self.__data__, self.__pix__)
        animations = AnimateOnce(
            AnimationGroup(
                *visualizer.get_effects()
            ),
            # advance_interval=5,
            auto_clear=False,
        )
        while animations.animate():
            pass




    def clear(self):
        self.__pixels__.fill(self.__config__.data().color.clear)
        self.__pixels__.show()
        return

    def test(self):
        # rc = RainbowChase(self.__pixels__, speed=0.1, size=4, spacing=2, step=8)
        rc = RainbowComet(self.__pixels__, speed=0.1, tail_length=7, bounce=True)
        animations = AnimateOnce(rc)
        while animations.animate():
            pass
        self.clear()

    def init_pixel_subsets(self):
        for i in range(0, 49):
            self.__pix__.append(PixelSubset(self.__pixels__, i, i + 1))

    def __init__(self, pixels, metars: metar.METAR, config: Config):
        """
        Creates a new renderer
        """

        self.__pixels__ = pixels
        self.__stations__ = metars.stations()   # list of station ids
        self.__data__ = metars.data             # all METAR data
        self.__config__ = config
        self.windCycle = False
        self.numAirports = len(self.__stations__)
        self.__pix__ = []                       # individual pixel submap - used to address one pixel for effects
        self.__effect__ = []                    # individual pixel effects - actual effects to be applied to a pixel

        self.flight_category_colors = []

        self.init_pixel_subsets()
        self.clear()
        # displayTime = 0.0
        # displayAirportCounter = 0


if __name__ == '__main__':
    print("Renderer")
