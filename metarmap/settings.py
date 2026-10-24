"""
The config.json schema: every setting with its type and default.

Settings load from an existing config.json unchanged; missing keys get their defaults and unknown keys are kept,
so older or hand-edited files keep working and round-trip on save.
"""
import dataclasses
import json
import typing
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class _Section:
    # keys found in config.json that this schema doesn't know; written back on save
    _extra: Dict[str, Any] = field(default_factory=dict, repr=False, compare=False)


@dataclass
class WebServer(_Section):
    user: str = "metar"
    password: str = "map"
    port: int = 80


@dataclass
class Brightness(_Section):
    normal: float = 0.5
    dimmed: float = 0.1
    off: float = 0.01


@dataclass
class Led(_Section):
    count: int = 50
    pin: int = 18
    order: str = "GRB"
    brightness: Brightness = field(default_factory=Brightness)
    inittest: bool = True


@dataclass
class MapPage(_Section):
    center: List[float] = field(default_factory=lambda: [30.603, -93.581])
    zoom: float = 7
    background: str = "sectional"  # sectional | satellite | radar
    chart_type: str = "sectional"  # sectional | terminal | ifr_low
    chart: str = ""  # FAA sectional name; empty = the one covering the most airports
    view: str = "airports"  # airports | chart | custom


@dataclass
class Geo(_Section):
    city: str = "Houston"
    map: MapPage = field(default_factory=MapPage)


@dataclass
class DisplayScreen(_Section):
    enabled: bool = True
    delay: float = 5.0
    locate_active: bool = True


@dataclass
class CategoryColors(_Section):
    vfr: List[int] = field(default_factory=lambda: [255, 0, 0])
    mvfr: List[int] = field(default_factory=lambda: [0, 0, 255])
    ifr: List[int] = field(default_factory=lambda: [0, 255, 0])
    lifr: List[int] = field(default_factory=lambda: [0, 125, 125])


@dataclass
class WeatherColors(_Section):
    lightning: List[int] = field(default_factory=lambda: [255, 255, 0])
    fog: List[int] = field(default_factory=lambda: [15, 15, 15])
    haze: List[int] = field(default_factory=lambda: [5, 5, 5])
    smoke: List[int] = field(default_factory=lambda: [75, 75, 75])
    rain: List[int] = field(default_factory=lambda: [0, 0, 255])
    mist: List[int] = field(default_factory=lambda: [0, 0, 15])
    drizzle: List[int] = field(default_factory=lambda: [255, 0, 0])


@dataclass
class Colors(_Section):
    """LED colors, in the strip's GRB order."""
    cat: CategoryColors = field(default_factory=CategoryColors)
    clear: List[int] = field(default_factory=lambda: [0, 0, 0])
    weather: WeatherColors = field(default_factory=WeatherColors)


@dataclass
class AutoRotate(_Section):
    enabled: bool = False
    delay_seconds: int = 60


@dataclass
class VisualizerSettings(_Section):
    active: int = 0
    auto_rotate: AutoRotate = field(default_factory=AutoRotate)


@dataclass
class Lightning(_Section):
    animation: bool = True


@dataclass
class Settings(_Section):
    web_server: WebServer = field(default_factory=WebServer)
    airports_file: str = "airports.json"
    led: Led = field(default_factory=Led)
    geo: Geo = field(default_factory=Geo)
    display_screen: DisplayScreen = field(default_factory=DisplayScreen)
    color: Colors = field(default_factory=Colors)
    visualizer: VisualizerSettings = field(default_factory=VisualizerSettings)
    lightning: Lightning = field(default_factory=Lightning)

    # ---- loading and saving ------------------------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Settings":
        return _from_dict(cls, data)

    @classmethod
    def load(cls, path) -> "Settings":
        with open(path) as f:
            return cls.from_dict(json.load(f))

    def to_dict(self) -> Dict[str, Any]:
        return _to_dict(self)

    def save(self, path) -> None:
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=4)

    # ---- editing -------------------------------------------------------------------------------------------------

    def set(self, key: str, value: Any) -> Any:
        """
        Sets one setting by its dotted path, e.g. set("geo.map.chart", "Houston").
        Text values (as they arrive from a URL) are converted to the setting's type.
        Raises KeyError for an unknown setting and ValueError for a value that doesn't fit.
        Returns the stored value.
        """
        *path, name = key.split(".")
        section = self
        for part in path:
            section = getattr(section, part, None)
            if not dataclasses.is_dataclass(section) or part.startswith("_"):
                raise KeyError(key)
        hints = typing.get_type_hints(type(section))
        if name.startswith("_") or name not in {f.name for f in dataclasses.fields(section)}:
            raise KeyError(key)
        if dataclasses.is_dataclass(getattr(section, name)):
            raise KeyError(f"{key} is a group of settings, not a single setting")
        converted = _convert(value, hints[name], key)
        setattr(section, name, converted)
        return converted


def _from_dict(cls, data):
    if not isinstance(data, dict):
        data = {}
    hints = typing.get_type_hints(cls)
    kwargs, known = {}, set()
    for f in dataclasses.fields(cls):
        if f.name.startswith("_"):
            continue
        known.add(f.name)
        if dataclasses.is_dataclass(hints[f.name]):
            kwargs[f.name] = _from_dict(hints[f.name], data.get(f.name, {}))
        elif f.name in data:
            kwargs[f.name] = data[f.name]
    obj = cls(**kwargs)
    obj._extra = {k: v for k, v in data.items() if k not in known}
    return obj


def _to_dict(obj):
    out = {}
    for f in dataclasses.fields(obj):
        if f.name.startswith("_"):
            continue
        value = getattr(obj, f.name)
        out[f.name] = _to_dict(value) if dataclasses.is_dataclass(value) else value
    out.update(obj._extra)
    return out


def _convert(value, kind, key):
    try:
        if kind is bool:
            if isinstance(value, bool):
                return value
            text = str(value).strip().lower()
            if text in ("true", "1", "yes", "on"):
                return True
            if text in ("false", "0", "no", "off"):
                return False
            raise ValueError(value)
        if kind is int:
            number = float(value)
            if not number.is_integer():
                raise ValueError(value)
            return int(number)
        if kind is float:
            number = float(value)
            # keep whole numbers as ints so config.json stays as people wrote it (zoom 7, not 7.0)
            return int(number) if number.is_integer() and "." not in str(value) else number
        if kind is str:
            text = str(value)
            # quoted strings were the old way to send text (e.g. %22Dallas%22)
            if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
                text = text[1:-1]
            return text
        if typing.get_origin(kind) is list:
            items = json.loads(value) if isinstance(value, str) else value
            if not isinstance(items, list):
                raise ValueError(value)
            (item_kind,) = typing.get_args(kind)
            return [_convert(item, item_kind, key) for item in items]
    except (TypeError, ValueError, json.JSONDecodeError):
        raise ValueError(f"{key}: {value!r} is not a valid {getattr(kind, '__name__', kind)}") from None
    raise TypeError(f"{key}: unsupported setting type {kind}")
