"""Tests for building and running the whole map (metarmap.app) on an in-memory strip and screen."""

import threading
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import schedule

from metarmap import app as app_module, visualizers
from metarmap.models import Report
from metarmap.visualizers import flightcategory

REPO = Path(__file__).parent.parent


def wait_for_fetches():
    """Joins the METAR fetches app.py runs in the background (start_fetch), including one a fetch starts at its end."""
    while True:
        running = [t for t in threading.enumerate() if t.name == "metars" and t is not threading.current_thread()]
        if not running:
            return
        for thread in running:
            thread.join(5)
            assert not thread.is_alive()


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

    assert jobs(app)["quiet_hours_boundary"] == 2
    assert {job.at_time.strftime("%H:%M") for job in app.scheduler.get_jobs("quiet_hours")} == {
        "22:00",
        "07:00",
    }


@pytest.fixture
def boundary(make_app, monkeypatch):
    """A map at a quiet-hours boundary, recording what the renderer plays: (app, calls, set_quiet)."""
    app = make_app()
    calls = []
    quiet = {"now": False}
    monkeypatch.setattr(app.renderer, "quiet_hours_active", lambda: quiet["now"])
    spy(monkeypatch, app.renderer, "fade_out", calls)
    spy(monkeypatch, app.renderer, "test_pattern", calls)
    adjust = app.renderer.adjust_brightness_for_time
    monkeypatch.setattr(
        app.renderer, "adjust_brightness_for_time", lambda: (calls.append("adjust"), adjust(), None)[-1]
    )
    return app, calls, lambda value: quiet.update(now=value)


def test_quiet_hours_begin_with_the_sequence_taking_the_map_dark(boundary):
    app, calls, set_quiet = boundary
    app.config.data.led.inittest = True
    set_quiet(True)
    app_module.quiet_hours_boundary(app)
    assert calls == ["fade_out", "adjust"]  # dark the way it lights up, then 0%


def test_quiet_hours_end_with_the_startup_sequence(boundary):
    app, calls, set_quiet = boundary
    app.config.data.led.inittest = True
    set_quiet(False)
    app_module.quiet_hours_boundary(app)
    assert calls == ["adjust", "test_pattern"]  # brightness back, then the map lights up


@pytest.mark.parametrize("quiet", [True, False])
def test_quiet_hours_without_the_startup_sequence_just_switch(boundary, quiet):
    app, calls, set_quiet = boundary
    app.config.data.led.inittest = False
    set_quiet(quiet)
    app_module.quiet_hours_boundary(app)
    assert calls == ["adjust"]


@pytest.mark.parametrize("quiet", [True, False])
def test_no_sequence_while_the_leds_are_at_zero(boundary, quiet, monkeypatch):
    """At night with led.brightness.off at 0%, there's nothing to see."""
    app, calls, set_quiet = boundary
    app.config.data.led.inittest = True
    app.renderer.brightness(0.0)
    monkeypatch.setattr(app.renderer, "brightness_for", lambda now: 0.0)
    set_quiet(quiet)
    app_module.quiet_hours_boundary(app)
    assert calls == ["adjust"]


def test_jobs(make_app):
    app = make_app()
    assert jobs(app) == {
        "update_data": 1,
        "load_suntimes": 1,
        "set_brightness": 4,
        "watch_display": 1,
        "check_releases": 1,
        "refresh": 1,  # the announcement on the network, checked against the address
        "fetch_delays": 1,  # the FAA airport status, every few minutes
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


def test_next_fetch(make_app):
    """The Home page's countdown: the regular fetch every 10 minutes, and when METARs were last fetched."""
    import time

    app = make_app()
    f = app_module.next_fetch(app)
    assert f["next"] == pytest.approx(time.time() + 600, abs=5)
    assert f["seconds"] == 600
    assert f["fetched"] is None  # not fetched in tests
    app.metars.lastFetchTime = datetime(2026, 11, 6, 12, 0)
    assert app_module.next_fetch(app)["fetched"] == datetime(2026, 11, 6, 12, 0).timestamp()


def test_next_fetch_counts_down_to_a_retry_first(make_app):
    import time

    app = make_app()
    app.metars.last_fetch_ok = False
    app_module.retry_soon(app)
    f = app_module.next_fetch(app)
    assert f["seconds"] == 60
    assert f["next"] == pytest.approx(time.time() + 60, abs=5)


def test_a_fetch_by_hand_restarts_the_wait(make_app):
    app = make_app()
    (job,) = app.scheduler.get_jobs("fetch")
    job.next_run = datetime.now() + timedelta(seconds=30)  # nearly due
    app_module.schedule_fetch(app)
    (job,) = app.scheduler.get_jobs("fetch")  # still one
    assert 595 <= (job.next_run - datetime.now()).total_seconds() <= 600


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


def dark_for(monkeypatch, *ids):
    """Every airport's look is off with the visualizers `ids`; the others show something (solid white)."""
    from metarmap.models import Look
    from metarmap.visualizers import visualizer

    monkeypatch.setattr(
        visualizer,
        "looks",
        lambda vis, codes, data, settings: [
            Look.off() if vis.id in ids else Look.solid((255, 255, 255)) for _ in codes
        ],
    )


def test_auto_rotate_skips_the_dark(make_app, monkeypatch):
    app = make_app(**{"visualizer.auto_rotate.skip_dark": True})
    dark_for(monkeypatch, "wind", "wind_gusts")
    app_module.rotate_visualizer(app)
    assert app.renderer.visualizer[1].id == "wind_direction"  # past Wind and Wind Gusts, with nothing to show


def test_auto_rotate_shows_the_dark_with_skip_dark_off(make_app, monkeypatch):
    app = make_app()
    dark_for(monkeypatch, "wind", "wind_gusts")
    app_module.rotate_visualizer(app)
    assert app.renderer.visualizer[1].id == "wind"


def test_auto_rotate_stays_when_every_other_visualizer_is_dark(make_app, monkeypatch):
    app = make_app(**{"visualizer.auto_rotate.skip_dark": True})
    dark_for(monkeypatch, *(v.id for v in visualizers.ALL if v.id != "flight_category"))
    app_module.rotate_visualizer(app)
    assert app.renderer.visualizer[1].id == "flight_category"


def test_skip_dark_leaves_the_buttons_alone(make_app, monkeypatch):
    """Next and previous still go to every visualizer, dark or not."""
    app = make_app(**{"visualizer.auto_rotate.skip_dark": True})
    dark_for(monkeypatch, "wind")
    app.renderer.visualizer_next()
    assert app.renderer.visualizer[1].id == "wind"


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
    assert calls == ["refresh", "adjust", "display.restart"]  # the OLED goes blank (or comes back) now too


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


def test_what_the_micro_shows_changes_now(quiet_app):
    app, calls = quiet_app
    app.config.edit("display_screen.shows", "visualizer")
    assert calls == ["display.restart"]  # and the LEDs aren't refreshed for it


def test_a_new_visualizer_reaches_the_micro(make_app, monkeypatch):
    app = make_app()
    calls = []
    monkeypatch.setattr(app.display, "restart", lambda timeout=None: calls.append(timeout))
    app.config.data.display_screen.shows = "visualizer"
    app.renderer.visualizer_next()
    assert calls == [5]


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
    app_module.update_data(app).join(5)
    assert app.renderer.looks[0].colors[0] == flightcategory.COLORS["VFR"]
    assert brightness == [normal / 2] and app.renderer.pixels().brightness == normal  # dimmed while fetching


@pytest.fixture
def slow_fetch(make_app, monkeypatch):
    """
    A map whose METAR fetch waits for release.set(): (app, release, fetched, entered). entered is set once a fetch has
    begun (inside the lock, past fetch_reports' clearing of refetch_due).
    """
    app = make_app()
    code = app.config.airports[0].code
    release, fetched, entered = threading.Event(), [], threading.Event()

    def fetch():
        entered.set()
        release.wait(5)
        app.metars.data = {code: Report(flight_category="VFR")}
        app.metars.last_fetch_ok = True
        fetched.append(True)
        return True

    monkeypatch.setattr(app.metars, "fetch", fetch)
    yield app, release, fetched, entered
    release.set()


def test_the_main_loop_doesnt_wait_for_the_fetch(slow_fetch):
    """aviationweather.gov has taken 20 s: the job only starts the fetch, so the LEDs keep going meanwhile."""
    app, release, fetched, entered = slow_fetch
    job = app.scheduler.get_jobs("fetch")[0]
    job.next_run = datetime.now() - timedelta(seconds=1)
    app.scheduler.run_pending()  # the main loop's call: back at once
    assert fetched == [] and app.fetching.locked()
    (thread,) = [t for t in threading.enumerate() if t.name == "metars"]
    release.set()
    thread.join(5)
    assert fetched == [True] and not app.fetching.locked()
    assert app.renderer.looks[0].colors[0] == flightcategory.COLORS["VFR"]  # the new data is on the LEDs


def test_a_fetch_due_while_the_last_one_runs_is_skipped(slow_fetch, caplog):
    app, release, fetched, entered = slow_fetch
    first = app_module.update_data(app)
    with caplog.at_level("INFO", logger="metarmap.app"):
        assert app_module.update_data(app) is None  # still fetching: not a second one at the same time
    assert "regular METAR fetch skipped" in caplog.text  # said in the log, not only at debug
    release.set()
    first.join(5)
    assert fetched == [True]
    app_module.update_data(app).join(5)  # the next one runs again
    assert fetched == [True, True]


def test_a_failed_fetch_thread_doesnt_stop_the_next(make_app, monkeypatch, caplog):
    """An error in the fetch's thread is logged, and the next regular fetch still runs."""
    app = make_app()

    def broken(metars):
        raise RuntimeError("boom")

    monkeypatch.setattr(app.metars, "fetch", lambda: True)
    monkeypatch.setattr(app.renderer, "update_data", broken)
    app_module.update_data(app).join(5)
    assert not app.fetching.locked()
    assert "METAR fetch failed: boom" in caplog.text
    assert app_module.update_data(app) is not None  # not skipped as if one were still running


def test_a_retry_waits_for_the_regular_fetch(slow_fetch, monkeypatch):
    """The retry job doesn't fetch on the main loop while the regular fetch is under way in the background."""
    app, release, fetched, entered = slow_fetch
    app.metars.last_fetch_ok = False
    thread = app_module.update_data(app)
    assert app_module.retry_fetch(app) is None and fetched == []  # left for next time, not a CancelJob
    release.set()
    thread.join(5)


def test_a_failing_retry_doesnt_stop_the_leds(slow_fetch):
    """The retry job (every RETRY_SECONDS while aviationweather.gov fails) fetches in the background too."""
    app, release, fetched, entered = slow_fetch
    app.metars.last_fetch_ok = False
    app_module.retry_soon(app)
    (retry,) = app.scheduler.get_jobs("retry")
    retry.next_run = datetime.now() - timedelta(seconds=1)
    app.scheduler.run_pending()  # the main loop's call: back while the fetch is still waiting
    assert fetched == [] and app.fetching.locked()
    release.set()
    wait_for_fetches()
    assert fetched == [True] and not app.fetching.locked()
    assert app.scheduler.get_jobs("retry") == []  # it worked: no more retries
    assert app.renderer.looks[0].colors[0] == flightcategory.COLORS["VFR"]


def test_a_new_airport_during_a_fetch_gets_its_metar_after_it(slow_fetch):
    """The fetch under way may have asked for the old airports: the airport change's fetch comes right after it."""
    app, release, fetched, entered = slow_fetch
    app_module.update_data(app)
    assert entered.wait(5)  # the fetch under way has asked for the airports
    assert app_module.refetch_soon(app) is None  # not at the same time...
    release.set()
    wait_for_fetches()
    assert fetched == [True, True]  # ...but after it
    assert not app.refetch_due.is_set() and not app.fetching.locked()


class WaitingLock:
    """app.fetching, saying (`waiting`) when someone waits for it: GET /fetch, not the background fetches."""

    def __init__(self, lock, waiting):
        self._lock, self._waiting = lock, waiting

    def acquire(self, blocking=True, timeout=-1):
        if blocking:
            self._waiting.set()
        return self._lock.acquire(blocking, timeout)

    def release(self):
        self._lock.release()

    def locked(self):
        return self._lock.locked()


def test_fetch_by_hand_waits_for_a_fetch_under_way(slow_fetch, monkeypatch):
    """GET /fetch runs its fetch after the one under way, never over it (two dims at once can leave the LEDs dim)."""
    app, release, fetched, entered = slow_fetch
    slow, began = app.metars.fetch, []
    monkeypatch.setattr(app.metars, "fetch", lambda: began.append(True) or slow())
    waiting = threading.Event()
    app.fetching = WaitingLock(app.fetching, waiting)
    app_module.update_data(app)
    assert entered.wait(5)
    done = []
    by_hand = threading.Thread(target=lambda: done.append(app_module.refetch_metars(app)))
    by_hand.start()
    assert waiting.wait(5)  # GET /fetch is waiting for the lock the fetch under way holds...
    assert len(began) == 1 and done == []  # ...not fetching alongside it
    release.set()
    by_hand.join(5)
    wait_for_fetches()
    assert done == [True] and fetched == [True, True]


def test_fetch_by_hand_gives_up_on_a_stuck_fetch(make_app, monkeypatch):
    app = make_app()
    monkeypatch.setattr(app_module, "FETCH_WAIT_SECONDS", 0.01)
    monkeypatch.setattr(app.metars, "fetch", lambda: pytest.fail("fetched over the fetch under way"))
    with app.fetching:  # a fetch under way
        assert app_module.refetch_metars(app) is False


def test_a_fetch_by_hand_that_fails_says_so(make_app, monkeypatch, caplog):
    """GET /fetch's fetch raising: logged, the lock let go, and raised again for /fetch to answer 500."""
    app = make_app()
    monkeypatch.setattr(app.metars, "fetch", lambda: True)
    monkeypatch.setattr(app.renderer, "update_data", lambda metars: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError, match="boom"):
        app_module.refetch_metars(app)
    assert not app.fetching.locked()
    assert "METAR fetch failed: boom" in caplog.text
    monkeypatch.setattr(app.renderer, "update_data", lambda metars: None)
    assert app_module.refetch_metars(app) is True  # the next one runs


def test_a_retry_that_raises_keeps_retrying(make_app, monkeypatch, caplog):
    """An error in the retry's thread is logged; the retry job stays, and the lock is let go."""
    app = make_app()
    app.metars.last_fetch_ok = False
    monkeypatch.setattr(app.metars, "fetch", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    app_module.retry_soon(app)
    (retry,) = app.scheduler.get_jobs("retry")
    retry.next_run = datetime.now() - timedelta(seconds=1)
    app.scheduler.run_pending()
    wait_for_fetches()
    assert not app.fetching.locked() and "METAR retry failed: boom" in caplog.text
    assert app.scheduler.get_jobs("retry") == [retry]


def test_new_data_keeps_the_forecast_step(make_app, monkeypatch):
    """The regular fetch landing mid-forecast doesn't take Flight Category Forecast back to Now."""
    from metarmap.clock import FakeClock

    app = make_app(**{"visualizer.active": "flight_category_forecast"})
    clock = FakeClock()
    monkeypatch.setattr(app.renderer, "_clock", clock)
    app.renderer.refresh()  # counted from the fake clock's now
    seconds = app.renderer._vis.steps(app.config.data)["seconds"]
    clock.advance(seconds * 1.5)
    assert app.renderer.step()["index"] == 1
    monkeypatch.setattr(app.metars, "fetch", lambda: True)
    app_module.update_data(app).join(5)
    assert app.renderer.step()["index"] == 1  # still +3h


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


def test_run_shows_the_splash_first(make_app, monkeypatch):
    """ "MetarMap2" and the logo on the Micro before anything else starts; the OLED loop waits it out."""
    app = make_app(**{"led.inittest": True, "display_screen.enabled": True})
    monkeypatch.setattr(app_module, "create_app", lambda services: FakeWebApp(services))
    monkeypatch.setattr(app_module, "serve", lambda web, host, port: None)
    order = []
    monkeypatch.setattr(app.display, "splash", lambda: order.append("splash"))
    monkeypatch.setattr(app.renderer, "test_pattern", lambda: order.append("test pattern"))
    monkeypatch.setattr(app.display, "start", lambda locate_delay: order.append("display"))
    monkeypatch.setattr(app.renderer, "render", lambda: (_ for _ in ()).throw(KeyboardInterrupt()))

    app_module.run(app)

    assert order == ["splash", "test pattern", "display"]


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

    app_module.update_data(app).join(5)  # e.g. aviationweather.gov answers 502
    (retry,) = app.scheduler.get_jobs("retry")
    assert retry.interval == app_module.RETRY_SECONDS and retry.unit == "seconds"
    app_module.update_data(app).join(5)  # failing again doesn't add a second retry
    assert len(app.scheduler.get_jobs("retry")) == 1

    retry.next_run = datetime.now() - timedelta(seconds=1)  # only the retry is due
    app.scheduler.run_pending()  # it works this time, so it stops
    wait_for_fetches()  # (in the background)
    assert app.scheduler.get_jobs("retry") == []
    assert jobs(app)["update_data"] == 1  # the regular fetch is still there


def test_a_failed_fetch_at_startup_is_retried(tmp_path, monkeypatch):
    import requests
    from metarmap import metar
    from metarmap.leds.strip import FakeStrip
    from metarmap.oled.screen import FakeScreen

    def bad_gateway(url, **kwargs):
        raise requests.exceptions.HTTPError("502 Server Error: Bad Gateway")

    monkeypatch.setattr(metar.http, "get", bad_gateway)
    (tmp_path / "config.json").write_text((REPO / "config.json").read_text())
    app = app_module.build(str(tmp_path / "config.json"), strip=FakeStrip(50), screen=FakeScreen())
    assert app.metars.last_fetch_ok is False
    assert len(app.scheduler.get_jobs("retry")) == 1


def _build_with_a_fetch(tmp_path, monkeypatch, locate):
    """Builds a map that fetches (METARs fine, nothing from the network) whose station lookup is `locate`."""
    from metarmap import metar
    from metarmap.leds.strip import FakeStrip
    from metarmap.oled.screen import FakeScreen

    def fetch(self, callback=None, locate=True):
        self.last_fetch_ok = True
        return True

    monkeypatch.setattr(metar.Reports, "fetch", fetch)
    monkeypatch.setattr(metar.Reports, "locate", locate)
    (tmp_path / "config.json").write_text((REPO / "config.json").read_text())
    return app_module.build(str(tmp_path / "config.json"), strip=FakeStrip(50), screen=FakeScreen())


def _wait_for_the_lookup():
    for thread in threading.enumerate():
        if thread.name == "stations":
            thread.join(timeout=5)
            assert not thread.is_alive()


def test_the_station_lookup_does_not_hold_up_startup(tmp_path, monkeypatch):
    """aviationweather.gov's station lookup has taken 20 s; the map is built while it is still going."""
    release, finished = threading.Event(), []

    def slow_locate(self):
        release.wait(timeout=5)
        finished.append(True)
        return True

    app = _build_with_a_fetch(tmp_path, monkeypatch, slow_locate)
    try:
        assert finished == []  # build() came back before the lookup did
        assert app.metars.last_fetch_ok is True
    finally:
        release.set()
    _wait_for_the_lookup()
    assert finished == [True]
    assert app.scheduler.get_jobs("retry") == []


def test_a_failed_station_lookup_at_startup_is_retried(tmp_path, monkeypatch):
    def failing_locate(self):
        self.locate_failed = True
        return False

    app = _build_with_a_fetch(tmp_path, monkeypatch, failing_locate)
    _wait_for_the_lookup()
    assert len(app.scheduler.get_jobs("retry")) == 1  # redone every RETRY_SECONDS, like a failed fetch


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

    app_module.update_data(app).join(5)
    (retry,) = app.scheduler.get_jobs("retry")
    for _ in range(2):
        retry.next_run = datetime.now() - timedelta(seconds=1)
        app.scheduler.run_pending()
        wait_for_fetches()
    assert calls == ["fetch", "locate", "locate"]
    assert app.scheduler.get_jobs("retry") == []


def test_names_are_filled_after_a_fetch(make_app, monkeypatch):
    app = make_app()
    first = app.config.airports[0]
    first.name = ""
    monkeypatch.setattr(app.metars, "fetch", lambda: True)
    monkeypatch.setattr(app.metars, "station_names", lambda: {first.code: "Somewhere Muni"})
    app_module.update_data(app).join(5)
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
    monkeypatch.setattr(metar.Reports, "fetch", lambda self, callback=None, locate=True: True)
    monkeypatch.setattr(app_module, "locate_soon", lambda app: None)  # it shows the areas too: not what this is about
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


# ---- advisories, TFRs and FAA status: tried again until each has loaded once -----------------------------------------


class Feed:
    """What retry_feeds() asks of a feed: advisories (waiting, failed), TFRs and delays (fetched, error)."""

    def __init__(self, fetched=None, error=None, waiting=True, failed=False):
        self.fetched, self.error, self._waiting, self._failed = fetched, error, waiting, failed

    def waiting(self):
        return self._waiting

    def failed(self):
        return self._failed


@pytest.fixture
def feeds(make_app, monkeypatch):
    """A map whose three feeds can be set to loaded, failed or still on their way; (app, what was asked again)."""
    app = make_app()
    app.advisories, app.tfrs, app.delays = Feed(), Feed(), Feed()
    asked = []
    for name in ("fetch_advisories_soon", "fetch_tfrs", "fetch_delays"):
        monkeypatch.setattr(app_module, name, lambda app, name=name: asked.append(name))
    return app, asked


def test_feeds_waiting_are_the_ones_never_loaded(feeds):
    app, _ = feeds
    assert app_module.feeds_waiting(app) == ["advisories", "TFR", "FAA status"]
    app.tfrs.fetched = 1000.0
    app.advisories._waiting = False
    assert app_module.feeds_waiting(app) == ["FAA status"]


def test_a_map_without_a_feed_doesnt_wait_for_it(feeds):
    app, _ = feeds
    app.advisories = app.tfrs = app.delays = None
    assert app_module.feeds_waiting(app) == []
    assert app_module.retry_feeds(app) is not None  # CancelJob: there is nothing to wait for


def test_only_feeds_whose_try_failed_are_asked_again(feeds):
    app, asked = feeds
    app.advisories._failed = True
    app.delays.error = "couldn't get the FAA airport status: down"
    app_module.retry_feeds(app)  # the TFR list is still on its way: left to finish
    assert asked == ["fetch_advisories_soon", "fetch_delays"]


def test_the_retry_ends_once_every_feed_has_loaded(feeds):
    app, asked = feeds
    app.advisories._waiting = False
    app.tfrs.fetched = app.delays.fetched = 1000.0
    assert app_module.retry_feeds(app) is schedule.CancelJob
    assert asked == []


def test_a_feed_that_loaded_once_is_not_asked_again_by_the_retry(feeds):
    app, asked = feeds
    app.tfrs.fetched, app.tfrs.error = 1000.0, "couldn't get the TFR list"  # a later failure keeps the old list
    app.advisories._waiting = False
    app.delays.fetched = 1000.0
    assert app_module.retry_feeds(app) is schedule.CancelJob and asked == []


def test_the_retry_is_scheduled_with_the_startup_fetches_only(make_app, monkeypatch, tmp_path):
    from metarmap.leds.strip import FakeStrip
    from metarmap.oled.screen import FakeScreen
    from metarmap.settings import Settings

    for name in ("fetch_advisories_soon", "fetch_tfrs", "fetch_delays", "fetch_forecasts", "locate_soon"):
        monkeypatch.setattr(app_module, name, lambda app: None)
    monkeypatch.setattr(app_module, "schedule_fetch", lambda app: None)
    config = Settings.load(REPO / "config.json")
    config.save(tmp_path / "config.json")
    for fetch, expected in ((True, 1), (False, 0)):
        app = app_module.build(
            str(tmp_path / "config.json"), strip=FakeStrip(config.led.count), screen=FakeScreen(), fetch=fetch
        )
        assert jobs(app)["retry_feeds"] == expected


def test_a_retry_says_so_once_per_feed(feeds, caplog):
    import logging

    app, asked = feeds
    app.advisories._failed = True
    with caplog.at_level(logging.INFO, logger=app_module.log.name):
        for _ in range(3):
            app_module.retry_feeds(app)
    said = [r for r in caplog.records if "trying again" in r.getMessage()]
    assert len(said) == 1 and asked == ["fetch_advisories_soon"] * 3  # asked every time, said once
    app.advisories._waiting = app.advisories._failed = False
    app.tfrs.fetched = app.delays.fetched = 1000.0
    assert app_module.retry_feeds(app) is schedule.CancelJob
    assert app_module._retrying == set()  # said again next time it's needed
