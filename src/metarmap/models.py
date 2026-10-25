"""
Data models shared across the map: METAR data, flight categories and LED looks.
"""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, TypedDict

import metarmap.lib.colors as colors_lib

# A color as stored in config.json and lib/colors.py: (green, red, blue), each 0-255
Color = Tuple[int, int, int]


class FlightCategory(str, Enum):
    """Flight rules reported by aviationweather.gov. Compares equal to the plain strings."""
    VFR = "VFR"
    MVFR = "MVFR"
    IFR = "IFR"
    LIFR = "LIFR"


class SkyCondition(TypedDict):
    cover: str
    cloudBaseFt: int


class Metar(TypedDict, total=False):
    """
    One airport's parsed METAR, as produced by metar.METAR.
    An airport with no report is an empty dict.
    """
    raw: str
    elevation_m: int
    flightCategory: Optional[str]
    windDir: str  # degrees as text, "VRB", or "" when not reported
    windSpeed: int
    windGustSpeed: int
    windGust: bool
    vis: int  # statute miles, rounded
    obs: str  # weather codes, e.g. "-RA BR"
    tempC: Optional[int]
    dewpointC: Optional[int]
    altimHg: float
    lightning: bool
    skyConditions: List[SkyCondition]
    obsTime: Optional[datetime]
    latitude: str
    longitude: str


def _color(color: Sequence[int]) -> Color:
    g, r, b = (int(c) for c in color)
    return g, r, b


@dataclass(frozen=True)
class Look:
    """
    How an LED (or the whole strip) should look, independent of the LED library.

    effect:
      off      - dark
      solid    - colors[0]
      blink    - colors[0] on/off; period = seconds per on+off cycle
      pulse    - colors[0] fading in and out; period = seconds per cycle
      cycle    - steps through colors, step seconds each
      rainbow  - whole strip, period = seconds per full rainbow
      chase    - whole strip, colors[0] moving size LEDs at a time, spacing apart, step seconds per move
    """
    effect: str
    colors: Tuple[Color, ...] = ()
    period: Optional[float] = None
    step: Optional[float] = None
    size: int = 1
    spacing: int = 0

    @classmethod
    def off(cls) -> "Look":
        return cls("off")

    @classmethod
    def solid(cls, color: Sequence[int]) -> "Look":
        return cls("solid", (_color(color),))

    @classmethod
    def blink(cls, color: Sequence[int], period: float = 2.0) -> "Look":
        return cls("blink", (_color(color),), period=period)

    @classmethod
    def pulse(cls, color: Sequence[int], period: float) -> "Look":
        return cls("pulse", (_color(color),), period=period)

    @classmethod
    def cycle(cls, colors: Iterable[Sequence[int]], step: float) -> "Look":
        return cls("cycle", tuple(_color(c) for c in colors), step=step)

    @classmethod
    def rainbow(cls, period: float) -> "Look":
        return cls("rainbow", period=period)

    @classmethod
    def chase(cls, color: Sequence[int], step: float, size: int, spacing: int) -> "Look":
        return cls("chase", (_color(color),), step=step, size=size, spacing=spacing)

    @property
    def color(self) -> Optional[Color]:
        return self.colors[0] if self.colors else None

    def to_dict(self) -> Dict[str, Any]:
        """
        The look for the web UI (/api/live): CSS colors plus only the timing fields the effect uses.
        A solid black LED is reported as off.
        """
        css = [colors_lib.to_css(c) for c in self.colors]
        if self.effect == "off" or (self.effect == "solid" and css == ["#000000"]):
            return {"effect": "off", "colors": []}
        out: Dict[str, Any] = {"effect": self.effect, "colors": css}
        if self.effect in ("blink", "pulse", "rainbow"):
            out["period"] = self.period
        if self.effect in ("cycle", "chase"):
            out["step"] = self.step
        if self.effect == "chase":
            out["size"] = self.size
            out["spacing"] = self.spacing
        return out
