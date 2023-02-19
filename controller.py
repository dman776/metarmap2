# METAR Map controller
# Darryl Quinn 2023
# Uses RPi.GPIO library: https://sourceforge.net/p/raspberry-gpio-python/wiki/BasicUsage/
# Free for personal use. Prohibited for commercial without consent
#
# pip install Adafruit-GPIO
# pip install RPi-GPIO
# pip install pytest
# pip install Adafruit_WS2801
#
# Raspberry Pi
# Run 'raspi-config' and enable the SPI bus under Advanced
#
# Wiring the WS2801 :
# https://learn.adafruit.com/12mm-led-pixels/wiring
# https://tutorials-raspberrypi.com/how-to-control-a-raspberry-pi-ws2801-rgb-led-strip/
# Blue -> 5V Minus AND Pi GND (Physical Pi 25)
# Red -> 5V Plus
# Yellow -> Pin 19(Physical)/SPI MOSI
# Green -> Pin 23(Physical)/SCLK/SPI
#

import json
import sys
import threading
import time
from datetime import datetime
import json
from pprint import pprint

import display
import lib.config
import webserver
import renderer
from display import Display
import lib.config
import schedule

from lib import logger, safe_logging, utils
import traceback
import metar as metar
from renderer import Renderer as Renderer
from adafruit_led_animation.helper import PixelSubset
from adafruit_led_animation.animation.rainbowchase import RainbowChase
from adafruit_led_animation.animation.rainbowcomet import RainbowComet
from visualizers.flightcategory import FlightCategory as FlightCategoryVisualizer
from visualizers.windgusts import WindGusts as WindGustsVisualizer
from visualizers.pressure import Pressure as PressureVisualizer
from visualizers.temperature import Temperature as TemperatureVisualizer
from visualizers.visibility import Visibility as VisibilityVisualizer

try:
    import board
    import neopixel
except:
    pass

thread_lock_object = threading.Lock()

try:
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BOARD)
except Exception:
    # ws281x causes an exception
    # when you try to set the board type
    pass

# ---------------------------------------------------------------------------
# ------------START OF CONFIGURATION-----------------------------------------
# ---------------------------------------------------------------------------
FADE_INSTEAD_OF_BLINK	= True			# Set to False if you want blinking
BLINK_TOTALTIME_SECONDS	= 600
# LED_ORDER = neopixel.GRB        # fix in config
# ---------------------------------------------------------------------------
# ------------END OF CONFIGURATION-------------------------------------------
# ---------------------------------------------------------------------------

# Globals
DAWN = None
SUNRISE = None
SUNSET = None
DUSK = None
config = None


def init_pixel_subsets(apixels: neopixel):
    p = []
    for i in range(0, 50):
        p.append(PixelSubset(apixels, i, i + 1))
    return p

# def render_thread(metars):
#     """
#     Main logic loop for rendering
#     """
#     print("Starting rendering thread")
#     while True:
#         try:
#             try:
#                 renderer.render()
#             except Exception as e:
#                 safe_logging.safe_log("[c]" + str(traceback.print_exc()))
#         except KeyboardInterrupt:
#             raise KeyboardInterrupt
#         except Exception as ex:
#             safe_logging.safe_log("[c]" + ex)


def update_data():
    metars.fetch()
    renderer.update_data(metars)


def load_airports(file):
    with open(file) as f:
        fdata = f.read()
    return json.loads(fdata)


def load_suntimes():
    global DAWN, SUNRISE, SUNSET, DUSK, config
    (DAWN, SUNRISE, SUNSET, DUSK) = utils.get_sun_times(config)
    # clear schedule/set schedule
    schedule.clear("suntimes")
    schedule.every().day.at(SUNSET.strftime("%H:%M")).do(set_brightness, level=config.data().led.brightness.dimmed).tag("suntimes")
    schedule.every().day.at(DUSK.strftime("%H:%M")).do(set_brightness, level=config.data().led.brightness.off).tag("suntimes")
    schedule.every().day.at(DAWN.strftime("%H:%M")).do(set_brightness, level=config.data().led.brightness.dimmed).tag("suntimes")
    schedule.every().day.at(SUNRISE.strftime("%H:%M")).do(set_brightness, level=config.data().led.brightness.normal).tag("suntimes")
    for j in schedule.get_jobs("suntimes"):
        safe_logging.safe_log("[c]" + str(j) + " next run: " + str(j.next_run))


def set_brightness(level):
    renderer.brightness(level)


# =====================================================================================================
# MAIN
# =====================================================================================================
if __name__ == '__main__':
    safe_logging.safe_log("[c]" + "Starting controller.py at " + datetime.now().strftime('%d/%m/%Y %H:%M'))

    # disp.message("METARMAP", "config...")
    config = lib.config.Config("config.json")

    # load airports file
    airports = load_airports("airports.json")

    # get sunrise/sunset times for dynamic dimming
    load_suntimes()

    # Start loading the METARs in the background
    safe_logging.safe_log("[c]" + "Get weather for all airports...")
    metars = metar.METAR(airports, config, fetch=True)

    # Init DISPLAY
    disp: Display
    if config.data().display_screen.enabled:
        disp = Display(airports, metars)
        disp.message("METARMAP", display.ICON_INFO,
                     "Starting",
                     "up the",
                     "map...")

    # init neopixels
    # bright = CONFIG.data().dimming.time_base.bright_start < datetime.now().time() < CONFIG.data().dimming.time_base.dim_start
    bright = False
    pixels = neopixel.NeoPixel(config.LED_PIN, config.data().led.count, brightness=config.data().led.brightness.normal,
                               pixel_order=config.LED_ORDER, auto_write=False)
    pix = init_pixel_subsets(pixels)

    # NEED to periodically update visualizer, renderer, webserver, disp with new METAR data
    visualizers = []
    visualizers.append(FlightCategoryVisualizer(metars.data, pix, config))
    visualizers.append(WindGustsVisualizer(metars.data, pix, config))
    visualizers.append(PressureVisualizer(metars.data, pix, config))
    visualizers.append(TemperatureVisualizer(metars.data, pix, config))
    visualizers.append(VisibilityVisualizer(metars.data, pix, config))

    renderer = renderer.Renderer(pixels, metars, config, visualizers)
    renderer.visualizer = 0

    # test pattern on pixels?
    if config.data().led.inittest:
        renderer.animate_once(RainbowComet(pixels, speed=0.05, tail_length=5, bounce=False))
        # renderer.animate_once(RainbowChase(pixels, speed=0.1, size=4, spacing=2, step=4))

    # Job Scheduler setup --------------
    schedule.every(10).minutes.do(update_data)          # Start up METAR update thread
    schedule.every().day.at('00:00').do(load_suntimes)  # load sun times and dim the map appropriately

    # Start up Web Server to handle UI
    web_server = webserver.WebServer("0.0.0.0", 8080, metars, renderer)
    web_server.run()

    # ============== MAIN LOOP =====================
    safe_logging.safe_log("[c]" + "Main loop...")
    if config.data().display_screen.enabled:
        disp.start()

    while True:
        try:
            renderer.render()
            schedule.run_pending()
        except Exception as e:
            safe_logging.safe_log("[c]" + e)
        except KeyboardInterrupt:
            break

    # Cleanup
    safe_logging.safe_log("[c]" + "Cleaning up...")
    schedule.clear()
    if config.data().display_screen.enabled:
        disp.stop()
    renderer.clear()
    web_server.stop()
    GPIO.cleanup()
