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
        self.__config__ = config
        self.__data__ = data
        self.__device__ = screen
        self.__renderer__ = renderer
        self.__clock__ = clock or Clock()
        self.__tz__ = tz or self.__local_timezone__()
        self.lock = threading.Lock()  # drawing; message() and the loop both draw
        self.event = threading.Event()
        self.__thread__ = self.__new_thread__()
        self.__screen__ = None  # what is on the OLED right now (mirrored by the web UI)
        self.last_change = self.__clock__.time()  # when the loop last moved on; used by the watchdog

    def __local_timezone__(self):
        location = utils.get_location(self.__config__.data.geo.city)
        return timezone(location.timezone) if location else pytz.utc

    def __new_thread__(self):
        return threading.Thread(target=self.loop, args=(self.event,), name="display", daemon=True)

    @property
    def screen(self) -> Optional[dict]:
        return self.__screen__

    def is_alive(self):
        return self.__thread__.is_alive()

    def start(self):
        self.last_change = self.__clock__.time()
        self.__thread__.start()

    def stop(self, clear=True):
        self.event.set()
        if clear:
            self.__device__.clear()
            self.__screen__ = None

    def restart(self, timeout=None):
        """
        Stops the loop thread and starts a new one. With a timeout, a thread that doesn't stop in time
        (e.g. stuck in an I2C write) is abandoned: it has its own stop event, so it can't fight the new one.
        A loop that was never started is left for start() (the web server starts first).
        """
        if self.__thread__.ident is None:
            return
        self.stop(False)
        self.__thread__.join(timeout)
        if self.__thread__.is_alive():
            safe_log("[d]display thread did not stop; starting a new one anyway")
        self.event = threading.Event()
        self.__thread__ = self.__new_thread__()
        self.start()

    def stalled(self) -> Optional[str]:
        """Why the loop needs a restart (it died, or hasn't moved on for too long), or None if it's fine."""
        if not self.is_alive():
            return "thread is not running"
        idle = self.__clock__.time() - self.last_change
        if idle > watchdog_limit(self.__config__.data.display_screen.delay):
            return f"no new page for {idle:.0f}s"
        return None

    # ---- the loop ----------------------------------------------------------------------------------------------

    def loop(self, event):
        while not event.is_set():
            # a fresh copy each pass: airports can be edited while the loop runs
            airports = airports_to_show(self.__config__.airports)
            for pixel, airport in airports:
                if event.is_set():
                    return
                if self.__renderer__ is not None and self.__config__.data.display_screen.locate_active:
                    try:
                        self.__renderer__.locate(pixel)
                    except Exception as e:
                        # a failed LED pulse shouldn't cost the airport its pages
                        safe_log(f"[d]locate {airport}: {e}")
                try:
                    self.show_airport(airport, self.__data__.data.get(airport) or {},
                                      self.__config__.data.display_screen.delay, event)
                except Exception as e:
                    # never let one airport stop the loop
                    safe_log(f"[d]loop: {airport}: {e}\n{traceback.format_exc()}")
                    self.__clock__.wait(event, 1)
            if not airports:
                self.last_change = self.__clock__.time()
                self.__clock__.wait(event, 5)  # nothing to show; don't spin

    def show_airport(self, airport, metar, delay, event):
        for page in pages_for(metar):
            if not self.show_page(screen_for(airport, metar, page, self.__tz__), delay, event):
                return

    def show_page(self, screen, delay, event):
        """
        Draws one page, then waits. The lock is only held while drawing, so message() isn't blocked.
        Returns False if the loop was stopped.
        """
        with self.lock:
            if event.is_set():
                return False
            self.__draw__(screen)
        self.last_change = self.__clock__.time()
        return not self.__clock__.wait(event, delay)

    def message(self, title, icon="", line1="", line2="", line3=""):
        """Shows a message, e.g. message("MAP", "info", "Starting..")."""
        with self.lock:
            self.__draw__(message_screen(title, icon, line1, line2, line3))

    def __draw__(self, screen):
        try:
            self.__device__.show(screen)
            self.__screen__ = screen
        except Exception as e:
            # e.g. an I2C error; keep going with the next page
            safe_log(f"[d]draw {screen.get('title')}: {e}")
