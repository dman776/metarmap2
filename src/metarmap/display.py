"""
The OLED loop: rotates through the airports set to show on the screen, two pages each, or (display_screen.shows
"visualizer") shows the active visualizer's name and icon. During quiet hours (led.quiet_hours) the screen is blank,
like the LEDs.

What each page says comes from metarmap.oled.screens; drawing is done by a screen driver
(metarmap.oled.screen.SSD1306Screen on the Pi, FakeScreen elsewhere).
"""

import logging
import threading
from datetime import timezone
from typing import Optional
from zoneinfo import ZoneInfo

from metarmap.config import Config
from metarmap.sun import get_location, quiet_hours_active
from metarmap.clock import Clock
from metarmap.oled.screens import (
    airports_to_show,
    message_screen,
    pages_for,
    screen_for,
    splash_screen,
    visualizer_screen,
)

log = logging.getLogger(__name__)

# at startup, seconds the LEDs show the visualizer before the first "Highlight active airport" pulse (app.run)
STARTUP_LOCATE_DELAY = 2.0
# at startup, seconds the splash ("MetarMap2" and the logo) stays before the first airport (app.run)
SPLASH_SECONDS = 5.0
# during quiet hours, how often the loop looks whether they're over (well inside the watchdog's 60 s; turning quiet
# hours off or changing them restarts the loop, so that's at once)
QUIET_CHECK_SECONDS = 30
STEP_CHECK_SECONDS = 1  # in Visualizer mode, how often a stepping visualizer's step is looked at


def watchdog_limit(delay: float) -> float:
    """Seconds without a new page before the loop counts as stuck: two pages per airport plus the locate pulse."""
    return max(60, 4 * delay + 10)


class Display:
    """
    Runs the OLED loop in a background thread.

    config:   config.Config (airports, display settings)
    data:     anything with a .data dict of airport -> Report or None (metar.Reports)
    screen:   a screen driver (show(screen), clear())
    renderer: pulses the LED of the airport on screen (display_screen.locate_active), and has the active visualizer
              for Visualizer mode; None for neither
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
        self._locate_delay = 0.0  # seconds the next locate pulse waits (start(locate_delay=...)); then 0
        self.locate_thread: Optional[threading.Thread] = None  # a delayed pulse, waiting or running
        self._hold_until = 0.0  # the splash stays until then (clock time): the loop's first airport waits for it

    def _local_timezone(self):
        location = get_location(self._config.data.geo.city)
        return ZoneInfo(location.timezone) if location else timezone.utc

    def _new_thread(self):
        return threading.Thread(target=self.loop, args=(self.event,), name="display", daemon=True)

    @property
    def screen(self) -> Optional[dict]:
        return self._screen

    def is_alive(self):
        return self._thread.is_alive()

    def start(self, locate_delay: float = 0.0):
        """
        Starts the loop. locate_delay: seconds the first airport's locate pulse waits (on its own thread, so the
        OLED shows the airport at once). At startup that lets the visualizer show first, instead of the pulse
        coming right after the LEDs' first frame, which looks like a glitch.
        """
        self._locate_delay = locate_delay
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
                log.warning("display thread did not stop; starting a new one anyway")
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
        held = self._hold_until - self._clock.time()
        if held > 0 and self._clock.wait(event, held):  # the splash, while the rest of startup goes on
            return
        self._hold_until = 0.0
        if self._config.data.display_screen.shows == "visualizer":
            self.show_visualizer(event)
            return
        while not event.is_set():
            # a fresh copy each pass: airports can be edited while the loop runs
            airports = airports_to_show(self._config.airports)
            for pixel, airport in airports:
                if event.is_set():
                    return
                if self.quiet():
                    if not self._wait_out_quiet_hours(event):
                        return
                    break  # quiet hours are over: from the first airport again
                if self._renderer is not None and self._config.data.display_screen.locate_active:
                    if self._locate_delay > 0:
                        self._locate_later(pixel, airport, self._locate_delay, event)
                    else:
                        self._locate(pixel, airport)
                self._locate_delay = 0.0  # only the first airport's pulse waits
                try:
                    self.show_airport(
                        airport,
                        self._data.data.get(airport),
                        self._config.data.display_screen.delay,
                        event,
                        virtual=pixel >= self._config.data.led.count,
                    )
                except Exception as e:
                    # never let one airport stop the loop
                    log.exception(f"loop: {airport}: {e}")
                    self._clock.wait(event, 1)
            if not airports:
                self.last_change = self._clock.time()
                self._clock.wait(event, 5)  # nothing to show; don't spin

    def show_visualizer(self, event):
        """
        Visualizer mode: the active visualizer's short name and icon, until the loop stops. A change of visualizer
        restarts the loop (visualizer_changed()), so it's drawn at once; it's also looked at every
        QUIET_CHECK_SECONDS, with quiet hours. No locate pulses: no airport is on the screen.
        """
        while not event.is_set():
            if self.quiet():
                if not self._wait_out_quiet_hours(event):
                    return
                continue
            screen = self.visualizer_screen()
            if screen != self._screen:
                with self.lock:
                    if event.is_set():
                        return
                    self._draw(screen)
            self.last_change = self._clock.time()  # waiting on purpose, not stuck
            # a stepping visualizer's screen shows its step: look every second, to change with it
            stepping = self._renderer is not None and self._renderer.step() is not None
            if self._clock.wait(event, STEP_CHECK_SECONDS if stepping else QUIET_CHECK_SECONDS):
                return

    def visualizer_screen(self):
        if self._renderer is None:
            return message_screen("Visualizer")
        _, vis = self._renderer.visualizer
        return visualizer_screen(vis.short_name, vis.icon, self._renderer.step())

    def visualizer_changed(self):
        """The renderer switched visualizers: in Visualizer mode the screen shows the new one now."""
        if self._config.data.display_screen.shows == "visualizer":
            self.restart(timeout=5)

    def quiet(self) -> bool:
        """Whether it's quiet hours now (led.quiet_hours): the screen stays blank."""
        return quiet_hours_active(self._clock.now(), self._config.data.led.quiet_hours)

    def _wait_out_quiet_hours(self, event) -> bool:
        """Blanks the screen until quiet hours are over. Returns False if the loop was stopped meanwhile."""
        with self.lock:
            try:
                self._device.clear()
            except Exception as e:
                log.warning(f"clear for quiet hours: {e}")
            self._screen = None
        while self.quiet():
            self.last_change = self._clock.time()  # waiting on purpose, not stuck: the watchdog leaves it be
            if self._clock.wait(event, QUIET_CHECK_SECONDS):
                return False
        return True

    def _locate(self, pixel, airport):
        try:
            self._renderer.locate(pixel)  # a virtual airport: on the web map only
        except Exception as e:
            # a failed LED pulse shouldn't cost the airport its pages
            log.warning(f"locate {airport}: {e}")

    def _locate_later(self, pixel, airport, delay, event):
        """The pulse after `delay` seconds on its own thread, while the loop goes on to the airport's pages."""

        def pulse():
            if not self._clock.wait(event, delay):  # not if the loop stopped meanwhile
                self._locate(pixel, airport)

        self.locate_thread = threading.Thread(target=pulse, name="locate", daemon=True)
        self.locate_thread.start()

    def show_airport(self, airport, metar, delay, event, virtual=False):
        for page in pages_for(metar):
            if self.quiet():
                return  # the loop blanks the screen before the next airport
            if not self.show_page(screen_for(airport, metar, page, self._tz, virtual), delay, event):
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

    def splash(self, seconds=SPLASH_SECONDS):
        """
        Shows the startup screen ("MetarMap2" and the logo). The loop, started meanwhile, shows its first airport
        once it has been up `seconds`.
        """
        with self.lock:
            self._draw(splash_screen())
        self._hold_until = self._clock.time() + seconds

    def _draw(self, screen):
        try:
            self._device.show(screen)
            self._screen = screen
        except Exception as e:
            # e.g. an I2C error; keep going with the next page
            log.warning(f"draw {screen.get('title')}: {e}")
