"""
Module to handle METAR fetching and processing
"""

from datetime import datetime
import pytz
import lib.safe_logging as safe_logging
import metar
try:
    from config import Config
except ImportError as e:
    pass

from adafruit_led_animation.sequence import AnimateOnce
from adafruit_led_animation.group import AnimationGroup
from adafruit_led_animation.animation.pulse import Pulse
from adafruit_led_animation.color import WHITE


class Renderer(object):
    """
    Object to control and handle a rendering Neopixels
    """
    def __init__(self, pixels, pixel_subsets, metars: metar.METAR, config: Config, visualizers):
        """
        Creates a new renderer
        """
        self.__pixels__ = pixels
        self.__stations__: list = metars.stations()   # list of station ids
        self.__data__: dict = metars.data             # all METAR data
        self.__config__: Config = config
        # self.windCycle = False
        self.numAirports = len(self.__stations__)
        self.__pix__ = pixel_subsets                       # individual pixel submap - used to address one pixel for effects
        self.__animationloop__: AnimateOnce = None
        self.__visualizers__: list = visualizers
        self.__vis__ = visualizers[0]
        self.active_visualizer: int = 0
        self.adjust_brightness_for_time()
        self.clear()

    def render(self):
        # i = 0
        try:
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
        except Exception as e:
            safe_logging.safe_log("[r]render error: " + str(e))

    def update_data(self, metars: metar.METAR):
        safe_logging.safe_log("[r]" + "updating data in the renderer")
        self.__data__ = metars.data
        self.__vis__.update_data(self.__data__)

    def stop(self):
        if self.__animationloop__ is not None:
            self.__animationloop__.freeze()

    def resume(self):
        if self.__animationloop__ is not None:
            self.__animationloop__.resume()

    def clear(self):
        self.__pixels__.fill(self.__config__.data.color.clear)
        self.__pixels__.show()
        return

    def animate_once(self, effect, clear=True):
        self.stop()
        animations = AnimateOnce(effect)
        while animations.animate():
            pass
        if clear:
            self.clear()
        self.resume()

    def locate(self, pixnum):
        if not self.__visualizers__[self.active_visualizer].exclusive:
            self.animate_once(Pulse(self.__pix__[int(pixnum)], speed=0.1, period=1, color=WHITE), False)

    @property
    # returns [number, visualizer]
    def visualizer(self):
        return self.active_visualizer, self.__visualizers__[self.active_visualizer]

    @property
    def visualizers(self):
        return self.__visualizers__

    @visualizer.setter
    def visualizer(self, vis):
        self.__vis__ = self.__visualizers__[vis]
        self.__vis__.update_data(self.__data__)
        self.active_visualizer = vis

    def refresh(self):
        self.visualizer = self.active_visualizer

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
        if 0 <= level <= 1:
            self.__pixels__.brightness = level

    def pixels(self):
        return self.__pixels__

    @property
    def config(self):
        return self.__config__

    def adjust_brightness_for_time(self):
        safe_logging.safe_log("[r]adjust brightness for time")
        right_now = datetime.now(pytz.utc)
        time_ranges = {
            'dawn': (self.__config__.suntimes['dawn'], self.__config__.suntimes['sunrise']),
            'daytime': (self.__config__.suntimes['sunrise'], self.__config__.suntimes['sunset']),
            'dusk': (self.__config__.suntimes['sunset'], self.__config__.suntimes['dusk']),
            'night': (self.__config__.suntimes['dusk'], self.__config__.suntimes['dawn'])
        }
        for name, (start, end) in time_ranges.items():
            if start < right_now < end:
                self.brightness(self.__config__.data.led.brightness[name])
                return
        # if current time doesn't fall within any time range, turn off the LED
        self.brightness(self.__config__.data.led.brightness.off)


if __name__ == '__main__':
    print("Renderer")
