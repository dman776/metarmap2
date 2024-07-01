#!/usr/bin/python3
# METAR Map controller
# Darryl Quinn 2023
# Free for personal use. Prohibited for commercial without consent
#

import threading
import time
from datetime import datetime
import signal

import display
import lib.utils
import webserver
import renderer
from config import Config
from display import Display

import schedule

from lib import safe_logging
import metar as metar
from adafruit_led_animation.helper import PixelSubset
from adafruit_led_animation.animation.rainbowcomet import RainbowComet

from visualizers.flightcategory import FlightCategory as FlightCategoryVisualizer
from visualizers.wind import Wind as WindVisualizer
from visualizers.windgusts import WindGusts as WindGustsVisualizer
from visualizers.pressure import Pressure as PressureVisualizer
from visualizers.temperature import Temperature as TemperatureVisualizer
from visualizers.visibility import Visibility as VisibilityVisualizer
from visualizers.precipitation import Precipitation as PrecipitationVisualizer
from visualizers.density_altitude import DensityAltitude as DensityAltitudeVisualizer
from visualizers.chase import ChaseTest as ChaseVisualizer
from visualizers.rainbow import Rainbow1 as RainbowVisualizer

try:
    import board
    import neopixel
except ModuleNotFoundError:
    pass

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
__version__ = "1.15.0"
CONFIG_FILE = "config.json"
config = None


def init_pixel_subsets(apixels: neopixel, pixel_count: int):
    return [PixelSubset(apixels, i, i + 1) for i in range(pixel_count)]


def update_data():
    metars.fetch()
    renderer.update_data(metars)


def sched_load_suntimes():
    safe_logging.safe_log("[sched]load suntimes")
    schedule.clear("suntimes")
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


def signal_handler(sig, frame):
    raise KeyboardInterrupt


# =====================================================================================================
# MAIN
# =====================================================================================================
if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

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

    pixels = neopixel.NeoPixel(config.LED_PIN, config.data.led.count, brightness=config.data.led.brightness.normal,
                               pixel_order=config.LED_ORDER, auto_write=False)
    pix_subs = init_pixel_subsets(pixels, config.data.led.count)  # individual pixels

    visualizers = [
        FlightCategoryVisualizer(metars.data, pix_subs, config),
        WindVisualizer(metars.data, pix_subs, config),
        WindGustsVisualizer(metars.data, pix_subs, config),
        PressureVisualizer(metars.data, pix_subs, config),
        PrecipitationVisualizer(metars.data, pix_subs, config),
        TemperatureVisualizer(metars.data, pix_subs, config),
        VisibilityVisualizer(metars.data, pix_subs, config),
        DensityAltitudeVisualizer(metars.data, pix_subs, config),
        RainbowVisualizer(metars.data, pixels, config),
        ChaseVisualizer(metars.data, pixels, config)
    ]

    renderer = renderer.Renderer(pixels, pix_subs, metars, config, visualizers)
    renderer.visualizer = config.data.visualizer.active
    config.renderer = renderer

    # Init DISPLAY
    disp: Display
    if config.data.display_screen.enabled:
        disp = Display(config, metars)
        config.display = disp
        disp.message("MAP", display.ICON_INFO,
                     "Starting..")
    else:
        disp = None

    # test pattern on pixels?
    if config.data.led.inittest:
        renderer.animate_once(RainbowComet(pixels, speed=0.05, tail_length=5, bounce=False))

    # Job Scheduler setup --------------
    schedule.every(10).minutes.do(update_data)  # Start up METAR update thread
    schedule.every().day.at('00:00').do(sched_load_suntimes)  # load sun times and dim the map appropriately

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

