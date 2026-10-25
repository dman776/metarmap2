"""
Pressure: colors each airport by its altimeter setting: red for low pressure, blue for high.
"""
import metarmap.lib.colors as colors_lib
from metarmap.models import Look, Metar
from metarmap.visualizers import style
from metarmap.visualizers.style import Band

NAME = "Pressure"
DESCRIPTION = "Display the atmospheric pressure (inHg)."
EXCLUSIVE = False

STANDARD_PRESSURE = 29.92

BANDS = [
    Band(29.80, colors_lib.RED, "Below 29.80 inHg (low)", "Red"),
    Band(STANDARD_PRESSURE, colors_lib.LIGHT_RED, "29.80-29.91 inHg", "Light red"),
    Band(30.20, colors_lib.LIGHT_BLUE, "29.92-30.19 inHg", "Light blue"),
    Band(None, colors_lib.BLUE, "30.20 inHg and over (high)", "Blue"),
]


def legend(settings):
    return [*style.band_legend(BANDS, settings), style.missing_legend("altimeter setting"), style.no_report_legend()]


def look(metar: Metar, settings) -> Look:
    if not metar:
        return style.no_report()
    if not metar.get('altimHg'):  # missing from the report (read as 0)
        return style.missing()
    return Look.solid(style.band_for(metar['altimHg'], BANDS, settings))
