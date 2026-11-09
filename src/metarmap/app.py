"""
The METAR map: builds every part from config.json, schedules the periodic jobs and runs the main loop.

build() wires the parts together without starting anything, so a map can be built on fake hardware in tests;
run() starts the web server and the OLED loop and drives the LEDs until stopped. main() is `python -m metarmap`
(`--port 8080` to use another web port for that run, e.g. on a computer, where port 80 needs sudo).
"""

import argparse
import fnmatch
import logging
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import schedule

from metarmap import __version__, logs, service, visualizers
from metarmap.atis import Atis
from metarmap.speech import Speech
from metarmap.advisories import Advisories
from metarmap.tfr import Tfrs
from metarmap.clock import Clock
from metarmap.config import Config
from metarmap.display import STARTUP_LOCATE_DELAY, Display
from metarmap.leds.strip import open_strip
from metarmap.metar import Reports
from metarmap.oled.screen import open_screen
from metarmap.releases import CHECK_HOURS, ReleaseCheck
from metarmap.renderer import Renderer
from metarmap.sun import LEVEL_AT, SunTimes
from metarmap.traffic import Traffic
from metarmap.web import create_app, serve

log = logging.getLogger(__name__)

CONFIG_FILE = "config.json"
METAR_MINUTES = 10  # how often METARs are fetched
RETRY_SECONDS = 60  # after a failed fetch or lookup (e.g. aviationweather.gov answering 502), how soon to try again
WATCHDOG_SECONDS = 15  # how often the OLED loop is checked


@dataclass
class App:
    """Every part of a map. The web server and the scheduled jobs reach the others through this."""

    config: Config
    sun: SunTimes
    metars: Reports
    renderer: Renderer
    display: Display  # always built; its loop runs while display_screen.enabled is on
    scheduler: schedule.Scheduler
    releases: Optional[ReleaseCheck] = None  # what's newest on GitHub, for "Update available"
    traffic: Optional[Traffic] = None  # live traffic for the Map page, fetched while a page asks for it
    advisories: Optional[Advisories] = None  # G-AIRMETs and SIGMETs, for Advisories (fetched with the METARs)
    tfrs: Optional[Tfrs] = None  # TFRs, for the TFR visualizer (fetched in the background with the METARs)
    speech: Optional[Speech] = None  # the METARs read aloud by a speech server (Piper or Kokoro), when one is set
    atis: Optional[Atis] = None  # the digital ATIS from atis.info, for the spoken ATIS (speech.atis)


# ---- building ------------------------------------------------------------------------------------------------


def build(config_file=CONFIG_FILE, strip=None, screen=None, clock: Clock = None, fetch=True) -> App:
    """
    Builds the map from config_file, with its jobs scheduled but nothing running yet.
    The LED strip and OLED screen are opened unless given; METARs are fetched unless fetch=False.
    """
    config = Config(config_file)
    sun = SunTimes(config.data.geo.city)
    sun.reload()

    log.info("Get weather for all airports...")
    advisories = Advisories()  # fetched in the background below: the map doesn't wait for them
    tfrs = Tfrs(nearby=lambda: config.data.tfr.nearby_nm)
    metars = Reports(config, fetch=fetch, clock=clock, advisories=advisories, tfrs=tfrs)

    if strip is None:
        strip = open_strip(config.data.led)  # the NeoPixel strip on the Pi; an in-memory strip anywhere else
    renderer = Renderer(strip, metars, config, list(visualizers.ALL), sun, clock=clock)
    renderer.visualizer = config.data.visualizer.active

    # built even when display_screen.enabled is off, so it can be turned on without a restart
    if screen is None:
        screen = open_screen()  # the OLED on the Pi; an in-memory screen anywhere else (the web UI mirrors it)
    display = Display(config, metars, screen, renderer=renderer, clock=clock)

    releases = ReleaseCheck(
        channel=lambda: config.data.update_channel(),
        branch=lambda: config.data.update.branch,
        dev_mode=lambda: config.data.dev_mode,
    )
    traffic = Traffic(
        lambda: config.data.geo.map,
        lambda: [p for p in (metars.position(a.code) for a in config.airports if a.code) if p],
    )
    speech = Speech(lambda: config.data.speech)
    atis = Atis(lambda: config.data.speech.enabled and config.data.speech.atis)
    app = App(
        config, sun, metars, renderer, display, schedule.Scheduler(), releases, traffic, advisories, tfrs, speech, atis
    )
    fill_names(app)
    schedule_jobs(app)
    wire_config(app)
    if fetch:
        # in the background, so a slow aviationweather.gov or FAA doesn't hold up the map; the LEDs show them when
        # they come (the first TFR list has a few dozen details to fetch)
        fetch_advisories_soon(app)
        fetch_tfrs(app)
        atis.available()  # with spoken ATIS on, which airports have one (in the background): the pages' ATIS buttons
    return app


def schedule_jobs(app: App):
    s = app.scheduler
    schedule_fetch(app)
    if needs_retry(app):  # the fetch or lookup at startup failed
        retry_soon(app)
    s.every().day.at("00:00").do(load_suntimes, app)  # new sun times every day, to dim the map at the right times
    schedule_brightness(app)
    schedule_quiet_hours(app)
    s.every(WATCHDOG_SECONDS).seconds.do(watch_display, app)
    s.every(CHECK_HOURS).hours.do(check_releases, app)
    schedule_rotation(app)
    # a visualizer picked by hand (or the previous/next buttons) gets the full auto-rotate delay before the next change
    app.renderer.subscribe(lambda: schedule_rotation(app))
    app.renderer.subscribe(app.display.visualizer_changed)  # the Micro's Visualizer mode shows the new one


def schedule_fetch(app: App):
    """
    The regular fetch every METAR_MINUTES, the wait starting now: at startup, and after a fetch by hand (/fetch), so
    the next one is a whole interval later instead of maybe a minute.
    """
    app.scheduler.clear("fetch")
    app.scheduler.every(METAR_MINUTES).minutes.do(update_data, app).tag("fetch")


UNIT_SECONDS = {"seconds": 1, "minutes": 60, "hours": 3600}  # a schedule job's unit, in seconds


def next_fetch(app: App) -> dict:
    """
    When METARs are next fetched (Unix time; None if nothing is scheduled) and that job's interval in seconds: the
    regular fetch, or a retry after a failed one if that comes first. With when they were last fetched, for the Home
    page's countdown.
    """
    jobs = [j for tag in ("fetch", "retry") for j in app.scheduler.get_jobs(tag) if j.next_run is not None]
    soonest = min(jobs, key=lambda j: j.next_run, default=None)
    fetched = app.metars.lastFetchTime
    return {
        "next": soonest.next_run.timestamp() if soonest else None,  # schedule's times are the map's local time
        "seconds": soonest.interval * UNIT_SECONDS[soonest.unit] if soonest else None,
        "fetched": fetched.timestamp() if fetched else None,
    }


def schedule_rotation(app: App):
    """
    Schedules auto-rotate from the settings, starting the wait now; called again when they change, so they need no
    restart, and when the visualizer changes, so one picked by hand is shown for the whole delay.
    """
    app.scheduler.clear("rotate_visualizer")
    rotate = app.config.data.visualizer.auto_rotate
    if rotate.enabled:
        app.scheduler.every(rotate.delay_seconds).seconds.do(rotate_visualizer, app).tag("rotate_visualizer")


def next_rotation(app: App) -> Optional[float]:
    """When auto-rotate next changes the visualizer (Unix time), or None when it's off."""
    runs = [job.next_run for job in app.scheduler.get_jobs("rotate_visualizer") if job.next_run is not None]
    return min(runs).timestamp() if runs else None  # schedule's times are the map's local time


# ---- following config changes ----------------------------------------------------------------------------------

# changes that don't change what the LEDs show
NOT_ON_LEDS = ("airports.name", "web_server.*", "led.init_*", "display_screen.shows")
# changes to what the OLED loop shows, or in which order; it starts over with the new list (names aren't on it)
OLED_AIRPORTS = (
    "airports.code",
    "airports.display",
    "airports.order",
    "airports.mock",
    "led.count",
    "led.virtual_count",
)


def wire_config(app: App):
    """
    What each config change does right away, so none needs a restart. Config publishes the keys that changed
    (config.Config.subscribe); the web routes only change the config. In order: a reaction that needs another's
    result comes after it (the strip is resized and the METARs reprocessed before the LEDs are refreshed).
    """
    on = app.config.subscribe
    renderer = app.renderer

    # the in-memory strip changes now; a NeoPixel strip after a restart
    on("led.count", lambda keys: renderer.resize(app.config.data.led.count))
    # reprocessed: the TFRs near each airport, measured with the new distance; a mock METAR in place of the real one
    on(("tfr.nearby_nm", "airports.mock"), lambda keys: show_areas(app))
    on("*", lambda keys: renderer.refresh() if any(not _matches(k, NOT_ON_LEDS) for k in keys) else None)
    on("visualizer.auto_rotate.*", lambda keys: schedule_rotation(app))
    on(
        "led.quiet_hours.*",
        # the OLED loop starts over: blank now, or showing again now
        lambda keys: (
            schedule_quiet_hours(app),
            renderer.adjust_brightness_for_time(),
            app.display.restart(timeout=15),
        ),
    )
    # the level in use now changes now; the others at their time
    on("led.brightness.*", lambda keys: brightness_changed(app, keys))
    # shows what it looks like, without a restart
    on("led.inittest", lambda keys: show_test_pattern(app) if app.config.data.led.inittest else None)
    on(("led.init_sequence", "led.init_sweep_from"), lambda keys: show_test_pattern(app))  # try one: it plays now
    on(("update.channel", "update.branch"), lambda keys: check_releases(app))  # "Update available" follows it
    on("display_screen.enabled", lambda keys: display_enabled(app))
    on(OLED_AIRPORTS, lambda keys: app.display.restart(timeout=15))
    on("display_screen.shows", lambda keys: app.display.restart(timeout=15))  # airports or the visualizer, now
    on("airports.code", lambda keys: airport_codes_changed(app))


def _matches(key, patterns):
    return any(fnmatch.fnmatchcase(key, p) for p in patterns)


def brightness_changed(app: App, keys):
    if any(k.rsplit(".", 1)[1] == app.renderer.scheduled_level() for k in keys):
        app.renderer.adjust_brightness_for_time()


def show_test_pattern(app: App):
    threading.Thread(target=app.renderer.test_pattern, name="test-pattern", daemon=True).start()


def display_enabled(app: App):
    """display_screen.enabled: the OLED turns on or off now."""
    app.display.turn_on() if app.config.data.display_screen.enabled else app.display.turn_off()


def airport_codes_changed(app: App):
    """
    A new airport code: its name now (looked up if need be), so the Airports page shows it when it reloads; its
    METAR in the background.
    """
    unnamed = {a.code for a in app.config.airports if a.code and not a.name}
    app.config.fill_names({code: app.metars.name_for(code) for code in unnamed})
    threading.Thread(target=refetch_metars, args=(app,), name="fetch", daemon=True).start()


def refetch_metars(app: App):
    """Only the METARs (an airport changed), not the advisories and TFRs that update_data() also fetches."""
    with app.renderer.dimmed():
        app.metars.fetch()
    app.renderer.update_data(app.metars)
    fill_names(app)


# ---- scheduled jobs ------------------------------------------------------------------------------------------


def update_data(app: App):
    fetch_advisories(app)
    fetch_tfrs(app)
    with app.renderer.dimmed():
        app.metars.fetch()  # adds the G-AIRMET hazards to each report
    app.renderer.update_data(app.metars)
    fill_names(app)
    if needs_retry(app):
        retry_soon(app)


def fetch_advisories(app: App):
    """New G-AIRMETs and SIGMETs; the METARs pick them up when next processed. Keeps the old ones if it fails."""
    if app.advisories is not None and app.advisories.fetch():
        app.metars.apply_mocks()  # reapplied now, in case the METAR fetch after this fails


def fetch_advisories_soon(app: App):
    """At startup: the G-AIRMETs and SIGMETs in the background; the LEDs show them when they come."""

    def fetch():
        started = time.monotonic()
        if app.advisories.fetch():
            log.info(f"advisories fetched in {time.monotonic() - started:.1f}s")
            show_areas(app)

    if app.advisories is not None:
        threading.Thread(target=fetch, name="advisories", daemon=True).start()


def fetch_tfrs(app: App):
    """Fetches the TFRs in the background; the LEDs show them when it's done."""
    if app.tfrs is not None:
        app.tfrs.fetch_soon(then=lambda: show_areas(app))


def show_areas(app: App):
    """The reports again, with the advisory and TFR areas each airport is in (or near), on the LEDs."""
    app.metars.apply_mocks()  # adds them to each report
    app.renderer.update_data(app.metars)


def fill_names(app: App):
    """Airports with an empty name get the name the station lookup found (saved to config.json)."""
    filled = app.config.fill_names(app.metars.station_names())
    if filled:
        log.info(f"filled in the names of {filled} airports")


def needs_retry(app: App):
    """Whether the METAR fetch, or the lookup of where airports without a report are, failed."""
    return app.metars.last_fetch_ok is False or app.metars.locate_failed


def retry_soon(app: App):
    """Tries again every RETRY_SECONDS until it works, instead of waiting for the next regular fetch."""
    if not app.scheduler.get_jobs("retry"):
        what = "METAR fetch" if app.metars.last_fetch_ok is False else "airport position lookup"
        log.warning(f"{what} failed; trying again every {RETRY_SECONDS} s until it works")
        app.scheduler.every(RETRY_SECONDS).seconds.do(retry_fetch, app).tag("retry")


def retry_fetch(app: App):
    """Redoes what failed: the fetch (which also does the lookup), or only the lookup."""
    if app.metars.last_fetch_ok is False:
        with app.renderer.dimmed():
            fetched = app.metars.fetch()
        if fetched:
            app.renderer.update_data(app.metars)
    elif app.metars.locate_failed:
        app.metars.locate()
    fill_names(app)
    if not needs_retry(app):
        return schedule.CancelJob


def load_suntimes(app: App):
    log.info("load suntimes")
    app.sun.reload()
    schedule_brightness(app)


def schedule_brightness(app: App):
    """Sets the LEDs' brightness at each of today's sun times (dimmed at dawn, normal at sunrise, ...)."""
    app.scheduler.clear("suntimes")
    for name, level in LEVEL_AT.items():
        at = app.sun.times[name].strftime("%H:%M")
        app.scheduler.every().day.at(at).do(set_brightness, app, level=level).tag("suntimes")


def schedule_quiet_hours(app: App):
    """Recreate local-time quiet-hours boundary jobs after a configuration change."""
    app.scheduler.clear("quiet_hours")
    night = app.config.data.led.quiet_hours
    if night.enabled and night.start != night.end:
        for at in (night.start, night.end):
            app.scheduler.every().day.at(at).do(quiet_hours_boundary, app).tag("quiet_hours")


def quiet_hours_boundary(app: App):
    """
    Quiet hours' start or end time. With the startup sequence on (led.inittest), the map goes dark with it at the
    start (Renderer.fade_out) and lights up with it at the end. Not when the LEDs are at 0% anyway (led.brightness.off
    at night), and not for a settings change, which switches the LEDs at once.
    """
    renderer = app.renderer
    play = app.config.data.led.inittest
    if renderer.quiet_hours_active():
        if play and renderer.pixels().brightness > 0:
            renderer.fade_out()
        renderer.adjust_brightness_for_time()
    else:
        renderer.adjust_brightness_for_time()
        if play and renderer.pixels().brightness > 0:
            renderer.test_pattern()


def set_brightness(app: App, level):
    """
    level: a led.brightness setting's name ("dimmed"), read when the job runs so a changed level needs no restart;
    or a brightness (0.25).
    """
    if isinstance(level, str):
        level = getattr(app.config.data.led.brightness, level)
    # The renderer owns the scheduled brightness and quiet-hours override.
    if app.renderer.quiet_hours_active():
        level = 0.0
    log.info("set brightness: " + str(level))
    app.renderer.brightness(level)


def check_releases(app: App):
    """Asks GitHub whether there's a newer release (in the background), for the web UI's "Update available"."""
    if app.releases is not None:
        app.releases.check_soon()


def rotate_visualizer(app: App):
    rotate = app.config.data.visualizer.auto_rotate
    app.renderer.visualizer_next(skip_exclusive=True, skip=rotate.skip, skip_dark=rotate.skip_dark)


def watch_display(app: App):
    """
    Restarts the OLED loop if its thread died or it hasn't moved on for a while.
    """
    disp = app.display
    if not app.config.data.display_screen.enabled or not disp.on:
        return  # turned off
    reason = disp.stalled()
    if reason:
        log.warning(f"display watchdog: {reason}; restarting")
        try:
            disp.restart(timeout=5)
        except Exception as e:
            # an exception here would end the main loop; just try again next time
            log.exception(f"display watchdog restart failed: {e}")


# ---- running -------------------------------------------------------------------------------------------------


def run(app: App, port=None):
    """
    Starts the web server and the OLED loop, then drives the LEDs until Ctrl-C, SIGTERM or an error.
    port: the web server's port for this run (--port), else web_server.port; it isn't saved to config.json.
    """
    port = port or app.config.data.web_server.port
    if app.config.data.display_screen.enabled:
        app.display.splash()  # "MetarMap2" and the logo, at least SPLASH_SECONDS while the rest starts

    # test pattern on pixels?
    if app.config.data.led.inittest:
        app.renderer.test_pattern()

    if app.releases is not None:
        app.releases.load_build()  # what's running, for the header (an update changes the files before a restart)
    web_app = create_app(app)
    check_releases(app)  # then every CHECK_HOURS
    try:
        web_server = serve(web_app, "0.0.0.0", port)
    except OSError as e:
        # e.g. the port is in use; the LEDs and OLED still run
        log.error(f"web server can't start on port {port}: {e}")
        web_server = None

    log.info("Main loop...")
    app.renderer.draw_frame()  # the visualizer first, then the OLED loop's first "Highlight active airport" pulse
    if app.config.data.display_screen.enabled:
        app.display.start(locate_delay=STARTUP_LOCATE_DELAY)
    try:
        while True:
            app.renderer.render()
            app.scheduler.run_pending()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        log.exception(f"main loop stopped: {e}")
    finally:
        shutdown(app, web_app, web_server)


def shutdown(app: App, web_app, web_server):
    log.info("Cleaning up...")
    app.scheduler.clear()
    app.display.stop()
    app.renderer.stop()
    app.renderer.clear()
    if web_server is not None:
        web_server.shutdown()
        web_server.server_close()
    web_app.close()


def pingable(host):
    """Whether one ping to `host` gets an answer."""
    return subprocess.run(["ping", "-c", "1", host], capture_output=True).returncode == 0


def wait_for_internet():
    log.info("Testing to see if internet (8.8.8.8) is reachable...")
    while not pingable("8.8.8.8"):
        log.info(".")
        time.sleep(1)
    log.info("done.")


# ---- process setup -------------------------------------------------------------------------------------------


def log_thread_exception(args):
    """
    Uncaught exceptions in background threads only go to stderr by default; put them in the log too.
    """
    name = args.thread.name if args.thread else "?"
    log.error(f"uncaught exception in thread {name}", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))


def log_uncaught_exception(exc_type, exc_value, exc_traceback):
    """
    A crash in the main thread: in the log, and (as an error) on the console, which systemd keeps in the journal.
    Python's own printout would be a second copy there, so it's only used for Ctrl-C.
    """
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
    else:
        log.critical("uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))


def signal_handler(sig, frame):
    raise KeyboardInterrupt


def port_number(text):
    try:
        port = int(text)
    except ValueError:
        port = 0
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError(f"{text!r} isn't a port number (1 to 65535)")
    return port


def parse_args(argv=None):
    """The command line: python -m metarmap [--port PORT]. argv: without the program name (sys.argv[1:] if None)."""
    parser = argparse.ArgumentParser(prog="python -m metarmap", description="Runs the METAR map.")
    parser.add_argument(
        "--port",
        type=port_number,
        help="the web server's port for this run, instead of web_server.port in config.json "
        "(which it doesn't change), e.g. 8080 on a computer, where port 80 needs sudo",
    )
    parser.add_argument("--version", action="version", version=f"metarmap {__version__}")
    return parser.parse_args(argv)


def main(config_file=CONFIG_FILE, argv=None):
    args = parse_args(argv)
    logs.configure()  # metarmap.log next to config.json, warnings also to the journal
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    threading.excepthook = log_thread_exception
    sys.excepthook = log_uncaught_exception

    log.info(f"Starting metarmap {__version__} at " + datetime.now().strftime("%d/%m/%Y %H:%M"))
    try:
        service.migrate()  # an installed metarmap.service that still runs controller.py
    except Exception as e:
        log.exception(f"service file check failed: {e}")
    wait_for_internet()
    run(build(config_file), port=args.port)
