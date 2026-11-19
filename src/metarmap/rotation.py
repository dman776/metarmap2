"""Auto-rotate: the schedule that changes the visualizer every few seconds, when it's turned on."""

import logging
from typing import Optional

import schedule

from metarmap.config import Config
from metarmap.renderer import Renderer

log = logging.getLogger(__name__)


class Rotation:
    def __init__(self, config: Config, renderer: Renderer, scheduler: schedule.Scheduler):
        self.config = config
        self.renderer = renderer
        self.scheduler = scheduler

    def schedule(self):
        """
        Schedules auto-rotate from the settings, starting the wait now; called again when they change, so they need no
        restart, and when the visualizer changes, so one picked by hand is shown for the whole delay.
        """
        self.scheduler.clear("rotate_visualizer")
        rotate = self.config.data.visualizer.auto_rotate
        if rotate.enabled:
            self.scheduler.every(rotate.delay_seconds).seconds.do(self.rotate).tag("rotate_visualizer")

    def next_rotation(self) -> Optional[float]:
        """When auto-rotate next changes the visualizer (Unix time), or None when it's off."""
        runs = [job.next_run for job in self.scheduler.get_jobs("rotate_visualizer") if job.next_run is not None]
        return min(runs).timestamp() if runs else None  # schedule's times are the map's local time

    def rotate(self):
        rotate = self.config.data.visualizer.auto_rotate
        self.renderer.visualizer_next(skip_exclusive=True, skip=rotate.skip, skip_dark=rotate.skip_dark)
