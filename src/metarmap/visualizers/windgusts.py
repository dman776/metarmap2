"""
Wind Gusts: colors each airport by how much stronger its gusts are than its wind (the gust spread), the cue pilots use
for how bumpy and changeable the wind is. Wind shows how strong the wind is; this shows how much it swings.
"""
import metarmap.lib.colors as colors_lib
from metarmap.models import Look, Metar
from metarmap.visualizers import style
from metarmap.visualizers.style import Band

NAME = "Wind Gusts"
DESCRIPTION = "Display how much stronger the gusts are than the wind: dim white with no gusts, then blue, yellow, " \
              "orange and red as the gusts get stronger."
EXCLUSIVE = False

# knots the gusts are above the wind
BANDS = [
    Band(1, colors_lib.GRAY, "No gusts", "Dim white"),
    Band(10, colors_lib.BLUE, "Gusts 1-9 kt above the wind", "Blue"),
    Band(15, colors_lib.YELLOW, "10-14 kt above", "Yellow"),
    Band(20, colors_lib.ORANGE, "15-19 kt above", "Orange"),
    Band(None, colors_lib.RED, "20 kt or more above", "Red"),
]


def gust_spread(metar: Metar) -> int:
    """Knots the gusts are above the wind; 0 when it isn't gusting."""
    if not metar.get('windGust'):
        return 0
    return max(0, (metar.get('windGustSpeed') or 0) - metar['windSpeed'])


def legend(settings):
    return [*style.band_legend(BANDS, settings), style.missing_legend("wind speed"), style.no_report_legend()]


def look(metar: Metar, settings) -> Look:
    if not metar:
        return style.no_report()
    if metar.get('windSpeed') is None:
        return style.missing()
    return Look.solid(style.band_for(gust_spread(metar), BANDS, settings))
