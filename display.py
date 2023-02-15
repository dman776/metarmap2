import pprint
import datetime
import metar
try:
	from board import SCL, SDA
	import busio
	from PIL import Image, ImageDraw, ImageFont
	import adafruit_ssd1306
	import time
	from pytz import timezone
	import pytz
	noDisplayLibraries = False
except ImportError:
	noDisplayLibraries = True

from lib.safe_logging import safe_log
import threading
import io

fontLarge = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf', 20)
fontMed = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', 15)
fontSmall = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', 12)
fontXSmall = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', 11)

padding = -3
x = 0


class Display(object):
    """
    Class to handle running an external OLED display
    """
    def on(self):
        """
        Starts the display.
        """
        if self.__disp__ is not None:
            self.__disp__.poweron()

    def show_metar(self, sta, dat, delay):
        self.page1(sta, dat)
        time.sleep(delay)
        self.page2(sta, dat)
        time.sleep(delay)
        # threading.Thread(target=self._app.run, kwargs=dict(host=self._host, port=self._port)).start()

    def off(self):
        if self.__disp__ is not None:
            self.__disp__.poweroff()

    def clear(self):
        self.__disp__.fill(0)
        self.__disp__.show()

    def __init__(self):
        self.width = 128
        self.height = 64
        self.__i2c__ = busio.I2C(SCL, SDA)
        self.__disp__ = adafruit_ssd1306.SSD1306_I2C(128, 64, self.__i2c__)
        self.__image__ = Image.new("1", (self.width, self.height))
        self.__draw__ = ImageDraw.Draw(self.__image__)

    def page1(self, station, data):
        # Draw a black filled box to clear the image.
        self.__draw__.rectangle((0, 0, self.width, self.height), outline=0, fill=0)

        top = padding
        bottom = self.height - padding

        # self.__draw__.line([(x + 64, top + 18), (x + 64, bottom)], fill=255, width=1)
        # central = timezone('US/Central')
        self.__draw__.text((x, top + 0), station[1:] + "-" + data["flightCategory"], font=fontLarge,
                   fill=255)  # StationID, Condition (VFR/IFR)
        # w, h = fontXSmall.getsize(str(station[1]))
        # draw1.text((self.width - w, top + 1), str(station[1]), font=fontXSmall, fill=255)  # Custom text ("HOME", "CNTRL" etc)
        #
        # draw1.text((x, top + 20), condition["windDir"] + "@" + str(condition["windSpeed"]) + (
        #             ("G" + str(condition["windGustSpeed"]) if condition["windGust"] else "") + "/" + str(
        #         condition["vis"]) + "SM "), font=fontMed, fill=255)
        # draw1.text((x, top + 35), str(condition["altimHg"]) + "Hg" + " " + str(condition["tempC"]) + "/" + str(
        #     condition["dewpointC"]) + "C", font=fontMed, fill=255)
        # draw1.text((x, top + 50),
        #            condition["obsTime"].astimezone(central).strftime("%H:%MC") + " " + condition["obsTime"].strftime(
        #                "%H:%MZ"), font=fontSmall, fill=255)

        self.__disp__.image(self.__image__)
        self.__disp__.show()


    def page2(self, station, data):
        self.__draw__.rectangle((0, 0, self.width, self.height), outline=0, fill=0)
        top = padding
        bottom = self.height - padding

        self.__draw__.rectangle((0, 0, self.width, self.height), outline=0, fill=0)
        self.__draw__.text((x, top + 0), station[1:] + "-" + data["flightCategory"], font=fontLarge,
                   fill=255)  # StationID, Condition (VFR/IFR)
        w, h = fontXSmall.getsize(str(station))
        self.__draw__.text((self.width - w, top + 1), "TEST", font=fontXSmall, fill=255)  # Custom text ("HOME", "CNTRL" etc)
        #
        # yOff = 18
        # xOff = 0
        # NewLine = False
        # for skyIter in condition["skyConditions"]:
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
        self.__disp__.image(self.__image__)
        self.__disp__.show()

    def message(self, title, msg):
        self.clear()
        self.__draw__.text((x, padding + 0), title, font=fontLarge, fill=255)
        self.__draw__.text((x, padding + 20), msg, font=fontMed, fill=255)
        self.__disp__.image(self.__image__)
        self.__disp__.show()


if __name__ == '__main__':
    d = Display()
    d.on()
    d.message("METARMap", "Loading...")
    time.sleep(2)
    d.show_metar("KDWH", {'altimHg': 30.0, 'dewpointC': 19, 'flightCategory': 'MVFR',
                'latitude': '30.07', 'lightning': False, 'longitude': '-95.55',
                'obs': '', 'obsTime': datetime.datetime(2023, 2, 8, 14, 53, tzinfo=datetime.timezone.utc),
                'raw': 'KDWH 081453Z 18007G21KT 10SM BKN012 OVC020 22/19 A3000 RMK AO2 SLP155 T02220194 51011',
                'skyConditions': [{'cloudBaseFt': 2000, 'cover': 'OVC'}],
                'tempC': 22,
                'vis': 10,
                'windDir': '180',
                'windGust': True,
                'windGustSpeed': 21,
                'windSpeed': 7},
                 5)

    d.off()

