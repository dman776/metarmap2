#!/usr/bin/python3
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
from datetime import datetime

import display
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
config = None


def init_pixel_subsets(apixels: neopixel):
    p = []
    for i in range(0, 50):
        p.append(PixelSubset(apixels, i, i + 1))
    return p


def update_data():
    metars.fetch()
    renderer.update_data(metars)


def sched_load_suntimes():
    safe_logging.safe_log("[sched]load suntimes")
    (DAWN, SUNRISE, SUNSET, DUSK) = config.suntimes

    # clear schedule/set schedule
    schedule.clear("suntimes")
    schedule.every().day.at(SUNSET.strftime("%H:%M")).do(sched_set_brightness, level=config.data.led.brightness.dimmed).tag("suntimes")
    schedule.every().day.at(DUSK.strftime("%H:%M")).do(sched_set_brightness, level=config.data.led.brightness.off).tag("suntimes")
    schedule.every().day.at(DAWN.strftime("%H:%M")).do(sched_set_brightness, level=config.data.led.brightness.dimmed).tag("suntimes")
    schedule.every().day.at(SUNRISE.strftime("%H:%M")).do(sched_set_brightness, level=config.data.led.brightness.normal).tag("suntimes")
    for j in schedule.get_jobs("suntimes"):
        safe_logging.safe_log("[c]" + str(j) + " next run: " + str(j.next_run))


def sched_set_brightness(level):
    safe_logging.safe_log("[sched]set brightness: " + str(level))
    renderer.brightness(level)


# =====================================================================================================
# MAIN
# =====================================================================================================
if __name__ == '__main__':
    safe_logging.safe_log("[c]" + "Starting controller.py at " + datetime.now().strftime('%d/%m/%Y %H:%M'))
    config = Config("config.json")

    # load sunrise/sunset times into scheduler for dynamic dimming
    sched_load_suntimes()

    # Start loading the METARs in the background
    safe_logging.safe_log("[c]" + "Get weather for all airports...")
    metars = metar.METAR(config, fetch=True)

    # init neopixels
    pixels = neopixel.NeoPixel(config.LED_PIN, config.data.led.count, brightness=config.data.led.brightness.normal,
                               pixel_order=config.LED_ORDER, auto_write=False)
    pix_subs = init_pixel_subsets(pixels)   # individual pixels

    # Load all the visualizers
    visualizers = [
        FlightCategoryVisualizer(metars.data, pix_subs, config),
        WindVisualizer(metars.data, pix_subs, config),
        WindGustsVisualizer(metars.data, pix_subs, config),
        PressureVisualizer(metars.data, pix_subs, config),
        PrecipitationVisualizer(metars.data, pix_subs, config),
        TemperatureVisualizer(metars.data, pix_subs, config),
        VisibilityVisualizer(metars.data, pix_subs, config),
        DensityAltitudeVisualizer(metars.data, pix_subs, config)
    ]

    renderer = renderer.Renderer(pixels, pix_subs, metars, config, visualizers)
    renderer.visualizer = config.data.visualizer.active

    # Init DISPLAY
    disp: Display
    if config.data.display_screen.enabled:
        disp = Display(config.airports, metars, renderer)
        disp.message("MAP", display.ICON_INFO,
                     "Starting..")

    # test pattern on pixels?
    if config.data.led.inittest:
        renderer.animate_once(RainbowComet(pixels, speed=0.05, tail_length=5, bounce=False))

    # Job Scheduler setup --------------
    schedule.every(10).minutes.do(update_data)                  # Start up METAR update thread
    schedule.every().day.at('00:00').do(sched_load_suntimes)    # load sun times and dim the map appropriately

    # Start up Web Server to handle UI
    web_server = webserver.WebServer("0.0.0.0", 80, metars, renderer, disp or None)
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

