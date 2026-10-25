"""
Visibility: colors each airport by its visibility, with the flight category limits and colors (so red means IFR here
too): more than 5 miles VFR, 3-5 MVFR, 1 to under 3 IFR, under 1 LIFR.
"""
from metarmap.models import Look, Metar
from metarmap.visualizers import style
from metarmap.visualizers.style import Band

NAME = "Visibility"
DESCRIPTION = "Display the visibility, in the flight category limits and colors (VFR over 5 miles ... LIFR under 1)."
EXCLUSIVE = False

BANDS = [
    Band(1, lambda s: s.color.cat.lifr, "Under 1 mile (LIFR)", "Purple"),
    Band(3, lambda s: s.color.cat.ifr, "1 to under 3 miles (IFR)", "Red"),
    Band(5, lambda s: s.color.cat.mvfr, "3 to 5 miles (MVFR)", "Blue", inclusive=True),
    Band(None, lambda s: s.color.cat.vfr, "Over 5 miles (VFR)", "Green"),
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
