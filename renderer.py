"""
Module to handle METAR fetching and processing
"""

import threading
import time
import traceback
from datetime import datetime
import pytz
import lib.safe_logging as safe_logging
import lib.colors as colors_lib
import metar
try:
    from config import Config
except ImportError:
    pass

from adafruit_led_animation.sequence import AnimateOnce
from adafruit_led_animation.group import AnimationGroup
from adafruit_led_animation.animation.pulse import Pulse
from adafruit_led_animation.color import WHITE


def describe_effect(effect):
    """
    Describes one LED animation so the web UI can replay it.
    Returns the pixels it drives (None = the whole strip) and how it looks.
    """
    kind = type(effect).__name__
    ranges = getattr(effect.pixel_object, "_ranges", None)
    pixels = [r[0] for r in ranges] if ranges else None

    def css(colors):
        return [colors_lib.to_css(c) for c in colors if c is not None]

    speed = effect.speed
    if kind == "Solid":
        look = {"effect": "solid", "colors": css([effect.color])}
    elif kind == "Blink":
        look = {"effect": "blink", "colors": css([effect.colors[0]]), "period": speed * 2}
    elif kind == "Pulse":
        look = {"effect": "pulse", "colors": css([effect.color]), "period": effect._period}
    elif kind == "ColorCycle":
        look = {"effect": "cycle", "colors": css(effect.colors), "step": speed}
    elif kind == "Rainbow":
        look = {"effect": "rainbow", "colors": [], "period": effect._period}
    elif kind == "Chase":
        look = {"effect": "chase", "colors": css([effect.color]), "step": speed,
                "size": effect._size, "spacing": effect._spacing}
    else:
        look = {"effect": "solid", "colors": css([effect.color])}
    if look["effect"] == "solid" and look["colors"] == ["#000000"]:
        look = {"effect": "off", "colors": []}
    return pixels, look


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
        self.__pix__ = pixel_subsets  # individual pixel submap - used to address one pixel for effects
        self.__animationloop__: AnimateOnce = None
        self.__visualizers__: list = visualizers
        self.__vis__ = visualizers[0]
        self.active_visualizer: int = 0
        self.last_locate = None  # {"pixel": n, "at": epoch seconds} of the last locate() pulse
        # the main loop and other threads (OLED locate, web) both drive the LEDs; only one at a time
        self.__lock__ = threading.RLock()
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
            while True:
                # one frame at a time, so locate() can get in between frames
                with self.__lock__:
                    if not animations.animate():
                        break
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
        with self.__lock__:
            self.stop()
            try:
                animations = AnimateOnce(effect)
                while animations.animate():
                    pass
                if clear:
                    self.clear()
            finally:
                self.resume()

    def locate(self, pixnum):
        if self.__visualizers__[self.active_visualizer].exclusive:
            return
        try:
            self.last_locate = {"pixel": int(pixnum), "at": time.time()}
            self.animate_once(Pulse(self.__pix__[int(pixnum)], speed=0.1, period=1, color=WHITE), False)
        except Exception as e:
            safe_logging.safe_log(f"[r]locate {pixnum}: {e}\n{traceback.format_exc()}")

    def led_states(self):
        """
        What every LED is doing right now, indexed by pixel, plus any effect that drives the whole strip.
        """
        leds, strip = {}, None
        for effect in self.__vis__.get_effects():
            try:
                pixels, look = describe_effect(effect)
            except Exception as e:
                safe_logging.safe_log("[r]describe effect: " + str(e))
                continue
            if pixels is None:
                strip = look
            else:
                for p in pixels:
                    leds[p] = look
        return leds, strip

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

    def visualizer_next(self, skip_exclusive=False):
        totalnum = len(self.__visualizers__)

        vnum = self.active_visualizer + 1
        if vnum >= totalnum:
            vnum = 0

        while skip_exclusive and self.__visualizers__[vnum].exclusive:
            vnum += 1
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
            'dawn': (self.__config__.suntimes['dawn'], self.__config__.suntimes['sunrise'],
                     self.__config__.data.led.brightness.dimmed),
            'daytime': (self.__config__.suntimes['sunrise'], self.__config__.suntimes['sunset'],
                        self.__config__.data.led.brightness.normal),
            'dusk': (self.__config__.suntimes['sunset'], self.__config__.suntimes['dusk'],
                     self.__config__.data.led.brightness.dimmed),
            'night': (
            self.__config__.suntimes['dusk'], self.__config__.suntimes['dawn'], self.__config__.data.led.brightness.off)
        }
        for name, (start, end, level) in time_ranges.items():
            if start < right_now < end:
                self.brightness(level)
                return
        # if current time doesn't fall within any time range, turn off the LED
        self.brightness(self.__config__.data.led.brightness.off)


if __name__ == '__main__':
    print("Renderer")
