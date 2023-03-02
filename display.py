# import os, sys
# import json
# from pprint import pprint
# import datetime
#
# import lib.config
from lib import utils

from renderer import Renderer

# import metar
# from PIL import Image, ImageDraw, ImageFont
# import io

try:
    from board import SCL, SDA
    import busio
    from oled_text import OledText, Layout64, BigLine, SmallLine
    import adafruit_ssd1306
    import time
    from pytz import timezone
    import pytz

    noDisplayLibraries = False
except ImportError:
    noDisplayLibraries = True

from lib.safe_logging import safe_log
import threading

from adafruit_led_animation.animation.pulse import Pulse
from adafruit_led_animation.color import RED

offset = -3
x = 0

ICON_DEGREES = u'\N{DEGREE SIGN}'
ICON_INFO = "\uf05a"
ICON_WIND = '\uf72e'
ICON_VISIBILITY = "\uf0c2"
ICON_PRESSURE = "\uf338"
ICON_TEMP = "\uf76b"
ICON_DEWPOINT = "\uf73d"
ICON_DATE = "\uf017"


def define_page_layouts():
    pl = []
    # Message/Info
    pl.append({
        1: BigLine(0, offset, size=20),  # TITLE
        2: BigLine(110, offset, font="FontAwesomeSolid.ttf", size=12),  # msg ico
        3: BigLine(0, 19 + offset),  # line 1
        4: BigLine(0, 36 + offset),  # line 2
        5: BigLine(0, 52 + offset),  # line 3
    })

    # Page station, cat, wind, vis, pressure
    pl.append({
        1: BigLine(0, offset, size=20),  # AIRPORT
        2: BigLine(80, offset, size=16),  # CAT
        3: BigLine(20, 19 + offset),  # wind
        4: BigLine(0, 19 + offset, font="FontAwesomeSolid.ttf", size=14),  # wind ico
        5: BigLine(20, 36 + offset),  # vis
        6: BigLine(0, 36 + offset, font="FontAwesomeSolid.ttf", size=14),  # vis ico
        7: BigLine(20, 52 + offset),  # pressure
        8: BigLine(6, 52 + offset, font="FontAwesomeSolid.ttf", size=14)  # pressure ico
    })

    # Page station, cat, temp, dew, time
    pl.append({
        1: BigLine(0, offset, size=20),  # AIRPORT
        2: BigLine(80, offset, size=16),  # CAT
        3: BigLine(20, 19 + offset),  # temp
        4: BigLine(0, 19 + offset, font="FontAwesomeSolid.ttf", size=14),  # temp ico
        5: BigLine(20, 36 + offset),  # dew
        6: BigLine(0, 36 + offset, font="FontAwesomeSolid.ttf", size=14),  # dew ico
        7: BigLine(20, 52 + offset),  # time
        8: BigLine(0, 52 + offset, font="FontAwesomeSolid.ttf", size=14)  # time ico
    })
    return pl


class Display(object):
    """
    Class to handle running an external OLED display
    """
    lock = threading.Lock()

    def __init__(self, airports, data, renderer: Renderer):
        self.width = 128
        self.height = 64

        self.event = threading.Event()
        self.__i2c__ = busio.I2C(SCL, SDA)
        self.__oled__ = OledText(self.__i2c__, self.width, self.height)
        self.__oled__.auto_show = False
        self.__page_layouts__ = define_page_layouts()
        self.__airports__ = airports
        self.__data__ = data
        self.__renderer__ = renderer
        self.__config__ = renderer.__config__
        self.__thread__ = threading.Thread(target=self.loop)
        self.__thread__.daemon = True
        self.__location__ = utils.get_location(self.__renderer__.config.data.geo.city)

    """
    method to start the looping thread
    """
    def start(self):
        self.__thread__.start()

    """
    method to stop the looping thread
    """
    def stop(self):
        self.event.set()
        self.__oled__.clear()

    def loop(self):
        while not self.event.is_set():
            for airport in self.__airports__.keys():
                i = utils.index_in_list(airport, self.__airports__)
                if self.__airports__[airport]['display']:
                    if self.__config__.data.display_screen.locate_active:
                        self.__renderer__.locate(i)
                    self.show_metar(airport, self.__data__.data[airport], self.__config__.data.display_screen.delay)

    def show_metar(self, sta, dat, delay):
        with self.lock:
            self.page1(sta, dat)
            time.sleep(delay)
            self.page2(sta, dat)
            time.sleep(delay)

    def message(self, title, icon="", line1="", line2="", line3=""):
        with self.lock:
            try:
                self.__oled__.layout = self.__page_layouts__[0]
                self.__oled__.text(title)
                self.__oled__.text(icon, 2)
                self.__oled__.text(line1, 3)
                self.__oled__.text(line2, 4)
                self.__oled__.text(line3, 5)
                self.__oled__.show()
            except Exception as e:
                safe_log("[d]: " + str(e))

    def page1(self, station, data):
        try:
            self.__oled__.layout = self.__page_layouts__[1]
            self.__oled__.text(station)
            self.__oled__.text(data["flightCategory"], 2)
            if int(data['windSpeed']) > 0:
                windline = "{0:03d}@{1:02d}".format(int(data["windDir"]), int(data["windSpeed"])) + \
                      ("G{0:2d}".format(int(data["windGustSpeed"])) if data["windGust"] else "")
            else:
                windline = "CALM"
            self.__oled__.text(windline, 3)
            self.__oled__.text(ICON_WIND, 4)
            self.__oled__.text("{0}SM".format(data['vis']), 5)
            self.__oled__.text(ICON_VISIBILITY, 6)
            self.__oled__.text("{0:2.2f}".format(data['altimHg']), 7)
            self.__oled__.text(ICON_PRESSURE, 8)
            self.__oled__.show()
        except Exception as e:
            safe_log(station + ": " + str(e))

    def page2(self, station, data):
        # TODO: change to CONFIG value
        tz = self.__location__.timezone

        try:
            self.__oled__.layout = self.__page_layouts__[2]
            self.__oled__.text(station)
            self.__oled__.text(data["flightCategory"], 2)
            self.__oled__.text("{0}\N{DEGREE SIGN}C / {1:.0f}\N{DEGREE SIGN}F".format(data['tempC'], utils.celsius_to_fahrenheit(data['tempC'])), 3)
            self.__oled__.text(ICON_TEMP, 4)
            self.__oled__.text("{0}\N{DEGREE SIGN}C / {1:.0f}\N{DEGREE SIGN}F".format(data['dewpointC'], utils.celsius_to_fahrenheit(data['dewpointC'])), 5)
            self.__oled__.text(ICON_DEWPOINT, 6)
            self.__oled__.text("{0} {1}".format(data["obsTime"].astimezone(tz).strftime("%H:%MC"), data["obsTime"].strftime("%H:%MZ")), 7)
            self.__oled__.text(ICON_DATE, 8)
            self.__oled__.show()
        except Exception as e:
            safe_log(station + ": " + str(e))

        #
        # yOff = 18
        # xOff = 0
        # NewLine = False
        # for skyIter in data["skyConditions"]:
        #     draw2.text((x + xOff, top + yOff),
        #                skyIter["cover"] + ("@" + str(skyIter["cloudBaseFt"]) if skyIter["cloudBaseFt"] > 0 else ""),
        #                font=fontSmall, fill=255)
        #     if NewLine:
        #         yOff += 12
        #         xOff = 0
        #         NewLine = False
        #     else:
        #         xOff = 65
        #         NewLine = True
        # draw2.text((x, yOff + 12), condition["obs"], font=fontMed, fill=255)


