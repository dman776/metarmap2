"""
Drives the LED strip: turns the active visualizer's looks into animations and runs them.
"""

import logging
import threading
import time
from contextlib import contextmanager

import metarmap.lib.colors as colors_lib
from metarmap.clock import Clock
from metarmap.leds import intro
from metarmap.leds.animations import animation_for, look_interval
from metarmap.models import Look
from metarmap.sun import SunTimes, brightness_for, level_at, quiet_hours_active
from metarmap.visualizers import index_of, visualizer

from adafruit_led_animation.sequence import AnimateOnce
from adafruit_led_animation.helper import PixelSubset
from adafruit_led_animation.animation.pulse import Pulse
from adafruit_led_animation.animation.rainbowcomet import RainbowComet
from adafruit_led_animation.color import WHITE

try:  # the animations' own clock, so "when it's next due" and "now" agree
    from adafruit_led_animation import monotonic_ms
except ImportError:  # an older library

    def monotonic_ms():
        return time.monotonic_ns() // 1_000_000


log = logging.getLogger(__name__)

# The animations decide when each effect moves on (the fastest changes every 0.1 s). Between frames the loop sleeps
# until the first of them is next due, instead of asking them "is it time yet?" many times a second.
FRAME_SECONDS = 0.01
MAX_FRAME_SECONDS = 0.05  # frame_seconds() at most
SLICE_SECONDS = 0.05  # the longest single sleep, so a change (brightness, locate, new data) still shows at once
IDLE_SECONDS = 0.5  # a frame at least this often, so the strip's resend (leds/strip.py) still runs on a still map
RENDER_SECONDS = 1.0  # render() returns after about this long, so the main loop's scheduled jobs run on time

INTRO_FRAME_SECONDS = 0.02  # a startup sequence's frames: 50 a second is smooth, and leaves the Pi time to spare
DIM_FACTOR = 0.5  # how bright the LEDs are while METARs are fetched, as a part of their brightness
DIM_SECONDS = 1  # the shortest dim, so a quick fetch still shows
FADE_SECONDS = 0.6  # the dim fades down and back up over this long, rather than cutting
FADE_STEPS = 12  # at most; about 20 a second
# the Pi's NeoPixel library ignores a brightness change smaller than 0.001, so each fade step is at least this big
# (at night, 1% brightness, that means fewer, larger steps; otherwise steps would be dropped and the level drift)
FADE_MIN_STEP = 0.0011


def frame_due(animations, window=0):
    """
    When to draw the next frame of `animations`, in the LED library's monotonic_ms: the last time any of them that
    isn't frozen is next due within `window` ms of the first one, so LEDs due at nearly the same time (a few ms
    apart, from how long each frame took) share a frame and stay together. With no window, when the first is due.
    None if none is running. Raises LookupError if one doesn't say (Animation._next_update: another version of the
    library).
    """
    dues = []
    for animation in animations:
        if getattr(animation, "_paused", False):
            continue
        at = getattr(animation, "_next_update", None)
        if isinstance(at, bool) or not isinstance(at, (int, float)):
            raise LookupError(f"{type(animation).__name__} has no _next_update")
        dues.append(at)
    if not dues:
        return None
    first = min(dues)
    return max(at for at in dues if at <= first + window)


class Renderer:
    """
    Runs the LED animations for the active visualizer.

    strip: a NeoPixel strip or metarmap.leds.strip.FakeStrip
    metars: anything with a .data dict of airport -> Report or None (metar.Reports)
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
        self._frozen = None  # the animations stop() froze, until resume()
        # (animations, monotonic_ms) when render() draws the next frame of those animations; other ones draw at once
        self._next_frame = (None, 0)
        # set (never waited on) when the strip must be drawn at once: a brightness change, resume() after locate()
        self._wake = threading.Event()
        self._warned = False  # logged that the animations don't say when they're next due
        self.last_locate = None  # {"pixel": n, "at": epoch seconds} of the last locate() pulse
        self._subscribers = []  # called when the visualizer changes: see subscribe()
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
            # the virtual airports (after led.count) have no LED; their looks are for the web map. A strip still
            # longer than led.count (a NeoPixel strip until the restart) keeps its extra LEDs dark
            animations = [animation_for(look, pixel) for look, pixel in zip(looks[: settings.led.count], self._pix)]
        self._looks, self._strip_look, self._animations = looks, strip_look, animations
        self._started = self._clock.time()  # the steps of a stepping visualizer count from here (step())
        self._look_dicts = None  # led_states()'s cache

    @property
    def looks(self):
        """The current look of each LED, in airport order."""
        return list(self._looks)

    def legend_in_use(self):
        """The keys of the active visualizer's legend entries the LEDs show now (virtual airports too); None while one
        look drives the whole strip."""
        return visualizer.in_use(self._vis, self._looks, self._config.data)

    def legend(self):
        """The active visualizer's legend, each entry with inUse: whether an LED shows it now (always, for a whole
        strip look, and for every entry while nothing is shown, e.g. no airports)."""
        used = self.legend_in_use()
        items = visualizer.legend(self._vis, self._config.data)
        return [{**item, "inUse": not used or item["key"] in used} for item in items]

    def step(self):
        """
        Which step a stepping visualizer (Visualizer.steps: Flight Category Forecast) is on now, as {"labels": [...],
        "index": n}, counted from when the LEDs were last built; None for any other visualizer.
        """
        if self._vis.steps is None or self._vis.look is None:
            return None
        steps = self._vis.steps(self._config.data)
        seconds = steps["seconds"]
        elapsed = max(0.0, self._clock.time() - self._started)
        index = int((elapsed % (len(steps["labels"]) * seconds)) // seconds)
        return {"labels": steps["labels"], "index": index, "prefix": steps.get("prefix", "")}

    @property
    def strip_look(self):
        return self._strip_look

    @property
    def animations(self):
        return list(self._animations)

    def led_states(self):
        """
        What every LED is doing right now, for the web UI: {pixel: look} plus any look that drives the whole strip.
        While one does, the virtual airports get their own look: the strip's (rainbow) or off (chase, a wiring check).
        """
        # converted once per rebuild, not at every poll of every open page: a stepping look has ~140 colors per LED
        # (Flight Category Forecast), which pegged a Pi's CPU
        if self._look_dicts is None:
            self._look_dicts = (
                [look.to_dict() for look in self._looks],
                self._strip_look.to_dict() if self._strip_look is not None else None,
            )
        looks, strip = self._look_dicts
        leds = dict(enumerate(looks))
        if self._strip_look is not None:
            settings = self._config.data
            virtual = strip if self._vis.covers_virtual else Look.off().to_dict()
            leds.update({i: virtual for i in range(settings.led.count, len(settings.airports))})
        return leds, strip

    # ---- running the LEDs -------------------------------------------------------------------------------------

    def draw_frame(self):
        """
        Draws the visualizer's first frame at once. At startup the LEDs then show it before the OLED loop's first
        locate() pulse (otherwise the pulse comes first and the visualizer only after it).
        """
        try:
            with self._lock:
                for animation in self._animations:
                    animation.animate(show=False)
                self._pixels.show()
        except Exception as e:
            log.warning("draw_frame error: " + str(e))

    def frame_seconds(self):
        """
        The shortest gap between two frames. A whole-strip look (Rainbow, Chase) is one animation, cheap to run, so it
        gets FRAME_SECONDS: a later frame makes its steps uneven (stutter). Looks per LED are one animation each, 50
        of them: an eighth of the shortest step of those, within FRAME_SECONDS and MAX_FRAME_SECONDS, so LEDs due at
        nearly the same time are drawn in one frame (100 frames a second for a look that changes every 0.2 s kept a
        Pi's CPU at 100% with Flight Category Forecast). MAX_FRAME_SECONDS when nothing moves (every look solid or off).
        It's also the steady tick if the animations can't say when they're next due (another library version).
        """
        if self._strip_look is not None:
            return FRAME_SECONDS
        steps = [look_interval(look) for look in self._looks]
        steps = [step for step in steps if step]
        return min(MAX_FRAME_SECONDS, max(FRAME_SECONDS, min(steps) / 8)) if steps else MAX_FRAME_SECONDS

    def render(self):
        """
        Runs the active visualizer's animations for about RENDER_SECONDS, then returns, so the main loop runs its
        scheduled jobs on time (and calls render() again). The animations keep their place in between: a fade or a
        forecast goes on where it was. Between frames it sleeps until the first animation is next due, in slices of
        at most SLICE_SECONDS, so new animations (new data, visualizer or strip length), a brightness change or the
        end of a locate() pulse reach the LEDs at once.
        """
        try:
            built = self._animations
            tick = self.frame_seconds()
            until = monotonic_ms() + RENDER_SECONDS * 1000
            while self._rest(built, until):
                with self._lock:  # one frame at a time, so locate() and the web UI can get in between frames
                    if self._animations is not built:
                        break  # rebuilt: the main loop starts the new animations
                    self._wake.clear()
                    for animation in built:  # each draws into the strip's buffer if it's due...
                        animation.animate(show=False)
                    self._pixels.show()  # ...and the strip is sent once per frame
                    self._next_frame = (built, self._next_frame_at(built, tick))
        except Exception as e:
            log.warning("render error: " + str(e))
            time.sleep(FRAME_SECONDS)  # the main loop calls render() again at once: no hot loop of errors

    def _rest(self, built, until):
        """
        Sleeps (outside the lock) until the next frame of `built` is due: True. False, at once, when the animations
        were rebuilt or it's `until` (monotonic_ms), for render() to return. Never sleeps more than SLICE_SECONDS at a
        time: no Event.wait(timeout), which on the Pi's Python 3.9 follows the wall clock, and that can jump (NTP).
        """
        while True:
            if self._animations is not built:
                return False
            now = monotonic_ms()
            if now >= until:
                return False
            frame_of, at = self._next_frame
            if frame_of is not built or self._wake.is_set() or now >= at:
                return True
            time.sleep(min(SLICE_SECONDS, (min(at, until) - now) / 1000))

    def _next_frame_at(self, built, tick):
        """
        When (monotonic_ms) to draw the next frame: when the first animation is next due, or the last of those due
        within `tick` (frame_seconds()) of it, so LEDs due at nearly the same time share one frame (frame_due()); at
        least `tick` after this frame and at most IDLE_SECONDS after it. While the strip settles after a change
        (SkipUnchangedShow.settling(): it's sent at every frame for a moment, e.g. each step of a forecast fade) every
        `tick`, as before.
        """
        now = monotonic_ms()
        soonest, latest = now + tick * 1000, now + IDLE_SECONDS * 1000
        try:
            due = frame_due(built, window=tick * 1000)
        except LookupError as e:
            if not self._warned:
                self._warned = True
                log.warning(f"the LED animations don't say when they're next due ({e}): rendering at a steady tick")
            due = soonest
        at = latest if due is None else max(soonest, due)
        settling = getattr(self._pixels, "settling", None)
        if callable(settling) and settling():
            at = min(at, soonest)
        return min(at, latest)

    def update_data(self, metars):
        log.info("updating data in the renderer")
        self._metars = metars
        self._rebuild()

    def stop(self):
        """Freezes the animations, e.g. while a locate() pulse or a startup sequence has the strip."""
        with self._lock:
            if self._frozen is None:
                self._frozen = self._animations
                for animation in self._frozen:
                    animation.freeze()

    def resume(self):
        """Lets the animations stop() froze go on, and draws them at once."""
        with self._lock:
            if self._frozen is not None:
                for animation in self._frozen:
                    animation.resume()
                self._frozen = None
            self._wake.set()

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
        self._pixels.fill(colors_lib.color(colors_lib.OFF))
        self._pixels.show()

    def animate_once(self, effect, clear=True):
        with self._lock:
            self.stop()
            try:
                animations = AnimateOnce(effect)
                while animations.animate():
                    time.sleep(FRAME_SECONDS)
                if clear:
                    self.clear()
            finally:
                self.resume()

    def locate(self, pixnum):
        """
        Pulses one LED white (ignored while an exclusive visualizer is running). A virtual airport has no LED: only
        the web map pulses it (from last_locate).
        """
        if self._vis.exclusive:
            return
        try:
            self.last_locate = {"pixel": int(pixnum), "at": self._clock.time()}
            if int(pixnum) >= self._config.data.led.count:
                return
            self.animate_once(Pulse(self._pix[int(pixnum)], speed=0.1, period=1, color=WHITE), False)
        except Exception as e:
            log.exception(f"locate {pixnum}: {e}")

    # ---- visualizers ------------------------------------------------------------------------------------------

    @property
    def visualizer(self):
        """(number, Visualizer) of the one running now."""
        return self.active_visualizer, self._visualizers[self.active_visualizer]

    @property
    def visualizers(self):
        return self._visualizers

    @visualizer.setter
    def visualizer(self, key):
        """Switches to a visualizer by its id ("wind") or number (3, "3"). Raises LookupError if there's none."""
        number = index_of(key, self._visualizers)
        changed = number != self.active_visualizer
        self._vis = self._visualizers[number]
        self.active_visualizer = number
        self._rebuild()
        if changed:
            for callback in list(self._subscribers):
                callback()

    def subscribe(self, callback):
        """
        Calls callback() after the visualizer changes to another one: picked, next, previous or auto-rotate (not
        refresh(), which rebuilds the same one). Runs in the thread that changed it.
        """
        self._subscribers.append(callback)

    def refresh(self):
        self.visualizer = self.active_visualizer

    def visualizer_next(self, skip_exclusive=False, skip=(), skip_dark=False):
        """
        Switches to the next visualizer, leaving out the exclusive ones if skip_exclusive, those whose id is in
        `skip`, and, if skip_dark, those that would leave every LED and virtual airport off (auto-rotate). If there's
        nothing to switch to, the visualizer stays.
        """
        total = len(self._visualizers)
        for step in range(1, total + 1):  # one lap, ending back at the current visualizer
            vnum = (self.active_visualizer + step) % total
            vis = self._visualizers[vnum]
            if (skip_exclusive and vis.exclusive) or vis.id in skip:
                continue
            if skip_dark and vnum != self.active_visualizer and self._dark(vis):
                continue
            self.visualizer = vnum
            return

    def _dark(self, vis):
        """Whether `vis` would show nothing now: every airport's look off (a whole-strip look never is)."""
        settings = self._config.data
        if visualizer.strip_look(vis, settings) is not None:
            return False
        looks = visualizer.looks(vis, [a.code for a in settings.airports], self._metars.data, settings)
        return all(look.effect == "off" for look in looks)

    def visualizer_previous(self):
        self.visualizer = (self.active_visualizer - 1) % len(self._visualizers)

    # ---- brightness -------------------------------------------------------------------------------------------

    def brightness(self, level: float):
        if 0 <= level <= 1:
            with self._lock:  # not in the middle of a frame's send
                self._pixels.brightness = level
                self._wake.set()  # render() sends it at once, not at the next animation's step

    @contextmanager
    def dimmed(self):
        """
        Dims the LEDs while the block runs (a METAR fetch), when led.dim_on_refresh is on: a short fade down, and
        back up afterwards, unless something else changed the brightness meanwhile (the web UI, the brightness
        schedule).
        """
        if not self._config.data.led.dim_on_refresh:
            yield
            return
        normal = self._pixels.brightness
        dim = self._fade(normal, normal * DIM_FACTOR)
        started = self._clock.time()
        try:
            yield
        finally:
            if dim is not None:
                self._clock.wait(threading.Event(), DIM_SECONDS - (self._clock.time() - started))
                self._fade(dim, normal)

    def _fade(self, start, end):
        """
        Steps the brightness from `start` to `end` over FADE_SECONDS. Stops if something else changes it meanwhile.
        Returns the brightness it ended at (what the strip reports), or None if it stopped.
        """
        steps = max(1, min(FADE_STEPS, int(abs(end - start) / FADE_MIN_STEP)))
        level = start
        for n in range(1, steps + 1):
            with self._lock:
                if self._pixels.brightness != level:
                    return None  # changed by someone else: theirs wins
                self._pixels.brightness = start + (end - start) * n / steps if n < steps else end
                self._pixels.show()
                self._wake.set()  # and render() draws frames again, for the strip's settling resends of the change
                level = self._pixels.brightness
            if n < steps:
                self._clock.wait(threading.Event(), FADE_SECONDS / steps)
        return level

    def pixels(self):
        return self._pixels

    @property
    def config(self):
        return self._config

    def quiet_hours_active(self):
        """Whether the current local time is inside the quiet-hours window."""
        return quiet_hours_active(self._clock.now(), self._config.data.led.quiet_hours)

    def brightness_for(self, now):
        """The scheduled LED brightness at `now` (timezone-aware), from today's sun times."""
        if quiet_hours_active(now, self._config.data.led.quiet_hours):
            return 0.0
        return brightness_for(now, self._sun.times, self._config.data.led.brightness)

    def scheduled_level(self):
        """Which led.brightness setting is in use now: "normal", "dimmed" or "off"."""
        return level_at(self._clock.now(), self._sun.times)

    def adjust_brightness_for_time(self):
        log.info("adjust brightness for time")
        self.brightness(self.brightness_for(self._clock.now()))

    def test_pattern(self):
        """
        The startup sequence (led.init_sequence), once: at startup with led.inittest on, when it's turned on or
        changed, and from the Config page's Play now. Comet is a rainbow along the strip; the others fade each LED
        in to its visualizer color, in an order from where its airport is (leds/intro.py).
        """
        sequence = self._config.data.led.init_sequence
        if sequence == "comet":
            self.animate_once(RainbowComet(self._pixels, speed=0.05, tail_length=5, bounce=False))
        else:
            self.fade_in(sequence)

    def fade_out(self):
        """
        Takes the map dark with the startup sequence (led.init_sequence), when quiet hours begin: the same path, from
        each LED's color to dark (Radar's beam sweeps the colors off clockwise from north). Comet runs the other way
        along the strip and leaves it dark.
        """
        sequence = self._config.data.led.init_sequence
        if sequence == "comet":
            self.animate_once(RainbowComet(self._pixels, speed=0.05, tail_length=5, reverse=True, bounce=False))
            return
        count = min(self._config.data.led.count, len(self._pixels))
        with self._lock:
            sources = [tuple(self._pixels[i]) for i in range(count)]  # what each LED shows now
        self._play_sequence(sequence, lambda t, starts: intro.colors_out_at(t, starts, sources))

    def fade_in(self, sequence):
        """
        Fades the LEDs in to the visualizer's colors over intro.SECONDS, each starting when the sequence says. A
        visualizer that drives the whole strip (Rainbow, Chase) fades in white, then starts.
        """
        count = min(self._config.data.led.count, len(self._pixels))
        if self._strip_look is not None:
            targets = [intro.WHITE] * count
        else:
            targets = [intro.target(look) for look in self._looks[:count]]
            targets += [intro.OFF] * (count - len(targets))
        self._play_sequence(sequence, lambda t, starts: intro.colors_at(t, starts, targets))

    def _play_sequence(self, sequence, colors_at):
        """
        Plays a sequence over intro.SECONDS: colors_at(t, starts) gives every LED's color t seconds in, starts being
        when each LED's fade begins (intro.start_times, from where its airport is).
        """
        settings = self._config.data
        count = min(settings.led.count, len(self._pixels))
        codes = [a.code for a in settings.airports[:count]]
        position = getattr(self._metars, "position", None)  # metar.Reports; a test's data may not have it
        positions = [position(code) if code and position else None for code in codes]
        positions += [None] * (count - len(positions))  # LEDs past the airports
        starts = intro.start_times(sequence, positions, settings.led.init_sweep_from)
        never = threading.Event()  # the clock's wait, so a test's fake clock runs it at once
        with self._lock:
            self.stop()
            try:
                begin = self._clock.time()
                while True:
                    t = self._clock.time() - begin
                    for i, color in enumerate(colors_at(t, starts)):
                        self._pixels[i] = color
                    self._pixels.show()
                    if t >= intro.SECONDS:
                        break
                    self._clock.wait(never, INTRO_FRAME_SECONDS)
            finally:
                self.resume()


if __name__ == "__main__":
    print("Renderer")
