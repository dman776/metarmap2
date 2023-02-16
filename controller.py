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

import threading
import time
from datetime import datetime
import json

import lib.config
import webserver
import renderer
from display import Display
import lib.config

from lib import logger, safe_logging, utils
import traceback
import metar as metar
from lib.recurring_task import RecurringTask
from renderer import Renderer as Renderer
from adafruit_led_animation.helper import PixelSubset
from adafruit_led_animation.animation.rainbowchase import RainbowChase
from adafruit_led_animation.animation.rainbowcomet import RainbowComet
from visualizers.flightcategory import FlightCategory as FlightCategoryVisualizer
from visualizers.wind import Wind as WindVisualizer
from visualizers.pressure import Pressure as PressureVisualizer

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

def update_data(adata):
    renderer.update_data(adata)

def init_pixel_subsets(apixels: neopixel):
    p = []
    for i in range(0, 50):
        p.append(PixelSubset(apixels, i, i + 1))
    return p

def render_thread(metars):
    """
    Main logic loop for rendering the lights.
    """

    print("Starting rendering thread")

    tic = time.perf_counter()
    toc = time.perf_counter()
    display = True

    # loaded_visualizers = visualizers.VisualizerManager.initialize_visualizers(
    #     renderer,
    #     stations)
    # last_visualizer = 0

    while True:
        try:
            try:
                renderer.render()
            except Exception as e:
                safe_logging.safe_log("[c]" + str(traceback.print_exc()))
                # safe_logging.safe_log(e)
                quit()
        except KeyboardInterrupt:
            raise KeyboardInterrupt
        except Exception as ex:
            # pass
            safe_logging.safe_log("[c]" + ex)
            quit()


if __name__ == '__main__':
    safe_logging.safe_log("[c]" + "Starting controller.py at " + datetime.now().strftime('%d/%m/%Y %H:%M'))

    # disp.message("METARMap", "config...")
    CONFIG = lib.config.Config("config.json")

    # all_stations(weather.OFF)

    # load airports file
    # disp.message("METARMap", "airports...")
    # CONVERT TO METHOD to be called upon REST API
    # with open('/home/pi/airports.json') as f:
    with open('airports.json') as f:
        data = f.read()
    airports = json.loads(data)

    # disp.message("METARMap", "sun times...")
    # get sunrise/sunset times for dynamic dimming
    (DAWN, SUNRISE, SUNSET, DUSK) = utils.get_sun_times(CONFIG)

    # setup for metars
    # disp.message("METARMap", "metars...")
    metars = metar.METAR(airports, CONFIG, fetch=True)

    # init display
    disp = Display(airports, metars)
    disp.on()
    disp.start()

    # init neopixels
    # disp.message("METARMap", "pixels...")
    pixels = None
    # bright = CONFIG.data().dimming.time_base.bright_start < datetime.now().time() < CONFIG.data().dimming.time_base.dim_start
    bright = False
    pixels = neopixel.NeoPixel(CONFIG.LED_PIN, CONFIG.data().led.count, brightness=CONFIG.data().led.brightness if (
            CONFIG.data().dimming.dynamic_base.enabled and bright is False) else CONFIG.data().led.brightness, pixel_order=CONFIG.LED_ORDER,
            auto_write=False)
    pix = init_pixel_subsets(pixels)

    # NEED to periodically update visualizer, renderer, webserver, disp with new METAR data
    visualizers = []
    visualizers.append(FlightCategoryVisualizer(metars.data, pix, CONFIG))
    visualizers.append(WindVisualizer(metars.data, pix, CONFIG))
    visualizers.append(PressureVisualizer(metars.data, pix, CONFIG))
    renderer = renderer.Renderer(pixels, metars, CONFIG, visualizers)
    renderer.visualizer = 0

    # test it
    #renderer.animate_once(RainbowChase(pixels, speed=0.1, size=4, spacing=2, step=4))
    renderer.animate_once(RainbowComet(pixels, speed=0.05, tail_length=5, bounce=False))


    # Start loading the METARs in the background
    safe_logging.safe_log("[c]" + "Get weather for all airports...")

    mf = RecurringTask(
        "metar_fetch",
        300,
        metars.fetch(renderer.update_data(metars)),
        logger.LOGGER,
        True)

    while metars.is_fetching():
        pass

    # safe_logging.safe_log(metars.data)

    # Start up Web Server to handle UI
    # disp.message("METARMap", "webserver...")
    web_server = webserver.WebServer("0.0.0.0", 8080, metars, renderer)
    web_server.run()


    # disp.show_metar("KDWH", metars.data['KDWH'], 5)

    while True:
        try:
            render_thread(metars)
        except KeyboardInterrupt:
            renderer.clear()
            mf.stop()
            web_server.stop()
            disp.off()
            break

    web_server.stop()
    GPIO.cleanup()
