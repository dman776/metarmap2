"""
Time, passed in rather than read globally, so tests can control it.
"""

import threading
import time
from datetime import datetime, timedelta, timezone


class Clock:
    """The real clock."""

    def now(self) -> datetime:
        """Current time, timezone-aware (UTC)."""
        return datetime.now(timezone.utc)

    def time(self) -> float:
        """Current time as Unix seconds."""
        return time.time()

    def monotonic(self) -> float:
        """Seconds that only go forward (not Unix time): for counting how long, when the wall clock can jump (NTP)."""
        return time.monotonic()

    def wait(self, event: threading.Event, seconds: float) -> bool:
        """Waits up to `seconds` or until the event is set. Returns True if the event was set."""
        return event.wait(seconds)


class FakeClock(Clock):
    """A clock for tests: time only moves when advanced, and waiting returns immediately."""

    def __init__(self, start: datetime = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)):
        self._now = start
        self._monotonic = 0.0

    def now(self) -> datetime:
        return self._now

    def time(self) -> float:
        return self._now.timestamp()

    def monotonic(self) -> float:
        return self._monotonic

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)
        self._monotonic += seconds

    def set_wall_clock(self, when: datetime) -> None:
        """The wall clock jumps (NTP setting a Pi's clock), forward or back; monotonic() doesn't."""
        self._now = when

    def wait(self, event: threading.Event, seconds: float) -> bool:
        if event.is_set():
            return True
        self.advance(seconds)
        return event.is_set()
