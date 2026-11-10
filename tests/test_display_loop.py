"""
Tests for the OLED loop (display.py) with a fake screen and clock: page order, timing, locate pulses,
recovering from errors, and the watchdog.
"""

import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from conftest import airports
from metarmap.display import QUIET_CHECK_SECONDS, Display, watchdog_limit
from metarmap.models import Report
from metarmap.clock import FakeClock
from metarmap.oled.screen import FakeScreen
from metarmap.settings import Settings

GOOD = Report(
    flight_category="VFR",
    wind_dir="100",
    wind_speed=13,
    wind_gust_speed=0,
    visibility_sm=10.0,
    altimeter_inhg=30.2,
    temp_c=28,
    dewpoint_c=16,
    obs_time=datetime(2026, 10, 24, 17, 53, tzinfo=timezone.utc),
)
AIRPORTS = airports("KHOU", "KIAH", "KDKR", "KGLS", display=("KHOU", "KDKR", "KGLS"))
DATA = {"KHOU": GOOD, "KIAH": GOOD, "KDKR": None, "KGLS": replace(GOOD, flight_category="LIFR")}


class FakeRenderer:
    def __init__(self, fail=False):
        self.located = []
        self.fail = fail

    def step(self):
        return None

    def locate(self, pixel):
        self.located.append(pixel)
        if self.fail:
            raise RuntimeError("simulated LED error")


def make(airports=AIRPORTS, data=DATA, delay=5.0, locate_active=True, renderer=None, stop_after=None, screen=None):
    settings = Settings()
    settings.display_screen.delay = delay
    settings.display_screen.locate_active = locate_active
    config = SimpleNamespace(airports=list(airports), data=settings)
    screen = screen or FakeScreen()
    clock = FakeClock()
    d = Display(
        config,
        SimpleNamespace(data=dict(data)),
        screen,
        renderer=renderer or FakeRenderer(),
        clock=clock,
        tz=timezone.utc,
    )
    if stop_after:

        def stop(_):
            if len(screen.shown) >= stop_after:
                d.event.set()

        screen.on_show = stop
    return d, screen, clock, config


def pages(screen):
    return [(s["title"], s["page"]) for s in screen.shown]


def run(d):
    """Runs the loop in this thread; the fake clock makes waits instant."""
    d.loop(d.event)


# ---- what gets shown --------------------------------------------------------------------------------------------


def test_rotates_through_display_airports():
    d, screen, _, _ = make(stop_after=6)
    run(d)
    assert pages(screen) == [("KHOU", 1), ("KHOU", 2), ("KDKR", 0), ("KGLS", 1), ("KGLS", 2), ("KHOU", 1)]
    assert d.screen == screen.shown[-1]


def test_virtual_airports_are_shown_marked():
    """KGLS, after the 3 LEDs, is virtual: shown like the others, with its code in a dashed box."""
    d, screen, _, config = make(stop_after=5)
    config.data.led.count = 3
    run(d)
    assert [(s["title"], s["virtual"]) for s in screen.shown] == [
        ("KHOU", False),
        ("KHOU", False),
        ("KDKR", False),
        ("KGLS", True),
        ("KGLS", True),
    ]
    assert d._renderer.located == [0, 2, 3]  # the renderer pulses KGLS on the web map only


def test_each_page_stays_for_the_delay():
    d, _, clock, _ = make(delay=7, stop_after=5)
    start = clock.time()
    run(d)
    assert clock.time() - start == pytest.approx(4 * 7)  # the loop stops right after drawing the 5th page


def test_locate_pulse_once_per_airport():
    renderer = FakeRenderer()
    d, _, _, _ = make(renderer=renderer, stop_after=5)
    run(d)
    assert renderer.located == [0, 2, 3]  # LED positions of KHOU, KDKR, KGLS


def test_the_first_pulse_can_wait_while_the_oled_goes_on():
    """At startup (start(locate_delay=2)) the LEDs show the visualizer before the first pulse; the OLED doesn't wait."""
    renderer = FakeRenderer()
    threads = {}
    locate = renderer.locate
    renderer.locate = lambda pixel: threads.setdefault(pixel, threading.current_thread().name) and locate(pixel)
    d, screen, _, _ = make(renderer=renderer, stop_after=5)
    d._locate_delay = 2.0  # what start(locate_delay=2.0) sets
    run(d)
    d.locate_thread.join(5)
    assert pages(screen) == [("KHOU", 1), ("KHOU", 2), ("KDKR", 0), ("KGLS", 1), ("KGLS", 2)]  # as without it
    assert sorted(renderer.located) == [0, 2, 3]  # every airport still pulses once
    assert threads[0] == "locate" and threads[2] != "locate"  # only the first waits, off the loop's thread
    assert d._locate_delay == 0.0


def test_a_delayed_pulse_is_dropped_if_the_loop_stops():
    renderer = FakeRenderer()
    d, _, _, _ = make(renderer=renderer)
    event = threading.Event()
    event.set()
    d._locate_later(0, "KHOU", 2.0, event)
    d.locate_thread.join(5)
    assert renderer.located == []


def test_locate_can_be_turned_off():
    renderer = FakeRenderer()
    d, _, _, _ = make(renderer=renderer, locate_active=False, stop_after=5)
    run(d)
    assert renderer.located == []


def test_last_change_moves_with_each_page():
    d, _, clock, _ = make(stop_after=3)
    run(d)
    assert d.last_change == clock.time()


def test_message():
    d, screen, _, _ = make()
    d.message("MAP", "info", "Starting..")
    assert d.screen["kind"] == "message"
    assert d.screen["title"] == "MAP"
    assert screen.current is d.screen


def test_splash():
    d, screen, _, _ = make()
    d.splash()
    assert d.screen["splash"] is True
    assert d.screen["title"] == "MetarMap2"
    assert screen.current is d.screen


def test_the_first_airport_waits_for_the_splash():
    """The splash stays its 5 s from when it was drawn, however long the rest of startup took."""
    d, screen, clock, _ = make(stop_after=2)
    d.splash(5)
    start = clock.time()
    clock.advance(2)  # the LED test pattern, the web server...
    shown = []
    screen.on_show = lambda s: (shown.append((s["title"], clock.time() - start)), d.event.set())
    run(d)
    assert shown == [("KHOU", 5.0)]


def test_without_a_splash_the_first_airport_comes_at_once():
    d, screen, clock, _ = make()
    start = clock.time()
    screen.on_show = lambda s: (setattr(d, "first_at", clock.time() - start), d.event.set())
    run(d)
    assert d.first_at == 0


def test_a_loop_stopped_during_the_splash_draws_nothing():
    d, screen, _, _ = make()
    d.splash(5)
    d.event.set()
    run(d)
    assert [s["title"] for s in screen.shown] == ["MetarMap2"]


# ---- Visualizer mode (display_screen.shows) --------------------------------------------------------------------


class VisRenderer(FakeRenderer):
    def __init__(self):
        super().__init__()
        self.vis = SimpleNamespace(short_name="Wind Dir", icon="compass")

    @property
    def visualizer(self):
        return 5, self.vis


def visualizer_mode(**kw):
    renderer = VisRenderer()
    d, screen, clock, config = make(renderer=renderer, **kw)
    config.data.display_screen.shows = "visualizer"
    return d, screen, clock, renderer


def test_visualizer_mode_shows_the_visualizer_and_no_airports():
    d, screen, clock, renderer = visualizer_mode()
    start = clock.time()
    clock.wait = stop_after_waits(d, clock, 3)
    run(d)
    assert [(s["title"], s.get("visualizer_icon")) for s in screen.shown] == [("Wind Dir", "compass")]  # drawn once
    assert renderer.located == []  # no airport on the screen: no pulses
    assert d.last_change == start + 2 * QUIET_CHECK_SECONDS  # moved on each look: the watchdog leaves it be


def test_visualizer_mode_follows_a_change_on_its_next_look():
    d, screen, clock, renderer = visualizer_mode()

    def wait(event, seconds):
        clock.advance(seconds)
        renderer.vis = SimpleNamespace(short_name="Precip", icon="rain")
        if len(screen.shown) >= 2:
            event.set()
        return event.is_set()

    clock.wait = wait
    run(d)
    assert [s["title"] for s in screen.shown] == ["Wind Dir", "Precip"]


def test_a_visualizer_change_restarts_the_loop_only_in_visualizer_mode():
    d, _, _, _ = make()
    restarts = []
    d.restart = lambda timeout=None: restarts.append(timeout)
    d.visualizer_changed()
    assert restarts == []  # Airports: the rotation goes on
    d._config.data.display_screen.shows = "visualizer"
    d.visualizer_changed()
    assert restarts == [5]


def test_visualizer_mode_is_blank_in_quiet_hours():
    d, screen, clock, _ = visualizer_mode()
    d.quiet = lambda: True
    clock.wait = stop_after_waits(d, clock, 1)
    run(d)
    assert screen.shown == []
    assert d.screen is None


def test_visualizer_mode_waits_for_the_splash():
    d, screen, clock, _ = visualizer_mode()
    d.splash(5)
    start = clock.time()
    shown = []
    screen.on_show = lambda s: (shown.append((s["title"], clock.time() - start)), d.event.set())
    run(d)
    assert shown == [("Wind Dir", 5.0)]


def stop_after_waits(d, clock, n):
    """A clock.wait that stops the loop on its n-th wait."""
    count = [0]

    def wait(event, seconds):
        count[0] += 1
        clock.advance(seconds)
        if count[0] >= n:
            event.set()
        return event.is_set()

    return wait


# ---- recovering from problems -----------------------------------------------------------------------------------


def test_failed_locate_still_shows_the_airport():
    d, screen, _, _ = make(renderer=FakeRenderer(fail=True), stop_after=5)
    run(d)
    assert pages(screen) == [("KHOU", 1), ("KHOU", 2), ("KDKR", 0), ("KGLS", 1), ("KGLS", 2)]


def test_drawing_error_moves_on_to_the_next_page():
    calls = {"n": 0}

    class FlakyScreen(FakeScreen):
        def show(self, screen):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("I2C write failed")
            super().show(screen)

    d, screen, _, _ = make(screen=FlakyScreen(), stop_after=3)
    run(d)
    assert pages(screen) == [("KHOU", 2), ("KDKR", 0), ("KGLS", 1)]


def test_airport_missing_from_data_shows_unavailable():
    d, screen, _, _ = make(data={"KHOU": GOOD}, stop_after=5)
    run(d)
    assert ("KDKR", 0) in pages(screen) and ("KGLS", 0) in pages(screen)


def test_airport_edits_are_picked_up_on_the_next_pass():
    d, screen, _, config = make(stop_after=None)

    def on_show(s):
        if len(screen.shown) == 1:
            config.airports = airports("KNEW", display=("KNEW",))  # replaced, like Config.read() does
        if len(screen.shown) >= 7:
            d.event.set()

    screen.on_show = on_show
    run(d)
    assert pages(screen)[-1] == ("KNEW", 0)


def test_nothing_to_show_waits_instead_of_spinning():
    d, screen, clock, _ = make(airports=airports("KHOU"))
    start = clock.time()
    calls = {"n": 0}
    real_wait = clock.wait

    def wait(event, seconds):
        calls["n"] += 1
        if calls["n"] >= 3:
            event.set()
        return real_wait(event, seconds)

    clock.wait = wait
    run(d)
    assert screen.shown == []
    assert clock.time() - start == pytest.approx(10)  # two waits of 5 s before it was stopped


# ---- watchdog ---------------------------------------------------------------------------------------------------


def test_watchdog_limit():
    assert watchdog_limit(5) == 60
    assert watchdog_limit(20) == 90


def test_stalled_when_thread_not_running():
    d, _, _, _ = make()
    assert d.stalled() == "thread is not running"


def test_stalled_when_no_new_page(monkeypatch):
    d, _, clock, _ = make()
    monkeypatch.setattr(d, "is_alive", lambda: True)
    d.last_change = clock.time()
    clock.advance(59)
    assert d.stalled() is None
    clock.advance(2)
    assert d.stalled() == "no new page for 61s"


def test_restart_replaces_a_hung_thread():
    """A thread stuck in hardware is abandoned; the new one keeps the screen rotating."""
    release = threading.Event()
    entered = threading.Event()

    class HangingRenderer(FakeRenderer):
        def locate(self, pixel):
            if not entered.is_set():
                entered.set()
                release.wait(5)  # simulate a hung LED write, once

    d, screen, _, _ = make(renderer=HangingRenderer())
    d.start()
    assert entered.wait(2)
    old_thread = d._Display__thread__ if hasattr(d, "_Display__thread__") else d.__dict__["_thread"]
    d.restart(timeout=0.2)
    time.sleep(0.2)
    assert old_thread.is_alive()  # still stuck
    assert d.is_alive()
    assert screen.shown, "the new thread is drawing"
    release.set()
    old_thread.join(2)
    assert not old_thread.is_alive()  # it noticed its own stop event and exited
    d.stop()


def test_restart_before_start_waits_for_start():
    """The web server starts before the OLED loop; an airport edit in between mustn't fail or start it twice."""
    d, _, _, _ = make()
    d.restart(timeout=1)
    assert not d.is_alive()
    d.start()
    try:
        assert d.is_alive()
    finally:
        d.stop()


def test_parallel_restarts_leave_one_loop():
    """An airport edit and the watchdog can restart the loop at the same time."""
    others = set(threading.enumerate())  # e.g. another test's loop, still finishing a locate pulse
    d, _, _, _ = make()
    d.start()
    try:
        threads = [threading.Thread(target=d.restart, kwargs={"timeout": 5}) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        time.sleep(0.2)
        loops = [t for t in threading.enumerate() if t.name == "display" and t.is_alive() and t not in others]
        assert loops == [d._thread]
    finally:
        d.stop()


# ---- turning the screen on and off (display_screen.enabled, no restart) -----------------------------------------


def test_turn_on_and_off():
    d, screen, _, config = make()
    d.turn_on()  # never started: starts
    try:
        assert d.is_alive()
        d.turn_on()  # already on: nothing changes
        first = d._thread
        d.turn_off()
        d._thread.join(5)
        assert not d.is_alive() and d.screen is None and screen.current is None  # blanked
        d.turn_on()  # a new loop
        assert d.is_alive() and d._thread is not first
    finally:
        d.stop()


def test_a_turned_off_screen_stays_off():
    """The watchdog and airport edits restart the loop; not when it's turned off."""
    d, _, _, config = make()
    d.start()
    d.turn_off()
    d._thread.join(5)
    config.data.display_screen.enabled = False
    d.restart(timeout=1)
    assert not d.is_alive()


# ---- quiet hours ------------------------------------------------------------------------------------------------


def quiet_from_now(config, clock, minutes):
    """Quiet hours from the fake clock's time (in this machine's local time, as the setting is) for `minutes`."""
    start = clock.now().astimezone()
    config.data.led.quiet_hours.enabled = True
    config.data.led.quiet_hours.start = start.strftime("%H:%M")
    config.data.led.quiet_hours.end = (start + timedelta(minutes=minutes)).strftime("%H:%M")


def test_the_screen_is_blank_during_quiet_hours():
    d, screen, clock, config = make(stop_after=2)
    screen.current = {"title": "left over"}
    blank = []
    clock_wait = clock.wait
    clock.wait = lambda event, seconds: blank.append((screen.current, d.screen)) or clock_wait(event, seconds)
    quiet_from_now(config, clock, 10)
    start = clock.time()
    run(d)
    assert blank[0] == (None, None)  # cleared first: the OLED and the Home page's preview
    assert clock.time() - start >= 9 * 60  # nothing drawn until quiet hours were over
    assert pages(screen) == [("KHOU", 1), ("KHOU", 2)]  # then from the first airport
    assert d._renderer.located == [0]  # no locate pulses meanwhile


def test_quiet_hours_starting_mid_airport_blank_the_screen():
    d, screen, clock, config = make()

    def show(_):
        if len(screen.shown) == 1:  # after KHOU's first page, quiet hours begin
            quiet_from_now(config, clock, 10)
        else:
            d.event.set()

    screen.on_show = show
    run(d)
    assert pages(screen) == [("KHOU", 1), ("KHOU", 1)]  # KHOU's second page skipped; after quiet hours, KHOU again


def test_the_watchdog_leaves_a_quiet_screen_alone():
    """Waiting out quiet hours counts as moving on, so a long quiet night isn't taken for a stuck loop."""
    d, _, clock, config = make()
    quiet_from_now(config, clock, 120)
    waits = []
    clock_wait = clock.wait

    def wait(event, seconds):
        waits.append(seconds)
        if len(waits) == 20:  # 10 minutes in
            event.set()
        return clock_wait(event, seconds)

    clock.wait = wait
    run(d)
    assert waits == [QUIET_CHECK_SECONDS] * 20
    assert clock.time() - d.last_change <= QUIET_CHECK_SECONDS < watchdog_limit(config.data.display_screen.delay)


def test_quiet_hours_off_shows_the_airports():
    d, screen, _, config = make(stop_after=2)
    config.data.led.quiet_hours.enabled = False
    run(d)
    assert pages(screen) == [("KHOU", 1), ("KHOU", 2)]


def test_a_stepping_visualizer_is_looked_at_every_second():
    """Flight Category Forecast's Micro screen carries its step in the title, so it follows the step."""
    from metarmap.display import STEP_CHECK_SECONDS

    d, screen, clock, renderer = visualizer_mode()
    start = clock.time()
    renderer.step = lambda: {
        "labels": ["Now", "+3h", "+6h", "+12h"],
        "index": int(clock.time() - start) % 4,
        "prefix": "FC",
    }
    renderer.vis = SimpleNamespace(short_name="FC Forecast", icon="clock")
    clock.wait = stop_after_waits(d, clock, 3)
    run(d)
    assert [s["title"] for s in screen.shown][:3] == ["FC Now", "FC +3h", "FC +6h"]
    assert clock.time() - start <= 4 * STEP_CHECK_SECONDS
