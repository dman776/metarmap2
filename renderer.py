"""
Module to handle METAR fetching and processing
"""

import sys
import time
from datetime import datetime
import pytz
from pprint import pprint
import json
import lib.safe_logging as safe_logging
import metar
from lib.config import Config
from lib.utils import wheel
from lib import utils

from adafruit_led_animation.helper import PixelSubset

from adafruit_led_animation.sequence import AnimationSequence, AnimateOnce
from adafruit_led_animation.group import AnimationGroup
from adafruit_led_animation.animation.pulse import Pulse
from adafruit_led_animation.color import WHITE
import adafruit_led_animation.animation


class Renderer(object):
    """
    Object to control and handle a rendering Neopixels
    """
    def __init__(self, pixels, metars: metar.METAR, config: Config, visualizers):
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
        self.__animationloop__: AnimateOnce = None
        self.__visualizers__ = visualizers
        self.__vis__ = visualizers[0]
        self.active_visualizer = 0
        self.adjust_brightness_for_time()
        self.clear()

    def render(self):
        i = 0
        animations = AnimateOnce(
            AnimationGroup(
                *self.__vis__.get_effects()
            ),
            # advance_interval=5,
            auto_clear=False,
        )
        self.__animationloop__ = animations
        while animations.animate():
            pass

    def update_data(self, metars: metar.METAR):
        safe_logging.safe_log("[r]" + "updating data in the renderer")
        self.__data__ = metars.data
        self.__vis__.update_data(self.__data__)

    def clear(self):
        self.__pixels__.fill(self.__config__.data().color.clear)
        self.__pixels__.show()
        return

    def animate_once(self, effect, clear=True):
        if self.__animationloop__ is not None:
            self.__animationloop__.freeze()
        animations = AnimateOnce(effect)
        while animations.animate():
            pass
        if clear:
            self.clear()
        if self.__animationloop__ is not None:
            self.__animationloop__.resume()

    def locate(self, pixnum):
        pix = PixelSubset(self.__pixels__, int(pixnum), int(pixnum) + 1)
        self.animate_once(Pulse(pix, speed=0.1, period=2, color=WHITE), False)

    @property
    # returns [number, visualizer]
    def visualizer(self):
        return self.active_visualizer, self.__visualizers__[self.active_visualizer]

    @visualizer.setter
    def visualizer(self, vis):
        self.__vis__ = self.__visualizers__[vis]
        self.__vis__.update_data(self.__data__)
        self.active_visualizer = vis

    def visualizer_next(self):
        totalnum = len(self.__visualizers__)
        vnum = self.active_visualizer + 1
        if vnum >= totalnum:
            vnum = 0
        self.visualizer = vnum

    def visualizer_previous(self):
        totalnum = len(self.__visualizers__)
        if self.active_visualizer == 0:
            vnum = totalnum - 1
        else:
            vnum = self.active_visualizer - 1
        self.visualizer = vnum

    def brightness(self, level: float):
        if 0 < level <= 1:
            self.__pixels__.brightness = level

    def pixels(self):
        return self.__pixels__

    def adjust_brightness_for_time(self):
        safe_logging.safe_log("[r]adjust brightness for time")
        right_now = datetime.now(pytz.utc)
        (DAWN, SUNRISE, SUNSET, DUSK) = utils.get_sun_times(self.__config__)

        if DAWN < right_now < SUNRISE:
            self.brightness(self.__config__.data().led.brightness.dimmed)
        elif SUNRISE < right_now < SUNSET:
            self.brightness(self.__config__.data().led.brightness.normal)
        elif SUNSET < right_now < DUSK:
            self.brightness(self.__config__.data().led.brightness.dimmed)
        else:
            self.brightness(self.__config__.data().led.brightness.off)


if __name__ == '__main__':
    print("Renderer")
