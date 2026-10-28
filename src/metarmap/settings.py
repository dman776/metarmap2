"""
The config.json schema: every setting with its type and default.

Settings load from an existing config.json unchanged; missing keys get their defaults and unknown keys are kept,
so older or hand-edited files keep working and round-trip on save.
"""
import dataclasses
import json
import os
import re
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
    count: int = 50  # LEDs on the strip
    virtual_count: int = 0  # airports after the strip's: on the web map and in Home Assistant only, no LED
    pin: int = 18
    order: str = "GRB"
    brightness: Brightness = field(default_factory=Brightness)
    inittest: bool = True
    dim_on_refresh: bool = True  # the LEDs dim while METARs are fetched, a sign of an update


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
    drizzle: List[int] = field(default_factory=lambda: [255, 0, 0])  # no longer used: drizzle is a dimmer rain
    snow: List[int] = field(default_factory=lambda: [255, 255, 255])  # white
    ice: List[int] = field(default_factory=lambda: [255, 0, 255])  # cyan: freezing rain and drizzle, ice pellets, hail
    hazard: List[int] = field(default_factory=lambda: [0, 255, 255])  # magenta: squalls, funnel clouds, ash, storms
    unknown: List[int] = field(default_factory=lambda: [126, 255, 0])  # orange: unknown precipitation (UP)


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
    skip: List[str] = field(default_factory=list)  # names of visualizers auto-rotate leaves out


@dataclass
class VisualizerSettings(_Section):
    active: int = 0  # a number in visualizers.ALL
    # which list `active` counts in; a file without it is from before Wind Direction (see renumber_visualizers)
    numbering: int = 2
    auto_rotate: AutoRotate = field(default_factory=AutoRotate)


@dataclass
class Lightning(_Section):
    animation: bool = True


UPDATE_CHANNELS = ("releases", "latest", "branch")

# a git branch name Update may check out: no leading "-" (git would read it as an option), no "..", no spaces
BRANCH_NAME = re.compile(r"^(?!-)(?!.*\.\.)[A-Za-z0-9._/-]+$")


@dataclass
class UpdateSettings(_Section):
    # releases: Update installs the newest release tag; latest: the newest commit, released or not (for testing);
    # branch: the newest commit of `branch` on GitHub, only with dev_mode (otherwise it's taken as releases)
    channel: str = "releases"
    branch: str = ""


@dataclass
class Airport(_Section):
    """One LED of the strip (or a virtual airport, after them) and the airport it shows."""
    code: str = ""  # ICAO code; empty for an LED with no airport
    name: str = ""  # shown next to the code in the web UI
    display: bool = False  # show this airport on the OLED screen


@dataclass
class Settings(_Section):
    web_server: WebServer = field(default_factory=WebServer)
    led: Led = field(default_factory=Led)
    geo: Geo = field(default_factory=Geo)
    display_screen: DisplayScreen = field(default_factory=DisplayScreen)
    color: Colors = field(default_factory=Colors)
    visualizer: VisualizerSettings = field(default_factory=VisualizerSettings)
    lightning: Lightning = field(default_factory=Lightning)
    update: UpdateSettings = field(default_factory=UpdateSettings)
    # for developing the map: Config > Software can update from any branch on GitHub. Edited in config.json by
    # hand only; the web UI can't change it
    dev_mode: bool = False
    # in LED order: airports[0] is the first LED; the led.virtual_count virtual airports come after the strip's
    airports: List[Airport] = field(default_factory=list)

    # ---- loading and saving ------------------------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Settings":
        settings = _from_dict(cls, data)
        renumber_visualizers(settings, data)
        return settings

    @classmethod
    def load(cls, path) -> "Settings":
        with open(path) as f:
            return cls.from_dict(json.load(f))

    def to_dict(self) -> Dict[str, Any]:
        return _to_dict(self)

    def save(self, path) -> None:
        """
        Writes config.json: to a temporary file first, then swapped in, so a power cut or a second save at the same
        time can't leave half a file. The file keeps its owner and permissions (the map runs as root).
        """
        tmp = f"{path}.tmp"
        with open(tmp, "w") as f:
            json.dump(self.to_dict(), f, indent=4)
        try:
            st = os.stat(path)
            os.chmod(tmp, st.st_mode & 0o7777)
            if hasattr(os, "chown") and (st.st_uid, st.st_gid) != (os.stat(tmp).st_uid, os.stat(tmp).st_gid):
                os.chown(tmp, st.st_uid, st.st_gid)
        except FileNotFoundError:
            pass  # a new file
        except PermissionError:
            pass  # not root: the file is ours anyway
        os.replace(tmp, path)

    # ---- editing -------------------------------------------------------------------------------------------------

    def update_channel(self) -> str:
        """The update channel in use: update.channel, except that branch is releases without dev_mode."""
        channel = self.update.channel
        return "releases" if channel == "branch" and not self.dev_mode else channel

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
        if dataclasses.is_dataclass(getattr(section, name)) or _is_section_list(hints[name]):
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
        elif _is_section_list(hints[f.name]):
            items = data.get(f.name)
            (item_cls,) = typing.get_args(hints[f.name])
            kwargs[f.name] = [_from_dict(item_cls, item) for item in (items if isinstance(items, list) else [])]
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
        if dataclasses.is_dataclass(value):
            value = _to_dict(value)
        elif isinstance(value, list) and value and dataclasses.is_dataclass(value[0]):
            value = [_to_dict(item) for item in value]
        out[f.name] = value
    out.update(obj._extra)
    return out


# numbering 1 -> 2: Wind Direction went in at 3, after Wind Gusts, moving the visualizers from Pressure on by one
INSERTED_AT = {2: 3}


def renumber_visualizers(settings, data):
    """Keeps an older file's visualizer.active on the same visualizer after one was added before it."""
    vis = data.get("visualizer") if isinstance(data.get("visualizer"), dict) else {}
    numbering = vis.get("numbering", 1 if "active" in vis else VisualizerSettings.numbering)
    for version in range(numbering + 1, VisualizerSettings.numbering + 1):
        if settings.visualizer.active >= INSERTED_AT[version]:
            settings.visualizer.active += 1
    settings.visualizer.numbering = VisualizerSettings.numbering


def _is_section_list(kind):
    """A list of settings groups, such as airports."""
    return typing.get_origin(kind) is list and dataclasses.is_dataclass(typing.get_args(kind)[0])


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


def parse_value(value, kind, key="value"):
    """Converts text (as it arrives from a URL) to `kind`, like set() does. Raises ValueError if it doesn't fit."""
    return _convert(value, kind, key)
