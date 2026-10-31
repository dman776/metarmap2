"""
How the LEDs show things, shared by every visualizer so the same meaning always looks the same:

  no report from the airport          off
  report without the value needed     slow red blink
  light (-)                           breathing: a slow pulse that never goes dark, so the color stays readable
  moderate                            solid
  heavy (+)                           fast blink between full and dim, so the LED never looks dead
  in the vicinity (VC)                solid, dim
  lightning or a thunderstorm         two quick flashes every 2 s over the airport's look, in every weather
                                      visualizer (with lightning.animation on; with_lightning())

Ranges (wind, temperature, ...) are a few solid bands of clearly different colors, not blends: a Band table is the
one place each visualizer's thresholds live, and its legend is built from the same table.
"""
import math
from dataclasses import dataclass
from typing import Callable, Optional, Sequence, Union

import metarmap.lib.colors as colors_lib
from metarmap.decode import parse_weather
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


# ---- lightning ----------------------------------------------------------------------------------------------
#
# A double flicker, like real lightning: flash, the airport's look, flash, then its look until the next one.

LIGHTNING_STEP = 0.05  # seconds per frame
LIGHTNING_EVERY = 2.0  # seconds from one flicker to the next
FLICKER = (True, True, True, False, False, True, True, True)  # 0.15 s flash, 0.1 s back, 0.15 s flash
# frames repeat after this long: a whole number of every look's period (breathing is 4 s), so they loop seamlessly
LIGHTNING_CYCLE = 4.0


def has_lightning(metar) -> bool:
    """LTG in the report (LTG DSNT W...), or a thunderstorm: TS, TSRA, VCTS..."""
    if not metar:
        return False
    return bool(metar.get("lightning")) or any(g.descriptor == "TS" for g in parse_weather(metar.get("obs")))


def color_at(look: Look, t: float):
    """The color an LED with `look` shows t seconds in (as the renderer and the web map draw it)."""
    black = (0, 0, 0)
    if look.effect == "blink":
        first = math.floor(t / (look.period / 2)) % 2 == 0
        return look.colors[0] if first else (look.colors[1] if len(look.colors) > 1 else black)
    if look.effect == "pulse":
        level = look.low + (1 - look.low) * (0.5 - 0.5 * math.cos(2 * math.pi * t / look.period))
        return dim(look.colors[0], level)
    if look.effect == "cycle":
        return look.colors[int(round(t / look.step)) % len(look.colors)]
    return look.colors[0] if look.effect != "off" and look.colors else black


def with_lightning(look: Look, settings) -> Look:
    """
    `look` with lightning flickering over it. Between flickers the LED does what `look` does; where that's the
    lightning color itself (a thunderstorm with nothing else to show), it's dimmed so the flashes stand out.
    """
    flash = tuple(settings.color.weather.lightning)
    every = round(LIGHTNING_EVERY / LIGHTNING_STEP)
    frames = []
    for n in range(round(LIGHTNING_CYCLE / LIGHTNING_STEP)):
        i = n % every
        if i < len(FLICKER) and FLICKER[i]:
            frames.append(flash)
        else:
            color = tuple(color_at(look, n * LIGHTNING_STEP))
            frames.append(dim(color) if color == flash else color)
    return Look.cycle(frames, step=LIGHTNING_STEP)


def lightning_legend(settings):
    return legend_item("Lightning or a thunderstorm", "Two quick yellow flashes every 2 s over the airport's color",
                       dim(named(colors_lib.WHITE)), settings.color.weather.lightning, effect="flash",
                       period=LIGHTNING_EVERY)


# ---- legend entries for the conventions ---------------------------------------------------------------------

def no_report_legend(label="METAR not available"):
    return legend_item(label, "Off")


def missing_legend(what):
    return legend_item(f"No {what} in the report", "Slow red blink", named(colors_lib.RED), effect="blink",
                       period=MISSING_PERIOD)


def intensity_legend(color, example):
    """How light, heavy and nearby look, shown with one color (e.g. rain's). Moderate is solid, which is how each
    kind's own entry already shows it, so it has no entry here."""
    return [
        legend_item(f"Light ({example})", "Breathing", color, effect="pulse", period=LIGHT_PERIOD, low=LIGHT_LOW),
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
