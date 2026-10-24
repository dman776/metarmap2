"""
Tests for the OLED loop (display.py) with a fake screen and clock: page order, timing, locate pulses,
recovering from errors, and the watchdog.
"""
import threading
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from display import Display, watchdog_limit
from metarmap.clock import FakeClock
from metarmap.oled.screen import FakeScreen
from metarmap.settings import Settings

GOOD = {"flightCategory": "VFR", "windDir": "100", "windSpeed": 13, "windGustSpeed": 0, "windGust": False,
        "vis": 10, "altimHg": 30.2, "tempC": 28, "dewpointC": 16,
        "obsTime": datetime(2026, 10, 24, 17, 53, tzinfo=timezone.utc)}
AIRPORTS = {"KHOU": {"display": True}, "KIAH": {"display": False}, "KDKR": {"display": True},
            "KGLS": {"display": True}}
DATA = {"KHOU": GOOD, "KIAH": GOOD, "KDKR": {}, "KGLS": {**GOOD, "flightCategory": "LIFR"}}


class FakeRenderer:
    def __init__(self, fail=False):
        self.located = []
        self.fail = fail

    def locate(self, pixel):
        self.located.append(pixel)
        if self.fail:
            raise RuntimeError("simulated LED error")


def make(airports=AIRPORTS, data=DATA, delay=5.0, locate_active=True, renderer=None, stop_after=None,
         screen=None):
    settings = Settings()
    settings.display_screen.delay = delay
    settings.display_screen.locate_active = locate_active
    config = SimpleNamespace(airports=dict(airports), data=settings)
    screen = screen or FakeScreen()
    clock = FakeClock()
    d = Display(config, SimpleNamespace(data=dict(data)), screen, renderer=renderer or FakeRenderer(),
                clock=clock, tz=timezone.utc)
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
            config.airports = {"KNEW": {"display": True}}  # replaced, like read_airports() does
        if len(screen.shown) >= 7:
            d.event.set()
    screen.on_show = on_show
    run(d)
    assert pages(screen)[-1] == ("KNEW", 0)


def test_nothing_to_show_waits_instead_of_spinning():
    d, screen, clock, _ = make(airports={"KHOU": {"display": False}})
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
    old_thread = d._Display__thread__ if hasattr(d, "_Display__thread__") else d.__dict__["__thread__"]
    d.restart(timeout=0.2)
    time.sleep(0.2)
    assert old_thread.is_alive()  # still stuck
    assert d.is_alive()
    assert screen.shown, "the new thread is drawing"
    release.set()
    old_thread.join(2)
    assert not old_thread.is_alive()  # it noticed its own stop event and exited
    d.stop()
