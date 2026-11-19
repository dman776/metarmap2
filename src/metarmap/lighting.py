"""When the LEDs' brightness changes by the clock: the sun's dawn, sunrise, sunset and dusk, and quiet hours."""

import logging

import schedule

from metarmap.config import Config
from metarmap.renderer import Renderer
from metarmap.sun import LEVEL_AT, SunTimes

log = logging.getLogger(__name__)


class Lighting:
    def __init__(self, config: Config, renderer: Renderer, sun: SunTimes, scheduler: schedule.Scheduler):
        self.config = config
        self.renderer = renderer
        self.sun = sun
        self.scheduler = scheduler

    def schedule_all(self):
        """The new sun times every day (to dim the map at the right times), the brightness at each, quiet hours."""
        self.scheduler.every().day.at("00:00").do(self.load_suntimes)
        self.schedule_brightness()
        self.schedule_quiet_hours()

    def load_suntimes(self):
        log.info("load suntimes")
        self.sun.reload()
        self.schedule_brightness()

    def schedule_brightness(self):
        """Sets the LEDs' brightness at each of today's sun times (dimmed at dawn, normal at sunrise, ...)."""
        self.scheduler.clear("suntimes")
        for name, level in LEVEL_AT.items():
            at = self.sun.times[name].strftime("%H:%M")
            self.scheduler.every().day.at(at).do(self.set_brightness, level=level).tag("suntimes")

    def schedule_quiet_hours(self):
        """Recreate local-time quiet-hours boundary jobs after a configuration change."""
        self.scheduler.clear("quiet_hours")
        night = self.config.data.led.quiet_hours
        if night.enabled and night.start != night.end:
            for at in (night.start, night.end):
                self.scheduler.every().day.at(at).do(self.quiet_hours_boundary).tag("quiet_hours")

    def quiet_hours_boundary(self):
        """
        Quiet hours' start or end time. With the startup sequence on (led.inittest), the map goes dark with it at the
        start (Renderer.fade_out) and lights up with it at the end. Not when the LEDs are at 0% anyway
        (led.brightness.off at night), and not for a settings change, which switches the LEDs at once.
        """
        renderer = self.renderer
        play = self.config.data.led.inittest
        if renderer.quiet_hours_active():
            if play and renderer.pixels().brightness > 0:
                renderer.fade_out()
            renderer.adjust_brightness_for_time()
        else:
            renderer.adjust_brightness_for_time()
            if play and renderer.pixels().brightness > 0:
                renderer.test_pattern()

    def set_brightness(self, level):
        """
        level: a led.brightness setting's name ("dimmed"), read when the job runs so a changed level needs no restart;
        or a brightness (0.25).
        """
        if isinstance(level, str):
            level = getattr(self.config.data.led.brightness, level)
        # The renderer owns the scheduled brightness and quiet-hours override.
        if self.renderer.quiet_hours_active():
            level = 0.0
        log.info("set brightness: " + str(level))
        self.renderer.brightness(level)

    def brightness_changed(self, keys):
        """led.brightness.*: the level in use now changes now; the others at their time."""
        if any(k.rsplit(".", 1)[1] == self.renderer.scheduled_level() for k in keys):
            self.renderer.adjust_brightness_for_time()
