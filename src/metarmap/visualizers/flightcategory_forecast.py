"""
Flight Category Forecast: every airport steps through its flight category now (from the METAR) and as its TAF forecasts
it 3, 6 and 12 hours ahead, fading from one step to the next, all airports together. The colors are Flight Category's.

An airport that issues no TAF (only about 700 US stations do) shows its category now, then a dim white for the forecast
steps, which isn't a category: it must not look like good weather. With nothing to tell the category now from, it's the
missing-data blink.

The forecast is in the report (Report.forecast: forecast.HOURS ahead); how long each step is shown is
visualizer.forecast_step_seconds, and whether TEMPO and PROB groups count is visualizer.forecast_include_tempo (which
is worked out with the reports, not here).
"""

from typing import Optional

import metarmap.lib.colors as colors_lib
from metarmap.decode import estimate_category
from metarmap.forecast import HOURS
from metarmap.models import FlightCategory as Category, Look, Report
from metarmap.visualizers import style
from metarmap.visualizers.flightcategory import COLORS
from metarmap.visualizers.visualizer import Visualizer, legend_item

NO_FORECAST = "no_forecast"
NO_FORECAST_COLOR = style.dim(colors_lib.color(colors_lib.WHITE), 0.25)
FRAME = 0.2  # seconds per frame (the LED library steps a look through its colors at one speed)
FADE = 1.0  # seconds a step takes to fade into the next
STEPS = ("Now",) + tuple(f"+{h}h" for h in HOURS)


def legend(settings):
    items = [
        legend_item(
            "VFR", "Green", COLORS[Category.VFR], effect="solid"
        ),  # the steps fade between these, so each is a solid color in the legend
        legend_item("MVFR", "Blue", COLORS[Category.MVFR]),
        legend_item("IFR", "Red", COLORS[Category.IFR]),
        legend_item("LIFR", "Purple", COLORS[Category.LIFR]),
        legend_item(
            "No forecast",
            "Dim white: the station issues no TAF, or its TAF doesn't reach that far",
            NO_FORECAST_COLOR,
            key=NO_FORECAST,
        ),
        style.missing_legend("flight category, visibility or sky condition"),
    ]
    items.append(style.no_report_legend())
    return items


def category_now(metar: Report) -> Optional[str]:
    return metar.flight_category or estimate_category(metar)


def step_color(category):
    return COLORS[category] if category in COLORS else NO_FORECAST_COLOR


def blend(a, b, amount):
    return tuple(int(round(x + (y - x) * amount)) for x, y in zip(a, b))


def frames(colors, seconds):
    """The colors a look steps through: each of `colors` held for `seconds`, fading into the next."""
    held = max(1, round(seconds / FRAME))
    fades = max(0, round(FADE / FRAME) - 1)
    out = []
    for n, color in enumerate(colors):
        following = colors[(n + 1) % len(colors)]
        out += [color] * held
        out += [blend(color, following, (i + 1) / (fades + 1)) for i in range(fades)]
    return out


def look(metar: Optional[Report], settings) -> Look:
    if not metar:
        return style.no_report()
    now = category_now(metar)
    if now is None:  # other data is reported, but nothing to tell the flight category from
        return style.missing()
    ahead = metar.forecast or (None,) * len(HOURS)
    categories = (now,) + tuple(ahead)
    keys = tuple(dict.fromkeys(Category(c).value if c else NO_FORECAST for c in categories))
    colors = [step_color(c) for c in categories]
    if len(set(colors)) == 1:  # the same all day
        return Look.solid(colors[0]).tagged(*keys)
    return Look.cycle(frames(colors, settings.visualizer.forecast_step_seconds), step=FRAME).tagged(*keys)


VISUALIZER = Visualizer(
    id="flight_category_forecast",
    name="Flight Category Forecast",
    description="Steps through each airport's flight category now and as its TAF forecasts it 3, 6 and 12 hours "
    "ahead, all airports together. A dim white is a step with no forecast.",
    short_name="FC Forecast",
    icon="clock",
    legend=legend,
    look=look,
)
