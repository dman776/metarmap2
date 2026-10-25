"""
Density Altitude: colors each airport by how far its density altitude is above the field: how much higher the
airport "feels" to an airplane on a hot day or with low pressure.
"""
from typing import Union

import metarmap.lib.colors as colors_lib
from metarmap.models import Look, Metar
from metarmap.visualizers import style
from metarmap.visualizers.style import Band

NAME = "Density Altitude"
DESCRIPTION = "Display the density altitude above the field elevation (how much higher the airport \"feels\")."
EXCLUSIVE = False

STANDARD_PRESSURE = 29.92

# feet of density altitude above the field elevation
BANDS = [
    Band(1000, colors_lib.LIGHT_BLUE, "Less than 1,000 ft above the field", "Cyan"),
    Band(2000, colors_lib.YELLOW, "1,000-1,999 ft above", "Yellow"),
    Band(3000, colors_lib.ORANGE, "2,000-2,999 ft above", "Orange"),
    Band(None, colors_lib.RED, "3,000 ft or more above", "Red"),
]


def meters_to_feet(m: float) -> float:
    return m * 3.28084


def calculate_density_altitude(pressure: float, field_elevation_m: float, oat: float) -> Union[None, float]:
    """
    Calculates the density altitude given the pressure (in inHg), field elevation (in meters),
    and the outside air temperature (in Celsius).
    Args:
        pressure (float): The pressure reading in inHg.
        field_elevation_m (float): The field elevation in meters.
        oat (float): The outside air temperature in Celsius.
    Returns:
        Union[None, float]: The density altitude in feet or None if any of the input parameters is None.
    """
    if None in [pressure, field_elevation_m, oat]:
        return None
    fef = meters_to_feet(field_elevation_m)
    pa = (STANDARD_PRESSURE - pressure) * 1000 + fef
    isa = 15 - 1.98 * fef / 1000
    return pa + 118.8 * (oat - isa)


def legend(settings):
    return [*style.band_legend(BANDS, settings), style.missing_legend("temperature or altimeter setting"),
            style.no_report_legend()]


def look(metar: Metar, settings) -> Look:
    if not metar:
        return style.no_report()
    # a sea-level field (0 m) and 0°C are real values; a missing altimeter setting is read as 0
    if not metar.get('altimHg') or metar.get('elevation_m') is None or metar.get('tempC') is None:
        return style.missing()
    density_altitude = calculate_density_altitude(metar['altimHg'], metar['elevation_m'], metar['tempC'])
    above = density_altitude - meters_to_feet(metar['elevation_m'])
    return Look.solid(style.band_for(above, BANDS, settings))
