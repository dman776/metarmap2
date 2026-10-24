# import os, sys
# import json
# from pprint import pprint
# import datetime
#
# import lib.config
from config import Config
from lib import utils


# import metar
# from PIL import Image, ImageDraw, ImageFont
# import io

import pytz
from pytz import timezone

try:
    # OLED drivers: only on the Pi. Blinka's board module raises NotImplementedError on other machines.
    from board import SCL, SDA
    import busio
    from oled_text import OledText, BigLine
    import adafruit_ssd1306  # noqa: F401 (oled_text needs it; fail early if missing)

    noDisplayLibraries = False
except (ImportError, NotImplementedError):
    noDisplayLibraries = True

from lib.safe_logging import safe_log
import threading
import time
import traceback


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


MISSING = "--"


def safe_text(fn, data):
    """
    Runs one line's formatter; a value that can't be shown becomes "--" instead of failing the page.
    """
    try:
        text = fn(data)
        return MISSING if text in (None, "") else str(text)
    except (KeyError, TypeError, ValueError, AttributeError):
        return MISSING


def wind_text(data):
    speed = data.get('windSpeed')
    if not isinstance(speed, int):
        return speed
    if speed <= 0:
        return "CALM"
    wind_dir = str(data.get("windDir", "")).upper()
    wind_dir = "VRB" if wind_dir in ("VRB", "") else "{0:03d}".format(int(wind_dir))
    gust = "G{0:02d}".format(int(data["windGustSpeed"])) if data.get("windGust") else ""
    return "{0}@{1:02d}{2}".format(wind_dir, speed, gust)


def temp_text(celsius):
    if celsius is None:
        return None
    return "{0}\N{DEGREE SIGN}C / {1:.0f}\N{DEGREE SIGN}F".format(celsius, utils.celsius_to_fahrenheit(celsius))


def time_text(obs, tz):
    return "{0} {1}".format(obs.astimezone(tz).strftime("%H:%MC"), obs.strftime("%H:%MZ"))


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
        lines = [{"icon": "wind", "text": safe_text(wind_text, data)},
                 {"icon": "visibility", "text": safe_text(lambda d: "{0}SM".format(d['vis']), data)},
                 {"icon": "pressure", "text": safe_text(lambda d: "{0:2.2f}".format(d['altimHg']), data)}]
    else:
        lines = [{"icon": "temp", "text": safe_text(lambda d: temp_text(d['tempC']), data)},
                 {"icon": "dewpoint", "text": safe_text(lambda d: temp_text(d['dewpointC']), data)},
                 {"icon": "date", "text": safe_text(lambda d: time_text(d['obsTime'], tz), data)}]
    return {"airport": station, "title": station, "badge": data.get("flightCategory") or "", "page": page,
            "lines": lines}


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
        self.__renderer__ = config.renderer
        self.__thread__ = threading.Thread(target=self.loop, args=(self.event,), name="display")
        self.__thread__.daemon = True
        location = utils.get_location(self.__renderer__.config.data.geo.city)
        self.__tz__ = timezone(location.timezone) if location else pytz.utc
        self.__screen__ = None  # what is on the OLED right now (mirrored by the web UI)
        self.last_change = time.time()  # when the loop last moved on; used by the watchdog

    def is_alive(self):
        return self.__thread__.is_alive()

    @property
    def screen(self):
        return self.__screen__

    """
    method to start the looping thread
    """

    def start(self):
        self.last_change = time.time()
        self.__thread__.start()

    """
    method to stop the looping thread
    """

    def stop(self, clear=True):
        self.event.set()
        if clear:
            self.__oled__.clear()
            self.__screen__ = None

    def restart(self, timeout=None):
        """
        Stops the loop thread and starts a new one. With a timeout, a thread that doesn't stop in time
        (e.g. stuck in an I2C write) is abandoned: it has its own stop event, so it can't fight the new one.
        """
        self.stop(False)
        self.__thread__.join(timeout)
        if self.__thread__.is_alive():
            safe_log("[d]display thread did not stop; starting a new one anyway")
        self.event = threading.Event()
        self.__thread__ = threading.Thread(target=self.loop, args=(self.event,), name="display")
        self.__thread__.daemon = True
        self.last_change = time.time()
        self.start()

    def loop(self, event):
        while not event.is_set():
            # a fresh copy each pass: airports can be edited while the loop runs
            airports = list(self.__config__.airports.items())
            shown = False
            for i, (airport, props) in enumerate(airports):
                if event.is_set():
                    return
                if not props.get('display'):
                    continue
                shown = True
                if self.__config__.data.display_screen.locate_active:
                    try:
                        self.__renderer__.locate(i)
                    except Exception as e:
                        # a failed LED pulse shouldn't cost the airport its pages
                        safe_log(f"[d]locate {airport}: {e}")
                try:
                    self.show_metar(airport, self.__data__.data.get(airport) or {},
                                    self.__config__.data.display_screen.delay, event)
                except Exception as e:
                    # never let one airport stop the loop
                    safe_log(f"[d]loop: {airport}: {e}\n{traceback.format_exc()}")
                    event.wait(1)
            if not shown:
                self.last_change = time.time()
                event.wait(5)  # nothing to show; don't spin

    def show_page(self, draw, delay, event):
        """
        Draws one page, then waits. The lock is only held while drawing, so message() isn't blocked.
        """
        with self.lock:
            if event.is_set():
                return False
            draw()
        self.last_change = time.time()
        return not event.wait(delay)

    def show_metar(self, sta, dat, delay, event):
        if dat:
            if self.show_page(lambda: self.page1(sta, dat), delay, event):
                self.show_page(lambda: self.page2(sta, dat), delay, event)
        else:
            self.show_page(lambda: self.page_unavailable(sta), delay, event)

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
                safe_log("[d]message: " + str(e))

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
        try:
            self.show_screen(screen_for(station, data, 2, self.__tz__))
        except Exception as e:
            safe_log("[d].page2: " + station + ": " + str(e))
