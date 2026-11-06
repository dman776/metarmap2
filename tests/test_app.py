"""Tests for building and running the whole map (metarmap.app) on an in-memory strip and screen."""

import threading
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from metarmap import app as app_module, visualizers
from metarmap.models import Report
from metarmap.visualizers import flightcategory

REPO = Path(__file__).parent.parent


def jobs(app):
    """The scheduled jobs, by function name."""
    return Counter(job.job_func.func.__name__ for job in app.scheduler.jobs)


# ---- building -------------------------------------------------------------------------------------------------


def test_build_wires_the_parts_together(make_app):
    app = make_app(**{"visualizer.active": "wind_gusts"})
    assert app.renderer.visualizer == (2, visualizers.BY_ID["wind_gusts"])
    assert app.renderer.visualizers == list(visualizers.ALL)
    assert app.display is not None
    assert app.display._renderer is app.renderer  # the OLED pulses the LED of the airport on screen
    assert set(app.sun.times) >= {"dawn", "sunrise", "sunset", "dusk"}
    assert len(app.renderer.pixels()) == app.config.data.led.count


def test_quiet_hours_jobs(make_app):
    app = make_app(
        **{
            "led.quiet_hours.enabled": True,
            "led.quiet_hours.start": "22:00",
            "led.quiet_hours.end": "07:00",
        }
    )

    assert jobs(app)["adjust_brightness_for_time"] == 2
    assert {job.at_time.strftime("%H:%M") for job in app.scheduler.get_jobs("quiet_hours")} == {
        "22:00",
        "07:00",
    }


def test_jobs(make_app):
    app = make_app()
    assert jobs(app) == {
        "update_data": 1,
        "load_suntimes": 1,
        "set_brightness": 4,
        "watch_display": 1,
        "check_releases": 1,
    }
    assert {job.at_time.strftime("%H:%M") for job in app.scheduler.get_jobs("suntimes")} == {
        app.sun.times[name].strftime("%H:%M") for name in ("dawn", "sunrise", "sunset", "dusk")
    }


def test_display_turned_off_at_startup(make_app):
    """The OLED loop is built anyway, so it can be turned on later without a restart; the watchdog leaves it off."""
    app = make_app(**{"display_screen.enabled": False})
    assert app.display is not None and not app.display.is_alive()
    app_module.watch_display(app)
    assert not app.display.is_alive()


def test_auto_rotate(make_app):
    app = make_app(**{"visualizer.auto_rotate.enabled": True, "visualizer.auto_rotate.delay_seconds": 30})
    (job,) = app.scheduler.get_jobs("rotate_visualizer")
    assert job.interval == 30
    app_module.rotate_visualizer(app)
    assert app.renderer.visualizer[0] == 1


def rotating(make_app, seconds=30):
    """A map with auto-rotate on, and its rotate job as if it were due in 5 s (most of the delay gone)."""
    app = make_app(**{"visualizer.auto_rotate.enabled": True, "visualizer.auto_rotate.delay_seconds": seconds})
    (job,) = app.scheduler.get_jobs("rotate_visualizer")
    job.next_run = datetime.now() + timedelta(seconds=5)
    return app


def due_in(app):
    """Seconds until auto-rotate's next change; there's exactly one rotate job."""
    (job,) = app.scheduler.get_jobs("rotate_visualizer")
    return (job.next_run - datetime.now()).total_seconds()


@pytest.mark.parametrize(
    "change",
    [
        lambda r: setattr(r, "visualizer", "wind_direction"),
        lambda r: r.visualizer_next(),
        lambda r: r.visualizer_previous(),
    ],
)
def test_a_visualizer_changed_by_hand_gets_the_whole_delay(make_app, change):
    app = rotating(make_app)
    change(app.renderer)
    assert 29 <= due_in(app) <= 30


def test_the_same_visualizer_keeps_the_timer(make_app):
    """Picking the one that's showing, or refreshing it after a config change, isn't a change."""
    app = rotating(make_app)
    app.renderer.visualizer = app.renderer.visualizer[1].id
    app.renderer.refresh()
    assert due_in(app) <= 5


def test_auto_rotate_keeps_its_pace(make_app):
    app = rotating(make_app)
    (job,) = app.scheduler.get_jobs("rotate_visualizer")
    job.next_run = datetime.now() - timedelta(seconds=1)
    app.scheduler.run_pending()
    assert app.renderer.visualizer[0] == 1
    assert 29 <= due_in(app) <= 30  # one job, the next change a whole delay away


def test_a_change_by_hand_with_auto_rotate_off_schedules_nothing(make_app):
    app = make_app()
    app.renderer.visualizer_next()
    assert app.scheduler.get_jobs("rotate_visualizer") == []


def test_next_rotation(make_app):
    """When auto-rotate next changes the visualizer, for /api/live; None while it's off."""
    import time

    app = make_app(**{"visualizer.auto_rotate.enabled": True, "visualizer.auto_rotate.delay_seconds": 30})
    assert app_module.next_rotation(app) == pytest.approx(time.time() + 30, abs=5)
    app.config.edit("visualizer.auto_rotate.enabled", "false")
    assert app_module.next_rotation(app) is None


def test_auto_rotate_leaves_out_the_skipped(make_app):
    app = make_app(**{"visualizer.auto_rotate.skip": '["wind", "wind_gusts"]'})
    app_module.rotate_visualizer(app)
    assert app.renderer.visualizer[1].id == "wind_direction"  # after Flight Category, past Wind and Wind Gusts


# ---- following config changes ---------------------------------------------------------------------------------


def spy(monkeypatch, obj, name, calls, label=None):
    """Records a call of obj.name in `calls` (as `label`, default the name) instead of running it."""
    monkeypatch.setattr(obj, name, lambda *args, **kwargs: calls.append(label or name))


@pytest.fixture
def quiet_app(make_app, monkeypatch):
    """A map whose reactions are recorded instead of run: (app, calls)."""
    app = make_app(**{"display_screen.enabled": False})
    calls = []
    spy(monkeypatch, app.renderer, "refresh", calls)
    spy(monkeypatch, app.display, "restart", calls, "display.restart")
    spy(monkeypatch, app_module, "refetch_metars", calls)
    # threads app.py starts (test pattern, fetch) are recorded, not started; only app.py's, not every thread's
    thread = SimpleNamespace(start=lambda: calls.append("thread"))
    monkeypatch.setattr(app_module, "threading", SimpleNamespace(Thread=lambda *args, **kwargs: thread))
    return app, calls


def test_led_count_resizes_the_strip_then_refreshes(quiet_app, monkeypatch):
    app, calls = quiet_app
    monkeypatch.setattr(app.renderer, "resize", lambda count: calls.append(f"resize {count}"))
    app.config.edit("led.count", "10")
    assert calls == ["resize 10", "refresh", "display.restart"]


def test_tfr_distance_reprocesses_the_metars(quiet_app, monkeypatch):
    app, calls = quiet_app
    spy(monkeypatch, app.metars, "apply_mocks", calls)
    spy(monkeypatch, app.renderer, "update_data", calls)
    app.config.edit("tfr.nearby_nm", "25")
    assert calls == ["apply_mocks", "update_data", "refresh"]


def test_names_and_logins_leave_the_leds_alone(quiet_app):
    app, calls = quiet_app
    app.config.set_airport(0, "name", "Somewhere Else")
    app.config.set_login("pilot", "secret")
    assert calls == []


def test_auto_rotate_is_rescheduled(quiet_app):
    app, _ = quiet_app
    assert app.scheduler.get_jobs("rotate_visualizer") == []
    app.config.edit("visualizer.auto_rotate.enabled", "true")
    assert len(app.scheduler.get_jobs("rotate_visualizer")) == 1
    app.config.edit("visualizer.auto_rotate.delay_seconds", "45")
    (job,) = app.scheduler.get_jobs("rotate_visualizer")
    assert job.interval == 45


def test_quiet_hours_are_rescheduled(quiet_app, monkeypatch):
    app, calls = quiet_app
    spy(monkeypatch, app.renderer, "adjust_brightness_for_time", calls, "adjust")
    app.config.edit("led.quiet_hours.enabled", "true")
    assert len(app.scheduler.get_jobs("quiet_hours")) == 2
    assert calls == ["refresh", "adjust"]


def test_only_the_brightness_in_use_changes_now(quiet_app, monkeypatch):
    app, calls = quiet_app
    spy(monkeypatch, app.renderer, "adjust_brightness_for_time", calls, "adjust")
    monkeypatch.setattr(app.renderer, "scheduled_level", lambda: "normal")
    app.config.edit("led.brightness.dimmed", "0.2")
    assert "adjust" not in calls
    app.config.edit("led.brightness.normal", "0.6")
    assert calls[-1] == "adjust"


def test_turning_inittest_on_shows_the_test_pattern(quiet_app):
    app, calls = quiet_app
    app.config.edit("led.inittest", "false")
    assert "thread" not in calls
    app.config.edit("led.inittest", "true")
    assert calls[-1] == "thread"


def test_choosing_a_startup_sequence_plays_it(quiet_app):
    app, calls = quiet_app
    app.config.edit("led.init_sequence", "radar")
    assert calls[-1] == "thread"
    calls.clear()
    app.config.edit("led.init_sweep_from", "N")
    assert calls == ["thread"]  # played, and the LEDs aren't refreshed for it


def test_update_channel_checks_for_releases(quiet_app, monkeypatch):
    app, calls = quiet_app
    spy(monkeypatch, app.releases, "check_soon", calls)
    app.config.edit("update.channel", "latest")
    assert calls[-1] == "check_soon"


def test_display_screen_enabled_turns_the_oled_on_and_off(quiet_app, monkeypatch):
    app, calls = quiet_app
    spy(monkeypatch, app.display, "turn_on", calls)
    spy(monkeypatch, app.display, "turn_off", calls)
    app.config.edit("display_screen.enabled", "true")
    app.config.edit("display_screen.enabled", "false")
    assert calls == ["refresh", "turn_on", "refresh", "turn_off"]


@pytest.mark.parametrize(
    "change",
    [
        lambda c: c.set_airport(0, "display", "true"),
        lambda c: c.move_airport(0, 1),
        lambda c: c.edit("led.virtual_count", "2"),
    ],
)
def test_airport_list_changes_restart_the_oled(quiet_app, change):
    app, calls = quiet_app
    change(app.config)
    assert calls == ["refresh", "display.restart"]


def test_a_new_code_gets_its_name_and_metar(quiet_app, monkeypatch):
    app, calls = quiet_app
    monkeypatch.setattr(app.metars, "name_for", lambda code: {"KDWH": "Hooks Meml"}.get(code, ""))
    app.config.set_airport(0, "code", "KDWH")
    assert app.config.airports[0].name == "Hooks Meml"
    assert calls == ["refresh", "display.restart", "thread"]  # the fetch runs in the background


def test_refetch_metars(make_app, monkeypatch):
    app = make_app()
    calls = []
    monkeypatch.setattr(app.metars, "fetch", lambda: calls.append("fetch") or True)
    monkeypatch.setattr(app.renderer, "update_data", lambda metars: calls.append("update_data"))
    monkeypatch.setattr(app_module, "fill_names", lambda a: calls.append("fill_names"))
    app_module.refetch_metars(app)
    assert calls == ["fetch", "update_data", "fill_names"]


# ---- scheduled jobs -------------------------------------------------------------------------------------------


def test_update_data_fetches_and_redraws(make_app, monkeypatch):
    app = make_app()
    code = app.config.airports[0].code
    brightness = []

    def fetch():
        brightness.append(app.renderer.pixels().brightness)
        app.metars.data = {code: Report(flight_category="VFR")}

    monkeypatch.setattr(app.metars, "fetch", fetch)
    normal = app.renderer.pixels().brightness
    app_module.update_data(app)
    assert app.renderer.looks[0].colors[0] == flightcategory.COLORS["VFR"]
    assert brightness == [normal / 2] and app.renderer.pixels().brightness == normal  # dimmed while fetching


def test_load_suntimes_replaces_the_brightness_jobs(make_app):
    app = make_app()
    app_module.load_suntimes(app)
    app_module.load_suntimes(app)
    assert jobs(app)["set_brightness"] == 4


def test_set_brightness(make_app):
    app = make_app()
    app_module.set_brightness(app, level=0.25)
    assert app.renderer.pixels().brightness == 0.25


def test_brightness_jobs_read_the_level_when_they_run(make_app):
    """A level changed in Config is used at its next sun time, without a restart."""
    app = make_app()
    dusk = next(job for job in app.scheduler.get_jobs("suntimes") if job.job_func.keywords["level"] == "off")
    app.config.data.led.brightness.off = 0.07
    dusk.job_func()
    assert app.renderer.pixels().brightness == 0.07


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
    clear = (0, 0, 0)
    assert all(c == clear for c in app.renderer.pixels())


def test_run_draws_the_visualizer_before_the_oled_loop_starts(make_app, monkeypatch):
    """So the first thing on the LEDs after the test pattern is the visualizer, not a locate pulse."""
    app = make_app(**{"led.inittest": False, "display_screen.enabled": True})
    monkeypatch.setattr(app_module, "create_app", lambda services: FakeWebApp(services))
    monkeypatch.setattr(app_module, "serve", lambda web, host, port: None)
    order = []
    monkeypatch.setattr(app.renderer, "draw_frame", lambda: order.append("frame"))
    monkeypatch.setattr(app.display, "start", lambda locate_delay: order.append(("display", locate_delay)))
    monkeypatch.setattr(app.renderer, "render", lambda: (_ for _ in ()).throw(KeyboardInterrupt()))

    app_module.run(app)

    assert order == ["frame", ("display", 2.0)]  # and the first pulse waits 2 s


def test_run_on_another_port_for_this_run_only(make_app, monkeypatch):
    app = make_app(**{"led.inittest": False})
    webs = []
    monkeypatch.setattr(app_module, "create_app", lambda services: webs.append(FakeWebApp(services)) or webs[-1])
    monkeypatch.setattr(app_module, "serve", lambda web, host, port: setattr(web, "port", port))
    monkeypatch.setattr(app.renderer, "render", lambda: (_ for _ in ()).throw(KeyboardInterrupt()))
    saved = app.config.data.web_server.port

    app_module.run(app, port=8080)

    assert webs[0].port == 8080
    assert app.config.data.web_server.port == saved  # not saved: config.json keeps its port


@pytest.mark.parametrize("argv, port", [([], None), (["--port", "8080"], 8080), (["--port=1"], 1)])
def test_parse_args(argv, port):
    assert app_module.parse_args(argv).port == port


@pytest.mark.parametrize("argv", [["--port", "0"], ["--port", "65536"], ["--port", "http"], ["--colour"]])
def test_parse_args_rejects(argv, capsys):
    with pytest.raises(SystemExit) as stopped:
        app_module.parse_args(argv)
    assert stopped.value.code == 2  # argparse's usage error


def test_version(capsys):
    with pytest.raises(SystemExit):
        app_module.parse_args(["--version"])
    assert f"metarmap {app_module.__version__}" in capsys.readouterr().out


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


def test_names_are_filled_after_a_fetch(make_app, monkeypatch):
    app = make_app()
    first = app.config.airports[0]
    first.name = ""
    monkeypatch.setattr(app.metars, "fetch", lambda: True)
    monkeypatch.setattr(app.metars, "station_names", lambda: {first.code: "Somewhere Muni"})
    app_module.update_data(app)
    assert app.config.airports[0].name == "Somewhere Muni"


def test_startup_doesnt_wait_for_the_advisories(tmp_path, monkeypatch):
    """A slow aviationweather.gov (21 s once) held up the map; the advisories now come in the background."""
    from metarmap import advisories, metar, tfr
    from metarmap.leds.strip import FakeStrip
    from metarmap.oled.screen import FakeScreen

    release, fetched = threading.Event(), threading.Event()

    def slow_fetch(self):
        release.wait(10)
        fetched.set()
        return True

    shown = threading.Event()
    monkeypatch.setattr(advisories.Advisories, "fetch", slow_fetch)
    monkeypatch.setattr(tfr.Tfrs, "fetch_soon", lambda self, then=None: None)
    monkeypatch.setattr(metar.Reports, "fetch", lambda self, callback=None: True)
    monkeypatch.setattr(app_module, "show_areas", lambda app: shown.set())
    (tmp_path / "config.json").write_text((REPO / "config.json").read_text())

    app_module.build(str(tmp_path / "config.json"), strip=FakeStrip(50), screen=FakeScreen())

    assert not fetched.is_set()  # built while the advisories are still on their way
    release.set()
    assert shown.wait(5)  # then the LEDs show them


def test_pingable(monkeypatch):
    import subprocess

    asked = []

    def ping(cmd, **kwargs):
        asked.append(cmd)
        return subprocess.CompletedProcess(cmd, 0 if cmd[-1] == "8.8.8.8" else 2)

    monkeypatch.setattr(app_module.subprocess, "run", ping)
    assert app_module.pingable("8.8.8.8") is True
    assert app_module.pingable("10.255.255.1") is False
    assert asked[0] == ["ping", "-c", "1", "8.8.8.8"]
