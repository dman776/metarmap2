"""
Precipitation Forecast: every airport steps through its weather now (from the METAR) and as its TAF forecasts it 3, 6
and 12 hours ahead, fading from one step to the next, all airports together. A step looks as it does in Precipitation:
the color says what it is, the effect how much (light breathes, heavy blinks...).

When a TEMPO or PROB group is in effect (and visualizer.forecast_include_tempo is on), the most significant weather of
it and the forecast it changes shows: thunderstorms, then hazards, ice, snow, rain... as Precipitation ranks them, and
the heavier of two of one kind. A dry forecast is off. An airport that issues no TAF (only about 700 US stations do)
shows its weather now, then a dim white for the forecast steps, which isn't "dry": it must not look like fair weather.

The forecast is in the report (Report.forecast_weather: forecast.HOURS ahead).
"""

from typing import Optional

from metarmap.decode import parse_weather
from metarmap.forecast import HOURS
from metarmap.models import Look, Report
from metarmap.visualizers import forecast_steps, precipitation, style
from metarmap.visualizers.forecast_steps import FRAME, NO_FORECAST, NO_FORECAST_COLOR
from metarmap.visualizers.visualizer import Visualizer, legend_item

# how much of a kind: heavy, moderate, light, in the vicinity
INTENSITY_ORDER = {style.HEAVY: 0, style.MODERATE: 1, style.LIGHT: 2, style.VICINITY: 3}


def weight(obs):
    """How significant a weather string is, as Precipitation ranks it: (rank, intensity), lower is more significant."""
    best = (len(precipitation.KINDS) + 1, 0)
    for group in parse_weather(obs):
        kinds = precipitation.kinds_in(group)
        if group.descriptor == "TS":
            rank = -1
        elif kinds:
            rank = precipitation.RANK[kinds[0]]
        else:
            continue
        best = min(best, (rank, INTENSITY_ORDER[precipitation.intensity_of(group)]))
    return best


def most_significant(candidates):
    """The most significant of weather strings (the first wins a tie); "" for a dry forecast (none)."""
    return min(candidates, key=weight, default="")


def step_look(obs, settings) -> Look:
    return precipitation.look_for_weather(obs, settings)


def hold(look: Look, frames: int):
    """What a step's look does over its hold: the color at each frame (a breathing light rain keeps breathing)."""
    return [tuple(style.color_at(look, n * FRAME)) for n in range(frames)]


def legend(settings):
    items = list(precipitation.legend(settings))
    at = next((n for n, item in enumerate(items) if item["key"] == style.MISSING), len(items))
    items.insert(
        at,
        legend_item(
            "No forecast",
            "Dim white: the station issues no TAF, or its TAF doesn't reach that far",
            NO_FORECAST_COLOR,
            key=NO_FORECAST,
        ),
    )
    return items


def look(metar: Optional[Report], settings) -> Look:
    if not metar:
        return style.no_report()
    now = step_look(metar.weather, settings)
    if now == style.missing():  # weather codes the map doesn't know: nothing to step from
        return now
    looks = [now]
    ahead = metar.forecast_weather or (None,) * len(HOURS)
    for candidates in ahead:
        if candidates is None:  # no TAF, or one that doesn't reach that far
            looks.append(Look.solid(NO_FORECAST_COLOR).tagged(NO_FORECAST))
        else:
            looks.append(step_look(most_significant(candidates), settings))
    keys = tuple(key for each in looks for key in each.legend)
    held = forecast_steps.hold_frames(settings)
    holds = [hold(each, held) for each in looks]
    if len({color for h in holds for color in h}) == 1:  # the same all day
        return Look.solid(holds[0][0]).tagged(*keys)
    return Look.cycle(forecast_steps.sequence(holds), step=FRAME).tagged(*keys)


VISUALIZER = Visualizer(
    id="precipitation_forecast",
    name="Precipitation Forecast",
    description="Steps through each airport's weather now and as its TAF forecasts it 3, 6 and 12 hours ahead, all "
    "airports together: the color is what it is, the effect how heavy. A dim white is a step with no forecast.",
    short_name="Precip Fcst",
    icon="umbrella",
    legend=legend,
    look=look,
    steps=lambda settings: forecast_steps.steps(settings, "PF"),
)
