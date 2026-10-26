"""
The OLED loop: rotates through the airports set to show on the screen, two pages each.

What each page says comes from metarmap.oled.screens; drawing is done by a screen driver
(metarmap.oled.screen.SSD1306Screen on the Pi, FakeScreen elsewhere).
"""
import threading
import traceback
from typing import Optional

import pytz
from pytz import timezone

from metarmap.config import Config
from metarmap.lib import utils
from metarmap.lib.safe_logging import safe_log
from metarmap.clock import Clock
from metarmap.oled.screens import airports_to_show, message_screen, pages_for, screen_for


def watchdog_limit(delay: float) -> float:
    """Seconds without a new page before the loop counts as stuck: two pages per airport plus the locate pulse."""
    return max(60, 4 * delay + 10)


class Display(object):
    """
    Runs the OLED loop in a background thread.

    config:   config.Config (airports, display settings)
    data:     anything with a .data dict of airport -> METAR (metar.METAR)
    screen:   a screen driver (show(screen), clear())
    renderer: pulses the LED of the airport on screen (display_screen.locate_active); None for no pulse
    """

    def __init__(self, config: Config, data, screen, renderer=None, clock: Clock = None, tz=None):
        self._config = config
        self._data = data
        self._device = screen
        self._renderer = renderer
        self._clock = clock or Clock()
        self._tz = tz or self._local_timezone()
        self.lock = threading.Lock()  # drawing; message() and the loop both draw
        self._restarting = threading.Lock()  # web requests and the watchdog can restart at the same time
        self.event = threading.Event()
        self._thread = self._new_thread()
        self._screen = None  # what is on the OLED right now (mirrored by the web UI)
        self.last_change = self._clock.time()  # when the loop last moved on; used by the watchdog
        self.on = False  # whether the screen should be showing: start()/turn_on() set it, turn_off() clears it

    def _local_timezone(self):
        location = utils.get_location(self._config.data.geo.city)
        return timezone(location.timezone) if location else pytz.utc

    def _new_thread(self):
        return threading.Thread(target=self.loop, args=(self.event,), name="display", daemon=True)

    @property
    def screen(self) -> Optional[dict]:
        return self._screen

    def is_alive(self):
        return self._thread.is_alive()

    def start(self):
        self.on = True
        self.last_change = self._clock.time()
        self._thread.start()

    def stop(self, clear=True):
        self.event.set()
        if clear:
            with self.lock:  # not in the middle of the loop drawing a page
                self._device.clear()
                self._screen = None

    def turn_on(self):
        """Starts the loop if it isn't running (display_screen.enabled turned on, no restart needed)."""
        with self._restarting:
            if self.is_alive() and not self.event.is_set():
                return
            if self._thread.ident is not None:  # an earlier loop that was turned off
                self._thread.join(5)
                self.event = threading.Event()
                self._thread = self._new_thread()
            self.start()

    def turn_off(self):
        """
        Stops the loop and blanks the screen: display_screen.enabled turned off, or the Home page's switch (which
        isn't saved, like the brightness).
        """
        with self._restarting:
            self.on = False
            self.stop(clear=True)

    def restart(self, timeout=None):
        """
        Stops the loop thread and starts a new one. With a timeout, a thread that doesn't stop in time
        (e.g. stuck in an I2C write) is abandoned: it has its own stop event, so it can't fight the new one.
        A loop that was never started is left for start() (the web server starts first), and a screen that's turned
        off stays off.
        """
        with self._restarting:
            if self._thread.ident is None or not self.on or not self._config.data.display_screen.enabled:
                return
            self.stop(False)
            self._thread.join(timeout)
            if self._thread.is_alive():
                safe_log("[d]display thread did not stop; starting a new one anyway")
            self.event = threading.Event()
            self._thread = self._new_thread()
            self.start()

    def stalled(self) -> Optional[str]:
        """Why the loop needs a restart (it died, or hasn't moved on for too long), or None if it's fine."""
        if not self.is_alive():
            return "thread is not running"
        idle = self._clock.time() - self.last_change
        if idle > watchdog_limit(self._config.data.display_screen.delay):
            return f"no new page for {idle:.0f}s"
        return None

    # ---- the loop ----------------------------------------------------------------------------------------------

    def loop(self, event):
        while not event.is_set():
            # a fresh copy each pass: airports can be edited while the loop runs
            airports = airports_to_show(self._config.airports)
            for pixel, airport in airports:
                if event.is_set():
                    return
                if self._renderer is not None and self._config.data.display_screen.locate_active:
                    try:
                        self._renderer.locate(pixel)
                    except Exception as e:
                        # a failed LED pulse shouldn't cost the airport its pages
                        safe_log(f"[d]locate {airport}: {e}")
                try:
                    self.show_airport(airport, self._data.data.get(airport) or {},
                                      self._config.data.display_screen.delay, event)
                except Exception as e:
                    # never let one airport stop the loop
                    safe_log(f"[d]loop: {airport}: {e}\n{traceback.format_exc()}")
                    self._clock.wait(event, 1)
            if not airports:
                self.last_change = self._clock.time()
                self._clock.wait(event, 5)  # nothing to show; don't spin

    def show_airport(self, airport, metar, delay, event):
        for page in pages_for(metar):
            if not self.show_page(screen_for(airport, metar, page, self._tz), delay, event):
                return

    def show_page(self, screen, delay, event):
        """
        Draws one page, then waits. The lock is only held while drawing, so message() isn't blocked.
        Returns False if the loop was stopped.
        """
        with self.lock:
            if event.is_set():
                return False
            self._draw(screen)
        self.last_change = self._clock.time()
        return not self._clock.wait(event, delay)

    def message(self, title, icon="", line1="", line2="", line3=""):
        """Shows a message, e.g. message("MAP", "info", "Starting..")."""
        with self.lock:
            self._draw(message_screen(title, icon, line1, line2, line3))

    def _draw(self, screen):
        try:
            self._device.show(screen)
            self._screen = screen
        except Exception as e:
            # e.g. an I2C error; keep going with the next page
            safe_log(f"[d]draw {screen.get('title')}: {e}")
