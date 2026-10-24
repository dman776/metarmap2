#!/usr/bin/python3
# METAR Map controller
# Darryl Quinn 2023
# Free for personal use. Prohibited for commercial without consent
#

import threading
import time
import traceback
from datetime import datetime
import signal

import lib.utils
import webserver
import renderer
from config import Config
from display import Display

import schedule

from lib import safe_logging
import metar as metar
from adafruit_led_animation.animation.rainbowcomet import RainbowComet
from metarmap.leds.strip import open_strip
from metarmap.oled.screen import open_screen

from visualizers.flightcategory import FlightCategory as FlightCategoryVisualizer
from visualizers.wind import Wind as WindVisualizer
from visualizers.windgusts import WindGusts as WindGustsVisualizer
from visualizers.pressure import Pressure as PressureVisualizer
from visualizers.temperature import Temperature as TemperatureVisualizer
from visualizers.visibility import Visibility as VisibilityVisualizer
from visualizers.precipitation import Precipitation as PrecipitationVisualizer
from visualizers.density_altitude import DensityAltitude as DensityAltitudeVisualizer
from visualizers.chase import Chase as ChaseVisualizer
from visualizers.rainbow import Rainbow as RainbowVisualizer

thread_lock_object = threading.Lock()

try:
    import RPi.GPIO as GPIO

    GPIO.setmode(GPIO.BOARD)
except ModuleNotFoundError:
    pass
except ValueError:
    # ws281x causes an exception
    # when you try to set the board type
    pass

# ---------------------------------------------------------------------------
# Globals
__version__ = "2.2.4"
CONFIG_FILE = "config.json"
config = None


def update_data():
    metars.fetch()
    renderer.update_data(metars)


def sched_load_suntimes():
    safe_logging.safe_log("[sched]load suntimes")
    schedule.clear("suntimes")
    config.set_suntimes()  # reload suntimes everyday
    times = {
        'sunset': config.suntimes['sunset'],
        'dusk': config.suntimes['dusk'],
        'dawn': config.suntimes['dawn'],
        'sunrise': config.suntimes['sunrise']
    }
    brightness_levels = {
        'sunset': config.data.led.brightness.dimmed,
        'dusk': config.data.led.brightness.off,
        'dawn': config.data.led.brightness.dimmed,
        'sunrise': config.data.led.brightness.normal
    }
    for key, value in times.items():
        schedule.every().day.at(value.strftime("%H:%M")).do(sched_set_brightness,
                                                            level=brightness_levels[key]).tag("suntimes")
    # for j in schedule.get_jobs("suntimes"):
    #     safe_logging.safe_log("[c]" + str(j) + " next run: " + str(j.next_run))


def sched_set_brightness(level):
    safe_logging.safe_log("[sched]set brightness: " + str(level))
    renderer.brightness(level)


def sched_rotate_visualizer():
    renderer.visualizer_next(skip_exclusive=True)


def sched_watch_display():
    """
    Restarts the OLED loop if its thread died or it hasn't moved on for a while.
    """
    disp = config.display
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


def log_thread_exception(args):
    """
    Uncaught exceptions in background threads only go to stderr by default; put them in the log too.
    """
    name = args.thread.name if args.thread else "?"
    safe_logging.safe_log(f"[c]uncaught exception in thread {name}: "
                          + "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))


def signal_handler(sig, frame):
    raise KeyboardInterrupt


# =====================================================================================================
# MAIN
# =====================================================================================================
if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    threading.excepthook = log_thread_exception

    safe_logging.safe_log("[c]" + "Starting controller.py at " + datetime.now().strftime('%d/%m/%Y %H:%M'))
    safe_logging.safe_log("[c]" + "Testing to see if internet (8.8.8.8) is reachable...")
    while lib.utils.is_pingable("8.8.8.8") != 0:
        safe_logging.safe_log("[c]" + ".")
        time.sleep(1)
    safe_logging.safe_log("[c]" + "done.")

    config = Config(CONFIG_FILE)

    # load sunrise/sunset times into scheduler for dynamic dimming
    sched_load_suntimes()

    safe_logging.safe_log("[c]" + "Get weather for all airports...")
    metars = metar.METAR(config, fetch=True)

    # the NeoPixel strip on the Pi; an in-memory strip anywhere else
    pixels = open_strip(config.data.led)

    visualizers = [
        FlightCategoryVisualizer(config),
        WindVisualizer(config),
        WindGustsVisualizer(config),
        PressureVisualizer(config),
        PrecipitationVisualizer(config),
        TemperatureVisualizer(config),
        VisibilityVisualizer(config),
        DensityAltitudeVisualizer(config),
        RainbowVisualizer(config),
        ChaseVisualizer(config)
    ]

    renderer = renderer.Renderer(pixels, metars, config, visualizers)
    renderer.visualizer = config.data.visualizer.active
    config.renderer = renderer

    # Init DISPLAY
    disp: Display
    if config.data.display_screen.enabled:
        # the OLED on the Pi; an in-memory screen anywhere else (the web UI still mirrors it)
        disp = Display(config, metars, open_screen())
        config.display = disp
        disp.message("MAP", "info", "Starting..")
    else:
        disp = None

    # test pattern on pixels?
    if config.data.led.inittest:
        renderer.animate_once(RainbowComet(pixels, speed=0.05, tail_length=5, bounce=False))

    # Job Scheduler setup --------------
    schedule.every(10).minutes.do(update_data)  # Start up METAR update thread
    schedule.every().day.at('00:00').do(sched_load_suntimes)  # load sun times and dim the map appropriately
    if config.data.display_screen.enabled:
        schedule.every(15).seconds.do(sched_watch_display)

    if config.data.visualizer.auto_rotate.enabled:
        delay_secs = config.data.visualizer.auto_rotate.delay_seconds
        schedule.every(delay_secs).seconds.do(sched_rotate_visualizer).tag("rotate_visualizer")

    # Start up Web Server to handle UI
    web_server = webserver.WebServer("0.0.0.0", config.data.web_server.port, metars, config)
    web_server.run()

    # ======================================================================================
    # ============== MAIN LOOP =============================================================
    # ======================================================================================
    safe_logging.safe_log("[c]" + "Main loop...")
    if config.data.display_screen.enabled:
        disp.start()

    while True:
        try:
            renderer.render()
            schedule.run_pending()
        except Exception as e:
            safe_logging.safe_log("[c]" + str(e))
            break
        except KeyboardInterrupt:
            break

    # Cleanup
    safe_logging.safe_log("[c]" + "Cleaning up...")
    schedule.clear()
    if config.data.display_screen.enabled:
        disp.stop()
    renderer.stop()
    renderer.clear()
    web_server.stop()

