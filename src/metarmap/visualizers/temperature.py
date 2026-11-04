"""
Temperature: colors each airport by its temperature, in a few bands from cold to hot.
"""

from typing import Optional

import metarmap.lib.colors as colors_lib
import metarmap.lib.utils as utils
from metarmap.models import Look, Report
from metarmap.visualizers import style
from metarmap.visualizers.style import Band
from metarmap.visualizers.visualizer import Visualizer


# in °F; below freezing gets its own band, since that's where icing starts
BANDS = [
    Band(32, colors_lib.WHITE, "Below 32°F (freezing)", "White"),
    Band(50, colors_lib.PURPLE, "32-49°F", "Purple"),
    Band(65, colors_lib.BLUE, "50-64°F", "Blue"),
    Band(80, colors_lib.LIGHT_BLUE, "65-79°F", "Cyan"),
    Band(90, colors_lib.YELLOW, "80-89°F", "Yellow"),
    Band(100, colors_lib.ORANGE, "90-99°F", "Orange"),
    Band(None, colors_lib.RED, "100°F and over", "Red"),
]


def legend(settings):
    return [*style.band_legend(BANDS, settings), style.missing_legend("temperature"), style.no_report_legend()]


def look(metar: Optional[Report], settings) -> Look:
    if not metar:
        return style.no_report()
    if metar.temp_c is None:
        return style.missing()
    return Look.solid(style.band_for(utils.celsius_to_fahrenheit(metar.temp_c), BANDS, settings))


VISUALIZER = Visualizer(
    id="temperature",
    name="Temperature",
    description="Display the temperature in degrees Fahrenheit.",
    legend=legend,
    look=look,
)
