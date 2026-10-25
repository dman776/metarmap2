"""
Visibility: colors each airport by its visibility, at the flight category limits (over 5 miles, 3-5, 1 to under 3,
under 1 mile): white when it's good, then yellow, orange and red as it gets worse.
"""
import metarmap.lib.colors as colors_lib
from metarmap.models import Look, Metar
from metarmap.visualizers import style
from metarmap.visualizers.style import Band

NAME = "Visibility"
DESCRIPTION = "Display the visibility: white over 5 miles, then yellow, orange and red as it gets worse."
EXCLUSIVE = False

BANDS = [
    Band(1, colors_lib.RED, "Under 1 mile (LIFR)", "Red"),
    Band(3, colors_lib.ORANGE, "1 to under 3 miles (IFR)", "Orange"),
    Band(5, colors_lib.YELLOW, "3 to 5 miles (MVFR)", "Yellow", inclusive=True),
    Band(None, colors_lib.WHITE, "Over 5 miles (VFR)", "White"),
]


def legend(settings):
    return [*style.band_legend(BANDS, settings), style.missing_legend("visibility"), style.no_report_legend()]


def look(metar: Metar, settings) -> Look:
    if not metar:
        return style.no_report()
    miles = metar.get('visibilitySM', metar.get('vis'))  # exact miles; older data only has the rounded 'vis'
    if miles is None:
        return style.missing()
    return Look.solid(style.band_for(miles, BANDS, settings))
