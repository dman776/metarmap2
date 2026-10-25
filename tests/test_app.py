"""Tests for building and running the whole map (metarmap.app) on an in-memory strip and screen."""
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from metarmap import app as app_module, visualizers

REPO = Path(__file__).parent.parent


def jobs(app):
    """The scheduled jobs, by function name."""
    return Counter(job.job_func.func.__name__ for job in app.scheduler.jobs)


# ---- building -------------------------------------------------------------------------------------------------

def test_build_wires_the_parts_together(make_app):
    app = make_app(**{"visualizer.active": 2})
    assert app.renderer.visualizer[0] == 2
    assert app.renderer.visualizers == list(visualizers.ALL)
    assert app.display is not None
    assert app.display._renderer is app.renderer  # the OLED pulses the LED of the airport on screen
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
    code = app.config.airports[0].code
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
    app.display._thread.join(5)
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


def test_the_leds_run_when_the_web_port_is_taken(make_app, monkeypatch):
    app = make_app(**{"led.inittest": False})

    def taken(web, host, port):
        raise OSError(48, "Address already in use")
    monkeypatch.setattr(app_module, "serve", taken)
    frames = []

    def render():
        frames.append(1)
        if len(frames) == 3:
            raise KeyboardInterrupt
    monkeypatch.setattr(app.renderer, "render", render)
    app_module.run(app)  # no error
    assert len(frames) == 3  # the main loop ran


# ---- retrying a failed fetch ----------------------------------------------------------------------------------

def test_a_failed_fetch_is_retried_every_minute_until_it_works(make_app, monkeypatch):
    app = make_app()
    results = [False, False, True]

    def fetch():
        app.metars.last_fetch_ok = results.pop(0)
        return app.metars.last_fetch_ok
    monkeypatch.setattr(app.metars, "fetch", fetch)

    app_module.update_data(app)  # e.g. aviationweather.gov answers 502
    (retry,) = app.scheduler.get_jobs("retry")
    assert retry.interval == app_module.RETRY_SECONDS and retry.unit == "seconds"
    app_module.update_data(app)  # failing again doesn't add a second retry
    assert len(app.scheduler.get_jobs("retry")) == 1

    retry.next_run = datetime.now() - timedelta(seconds=1)  # only the retry is due
    app.scheduler.run_pending()  # it works this time, so it stops
    assert app.scheduler.get_jobs("retry") == []
    assert jobs(app)["update_data"] == 1  # the regular fetch is still there


def test_a_failed_fetch_at_startup_is_retried(tmp_path, monkeypatch):
    import requests
    from metarmap import metar
    from metarmap.leds.strip import FakeStrip
    from metarmap.oled.screen import FakeScreen

    def bad_gateway(url, **kwargs):
        raise requests.exceptions.HTTPError("502 Server Error: Bad Gateway")
    monkeypatch.setattr(metar.requests, "get", bad_gateway)
    (tmp_path / "config.json").write_text((REPO / "config.json").read_text())
    app = app_module.build(str(tmp_path / "config.json"), strip=FakeStrip(50), screen=FakeScreen())
    assert app.metars.last_fetch_ok is False
    assert len(app.scheduler.get_jobs("retry")) == 1


def test_a_failed_position_lookup_is_retried_on_its_own(make_app, monkeypatch):
    """The METARs arrived but the lookup of where non-reporting airports are got a 502: only the lookup is redone."""
    app = make_app()
    calls = []

    def fetch():
        calls.append("fetch")
        app.metars.last_fetch_ok, app.metars.locate_failed = True, True
        return True

    def locate():
        calls.append("locate")
        app.metars.locate_failed = len(calls) < 3  # fails once more, then works
        return not app.metars.locate_failed
    monkeypatch.setattr(app.metars, "fetch", fetch)
    monkeypatch.setattr(app.metars, "locate", locate)

    app_module.update_data(app)
    (retry,) = app.scheduler.get_jobs("retry")
    for _ in range(2):
        retry.next_run = datetime.now() - timedelta(seconds=1)
        app.scheduler.run_pending()
    assert calls == ["fetch", "locate", "locate"]
    assert app.scheduler.get_jobs("retry") == []
