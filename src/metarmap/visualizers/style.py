"""
How the LEDs show things, shared by every visualizer so the same meaning always looks the same:

  no report from the airport          off
  report without the value needed     slow red blink
  light (-)                           breathing: a slow pulse that never goes dark, so the color stays readable
  moderate                            solid
  heavy (+)                           fast blink between full and dim, so the LED never looks dead
  in the vicinity (VC)                solid, dim

Ranges (wind, temperature, ...) are a few solid bands of clearly different colors, not blends: a Band table is the
one place each visualizer's thresholds live, and its legend is built from the same table.
"""
from dataclasses import dataclass
from typing import Callable, Optional, Sequence, Union

import metarmap.lib.colors as colors_lib
from metarmap.models import Look
from metarmap.visualizers.visualizer import legend_item

LIGHT, MODERATE, HEAVY, VICINITY = "-", "", "+", "VC"

LIGHT_PERIOD = 4.0  # seconds per breath
LIGHT_LOW = 0.3  # a breath's dimmest point
HEAVY_PERIOD = 1.0  # seconds per blink
DIM = 0.3  # brightness of "in the vicinity", and of a heavy blink's dim half
MISSING_PERIOD = 2.0


def named(name):
    return colors_lib.get_colors()[name]


def dim(color: Sequence[int], factor: float = DIM):
    return tuple(int(round(c * factor)) for c in color)


def no_report() -> Look:
    return Look.off()


def missing() -> Look:
    """The airport reported, but not the value this visualizer shows."""
    return Look.blink(named(colors_lib.RED), period=MISSING_PERIOD)


def by_intensity(color, intensity=MODERATE) -> Look:
    if intensity == LIGHT:
        return Look.pulse(color, period=LIGHT_PERIOD, low=LIGHT_LOW)
    if intensity == HEAVY:
        return Look.blink(color, period=HEAVY_PERIOD, background=dim(color))
    if intensity == VICINITY:
        return Look.solid(dim(color))
    return Look.solid(color)


# ---- legend entries for the conventions ---------------------------------------------------------------------

def no_report_legend(label="METAR not available"):
    return legend_item(label, "Off")


def missing_legend(what):
    return legend_item(f"No {what} in the report", "Slow red blink", named(colors_lib.RED), effect="blink",
                       period=MISSING_PERIOD)


def intensity_legend(color, example):
    """How light, moderate, heavy and nearby look, shown with one color (e.g. rain's)."""
    return [
        legend_item(f"Light ({example})", "Breathing", color, effect="pulse", period=LIGHT_PERIOD, low=LIGHT_LOW),
        legend_item(f"Moderate ({example})", "Solid", color),
        legend_item(f"Heavy ({example})", "Fast blink, bright and dim", color, dim(color), effect="alternate",
                    period=HEAVY_PERIOD),
        legend_item(f"In the vicinity ({example})", "Dim", dim(color)),
    ]


# ---- bands --------------------------------------------------------------------------------------------------

ColorSpec = Union[str, Callable[[object], Sequence[int]]]  # a colors_lib name, or settings -> color


@dataclass(frozen=True)
class Band:
    """Values below `below` (or up to it, if `inclusive`), down to the band before; None: no upper limit."""
    below: Optional[float]
    color: ColorSpec
    label: str  # e.g. "10-14 kt"
    detail: str  # e.g. "Yellow"
    inclusive: bool = False

    def holds(self, value) -> bool:
        if self.below is None:
            return True
        return value <= self.below if self.inclusive else value < self.below

    def color_for(self, settings):
        return self.color(settings) if callable(self.color) else named(self.color)


def band_for(value, bands, settings):
    """The color of the band `value` falls in."""
    return next(band for band in bands if band.holds(value)).color_for(settings)


def band_legend(bands, settings):
    return [legend_item(band.label, band.detail, band.color_for(settings)) for band in bands]
