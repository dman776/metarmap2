"""
Dewpoint Spread: colors each airport by how far apart its temperature and dewpoint are. The closer they are, the
more humid the air: at 2°C or less, fog or low clouds can form (especially as it cools overnight).
"""
import metarmap.lib.colors as colors_lib
from metarmap.models import Look, Metar
from metarmap.visualizers import style
from metarmap.visualizers.style import Band

NAME = "Dewpoint Spread"
DESCRIPTION = "Display the temperature-dewpoint spread (fog risk): white when it's dry, red when fog is likely."
EXCLUSIVE = False

# °C between the temperature and the dewpoint
BANDS = [
    Band(1, colors_lib.RED, "1°C or less: fog or low clouds likely", "Red", inclusive=True),
    Band(2, colors_lib.ORANGE, "2°C: fog or low clouds can form", "Orange", inclusive=True),
    Band(4, colors_lib.YELLOW, "3-4°C: humid", "Yellow", inclusive=True),
    Band(None, colors_lib.WHITE, "More than 4°C: dry", "White"),
]


def legend(settings):
    return [*style.band_legend(BANDS, settings), style.missing_legend("temperature or dewpoint"),
            style.no_report_legend()]


def look(metar: Metar, settings) -> Look:
    if not metar:
        return style.no_report()
    if metar.get('tempC') is None or metar.get('dewpointC') is None:
        return style.missing()
    return Look.solid(style.band_for(metar['tempC'] - metar['dewpointC'], BANDS, settings))
