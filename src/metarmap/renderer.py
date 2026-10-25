"""
Drives the LED strip: turns the active visualizer's looks into animations and runs them.
"""
import threading
import traceback

import metarmap.lib.safe_logging as safe_logging
from metarmap.clock import Clock
from metarmap.leds.animations import animation_for
from metarmap.sun import SunTimes, brightness_for

from adafruit_led_animation.sequence import AnimateOnce
from adafruit_led_animation.group import AnimationGroup
from adafruit_led_animation.helper import PixelSubset
from adafruit_led_animation.animation.pulse import Pulse
from adafruit_led_animation.color import WHITE


class Renderer(object):
    """
    Runs the LED animations for the active visualizer.

    strip: a NeoPixel strip or metarmap.leds.strip.FakeStrip
    metars: anything with a .data dict of airport -> METAR (metar.METAR)
    config: settings, including the airport on each LED (config.data.airports)
    sun: today's sun times, for the scheduled brightness
    """
    def __init__(self, strip, metars, config, visualizers, sun: SunTimes, clock: Clock = None):
        self.__pixels__ = strip
        # one addressable subset per LED, so each airport gets its own animation
        self.__pix__ = [PixelSubset(strip, i, i + 1) for i in range(len(strip))]
        self.__metars__ = metars
        self.__config__ = config
        self.__sun__ = sun
        self.__clock__ = clock or Clock()
        self.__visualizers__: list = visualizers
        self.__vis__ = visualizers[0]
        self.active_visualizer: int = 0
        self.__looks__ = []  # one Look per airport, in LED order
        self.__strip_look__ = None  # set instead when one look drives the whole strip
        self.__animations__ = []
        self.__animationloop__: AnimateOnce = None
        self.last_locate = None  # {"pixel": n, "at": epoch seconds} of the last locate() pulse
        # the main loop and other threads (OLED locate, web) both drive the LEDs; only one at a time
        self.__lock__ = threading.RLock()
        self.adjust_brightness_for_time()
        self.clear()
        self.refresh()

    # ---- looks -> animations ------------------------------------------------------------------------------------

    def __rebuild__(self):
        data = self.__metars__.data
        strip_look = self.__vis__.strip_look()
        if strip_look is not None:
            looks, animations = [], [animation_for(strip_look, self.__pixels__)]
        else:
            looks = self.__vis__.looks([a.code for a in self.__config__.data.airports], data)
            # an airport list longer than the strip can't be shown; extra airports are ignored
            animations = [animation_for(look, pixel) for look, pixel in zip(looks, self.__pix__)]
        self.__looks__, self.__strip_look__, self.__animations__ = looks, strip_look, animations

    @property
    def looks(self):
        """The current look of each LED, in airport order."""
        return list(self.__looks__)

    @property
    def strip_look(self):
        return self.__strip_look__

    @property
    def animations(self):
        return list(self.__animations__)

    def led_states(self):
        """
        What every LED is doing right now, for the web UI: {pixel: look} plus any look that drives the whole strip.
        """
        leds = {i: look.to_dict() for i, look in enumerate(self.__looks__)}
        strip = self.__strip_look__.to_dict() if self.__strip_look__ is not None else None
        return leds, strip

    # ---- running the LEDs -------------------------------------------------------------------------------------

    def render(self):
        try:
            animations = AnimateOnce(AnimationGroup(*self.__animations__), auto_clear=False)
            self.__animationloop__ = animations
            while True:
                # one frame at a time, so locate() can get in between frames
                with self.__lock__:
                    if not animations.animate():
                        break
        except Exception as e:
            safe_logging.safe_log("[r]render error: " + str(e))

    def update_data(self, metars):
        safe_logging.safe_log("[r]" + "updating data in the renderer")
        self.__metars__ = metars
        self.__rebuild__()

    def stop(self):
        if self.__animationloop__ is not None:
            self.__animationloop__.freeze()

    def resume(self):
        if self.__animationloop__ is not None:
            self.__animationloop__.resume()

    def clear(self):
        self.__pixels__.fill(self.__config__.data.color.clear)
        self.__pixels__.show()

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
        """Pulses one LED white (ignored while an exclusive visualizer is running)."""
        if self.__vis__.exclusive:
            return
        try:
            self.last_locate = {"pixel": int(pixnum), "at": self.__clock__.time()}
            self.animate_once(Pulse(self.__pix__[int(pixnum)], speed=0.1, period=1, color=WHITE), False)
        except Exception as e:
            safe_logging.safe_log(f"[r]locate {pixnum}: {e}\n{traceback.format_exc()}")

    # ---- visualizers ------------------------------------------------------------------------------------------

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
        self.active_visualizer = vis
        self.__rebuild__()

    def refresh(self):
        self.visualizer = self.active_visualizer

    def visualizer_next(self, skip_exclusive=False):
        total = len(self.__visualizers__)
        vnum = (self.active_visualizer + 1) % total
        # stop after one lap, in case every visualizer is exclusive
        for _ in range(total):
            if not (skip_exclusive and self.__visualizers__[vnum].exclusive):
                break
            vnum = (vnum + 1) % total
        self.visualizer = vnum

    def visualizer_previous(self):
        self.visualizer = (self.active_visualizer - 1) % len(self.__visualizers__)

    # ---- brightness -------------------------------------------------------------------------------------------

    def brightness(self, level: float):
        if 0 <= level <= 1:
            self.__pixels__.brightness = level

    def pixels(self):
        return self.__pixels__

    @property
    def config(self):
        return self.__config__

    def brightness_for(self, now):
        """The scheduled LED brightness at `now` (timezone-aware), from today's sun times."""
        return brightness_for(now, self.__sun__.times, self.__config__.data.led.brightness)

    def adjust_brightness_for_time(self):
        safe_logging.safe_log("[r]adjust brightness for time")
        self.brightness(self.brightness_for(self.__clock__.now()))


if __name__ == '__main__':
    print("Renderer")
