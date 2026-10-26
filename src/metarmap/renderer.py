"""
Drives the LED strip: turns the active visualizer's looks into animations and runs them.
"""
import threading
import traceback

import metarmap.lib.safe_logging as safe_logging
from metarmap.clock import Clock
from metarmap.leds.animations import animation_for
from metarmap.sun import SunTimes, brightness_for
from metarmap.visualizers import visualizer

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
        self._pixels = strip
        # one addressable subset per LED, so each airport gets its own animation
        self._pix = [PixelSubset(strip, i, i + 1) for i in range(len(strip))]
        self._metars = metars
        self._config = config
        self._sun = sun
        self._clock = clock or Clock()
        self._visualizers: list = visualizers
        self._vis = visualizers[0]
        self.active_visualizer: int = 0
        self._looks = []  # one Look per airport, in LED order
        self._strip_look = None  # set instead when one look drives the whole strip
        self._animations = []
        self._animationloop: AnimateOnce = None
        self.last_locate = None  # {"pixel": n, "at": epoch seconds} of the last locate() pulse
        # the main loop and other threads (OLED locate, web) both drive the LEDs; only one at a time
        self._lock = threading.RLock()
        self.adjust_brightness_for_time()
        self.clear()
        self.refresh()

    # ---- looks -> animations ------------------------------------------------------------------------------------

    def _rebuild(self):
        data = self._metars.data
        settings = self._config.data
        strip_look = visualizer.strip_look(self._vis, settings)
        if strip_look is not None:
            looks, animations = [], [animation_for(strip_look, self._pixels)]
        else:
            looks = visualizer.looks(self._vis, [a.code for a in settings.airports], data, settings)
            # an airport list longer than the strip can't be shown; extra airports are ignored
            animations = [animation_for(look, pixel) for look, pixel in zip(looks, self._pix)]
        self._looks, self._strip_look, self._animations = looks, strip_look, animations

    @property
    def looks(self):
        """The current look of each LED, in airport order."""
        return list(self._looks)

    @property
    def strip_look(self):
        return self._strip_look

    @property
    def animations(self):
        return list(self._animations)

    def led_states(self):
        """
        What every LED is doing right now, for the web UI: {pixel: look} plus any look that drives the whole strip.
        """
        leds = {i: look.to_dict() for i, look in enumerate(self._looks)}
        strip = self._strip_look.to_dict() if self._strip_look is not None else None
        return leds, strip

    # ---- running the LEDs -------------------------------------------------------------------------------------

    def render(self):
        try:
            built = self._animations
            animations = AnimateOnce(AnimationGroup(*built), auto_clear=False)
            self._animationloop = animations
            while True:
                # one frame at a time, so locate() can get in between frames
                with self._lock:
                    # rebuilt (new data, visualizer or strip length): the main loop starts the new animations
                    if self._animations is not built or not animations.animate():
                        break
        except Exception as e:
            safe_logging.safe_log("[r]render error: " + str(e))

    def update_data(self, metars):
        safe_logging.safe_log("[r]" + "updating data in the renderer")
        self._metars = metars
        self._rebuild()

    def stop(self):
        if self._animationloop is not None:
            self._animationloop.freeze()

    def resume(self):
        if self._animationloop is not None:
            self._animationloop.resume()

    def resize(self, count):
        """
        Gives the strip `count` LEDs now, if it can change its length (the in-memory strip). A NeoPixel strip can't:
        the new number takes effect after a restart. Returns whether the strip was resized.
        """
        if not callable(getattr(self._pixels, "resize", None)):
            return False
        with self._lock:
            self._pixels.resize(count)
            self._pix = [PixelSubset(self._pixels, i, i + 1) for i in range(len(self._pixels))]
            self._rebuild()
            self.clear()
        return True

    def clear(self):
        self._pixels.fill(self._config.data.color.clear)
        self._pixels.show()

    def animate_once(self, effect, clear=True):
        with self._lock:
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
        if self._vis.EXCLUSIVE:
            return
        try:
            self.last_locate = {"pixel": int(pixnum), "at": self._clock.time()}
            self.animate_once(Pulse(self._pix[int(pixnum)], speed=0.1, period=1, color=WHITE), False)
        except Exception as e:
            safe_logging.safe_log(f"[r]locate {pixnum}: {e}\n{traceback.format_exc()}")

    # ---- visualizers ------------------------------------------------------------------------------------------

    @property
    # returns [number, visualizer]
    def visualizer(self):
        return self.active_visualizer, self._visualizers[self.active_visualizer]

    @property
    def visualizers(self):
        return self._visualizers

    @visualizer.setter
    def visualizer(self, vis):
        self._vis = self._visualizers[vis]
        self.active_visualizer = vis
        self._rebuild()

    def refresh(self):
        self.visualizer = self.active_visualizer

    def visualizer_next(self, skip_exclusive=False):
        total = len(self._visualizers)
        vnum = (self.active_visualizer + 1) % total
        # stop after one lap, in case every visualizer is exclusive
        for _ in range(total):
            if not (skip_exclusive and self._visualizers[vnum].EXCLUSIVE):
                break
            vnum = (vnum + 1) % total
        self.visualizer = vnum

    def visualizer_previous(self):
        self.visualizer = (self.active_visualizer - 1) % len(self._visualizers)

    # ---- brightness -------------------------------------------------------------------------------------------

    def brightness(self, level: float):
        if 0 <= level <= 1:
            self._pixels.brightness = level

    def pixels(self):
        return self._pixels

    @property
    def config(self):
        return self._config

    def brightness_for(self, now):
        """The scheduled LED brightness at `now` (timezone-aware), from today's sun times."""
        return brightness_for(now, self._sun.times, self._config.data.led.brightness)

    def adjust_brightness_for_time(self):
        safe_logging.safe_log("[r]adjust brightness for time")
        self.brightness(self.brightness_for(self._clock.now()))


if __name__ == '__main__':
    print("Renderer")
