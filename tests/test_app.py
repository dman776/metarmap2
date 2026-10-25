"""Tests for building and running the whole map (metarmap.app) on an in-memory strip and screen."""
from collections import Counter

import pytest

from metarmap import app as app_module


def jobs(app):
    """The scheduled jobs, by function name."""
    return Counter(job.job_func.func.__name__ for job in app.scheduler.jobs)


# ---- building -------------------------------------------------------------------------------------------------

def test_build_wires_the_parts_together(make_app):
    app = make_app(**{"visualizer.active": 2})
    assert app.renderer.visualizer[0] == 2
    assert len(app.renderer.visualizers) == len(app_module.VISUALIZERS)
    assert app.display is not None
    assert app.display.__renderer__ is app.renderer  # the OLED pulses the LED of the airport on screen
    assert set(app.sun.times) >= {"dawn", "sunrise", "sunset", "dusk"}
    assert len(app.renderer.pixels()) == app.config.data.led.count


def test_jobs(make_app):
    app = make_app()
    assert jobs(app) == {"update_data": 1, "load_suntimes": 1, "set_brightness": 4, "watch_display": 1}
    assert {job.at_time.strftime("%H:%M") for job in app.scheduler.get_jobs("suntimes")} == \
        {app.sun.times[name].strftime("%H:%M") for name in ("dawn", "sunrise", "sunset", "dusk")}


def test_no_display(make_app):
    app = make_app(**{"display_screen.enabled": False})
    assert app.display is None
    assert "watch_display" not in jobs(app)
    app_module.watch_display(app)  # nothing to watch; no error


def test_auto_rotate(make_app):
    app = make_app(**{"visualizer.auto_rotate.enabled": True, "visualizer.auto_rotate.delay_seconds": 30})
    (job,) = app.scheduler.get_jobs("rotate_visualizer")
    assert job.interval == 30
    app_module.rotate_visualizer(app)
    assert app.renderer.visualizer[0] == 1


# ---- scheduled jobs -------------------------------------------------------------------------------------------

def test_update_data_fetches_and_redraws(make_app, monkeypatch):
    app = make_app()
    code = next(iter(app.config.airports))
    monkeypatch.setattr(app.metars, "fetch", lambda: setattr(app.metars, "data", {code: {"flightCategory": "VFR"}}))
    app_module.update_data(app)
    assert app.renderer.looks[0].colors[0] == tuple(app.config.data.color.cat.vfr)


def test_load_suntimes_replaces_the_brightness_jobs(make_app):
    app = make_app()
    app_module.load_suntimes(app)
    app_module.load_suntimes(app)
    assert jobs(app)["set_brightness"] == 4


def test_set_brightness(make_app):
    app = make_app()
    app_module.set_brightness(app, level=0.25)
    assert app.renderer.pixels().brightness == 0.25


def test_watchdog_restarts_a_dead_display(make_app):
    app = make_app()
    app.display.start()
    app.display.stop(clear=False)  # the loop thread ends, as if it had crashed
    app.display.__thread__.join(5)
    assert app.display.stalled() == "thread is not running"
    app_module.watch_display(app)
    try:
        assert app.display.is_alive()
        assert app.display.stalled() is None
    finally:
        app.display.stop()


# ---- running --------------------------------------------------------------------------------------------------

class FakeWebApp:
    def __init__(self, services):
        self.services = services
        self.port = None
        self.closed = False

    def close(self):
        self.closed = True


@pytest.mark.parametrize("error", [KeyboardInterrupt, RuntimeError])
def test_run_cleans_up_when_stopped(make_app, monkeypatch, error):
    app = make_app(**{"led.inittest": False})
    webs = []
    monkeypatch.setattr(app_module, "create_app", lambda services: webs.append(FakeWebApp(services)) or webs[-1])
    monkeypatch.setattr(app_module, "serve", lambda web, host, port: setattr(web, "port", port))
    frames = []

    def render():
        frames.append(1)
        if len(frames) == 3:
            raise error("stop")
    monkeypatch.setattr(app.renderer, "render", render)

    app_module.run(app)

    (web,) = webs
    assert web.services is app and web.port == app.config.data.web_server.port
    assert web.closed
    assert app.scheduler.jobs == []
    assert app.display.screen is None  # stopped and cleared
    clear = tuple(app.config.data.color.clear)
    assert all(c == clear for c in app.renderer.pixels())
