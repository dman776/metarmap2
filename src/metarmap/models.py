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


@dataclass(frozen=True)
class SkyLayer:
    """One layer of the sky: its cover (FEW, SCT, BKN, OVC; CLR, SKC, CAVOK...; OVX for an obscured sky) and base."""

    cover: str
    base_ft: int = 0  # 0 when the cover has no base (CLR, OVX)

    def to_api(self) -> Dict[str, Any]:
        return {"cover": self.cover, "cloudBaseFt": self.base_ft}

    # TEMPORARY, while readers move from dicts to attributes: the old dict keys
    def get(self, key, default=None):
        return {"cover": self.cover, "cloudBaseFt": self.base_ft}.get(key, default)

    def __getitem__(self, key):
        return {"cover": self.cover, "cloudBaseFt": self.base_ft}[key]


@dataclass(frozen=True)
class Report:
    """
    One airport's parsed METAR (metar.parse_report, or metar.parse_raw for a mock). An airport with no report has
    None instead. Values a report leaves out are None, except the ones read as 0 or "" (wind, altimeter, weather),
    as aviationweather.gov's own fields are.
    """

    raw: str = ""
    name: str = ""  # the station's, e.g. "Houston/Hobby Arpt, TX, US"
    elevation_m: int = 0
    flight_category: Optional[str] = None  # FlightCategory's values; None when the station doesn't report one
    wind_dir: str = ""  # degrees as text ("80"), "VRB", or "" when not reported
    wind_speed: int = 0  # knots
    wind_gust_speed: int = 0  # knots, 0 for no gusts
    visibility_sm: Optional[float] = None  # statute miles, exact (0.25)
    visibility_more: bool = False  # "10+": more than visibility_sm
    vert_vis_ft: Optional[int] = None  # vertical visibility into an obscured sky
    weather: str = ""  # weather codes, e.g. "-RA BR"
    temp_c: Optional[int] = None
    dewpoint_c: Optional[int] = None
    altimeter_inhg: float = 0.0  # 0 when not reported
    lightning: bool = False  # LTG in the report
    sky_conditions: Tuple[SkyLayer, ...] = ()
    obs_time: Optional[datetime] = None  # UTC
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    # added by the map, not the report:
    mock: bool = False  # a mock METAR (dev_mode) in place of the fetched one
    airmets: Optional[List[dict]] = None  # G-AIRMET hazards over the airport (metar.with_advisories)
    sigmets: Optional[List[dict]] = None
    tfrs: Optional[List[dict]] = None  # TFRs at or near it (metar.with_tfrs)

    @property
    def wind_gust(self) -> bool:
        return self.wind_gust_speed > 0

    @property
    def vis(self) -> int:
        """The visibility in whole statute miles (0 when not reported), as the OLED and the API show it."""
        return int(round(self.visibility_sm or 0))

    def to_api(self) -> Dict[str, Any]:
        """
        The report with the field names the API (API.md) and Home Assistant use, ready for JSON (obsTime as ISO
        8601). The map's additions (mock, advisories, TFRs) aren't part of it.
        """
        return {
            "raw": self.raw,
            "name": self.name,
            "elevation_m": self.elevation_m,
            "flightCategory": self.flight_category,
            "windDir": self.wind_dir,
            "windSpeed": self.wind_speed,
            "windGustSpeed": self.wind_gust_speed,
            "windGust": self.wind_gust,
            "vis": self.vis,
            "visibilitySM": self.visibility_sm,
            "visibilityMore": self.visibility_more,
            "vertVisFt": self.vert_vis_ft,
            "obs": self.weather,
            "tempC": self.temp_c,
            "dewpointC": self.dewpoint_c,
            "altimHg": self.altimeter_inhg,
            "lightning": self.lightning,
            "skyConditions": [layer.to_api() for layer in self.sky_conditions],
            "obsTime": self.obs_time.isoformat() if self.obs_time else None,
            "latitude": self.latitude,
            "longitude": self.longitude,
        }

    # TEMPORARY, while readers move from dicts to attributes: the old dict keys
    _KEYS = {
        "raw": "raw",
        "name": "name",
        "elevation_m": "elevation_m",
        "flightCategory": "flight_category",
        "windDir": "wind_dir",
        "windSpeed": "wind_speed",
        "windGustSpeed": "wind_gust_speed",
        "windGust": "wind_gust",
        "vis": "vis",
        "visibilitySM": "visibility_sm",
        "visibilityMore": "visibility_more",
        "vertVisFt": "vert_vis_ft",
        "obs": "weather",
        "tempC": "temp_c",
        "dewpointC": "dewpoint_c",
        "altimHg": "altimeter_inhg",
        "lightning": "lightning",
        "skyConditions": "sky_conditions",
        "obsTime": "obs_time",
        "latitude": "latitude",
        "longitude": "longitude",
        "mock": "mock",
        "airmets": "airmets",
        "sigmets": "sigmets",
        "tfrs": "tfrs",
    }

    def get(self, key, default=None):
        return getattr(self, self._KEYS[key]) if key in self._KEYS else default

    def __getitem__(self, key):
        return getattr(self, self._KEYS[key])


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
      blink    - colors[0] on/off, or alternating with colors[1] if given; period = seconds per on+off cycle
      pulse    - colors[0] fading in and out; period = seconds per cycle; low = the dimmest point (0: dark)
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
    low: float = 0.0

    @classmethod
    def off(cls) -> "Look":
        return cls("off")

    @classmethod
    def solid(cls, color: Sequence[int]) -> "Look":
        return cls("solid", (_color(color),))

    @classmethod
    def blink(cls, color: Sequence[int], period: float = 2.0, background: Optional[Sequence[int]] = None) -> "Look":
        """On and off, or with `background`, alternating between the two colors."""
        colors = (_color(color),) if background is None else (_color(color), _color(background))
        return cls("blink", colors, period=period)

    @classmethod
    def pulse(cls, color: Sequence[int], period: float, low: float = 0.0) -> "Look":
        """Fading between full brightness and `low` (0: dark; 0.3: never dark, so the color stays readable)."""
        return cls("pulse", (_color(color),), period=period, low=low)

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
        if self.effect == "pulse" and self.low:
            out["low"] = self.low
        if self.effect in ("cycle", "chase"):
            out["step"] = self.step
        if self.effect == "chase":
            out["size"] = self.size
            out["spacing"] = self.spacing
        return out
