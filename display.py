# import os, sys
# import json
# from pprint import pprint
# import datetime
#
# import lib.config
from config import Config
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


def wind_text(data):
    if isinstance(data['windSpeed'], int):
        if int(data['windSpeed']) > 0:
            if str(data["windDir"]).upper() == "VRB":
                wind_dir = "VRB"
            else:
                wind_dir = "{0:03d}".format(int(data["windDir"]))

            return "{0}@{1:02d}".format(
                wind_dir,
                int(data["windSpeed"])
            ) + (
                "G{0:02d}".format(int(data["windGustSpeed"])) if data.get("windGust") else ""
            )
        return "CALM"
    return data['windSpeed']


def temp_text(celsius):
    return "{0}\N{DEGREE SIGN}C / {1:.0f}\N{DEGREE SIGN}F".format(celsius, utils.celsius_to_fahrenheit(celsius))


def screen_for(station, data, page, tz=None):
    """
    What the screen shows for one airport: page 1 (wind, visibility, pressure),
    page 2 (temperature, dewpoint, time) or page 0 (no data).
    Returned as a dict so the web UI can mirror the OLED.
    """
    if page == 0:
        return {"airport": station, "title": station, "badge": "", "page": 0,
                "lines": [{"icon": "", "text": "Data"}, {"icon": "", "text": "Unavailable"}, {"icon": "", "text": ""}]}
    if page == 1:
        lines = [{"icon": "wind", "text": wind_text(data)},
                 {"icon": "visibility", "text": "{0}SM".format(data['vis'])},
                 {"icon": "pressure", "text": "{0:2.2f}".format(data['altimHg'])}]
    else:
        has_temp = isinstance(data['tempC'], int)
        obs = data["obsTime"]
        lines = [{"icon": "temp", "text": temp_text(data['tempC']) if has_temp else ""},
                 {"icon": "dewpoint", "text": temp_text(data['dewpointC']) if has_temp else ""},
                 {"icon": "date", "text": "{0} {1}".format(obs.astimezone(tz).strftime("%H:%MC"), obs.strftime("%H:%MZ"))}]
    return {"airport": station, "title": station, "badge": data["flightCategory"] or "", "page": page, "lines": lines}


ICONS = {"wind": ICON_WIND, "visibility": ICON_VISIBILITY, "pressure": ICON_PRESSURE, "temp": ICON_TEMP,
         "dewpoint": ICON_DEWPOINT, "date": ICON_DATE, "info": ICON_INFO, "": ""}


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

    def __init__(self, config: Config, data):
        self.width = 128
        self.height = 64

        self.event = threading.Event()
        self.__i2c__ = busio.I2C(SCL, SDA)
        self.__oled__ = OledText(self.__i2c__, self.width, self.height)
        self.__oled__.auto_show = False
        self.__page_layouts__ = define_page_layouts()
        self.__data__ = data
        self.__config__ = config
        self.__airports__ = config.airports
        self.__renderer__ = config.renderer
        self.__thread__ = threading.Thread(target=self.loop)
        self.__thread__.daemon = True
        self.__location__ = utils.get_location(self.__renderer__.config.data.geo.city)
        self.__screen__ = None  # what is on the OLED right now (mirrored by the web UI)

    @property
    def screen(self):
        return self.__screen__

    """
    method to start the looping thread
    """

    def start(self):
        self.__thread__.start()

    """
    method to stop the looping thread
    """

    def stop(self, clear=True):
        self.event.set()
        if clear:
            self.__oled__.clear()
            self.__screen__ = None

    def restart(self):
        self.stop(False)
        self.__thread__.join()
        self.event.clear()
        self.__thread__ = threading.Thread(target=self.loop)
        self.__thread__.daemon = True
        self.start()

    def loop(self):
        while not self.event.is_set():
            for airport in self.__airports__.keys():
                i = utils.index_in_list(airport, self.__airports__)
                if self.__airports__[airport]['display']:
                    if self.__config__.data.display_screen.locate_active:
                        self.__renderer__.locate(i)
                    self.show_metar(airport, self.__data__.data[airport], self.__config__.data.display_screen.delay)
                if self.event.is_set():
                    return

    def show_metar(self, sta, dat, delay):
        if len(dat) > 0:
            with self.lock:
                if self.event.is_set():
                    return
                self.page1(sta, dat)
                time.sleep(delay)
                if self.event.is_set():
                    return
                self.page2(sta, dat)
                time.sleep(delay)
        else:
            with self.lock:
                if self.event.is_set():
                    return
                self.page_unavailable(sta)
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
                self.__screen__ = {"airport": None, "title": title, "badge": "", "page": 0,
                                   "icon": next((k for k, v in ICONS.items() if v == icon and k), ""),
                                   "lines": [{"icon": "", "text": t} for t in (line1, line2, line3)]}
            except Exception as e:
                safe_log("[d]: " + str(e))

    def show_screen(self, screen):
        self.__oled__.layout = self.__page_layouts__[1 if screen["page"] < 2 else 2]
        self.__oled__.text(screen["title"])
        self.__oled__.text(screen["badge"], 2)
        for n, line in enumerate(screen["lines"]):
            self.__oled__.text(line["text"], 3 + n * 2)
            self.__oled__.text(ICONS[line["icon"]], 4 + n * 2)
        self.__oled__.show()
        self.__screen__ = screen

    def page_unavailable(self, station):
        try:
            self.show_screen(screen_for(station, None, 0))
        except Exception as e:
            safe_log("[d].page_unavailable: " + station + ": " + str(e))

    def page1(self, station, data):
        try:
            self.show_screen(screen_for(station, data, 1))
        except Exception as e:
            safe_log("[d].page1: " + station + ": " + str(e))

    def page2(self, station, data):
        tz = timezone(self.__location__.timezone)
        try:
            self.show_screen(screen_for(station, data, 2, tz))
        except Exception as e:
            safe_log("[d].page2: " + station + ": " + str(e))
