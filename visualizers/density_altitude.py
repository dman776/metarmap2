"""
Module to handle visualizing Pressure data
"""

import sys
import time
import datetime
from pprint import pprint
import json

import lib.safe_logging as safe_logging
from config import Config
import lib.utils as utils
import lib.colors as colors_lib
from metar import METAR
from visualizers.visualizer import Visualizer
from adafruit_led_animation.animation.solid import Solid

STANDARD_PRESSURE = 29.92

def get_color_by_da(da: int, elevation_f: int) -> list:
    """
    Given a DA reading, return a RGB color to show on the map.
    Args:
        density altitude (int): The DA reading from a metar in feet.
    Returns:
        list: The RGB color to show on the map for the station.
    """

    colors_by_name = colors_lib.get_colors()

    daf = round(da/elevation_f)     # DA factor

    if da is None:
        return colors_by_name[colors_lib.OFF]

    # if da == elevation_f:
    #     return colors_by_name[colors_lib.BLUE]

    if daf < -20:
        return colors_by_name[colors_lib.GREEN]

    if daf in range(-20, -10):
        return colors_lib.get_color_mix(
            colors_by_name[colors_lib.GREEN], colors_by_name[colors_lib.BLUE],
            utils.get_proportion_between_floats(-20, daf, -10))

    if daf in range(-10, -5):
        return colors_lib.get_color_mix(
            colors_by_name[colors_lib.BLUE], colors_by_name[colors_lib.LIGHT_BLUE],
            utils.get_proportion_between_floats(-10, daf, -5))

    if daf in range(-5, 0):
        return colors_lib.get_color_mix(
            colors_by_name[colors_lib.LIGHT_BLUE], colors_by_name[colors_lib.DARK_GRAY],
            utils.get_proportion_between_floats(-5, daf, 0))

    # if daf in range(0, 30):
    #     return colors_lib.get_color_mix(
    #         [1, 1, 1], colors_by_name[colors_lib.DARK_RED],
    #         utils.get_proportion_between_floats(0, daf, 30))

    # if daf in range(10, 20):
    #     return colors_lib.get_color_mix(
    #         colors_by_name[colors_lib.YELLOW], colors_by_name[colors_lib.LIGHT_RED],
    #         utils.get_proportion_between_floats(10, daf, 20))

    if daf in range(0, 40):
        return colors_lib.get_color_mix(
            colors_by_name[colors_lib.DARK_GRAY], colors_by_name[colors_lib.RED],
            utils.get_proportion_between_floats(0, daf, 40))

    if daf >= 40:
        return colors_by_name[colors_lib.RED]


def meters_to_feet(m):
    return m * 3.28084


def calculate_density_altitude(pressure, field_elevation, oat: float):
    fef = meters_to_feet(field_elevation)
    pa = (STANDARD_PRESSURE - pressure) * 1000 + fef
    isa = 15 - 1.98 * fef / 1000
    da = pa + 118.8 * (float(oat) - isa)
    return da


class DensityAltitude(Visualizer):
    """
    Object to handle DA
    Returns a list of Effects on each pixel
    """
    def __init__(self, data, pix, config):
        super().__init__(data, pix, config)

    @property
    def name(self):
        return "Density Altitude"

    @property
    def description(self):
        return """
            Display the density altitude (DA) relative to field elevation (FE) (ie. Density altitude factor).
            <div class="w-100">
            <ul>
                <li>DA = FE =<font color='blue'>BLUE</font></li>
                <li>DA/FE (aka. Density altitude factor, DAF) < -40 = <font color='green'>GREEN</font></li>
                <li>DAF between -40 (<font color='green'>GREEN</font>) and -20 (<font color='blue'>BLUE</font>)</li>
                <li>DAF between -20 (<font color='blue'>BLUE</font>) and -10 (<font color='lightblue'>LIGHT BLUE</font>)</li>
                <li>DAF between -10 (<font color='lightblue'>LIGHT BLUE</font>) and 0 (<font color='gray'>GRAY</font>)</li>
                <li>DAF between 0 (<font color='gray'>GRAY</font>) and 30 (<font color='darkred'>DARK RED</font>)</li>
                <li>DAF between 30 (<font color='darkred'>DARK RED</font>) and 40 (<font color='red'>RED</font>)</li>
                <li>DAF between 0 (<font color='gray'>GRAY</font>) and 30 (<font color='darkred'>DARK RED</font>)</li>
                <li>DAF Greater than 40 =<font color='red'>RED</font></li>
            </ul>
            </div>
        """

    def update_data(self, data):
        super().update_data(data)

        # loop over all stations
        i = 0
        # for airport in list(self.__stations__):
        for airport in list(self.__data__.keys()):
            # Skip NULL entries
            if "NULL" in airport:
                self.__effect__.append(Solid(self.__pix__[i], color=[0, 0, 0]))
                i += 1
                continue
            airport_data = self.__data__.get(airport, None)

            if len(airport_data.keys()) > 0:
                if airport_data is not None and airport_data['altimHg'] != "" and airport_data['elevation_m'] != ""  and airport_data['tempC'] != "":
                    da = calculate_density_altitude(airport_data['altimHg'], meters_to_feet(airport_data['elevation_m']), airport_data['tempC'])
                    daf = round(da/meters_to_feet(airport_data['elevation_m']))     # density altitude factor
                    pcolor = get_color_by_da(da, meters_to_feet(airport_data['elevation_m']))
                    # safe_logging.safe_log("STA: " + airport + " " + str(round(da/meters_to_feet(airport_data['elevation_m']))))
                    # if daf >= 40: effect should BLINK
                    # else:
                    self.__effect__.append(Solid(self.__pix__[i], color=pcolor))
                else:  # airport key not found in metar data
                    self.__effect__.append(Solid(self.__pix__[i], color=[0, 0, 0]))
            else:  # airport data is empty METAR data
                self.__effect__.append(Solid(self.__pix__[i], color=[0, 0, 0]))
            i += 1


