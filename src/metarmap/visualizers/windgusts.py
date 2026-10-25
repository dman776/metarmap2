"""
Wind Gusts: each airport's wind color (as in Wind); when it's gusting, the LED alternates with the gusts' color.
"""
from metarmap.models import Look, Metar
from metarmap.visualizers import style, wind
from metarmap.visualizers.visualizer import legend_item

NAME = "Wind Gusts"
DESCRIPTION = "Display the wind gusts: the wind's color, alternating with the color of the gusts when it's gusting."
EXCLUSIVE = False

GUST_PERIOD = 2.0  # seconds per alternation between the wind's and the gusts' colors


def legend(settings):
    bands = wind.BANDS
    return [
        *style.band_legend(bands, settings),
        legend_item("Gusting", "The wind's color, alternating with the gusts' color (e.g. 12 kt gusting 27)",
                    bands[2].color_for(settings), bands[4].color_for(settings), effect="alternate",
                    period=GUST_PERIOD),
        legend_item("Gusting, gusts in the same band", "Breathing", bands[1].color_for(settings), effect="pulse",
                    period=GUST_PERIOD, low=style.LIGHT_LOW),
        style.missing_legend("wind speed"),
        style.no_report_legend(),
    ]


def look(metar: Metar, settings) -> Look:
    if not metar:
        return style.no_report()
    if metar.get('windSpeed') is None:
        return style.missing()
    color = wind.color_for(metar['windSpeed'], settings)
    if not metar.get('windGust'):
        return Look.solid(color)
    gust = wind.color_for(metar.get('windGustSpeed') or 0, settings)
    if gust == color:
        return Look.pulse(color, period=GUST_PERIOD, low=style.LIGHT_LOW)
    return Look.blink(color, period=GUST_PERIOD, background=gust)
