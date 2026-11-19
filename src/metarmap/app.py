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
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import schedule

from metarmap import __version__, logs, service, visualizers
from metarmap.advisories import Advisories
from metarmap.atis import Atis
from metarmap.clock import Clock
from metarmap.config import Config
from metarmap.delays import DELAYS_MINUTES, Delays
from metarmap.discovery import Discovery
from metarmap.display import STARTUP_LOCATE_DELAY, Display
from metarmap.feeds import Feeds
from metarmap.forecast import Forecasts
from metarmap.leds.strip import open_strip
from metarmap.lighting import Lighting
from metarmap.metar import Reports
from metarmap.oled.screen import open_screen
from metarmap.releases import CHECK_HOURS, ReleaseCheck
from metarmap.renderer import Renderer
from metarmap.rotation import Rotation
from metarmap.speech import Speech
from metarmap.sun import SunTimes
from metarmap.tfr import Tfrs
from metarmap.traffic import Traffic
from metarmap.web import create_app, serve
from metarmap.web.site import my_ip

log = logging.getLogger(__name__)

CONFIG_FILE = "config.json"
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
    forecasts: Optional[Forecasts] = None  # TAFs, for the forecast visualizers (fetched in the background)
    discovery: Optional[Discovery] = None  # announces the map on the network (zeroconf), for the Copilot's map list
    delays: Optional[Delays] = None  # the FAA airport status, for FAA Delays (fetched in the background)
    feeds: Feeds = field(init=False)  # fetching the feeds and trying again (built from the parts above)
    rotation: Rotation = field(init=False)  # auto-rotate
    lighting: Lighting = field(init=False)  # brightness by the sun and quiet hours

    def __post_init__(self):
        # Feeds keeps its own references to the feeds above: they are fixed once the App is built
        self.feeds = Feeds(
            self.config,
            self.metars,
            self.renderer,
            self.scheduler,
            advisories=self.advisories,
            tfrs=self.tfrs,
            delays=self.delays,
            forecasts=self.forecasts,
        )
        self.rotation = Rotation(self.config, self.renderer, self.scheduler)
        self.lighting = Lighting(self.config, self.renderer, self.sun, self.scheduler)

    # what the web layer calls (web.services.Services), so it never imports this module
    def refetch_metars(self) -> bool:
        return self.feeds.refetch_metars()

    def schedule_fetch(self) -> None:
        self.feeds.schedule_fetch()

    def next_fetch(self) -> dict:
        return self.feeds.next_fetch()

    def next_rotation(self) -> Optional[float]:
        return self.rotation.next_rotation()


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
    # the station lookup (where airports without a report are, and the names) is done in the background below
    forecasts = Forecasts()
    delays = Delays()
    metars = Reports(
        config,
        fetch=fetch,
        clock=clock,
        advisories=advisories,
        tfrs=tfrs,
        locate_now=False,
        forecasts=forecasts,
        delays=delays,
    )

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
        config,
        sun,
        metars,
        renderer,
        display,
        schedule.Scheduler(),
        releases,
        traffic,
        advisories,
        tfrs,
        speech,
        atis,
        forecasts,
        Discovery(config, address=my_ip, build=lambda: releases.build),
        delays,
    )
    app.feeds.fill_names()
    schedule_jobs(app)
    wire_config(app)
    if fetch:
        # in the background, so a slow aviationweather.gov or FAA doesn't hold up the map; the LEDs show them when
        # they come (the first TFR list has a few dozen details to fetch)
        app.feeds.start()
        atis.available()  # with spoken ATIS on, which airports have one (in the background): the pages' ATIS buttons
    return app


DISCOVERY_MINUTES = 5  # how often the announcement is checked against the address


def schedule_jobs(app: App):
    s = app.scheduler
    app.feeds.schedule_fetch()
    if app.feeds.needs_retry():  # the fetch or lookup at startup failed
        app.feeds.retry_soon()
    app.lighting.schedule_all()
    s.every(WATCHDOG_SECONDS).seconds.do(watch_display, app)
    s.every(CHECK_HOURS).hours.do(check_releases, app)
    if app.discovery is not None:
        s.every(DISCOVERY_MINUTES).minutes.do(app.discovery.refresh)  # a new address, or no network at first
    s.every(DELAYS_MINUTES).minutes.do(app.feeds.fetch_delays)  # ground stops come and go faster than the METARs
    app.rotation.schedule()
    # a visualizer picked by hand (or the previous/next buttons) gets the full auto-rotate delay before the next change
    app.renderer.subscribe(app.rotation.schedule)
    app.renderer.subscribe(app.display.visualizer_changed)  # the Micro's Visualizer mode shows the new one


# ---- following config changes ----------------------------------------------------------------------------------

# changes that don't change what the LEDs show
NOT_ON_LEDS = (
    "airports.name",
    "web_server.*",
    "led.init_*",
    "display_screen.shows",
    "visualizer.auto_rotate.skip",  # only who auto-rotate picks next
)
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
    on(("tfr.nearby_nm", "airports.mock", "visualizer.forecast_include_tempo"), lambda keys: app.feeds.show_areas())
    on("*", lambda keys: renderer.refresh() if any(not _matches(k, NOT_ON_LEDS) for k in keys) else None)
    # (the skip list is read at each rotation: changing it neither restarts the countdown nor refreshes the LEDs)
    on(
        "visualizer.auto_rotate.*",
        lambda keys: app.rotation.schedule() if any(k != "visualizer.auto_rotate.skip" for k in keys) else None,
    )
    on(
        "led.quiet_hours.*",
        # the OLED loop starts over: blank now, or showing again now
        lambda keys: (
            app.lighting.schedule_quiet_hours(),
            renderer.adjust_brightness_for_time(),
            app.display.restart(timeout=15),
        ),
    )
    # the level in use now changes now; the others at their time
    on("led.brightness.*", lambda keys: app.lighting.brightness_changed(keys))
    # shows what it looks like, without a restart
    on("led.inittest", lambda keys: show_test_pattern(app) if app.config.data.led.inittest else None)
    on(("led.init_sequence", "led.init_sweep_from"), lambda keys: show_test_pattern(app))  # try one: it plays now
    on(("update.channel", "update.branch"), lambda keys: check_releases(app))  # "Update available" follows it
    on("display_screen.enabled", lambda keys: display_enabled(app))
    # announced again with the new name, in the background
    on(("web_server.name", "web_server.announce"), lambda keys: app.discovery.start() if app.discovery else None)
    on(OLED_AIRPORTS, lambda keys: app.display.restart(timeout=15))
    on("display_screen.shows", lambda keys: app.display.restart(timeout=15))  # airports or the visualizer, now
    on("airports.code", lambda keys: app.feeds.airport_codes_changed())


def _matches(key, patterns):
    return any(fnmatch.fnmatchcase(key, p) for p in patterns)


def show_test_pattern(app: App):
    threading.Thread(target=app.renderer.test_pattern, name="test-pattern", daemon=True).start()


def display_enabled(app: App):
    """display_screen.enabled: the OLED turns on or off now."""
    app.display.turn_on() if app.config.data.display_screen.enabled else app.display.turn_off()


def check_releases(app: App):
    """Asks GitHub whether there's a newer release (in the background), for the web UI's "Update available"."""
    if app.releases is not None:
        app.releases.check_soon()


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
    if web_server is not None and app.discovery is not None:
        app.discovery.start(port)  # in the background; nothing happens without the zeroconf package

    log.info("Main loop...")
    app.renderer.draw_frame()  # the visualizer first, then the OLED loop's first "Highlight active airport" pulse
    if app.config.data.display_screen.enabled:
        app.display.start(locate_delay=STARTUP_LOCATE_DELAY)
    try:
        while True:
            app.renderer.render()  # returns about once a second (RENDER_SECONDS), so the jobs below run on time
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
    if app.discovery is not None:
        app.discovery.stop()
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
