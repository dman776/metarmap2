"""
Wind: colors each airport by its wind speed, in a few bands.
"""

from typing import Optional

import metarmap.lib.colors as colors_lib
from metarmap.models import Look, Report
from metarmap.visualizers import style
from metarmap.visualizers.style import Band
from metarmap.visualizers.visualizer import Visualizer


# also the gust colors in Wind Gusts
BANDS = [
    Band(1, colors_lib.GRAY, "Calm", "Dim white"),
    Band(10, colors_lib.BLUE, "1-9 kt", "Blue"),
    Band(15, colors_lib.YELLOW, "10-14 kt", "Yellow"),
    Band(25, colors_lib.ORANGE, "15-24 kt", "Orange"),
    Band(None, colors_lib.RED, "25 kt and over", "Red"),
]


def color_for(speed_kt, settings):
    return style.band_for(speed_kt, BANDS, settings)


def legend(settings):
    return [*style.band_legend(BANDS, settings), style.missing_legend("wind speed"), style.no_report_legend()]


def look(metar: Optional[Report], settings) -> Look:
    if not metar:
        return style.no_report()
    if metar.wind_speed is None:
        return style.missing()
    return Look.solid(color_for(metar.wind_speed, settings))


VISUALIZER = Visualizer(
    id="wind",
    name="Wind",
    description="Display the current wind speed.",
    legend=legend,
    look=look,
    barbs=True,  # the Map page draws each airport's wind barb
)
