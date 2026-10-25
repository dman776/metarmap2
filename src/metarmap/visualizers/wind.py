"""
Wind: colors each airport by its wind speed, in a few bands.
"""
import metarmap.lib.colors as colors_lib
from metarmap.models import Look, Metar
from metarmap.visualizers import style
from metarmap.visualizers.style import Band

NAME = "Wind"
DESCRIPTION = "Display the current wind speed."
EXCLUSIVE = False

# also the gust colors in Wind Gusts
BANDS = [
    Band(1, colors_lib.GRAY, "Calm", "Dim white"),
    Band(10, colors_lib.GREEN, "1-9 kt", "Green"),
    Band(15, colors_lib.YELLOW, "10-14 kt", "Yellow"),
    Band(25, colors_lib.ORANGE, "15-24 kt", "Orange"),
    Band(None, colors_lib.RED, "25 kt and over", "Red"),
]


def color_for(speed_kt, settings):
    return style.band_for(speed_kt, BANDS, settings)


def legend(settings):
    return [*style.band_legend(BANDS, settings), style.missing_legend("wind speed"), style.no_report_legend()]


def look(metar: Metar, settings) -> Look:
    if not metar:
        return style.no_report()
    if metar.get('windSpeed') is None:
        return style.missing()
    return Look.solid(color_for(metar['windSpeed'], settings))
