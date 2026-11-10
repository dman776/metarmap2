"""
What the forecast visualizers (Flight Category Forecast, Precipitation Forecast) share: the steps Now, +3h, +6h and
+12h, the dim white of a step with no forecast, and the frames of a look that holds each step, then fades into the
next, all airports together.

A step lasts visualizer.forecast_step_seconds plus FADE; the pages and the Micro count steps by that (Visualizer.steps).
"""

import metarmap.lib.colors as colors_lib
from metarmap.forecast import HOURS
from metarmap.visualizers import style

NO_FORECAST = "no_forecast"  # the legend entry's key
NO_FORECAST_COLOR = style.dim(colors_lib.color(colors_lib.WHITE), 0.25)
FRAME = 0.2  # seconds per frame (the LED library steps a look through its colors at one speed)
FADE = 1.0  # seconds a step takes to fade into the next
STEPS = ("Now",) + tuple(f"+{h}h" for h in HOURS)


def blend(a, b, amount):
    return tuple(int(round(x + (y - x) * amount)) for x, y in zip(a, b))


def hold_frames(settings):
    """How many frames a step is held: forecast_step_seconds."""
    return max(1, round(settings.visualizer.forecast_step_seconds / FRAME))


def step_seconds(settings):
    """How long one step lasts: it is shown for forecast_step_seconds, then fades into the next for FADE."""
    return settings.visualizer.forecast_step_seconds + FADE


def steps(settings, prefix):
    """Visualizer.steps for a forecast visualizer; prefix is what the Micro puts before the step ("FC +3h")."""
    return {"labels": list(STEPS), "seconds": step_seconds(settings), "prefix": prefix}


def sequence(holds):
    """
    The colors a look steps through: each step's frames (`holds`, a list of colors per step), the last color of one
    fading into the first of the next (the last step into the first).
    """
    fades = max(0, round(FADE / FRAME))  # the frames between two steps; a step is its hold + FADE long
    out = []
    for n, hold in enumerate(holds):
        following = holds[(n + 1) % len(holds)][0]
        out += hold
        out += [blend(hold[-1], following, (i + 1) / (fades + 1)) for i in range(fades)]
    return out
