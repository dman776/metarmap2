"""
FAA Delays: colors each airport by its worst FAA status now (metarmap.delays): closed magenta, a ground stop blinking
red, a delay (a Ground Delay Program's average, or an arrival or departure delay) yellow, orange or red by its minutes,
and no delay (or an airport the FAA doesn't list, such as one abroad) dim white. Only full closures count: one to
some aircraft only (TO NON SKED, EXC, PPR) is left out.
"""

from typing import Optional

import metarmap.lib.colors as colors_lib
from metarmap.delays import CLOSED, DELAY, GROUND_STOP, NORMAL
from metarmap.models import Look, Report
from metarmap.visualizers import style
from metarmap.visualizers.visualizer import Visualizer, legend_item

# a delay's color by its minutes (a Ground Delay Program's average; the middle of an arrival or departure delay's
# range). A delay whose minutes the FAA doesn't give in a form that can be read shows as the shortest
DELAY_BANDS = (
    style.Band(30, colors_lib.YELLOW, "Delay under 30 min", "Yellow"),
    style.Band(60, colors_lib.ORANGE, "Delay 30-59 min", "Orange"),
    style.Band(None, colors_lib.RED, "Delay of an hour or more", "Red"),
)
CLOSED_COLOR = colors_lib.MAGENTA
STOP_COLOR = colors_lib.RED
NONE = colors_lib.GRAY
STOP_PERIOD = style.HEAVY_PERIOD  # a ground stop blinks like heavy weather: bright and dim, never dark
CLOSED_LABEL, STOP_LABEL, NORMAL_LABEL = "Closed", "Ground stop", "No delay, or not an FAA airport"


def stop_look() -> Look:
    red = style.named(STOP_COLOR)
    return Look.blink(red, period=STOP_PERIOD, background=style.dim(red)).tagged(STOP_LABEL)


def legend(settings):
    red = style.named(STOP_COLOR)
    return [
        legend_item(CLOSED_LABEL, "Magenta", style.named(CLOSED_COLOR)),
        legend_item(
            STOP_LABEL, "Fast blink, red and dim red", red, style.dim(red), effect="alternate", period=STOP_PERIOD
        ),
        *style.band_legend(DELAY_BANDS, settings),
        legend_item(NORMAL_LABEL, "Dim white", style.named(NONE)),
        style.missing_legend("", label="No FAA status yet"),
        style.no_report_legend(),
    ]


def look(metar: Optional[Report], settings) -> Look:
    if not metar:
        return style.no_report()
    status = metar.faa_status
    if not status:
        return style.missing()
    kind = status.get("kind")
    if kind == CLOSED:
        return Look.solid(style.named(CLOSED_COLOR)).tagged(CLOSED_LABEL)
    if kind == GROUND_STOP:
        return stop_look()
    if kind == DELAY:
        return style.band_look(status.get("minutes") or 0, DELAY_BANDS, settings)
    if kind == NORMAL:
        return Look.solid(style.named(NONE)).tagged(NORMAL_LABEL)
    return style.missing()


VISUALIZER = Visualizer(
    id="faa_delays",
    name="FAA Delays",
    description="Display each airport's FAA status: closed magenta, a ground stop blinking red, delays yellow under "
    "30 minutes, orange to an hour, red an hour or more; no delay, or not an FAA airport, is dim white.",
    short_name="FAA Delays",
    icon="hourglass",
    legend=legend,
    look=look,
)
