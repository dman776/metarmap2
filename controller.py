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

import webserver
import renderer
from lib.config import Config

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

# NeoPixel LED Configuration
LED_COUNT		= 50			# Number of LED pixels.
LED_PIN			= 18		# GPIO pin connected to the pixels (18 is PCM). board.D18
LED_BRIGHTNESS		= 0.75			# Float from 0.0 (min) to 1.0 (max)
LED_ORDER		= "GRB"		# Strip type and colour ordering

# COLOR_VFR		= (255,0,0)		# Green
# COLOR_VFR_FADE		= (125,0,0)		# Green Fade for wind
# COLOR_MVFR		= (0,0,255)		# Blue
# COLOR_MVFR_FADE		= (0,0,125)		# Blue Fade for wind
# COLOR_IFR		= (0,255,0)		# Red
# COLOR_IFR_FADE		= (0,125,0)		# Red Fade for wind
# COLOR_LIFR		= (0,125,125)		# Magenta
# COLOR_LIFR_FADE		= (0,75,75)		# Magenta Fade for wind
# COLOR_CLEAR		= (0,0,0)		# Clear
# COLOR_LIGHTNING		= (255,255,255)		# White

# ----- Blink/Fade functionality for Wind and Lightning -----
# Do you want the METARMap to be static to just show flight conditions, or do you also want blinking/fading based on current wind conditions
ACTIVATE_WINDCONDITION_ANIMATION = True	# Set this to False for Static or True for animated wind conditions
#Do you want the Map to Flash white for lightning in the area
ACTIVATE_LIGHTNING_ANIMATION = False		# Set this to False for Static or True for animated Lightning
# Fade instead of blink
FADE_INSTEAD_OF_BLINK	= True			# Set to False if you want blinking
# Blinking Windspeed Threshold
WIND_BLINK_THRESHOLD	= 18			# Knots of windspeed
ALWAYS_BLINK_FOR_GUSTS	= False			# Always animate for Gusts (regardless of speeds)
# Blinking Speed in seconds
BLINK_SPEED		= 1.0			# Float in seconds, e.g. 0.5 for half a second

# Total blinking time in seconds.
# For example set this to 300 to keep blinking for 5 minutes if you plan to run the script every 5 minutes to fetch the updated weather
BLINK_TOTALTIME_SECONDS	= 600

# ----- Daytime dimming of LEDs based on time of day or Sunset/Sunrise -----
ACTIVATE_DAYTIME_DIMMING = True		# Set to True if you want to dim the map after a certain time of day
# BRIGHT_TIME_START = datetime.time(7,0)	# Time of day to run at LED_BRIGHTNESS in hours and minutes
# DIM_TIME_START = datetime.time(19,0)	# Time of day to run at LED_BRIGHTNESS_DIM in hours and minutes
LED_BRIGHTNESS_DIM = 0.1			# Float from 0.0 (min) to 1.0 (max)

USE_SUNRISE_SUNSET 	= True			# Set to True if instead of fixed times for bright/dimming, you want to use local sunrise/sunset
LOCATION 		= "Houston"		# Nearby city for Sunset/Sunrise timing, refer to https://astral.readthedocs.io/en/latest/#cities for list of cities supported

# ----- External Display support -----
ACTIVATE_EXTERNAL_METAR_DISPLAY = True		# Set to True if you want to display METAR conditions to a small external display
DISPLAY_ROTATION_SPEED = 6.0			# Float in seconds, e.g 2.0 for two seconds

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
            # renderer.render()

            # safe_logging.safe_log("KDWH is " + metars.data['KDWH']['flightCategory'])
            time.sleep(0.1)

            toc = time.perf_counter()
        except KeyboardInterrupt:
            quit()
        except Exception as ex:
            safe_logging.safe_log(ex)


if __name__ == '__main__':
    safe_logging.safe_log("Starting controller.py at " + datetime.now().strftime('%d/%m/%Y %H:%M'))
    CONFIG = Config("config.json")

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
    # pixels = neopixel.NeoPixel(board.D18, LED_COUNT, brightness=LED_BRIGHTNESS_DIM if (
    #         ACTIVATE_DAYTIME_DIMMING and bright == False) else LED_BRIGHTNESS, pixel_order=LED_ORDER,
    #         auto_write=False)

    renderer = renderer.Renderer(pixels, metars, CONFIG)

    # renderer.test()

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
