"""
Ceiling: colors each airport by its ceiling (the lowest broken or overcast layer, or the vertical visibility when the
sky is obscured), at the flight category limits: white when it's high, then yellow, orange and red as it gets lower.
Flight Category shows the worse of ceiling and visibility; this shows the ceiling on its own.
"""
import metarmap.lib.colors as colors_lib
from metarmap.decode import ceiling_ft
from metarmap.models import Look, Metar
from metarmap.visualizers import style
from metarmap.visualizers.style import Band

NAME = "Ceiling"
DESCRIPTION = "Display the ceiling: white above 3,000 ft, then yellow, orange and red as it gets lower."
EXCLUSIVE = False

BANDS = [
    Band(500, colors_lib.RED, "Below 500 ft (LIFR)", "Red"),
    Band(1000, colors_lib.ORANGE, "500-999 ft (IFR)", "Orange"),
    Band(3000, colors_lib.YELLOW, "1,000-3,000 ft (MVFR)", "Yellow", inclusive=True),
    Band(None, colors_lib.WHITE, "Above 3,000 ft (VFR)", "White"),
]


def no_ceiling(settings):
    return style.dim(style.named(colors_lib.WHITE))


def legend(settings):
    return [*style.band_legend(BANDS, settings),
            style.legend_item("No ceiling (clear, few or scattered clouds)", "Dim white", no_ceiling(settings)),
            style.missing_legend("sky condition"), style.no_report_legend()]


def look(metar: Metar, settings) -> Look:
    if not metar:
        return style.no_report()
    layers = metar.get('skyConditions')
    if not layers:
        return style.missing()
    feet = ceiling_ft(layers, metar.get('vertVisFt'))
    if feet is None:
        return Look.solid(no_ceiling(settings))
    return Look.solid(style.band_for(feet, BANDS, settings))
