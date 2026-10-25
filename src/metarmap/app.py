"""
The METAR map: builds every part from config.json, schedules the periodic jobs and runs the main loop.

build() wires the parts together without starting anything, so a map can be built on fake hardware in tests;
run() starts the web server and the OLED loop and drives the LEDs until stopped. main() is `python -m metarmap`.
"""
# Darryl Quinn 2023
# Free for personal use. Prohibited for commercial without consent

import signal
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import schedule
from adafruit_led_animation.animation.rainbowcomet import RainbowComet

from metarmap import __version__, service, visualizers
from metarmap.clock import Clock
from metarmap.config import Config
from metarmap.display import Display
from metarmap.leds.strip import open_strip
from metarmap.lib import safe_logging, utils
from metarmap.metar import METAR
from metarmap.oled.screen import open_screen
from metarmap.renderer import Renderer
from metarmap.sun import LEVEL_AT, SunTimes
from metarmap.web import create_app, serve

CONFIG_FILE = "config.json"
METAR_MINUTES = 10  # how often METARs are fetched
RETRY_SECONDS = 60  # after a failed fetch or lookup (e.g. aviationweather.gov answering 502), how soon to try again
WATCHDOG_SECONDS = 15  # how often the OLED loop is checked


@dataclass
class App:
    """Every part of a map. The web server and the scheduled jobs reach the others through this."""
    config: Config
    sun: SunTimes
    metars: METAR
    renderer: Renderer
    display: Optional[Display]  # None when display_screen.enabled is off
    scheduler: schedule.Scheduler


# ---- building ------------------------------------------------------------------------------------------------

def build(config_file=CONFIG_FILE, strip=None, screen=None, clock: Clock = None, fetch=True) -> App:
    """
    Builds the map from config_file, with its jobs scheduled but nothing running yet.
    The LED strip and OLED screen are opened unless given; METARs are fetched unless fetch=False.
    """
    config = Config(config_file)
    sun = SunTimes(config.data.geo.city)
    sun.reload()

    safe_logging.safe_log("[c]" + "Get weather for all airports...")
    metars = METAR(config, fetch=fetch, clock=clock)

    if strip is None:
        strip = open_strip(config.data.led)  # the NeoPixel strip on the Pi; an in-memory strip anywhere else
    renderer = Renderer(strip, metars, config, list(visualizers.ALL), sun, clock=clock)
    renderer.visualizer = config.data.visualizer.active

    display = None
    if config.data.display_screen.enabled:
        if screen is None:
            screen = open_screen()  # the OLED on the Pi; an in-memory screen anywhere else (the web UI mirrors it)
        display = Display(config, metars, screen, renderer=renderer, clock=clock)

    app = App(config, sun, metars, renderer, display, schedule.Scheduler())
    schedule_jobs(app)
    return app


def schedule_jobs(app: App):
    s = app.scheduler
    s.every(METAR_MINUTES).minutes.do(update_data, app)
    if needs_retry(app):  # the fetch or lookup at startup failed
        retry_soon(app)
    s.every().day.at("00:00").do(load_suntimes, app)  # new sun times every day, to dim the map at the right times
    schedule_brightness(app)
    if app.display is not None:
        s.every(WATCHDOG_SECONDS).seconds.do(watch_display, app)
    rotate = app.config.data.visualizer.auto_rotate
    if rotate.enabled:
        s.every(rotate.delay_seconds).seconds.do(rotate_visualizer, app).tag("rotate_visualizer")


# ---- scheduled jobs ------------------------------------------------------------------------------------------

def update_data(app: App):
    app.metars.fetch()
    app.renderer.update_data(app.metars)
    if needs_retry(app):
        retry_soon(app)


def needs_retry(app: App):
    """Whether the METAR fetch, or the lookup of where airports without a report are, failed."""
    return app.metars.last_fetch_ok is False or app.metars.locate_failed


def retry_soon(app: App):
    """Tries again every RETRY_SECONDS until it works, instead of waiting for the next regular fetch."""
    if not app.scheduler.get_jobs("retry"):
        what = "METAR fetch" if app.metars.last_fetch_ok is False else "airport position lookup"
        safe_logging.safe_log(f"[c]{what} failed; trying again every {RETRY_SECONDS} s until it works")
        app.scheduler.every(RETRY_SECONDS).seconds.do(retry_fetch, app).tag("retry")


def retry_fetch(app: App):
    """Redoes what failed: the fetch (which also does the lookup), or only the lookup."""
    if app.metars.last_fetch_ok is False:
        if app.metars.fetch():
            app.renderer.update_data(app.metars)
    elif app.metars.locate_failed:
        app.metars.locate()
    if not needs_retry(app):
        return schedule.CancelJob


def load_suntimes(app: App):
    safe_logging.safe_log("[sched]load suntimes")
    app.sun.reload()
    schedule_brightness(app)


def schedule_brightness(app: App):
    """Sets the LEDs' brightness at each of today's sun times (dimmed at dawn, normal at sunrise, ...)."""
    app.scheduler.clear("suntimes")
    levels = app.config.data.led.brightness
    for name, level in LEVEL_AT.items():
        at = app.sun.times[name].strftime("%H:%M")
        app.scheduler.every().day.at(at).do(set_brightness, app, level=getattr(levels, level)).tag("suntimes")


def set_brightness(app: App, level):
    safe_logging.safe_log("[sched]set brightness: " + str(level))
    app.renderer.brightness(level)


def rotate_visualizer(app: App):
    app.renderer.visualizer_next(skip_exclusive=True)


def watch_display(app: App):
    """
    Restarts the OLED loop if its thread died or it hasn't moved on for a while.
    """
    disp = app.display
    if disp is None:
        return
    reason = disp.stalled()
    if reason:
        safe_logging.safe_log(f"[c]display watchdog: {reason}; restarting")
        try:
            disp.restart(timeout=5)
        except Exception as e:
            # an exception here would end the main loop; just try again next time
            safe_logging.safe_log(f"[c]display watchdog restart failed: {e}\n{traceback.format_exc()}")


# ---- running -------------------------------------------------------------------------------------------------

def run(app: App):
    """Starts the web server and the OLED loop, then drives the LEDs until Ctrl-C, SIGTERM or an error."""
    if app.display is not None:
        app.display.message("MAP", "info", "Starting..")

    # test pattern on pixels?
    if app.config.data.led.inittest:
        app.renderer.animate_once(RainbowComet(app.renderer.pixels(), speed=0.05, tail_length=5, bounce=False))

    web_app = create_app(app)
    try:
        web_server = serve(web_app, "0.0.0.0", app.config.data.web_server.port)
    except OSError as e:
        # e.g. the port is in use; the LEDs and OLED still run
        safe_logging.safe_log(f"[c]web server can't start on port {app.config.data.web_server.port}: {e}")
        web_server = None

    safe_logging.safe_log("[c]" + "Main loop...")
    if app.display is not None:
        app.display.start()
    try:
        while True:
            app.renderer.render()
            app.scheduler.run_pending()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        safe_logging.safe_log(f"[c]main loop stopped: {e}\n{traceback.format_exc()}")
    finally:
        shutdown(app, web_app, web_server)


def shutdown(app: App, web_app, web_server):
    safe_logging.safe_log("[c]" + "Cleaning up...")
    app.scheduler.clear()
    if app.display is not None:
        app.display.stop()
    app.renderer.stop()
    app.renderer.clear()
    if web_server is not None:
        web_server.shutdown()
        web_server.server_close()
    web_app.close()


def wait_for_internet():
    safe_logging.safe_log("[c]" + "Testing to see if internet (8.8.8.8) is reachable...")
    while utils.is_pingable("8.8.8.8") != 0:
        safe_logging.safe_log("[c]" + ".")
        time.sleep(1)
    safe_logging.safe_log("[c]" + "done.")


# ---- process setup -------------------------------------------------------------------------------------------

def log_thread_exception(args):
    """
    Uncaught exceptions in background threads only go to stderr by default; put them in the log too.
    """
    name = args.thread.name if args.thread else "?"
    safe_logging.safe_log(f"[c]uncaught exception in thread {name}: "
                          + "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))


def log_uncaught_exception(exc_type, exc_value, exc_traceback):
    """
    A crash in the main thread only goes to stderr (the systemd journal); put it in the log too.
    """
    if not issubclass(exc_type, KeyboardInterrupt):
        safe_logging.safe_log("[c]uncaught exception: "
                              + "".join(traceback.format_exception(exc_type, exc_value, exc_traceback)))
    sys.__excepthook__(exc_type, exc_value, exc_traceback)


def signal_handler(sig, frame):
    raise KeyboardInterrupt


def main(config_file=CONFIG_FILE):
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    threading.excepthook = log_thread_exception
    sys.excepthook = log_uncaught_exception

    safe_logging.safe_log(f"[c]Starting metarmap {__version__} at " + datetime.now().strftime('%d/%m/%Y %H:%M'))
    try:
        service.migrate()  # an installed metarmap.service that still runs controller.py
    except Exception as e:
        safe_logging.safe_log(f"[c]service file check failed: {e}\n{traceback.format_exc()}")
    wait_for_internet()
    run(build(config_file))
