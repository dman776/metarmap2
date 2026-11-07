"""
The config.json schema: every setting with its type and default.

Settings load from an existing config.json unchanged; missing keys get their defaults and unknown keys are kept,
so older or hand-edited files keep working and round-trip on save.
"""

import dataclasses
import json
import logging
import os
import re
import typing
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Rule:
    """
    What a setting accepts, beyond its type: checked when the web UI edits it (Settings.set) and when config.json
    loads (Settings.from_dict, where a value it rejects is logged and replaced by the default).

    choices:  the only values allowed
    between:  (lowest, highest), inclusive
    pattern:  a regular expression the whole value must match
    message:  the error for a pattern mismatch, formatted with key and value (the value as it was sent)
    unit:     after the range in a `between` error, e.g. " NM"
    parse:    parse(value, key) -> the value to store, e.g. a visualizer's id from its number; raises ValueError for
              one it doesn't know
    check:    check(value, settings) -> an error or None, for a rule that depends on other settings; edits only
    editable: False: the web UI can't change it (Config.edit refuses it), and `message` says why
    """

    choices: Optional[Tuple[Any, ...]] = None
    between: Optional[Tuple[float, float]] = None
    pattern: Optional[re.Pattern] = None
    message: str = ""
    unit: str = ""
    parse: Optional[Callable[[Any, str], Any]] = None
    check: Optional[Callable[[Any, Any], Optional[str]]] = None
    editable: bool = True

    def problem(self, key, sent, value, settings=None) -> Optional[str]:
        """Why `value` (converted from `sent`) isn't allowed, or None. Without settings (loading), skips `check`."""
        if self.choices is not None and value not in self.choices:
            return f"{key}: {sent!r} is not one of {', '.join(map(str, self.choices))}"
        if self.between is not None:
            low, high = self.between
            if not low <= value <= high:
                return f"{key}: {sent!r} is not between {low} and {high}{self.unit}"
        if self.pattern is not None and not (isinstance(value, str) and self.pattern.fullmatch(value)):
            return self.message.format(key=key, value=sent)
        if self.check is not None and settings is not None:
            return self.check(value, settings)
        return None


def setting(default=dataclasses.MISSING, *, default_factory=dataclasses.MISSING, **rule):
    """A field with a Rule, e.g. pin: int = setting(18, choices=LED_PINS); default_factory for a list."""
    return field(default=default, default_factory=default_factory, metadata={"rule": Rule(**rule)})


def default_of(f):
    return f.default_factory() if f.default is dataclasses.MISSING else f.default


def visualizer_id(value, key):
    """A visualizer's id from its id or its number in visualizers.ALL (as the API accepts them)."""
    from metarmap import visualizers  # here, not at the top: the visualizers don't need the settings to load

    try:
        return visualizers.ALL[visualizers.index_of(value)].id
    except LookupError:
        raise ValueError(f"{key}: {value!r} is not a visualizer") from None


def visualizer_ids(values, key):
    """Visualizers' ids from their ids, names or numbers, each once."""
    from metarmap import visualizers

    by_name = {v.name: v.id for v in visualizers.ALL}
    ids = []
    for value in values:
        vid = by_name.get(value) or visualizer_id(value, key)
        if vid not in ids:
            ids.append(vid)
    return ids


def known_city(value, key):
    """A city astral's list has (case doesn't matter), for the sun times and the OLED's time zone."""
    from metarmap.sun import get_location  # here, not at the top: the settings load before anything else

    if get_location(value) is None:
        raise ValueError(f"{key}: {value!r} is not a city the sun times know (astral's list)")
    return value


def rule_of(f) -> Optional[Rule]:
    return f.metadata.get("rule")


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


# the GPIO pins the Pi's NeoPixel library can drive a strip from: PWM0 (18, 12), PWM1 (13), PCM (21) and SPI (10)
LED_PINS = (18, 12, 13, 21, 10)
# the order the strip wants its colors in; the wrong one swaps red and green
LED_ORDERS = ("GRB", "RGB")
# the startup sequences (led.init_sequence; leds/intro.py plays them) and the sides Sweep can start from
INIT_SEQUENCES = ("comet", "center_out", "edges_in", "sweep", "radar", "sparkle")
SWEEP_SIDES = ("W", "NW", "N", "NE", "E", "SE", "S", "SW")
QUIET_TIME = re.compile(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
QUIET_TIME_MESSAGE = "{key}: expected local time in 24-hour HH:MM format"


def valid_quiet_time(value):
    return isinstance(value, str) and QUIET_TIME.fullmatch(value) is not None


# geo.map.traffic_seconds: the fewest and most seconds between live traffic fetches. adsb.fi allows one request a
# second; 2 leaves room for a slow answer and a retry
TRAFFIC_SECONDS = (2, 60)


@dataclass
class QuietHours(_Section):
    enabled: bool = False
    start: str = setting("23:00", pattern=QUIET_TIME, message=QUIET_TIME_MESSAGE)  # local time, 24-hour HH:MM
    end: str = setting("05:00", pattern=QUIET_TIME, message=QUIET_TIME_MESSAGE)


@dataclass
class Led(_Section):
    count: int = 50  # LEDs on the strip
    virtual_count: int = 0  # airports after the strip's: on the web map and in Home Assistant only, no LED
    pin: int = setting(18, choices=LED_PINS)
    order: str = setting("GRB", choices=LED_ORDERS)
    brightness: Brightness = field(default_factory=Brightness)
    quiet_hours: QuietHours = field(default_factory=QuietHours)
    inittest: bool = True  # play the startup sequence when the map starts
    init_sequence: str = setting("comet", choices=INIT_SEQUENCES)
    init_sweep_from: str = setting("W", choices=SWEEP_SIDES)  # where Sweep starts: W goes west to east
    dim_on_refresh: bool = True  # the LEDs dim while METARs are fetched, a sign of an update


@dataclass
class MapPage(_Section):
    center: List[float] = field(default_factory=lambda: [30.603, -93.581])
    zoom: float = 7
    background: str = "sectional"  # sectional | satellite | radar
    chart_type: str = "sectional"  # sectional | terminal | ifr_low
    chart: str = ""  # FAA sectional name; empty = the one covering the most airports
    view: str = "airports"  # airports | chart | custom
    # live traffic (adsb.fi), shown when a viewer ticks it on the Map page: how often it's fetched, and whether
    # aircraft on the ground are shown too
    traffic_seconds: float = setting(5, between=TRAFFIC_SECONDS, unit=" seconds (adsb.fi's limit)")
    traffic_ground: bool = False


@dataclass
class Geo(_Section):
    city: str = setting("Houston", parse=known_city)
    map: MapPage = field(default_factory=MapPage)


@dataclass
class DisplayScreen(_Section):
    enabled: bool = True
    delay: float = 5.0
    locate_active: bool = True


@dataclass
class AutoRotate(_Section):
    enabled: bool = False
    delay_seconds: int = 60
    # the ids of the visualizers auto-rotate leaves out (names and numbers are taken too, and saved as ids)
    skip: List[str] = setting(default_factory=list, parse=visualizer_ids)
    # leaves out a visualizer while every LED and virtual airport would be off with it (Precipitation on a dry day)
    skip_dark: bool = False


@dataclass
class VisualizerSettings(_Section):
    # the id of the visualizer at startup (its number is taken too, and saved as the id). Older files saved a number
    # (and a `numbering`): see migrate_visualizers
    active: str = setting("flight_category", parse=visualizer_id)
    auto_rotate: AutoRotate = field(default_factory=AutoRotate)
    # the slow red blink of an airport whose report lacks what the visualizer shows; off: its LED stays dark
    missing_data_blink: bool = True
    # an estimated flight category breathes slowly; off: it shows in a steady color
    estimated_category_breathing: bool = True
    # the legends on Home, Map and Remote list only what the LEDs are showing now (e.g. only VFR and MVFR)
    legend_in_use_only: bool = False


# lightning.color: the colors the lightning flashes can be (style.LIGHTNING_COLORS has each one's LED color)
LIGHTNING_COLORS = ("yellow", "white")


@dataclass
class Lightning(_Section):
    animation: bool = True
    color: str = setting("yellow", choices=LIGHTNING_COLORS)


# tfr.nearby_nm: the most a TFR can be from an airport and still show on its LED (0: inside only)
TFR_NEARBY_NM = (0, 50)


@dataclass
class TfrSettings(_Section):
    # the TFR visualizer shows TFRs this close to an airport too (dim); 0: inside only
    nearby_nm: float = setting(10, between=TFR_NEARBY_NM, unit=" NM")


UPDATE_CHANNELS = ("releases", "latest", "branch")

# a git branch name Update may check out: no leading "-" (git would read it as an option), no "..", no spaces
BRANCH_NAME = re.compile(r"^(?!-)(?!.*\.\.)[A-Za-z0-9._/-]+$")


def branch_needs_dev_mode(channel, settings):
    if channel == "branch" and not settings.dev_mode:
        return "update.channel: branch needs dev_mode in config.json"
    return None


@dataclass
class UpdateSettings(_Section):
    # releases: Update installs the newest release tag; latest: the newest commit, released or not (for testing);
    # branch: the newest commit of `branch` on GitHub, only with dev_mode (otherwise it's taken as releases)
    channel: str = setting("releases", choices=UPDATE_CHANNELS, check=branch_needs_dev_mode)
    branch: str = setting("", pattern=BRANCH_NAME, message="{key}: {value!r} isn't a branch name")


def blank(value, key):
    """ "-" (how a URL says empty, as on the Airports page) and spaces as ""."""
    text = str(value).strip()
    return "" if text == "-" else text


HOST_NAME = re.compile(r"^$|^[A-Za-z0-9]([A-Za-z0-9.-]{0,252}[A-Za-z0-9])?$")
PIPER_VOICE = re.compile(r"^$|^[a-z]{2,3}_[A-Z]{2}-[A-Za-z0-9_]+-(x_low|low|medium|high)$")


KOKORO_VOICE = re.compile(r"^[a-z]{2}_[a-z0-9_]{1,40}$")


def http_url(value, key):
    """A server's address as http(s)://host[:port], "" (or "-") for none; one without a scheme gets http://."""
    text = blank(value, key).rstrip("/")
    if text and "://" not in text:
        text = "http://" + text
    return text


SERVER_URL = re.compile(r"^$|^https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?$")


@dataclass
class SpeechSettings(_Section):
    # /api/speak/<code>.audio reads an airport's METAR aloud, by a speech server on another computer (metarmap.speech)
    engine: str = setting("wyoming", choices=("wyoming", "kokoro"))
    # wyoming: Piper over the Wyoming protocol, e.g. Home Assistant's Piper add-on (its port, 10200, opened in the
    # add-on's Network settings). "": no speech
    wyoming_host: str = setting(
        "", pattern=HOST_NAME, parse=blank, message="{key}: {value!r} isn't a host name or address"
    )
    wyoming_port: int = setting(10200, between=(1, 65535))
    # the Piper voice to ask for, e.g. "en_US-lessac-medium"; "": the server's own
    wyoming_voice: str = setting("", pattern=PIPER_VOICE, parse=blank, message="{key}: {value!r} isn't a Piper voice")
    # kokoro: Kokoro-FastAPI, e.g. "http://192.168.0.164:8880". "": no speech
    kokoro_url: str = setting(
        "", pattern=SERVER_URL, parse=http_url, message="{key}: {value!r} isn't a server address like http://host:8880"
    )
    kokoro_voice: str = setting("af_heart", pattern=KOKORO_VOICE, message="{key}: {value!r} isn't a Kokoro voice")
    kokoro_speed: float = setting(1.0, between=(0.5, 2.0))


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
    visualizer: VisualizerSettings = field(default_factory=VisualizerSettings)
    lightning: Lightning = field(default_factory=Lightning)
    tfr: TfrSettings = field(default_factory=TfrSettings)
    update: UpdateSettings = field(default_factory=UpdateSettings)
    speech: SpeechSettings = field(default_factory=SpeechSettings)
    # for developing the map: Config > Software can update from any branch on GitHub. Edited in config.json by
    # hand only; the web UI can't change it
    dev_mode: bool = setting(False, editable=False, message="dev_mode is only changed by editing config.json")
    # in LED order: airports[0] is the first LED; the led.virtual_count virtual airports come after the strip's
    airports: List[Airport] = field(default_factory=list)

    # ---- loading and saving ------------------------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Settings":
        settings = _from_dict(cls, data)
        # a hand-edited time the scheduler can't take would stop the map at startup, or when quiet hours is turned on
        quiet = settings.led.quiet_hours
        if not all(valid_quiet_time(t) for t in (quiet.start, quiet.end)):
            logging.getLogger(__name__).warning(
                "Invalid quiet hours in config.json (start=%r, end=%r); quiet hours is off and the times are reset",
                quiet.start,
                quiet.end,
            )
            quiet.enabled, quiet.start, quiet.end = False, QuietHours.start, QuietHours.end
        migrate_visualizers(settings, data)
        _check_rules(settings, "")
        settings._extra.pop("color", None)  # the LED colors live in the code now (3.1.2); an older file's are dropped
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

    def rule(self, key: str) -> Optional[Rule]:
        """A setting's Rule, or None if it has none. Raises KeyError for an unknown setting."""
        return rule_of(self._field(key)[1])

    def get(self, key: str) -> Any:
        """One setting by its dotted path, e.g. get("led.pin"). Raises KeyError for an unknown setting."""
        section, f, _ = self._field(key)
        return getattr(section, f.name)

    def set(self, key: str, value: Any) -> Any:
        """
        Sets one setting by its dotted path, e.g. set("geo.map.chart", "Houston").
        Text values (as they arrive from a URL) are converted to the setting's type, then checked against its Rule.
        Raises KeyError for an unknown setting and ValueError for a value that doesn't fit.
        Returns the stored value.
        """
        section, f, kind = self._field(key)
        rule = rule_of(f)
        converted = _convert(value, kind, key)
        if rule is not None and rule.parse is not None:
            converted = rule.parse(converted, key)
        problem = rule.problem(key, value, converted, self) if rule is not None else None
        if problem:
            raise ValueError(problem)
        setattr(section, f.name, converted)
        return converted

    def _field(self, key):
        """The section holding a single setting, its dataclass field and its type. KeyError if there isn't one."""
        *path, name = key.split(".")
        section = self
        for part in path:
            section = getattr(section, part, None)
            if not dataclasses.is_dataclass(section) or part.startswith("_"):
                raise KeyError(key)
        fields = {f.name: f for f in dataclasses.fields(section)}
        if name.startswith("_") or name not in fields:
            raise KeyError(key)
        kind = typing.get_type_hints(type(section))[name]
        if dataclasses.is_dataclass(getattr(section, name)) or _is_section_list(kind):
            raise KeyError(f"{key} is a group of settings, not a single setting")
        return section, fields[name], kind


def _check_rules(section, prefix):
    """
    Loading: a hand-edited value its Rule rejects (or of the wrong type) is logged and replaced by the default, so
    the rest of the map can rely on every loaded setting being valid. Rules that depend on other settings (check)
    and settings the web UI can't edit are left alone.
    """
    hints = typing.get_type_hints(type(section))
    for f in dataclasses.fields(section):
        if f.name.startswith("_"):
            continue
        value, key = getattr(section, f.name), prefix + f.name
        if dataclasses.is_dataclass(value):
            _check_rules(value, key + ".")
            continue
        rule, default = rule_of(f), default_of(f)
        if rule is None or not rule.editable or value == default:
            continue
        try:
            converted = _convert(value, hints[f.name], key)
            if rule.parse is not None:
                converted = rule.parse(converted, key)
            problem = rule.problem(key, value, converted)
        except (TypeError, ValueError) as e:
            problem = str(e)
        if problem:
            logging.getLogger(__name__).warning("Invalid %s in config.json (%s); using %r", key, problem, default)
            setattr(section, f.name, default)
        else:
            setattr(section, f.name, converted)


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


# Older files saved visualizer.active as a number in the list of visualizers, which changed as visualizers were added
# (visualizer.numbering said which list), and visualizer.auto_rotate.skip as names. Both are ids now; these turn the
# old ones into ids once. They describe the past, so they never change: not even when a visualizer is renamed or added.
# numbering 1 -> 2: Wind Direction went in at 3, after Wind Gusts, moving the visualizers from Pressure on by one;
# 2 -> 3: AIRMET went in at 11, after Dewpoint Spread, moving Rainbow and Chase by one; 3 -> 4: TFR at 12, after it
INSERTED_AT = {2: 3, 3: 11, 4: 12}
LAST_NUMBERING = 4
# (id, name) in the order of numbering 4, the last
NUMBERED = (
    ("flight_category", "Flight Category"),
    ("wind", "Wind"),
    ("wind_gusts", "Wind Gusts"),
    ("wind_direction", "Wind Direction"),
    ("pressure", "Pressure"),
    ("precipitation", "Precipitation"),
    ("temperature", "Temperature"),
    ("visibility", "Visibility"),
    ("density_altitude", "Density Altitude"),
    ("ceiling", "Ceiling"),
    ("dewpoint_spread", "Dewpoint Spread"),
    ("advisories", "Advisories"),
    ("tfr", "TFR"),
    ("rainbow", "Rainbow"),
    ("chase", "Chase"),
)


def migrate_visualizers(settings, data):
    """An older file's visualizer.active (a number) and auto_rotate.skip (names) as ids, for the same visualizers."""
    vis = settings.visualizer
    stored = data.get("visualizer") if isinstance(data.get("visualizer"), dict) else {}
    numbering = vis._extra.pop("numbering", 1)  # a file with no numbering is from before Wind Direction
    if isinstance(vis.active, int) and not isinstance(vis.active, bool) and "active" in stored:
        number = vis.active
        for version in range(numbering + 1, LAST_NUMBERING + 1):
            if number >= INSERTED_AT[version]:
                number += 1
        vis.active = NUMBERED[number][0] if 0 <= number < len(NUMBERED) else VisualizerSettings.active
    if isinstance(vis.auto_rotate.skip, list):
        ids = dict((name, vid) for vid, name in NUMBERED)
        vis.auto_rotate.skip = [ids.get(name, name) for name in vis.auto_rotate.skip]


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
