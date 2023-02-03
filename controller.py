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
import lib.config

from lib import logger, safe_logging, utils
import metar as metar
from lib.recurring_task import RecurringTask
# from visualizers import visualizers

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
            delta_time = toc - tic
            tic = time.perf_counter()

            # renderer.clear()
            try:
                renderer.render()
            except Exception as e:
                safe_logging.safe_log(e)

            # safe_logging.safe_log("KDWH is " + metars.data['KDWH']['flightCategory'])
            time.sleep(1.0)

            toc = time.perf_counter()
        except KeyboardInterrupt:
            quit()
        except Exception as ex:
            pass
            # safe_logging.safe_log(ex)


if __name__ == '__main__':
    safe_logging.safe_log("Starting controller.py at " + datetime.now().strftime('%d/%m/%Y %H:%M'))
    CONFIG = lib.config.Config("config.json")

    # all_stations(weather.OFF)

    # load airports file
    # CONVERT TO METHOD to be called upon REST API
    # with open('/home/pi/airports.json') as f:
    with open('airports.json') as f:
        data = f.read()
    airports = json.loads(data)

    # get sunrise/sunset times for dynamic dimming
    (DAWN, SUNRISE, SUNSET, DUSK) = utils.get_sun_times(CONFIG)

    # setup for metars
    metars = metar.METAR(airports, CONFIG, fetch=False)

    # init neopixels
    pixels = None
    # bright = CONFIG.data().dimming.time_base.bright_start < datetime.now().time() < CONFIG.data().dimming.time_base.dim_start
    bright = False
    pixels = neopixel.NeoPixel(CONFIG.LED_PIN, CONFIG.data().led.count, brightness=CONFIG.data().led.brightness if (
            CONFIG.data().dimming.dynamic_base.enabled and bright == False) else CONFIG.data().led.brightness, pixel_order=CONFIG.LED_ORDER,
            auto_write=False)

    renderer = renderer.Renderer(pixels, metars, CONFIG)

    # renderer.test()
    # renderer.rainbow_test()

    # init display
    # init webserver

    # Start loading the METARs in the background
    safe_logging.safe_log("Get weather for all airports...")



    mf = RecurringTask(
        "metar_fetch",
        300,
        metars.fetch(),
        logger.LOGGER,
        True)



    while metars.is_fetching():
        pass

    # safe_logging.safe_log(metars.data)

    # __test_all_leds__()

    # Start up REST API Server to handle config requests
    # rest_server = restserver.RESTServer()
    # rest_server.run()

    # Start up Web Server to handle UI
    web_server = webserver.WebServer("0.0.0.0", 8080, metars)
    web_server.run()


    while True:
        try:
            render_thread(metars)
        except KeyboardInterrupt:
            break

    web_server.stop()
    GPIO.cleanup()
