import functools
import json
import re
import threading
from datetime import datetime, timezone

from metarmap.lib.safe_logging import safe_log
from metarmap.metar import MOCK_KEY, parse_raw
from metarmap.settings import BRANCH_NAME, LED_ORDERS, LED_PINS, UPDATE_CHANNELS, Airport, Settings, parse_value

MAX_LEDS = 1000
ICAO = re.compile(r"^[A-Z0-9]{3,4}$")
NO_AIRPORT = "-"  # in a URL, stands for an empty code or name


def locked(method):
    """Runs a change under the config's lock: web requests arrive in parallel, and each change saves config.json."""
    @functools.wraps(method)
    def run(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return run


class Config(object):
    """
    The map's settings, including its airports (one per LED, in LED order, then the virtual ones), saved in
    config.json.

    Older maps kept the airports in a separate airports.json; read() moves them into config.json once and leaves
    airports.json as a backup.
    """
    def __init__(self, file):
        self._file = file
        self._lock = threading.RLock()
        self._data = Settings()
        self.read()

    def read(self):
        with open(self._file) as f:
            raw = json.load(f)
        self._data = Settings.from_dict(raw)
        if "airports" not in raw:
            self._migrate(raw)
        # one entry per LED, then the virtual airports; LEDs without an entry show nothing
        airports, led = self._data.airports, self._data.led
        # airports past both (older files kept airports past the strip) are already on the web map only: virtual
        led.virtual_count = max(led.virtual_count, len(airports) - led.count, 0)
        airports.extend(Airport() for _ in range(led.count + led.virtual_count - len(airports)))

    def _migrate(self, raw):
        path = raw.get("airports_file", "airports.json")
        try:
            with open(path) as f:
                old = json.load(f)
        except (OSError, ValueError) as e:
            safe_log(f"no airports in {self._file} and can't read {path} ({e}); starting with none")
            return
        self._data.airports = airports_from_json(old)
        self._data._extra.pop("airports_file", None)
        self._data.save(self._file)
        safe_log(f"moved {len(self._data.airports)} airports from {path} into {self._file}; "
                 f"{path} is kept as a backup")

    @locked
    def write(self):
        self._data.save(self._file)
        self.read()

    @locked
    def edit(self, key, value):
        """
        Saves one setting by its dotted path, e.g. edit("display_screen.delay", "5").
        Raises KeyError for an unknown setting and ValueError for a value of the wrong type.
        """
        if key == "led.count":
            return self.set_led_count(value)
        if key == "led.virtual_count":
            return self.set_virtual_count(value)
        if key == "dev_mode":
            raise ValueError("dev_mode is only changed by editing config.json")
        if key == "visualizer.numbering":
            raise ValueError("visualizer.numbering is kept by the map")
        if key == "update.channel":
            channel = str(value).strip("\"'")
            if channel not in UPDATE_CHANNELS:
                raise ValueError(f"update.channel: {value!r} is not one of {', '.join(UPDATE_CHANNELS)}")
            if channel == "branch" and not self._data.dev_mode:
                raise ValueError("update.channel: branch needs dev_mode in config.json")
        if key == "update.branch" and not BRANCH_NAME.match(str(value)):
            raise ValueError(f"update.branch: {value!r} isn't a branch name")
        if key == "led.pin" and str(value).strip("\"'") not in {str(pin) for pin in LED_PINS}:
            raise ValueError(f"led.pin: {value!r} is not one of {', '.join(map(str, LED_PINS))}")
        if key == "led.order" and str(value).strip("\"'") not in LED_ORDERS:
            raise ValueError(f"led.order: {value!r} is not one of {', '.join(LED_ORDERS)}")
        self._data.set(key, value)
        self.write()

    @locked
    def set_login(self, user, password=None):
        """
        Sets the web UI's user name and (unless None or empty) password, saved together.
        The user name is stored in lower case, which is how logins are compared.
        """
        self._data.web_server.user = parse_user(user)
        if password:
            self._data.web_server.password = password
        self.write()

    @property
    def data(self):
        return self._data

    @property
    def airports(self):
        """
        The airports, one per LED in LED order, then the virtual ones (Airport; code is "" for an LED with no
        airport).
        """
        return self._data.airports

    def is_virtual(self, pixel):
        """Whether airport `pixel` is a virtual one: after the strip's LEDs, so on the web map only."""
        return pixel >= self._data.led.count

    # ---- airports --------------------------------------------------------------------------------------------

    @locked
    def set_led_count(self, count):
        """
        Sets the number of LEDs (led.count): new LEDs at the end of the strip have no airport; lowering it removes
        the airports on the last LEDs. The virtual airports after them are kept.
        """
        count = parse_value(count, int, "led.count")
        if not 1 <= count <= MAX_LEDS - self._data.led.virtual_count:
            raise ValueError(f"led.count: {count} is not between 1 and {MAX_LEDS - self._data.led.virtual_count} "
                             f"({MAX_LEDS} airports in all, with the virtual ones)")
        old, airports = self._data.led.count, self._data.airports
        if count < old:
            del airports[count:old]
        else:
            airports[old:old] = [Airport() for _ in range(count - old)]
        self._data.led.count = count
        self.write()

    @locked
    def set_virtual_count(self, count):
        """
        Sets the number of virtual airports (led.virtual_count), after the strip's: new ones have no airport;
        lowering it removes the last ones. The strip and its virtual airports have MAX_LEDS airports at most
        (each is part of every METAR fetch).
        """
        count = parse_value(count, int, "led.virtual_count")
        if not 0 <= count <= MAX_LEDS - self._data.led.count:
            raise ValueError(f"led.virtual_count: {count} is not between 0 and {MAX_LEDS - self._data.led.count} "
                             f"({MAX_LEDS} airports in all, with the LEDs)")
        self._data.led.virtual_count = count
        del self._data.airports[self._data.led.count + count:]
        self.write()  # read() adds the new ones

    @locked
    def set_airport(self, pixel, key, value):
        """
        Sets the code, name or display flag of the airport on LED `pixel` (counting from 0).
        "-" or "" clears the code or name. Raises IndexError for no such LED, and ValueError for another key or
        a code that isn't 3-4 letters and digits.
        """
        airport = self.airports[self._pixel(pixel)]
        if key == "code":
            code = parse_code(value)
            if code != airport.code:
                airport.name = ""  # the old name was the old airport's; fill_names() gives the new one
                airport._extra.pop(MOCK_KEY, None)  # and so was its mock METAR
            airport.code = code
        elif key == "name":
            airport.name = "" if value == NO_AIRPORT else str(value)
        elif key == "display":
            airport.display = parse_value(value, bool, "display")
        else:
            raise ValueError(f"unknown airport setting: {key}")
        self.write()

    @locked
    def set_mock_metar(self, pixel, text):
        """
        Saves a mock METAR for the airport on LED `pixel` (dev_mode; the Airports page), or with "" removes it.
        Raises IndexError for no such LED, and ValueError without dev_mode, without an airport, or for text that
        isn't a METAR.
        """
        if not self._data.dev_mode:
            raise ValueError("mock METARs need dev_mode in config.json")
        airport = self.airports[self._pixel(pixel)]
        text = " ".join(str(text or "").split())
        if text and not airport.code:
            raise ValueError("this LED has no airport")
        if text:
            parse_raw(text, datetime.now(timezone.utc))  # raises ValueError if it isn't a METAR
            airport._extra[MOCK_KEY] = text
        else:
            airport._extra.pop(MOCK_KEY, None)
        self.write()

    @locked
    def fill_names(self, names):
        """
        Gives airports with an empty name their name from `names` ({code: name}), saved in one write.
        Names people typed are never changed. Returns how many were filled.
        """
        filled = 0
        for airport in self.airports:
            if airport.code and not airport.name and names.get(airport.code):
                airport.name = names[airport.code]
                filled += 1
        if filled:
            self.write()
        return filled

    @locked
    def move_airport(self, src, dst):
        """Moves the airport on LED `src` to LED `dst`; the ones in between shift by one."""
        airports = self.airports
        airports.insert(self._pixel(dst), airports.pop(self._pixel(src)))
        self.write()

    def _pixel(self, pixel):
        pixel = int(pixel)
        if not 0 <= pixel < len(self.airports):
            raise IndexError(f"no LED {pixel}")
        return pixel

    # the older, by-code edits (GET /config/airports/edit/...), for the first airport with that code

    @locked
    def edit_airport(self, oldkey, newkey):
        self.set_airport(self._find(oldkey), "code", newkey)

    @locked
    def edit_airport_property(self, airport, key, value):
        pixel = self._find(airport)
        if key in ("text", "name"):
            self.set_airport(pixel, "name", value)
        elif key == "display":
            self.set_airport(pixel, "display", value)
        elif key == MOCK_KEY:
            raise ValueError(f"{MOCK_KEY} is set on the Airports page (dev_mode) or in config.json")
        else:
            # anything else is kept with the airport, as airports.json did
            self.airports[pixel]._extra[key] = value == "true" if value in ("true", "false") else value
            self.write()

    def _find(self, code):
        for pixel, airport in enumerate(self.airports):
            if airport.code == code:
                return pixel
        raise KeyError(code)


def parse_user(value):
    """A web UI user name: lower case (logins are compared that way). Raises ValueError for one that can't log in."""
    user = str(value).strip().lower()
    if not user or ":" in user or any(ord(ch) < 33 for ch in user):
        raise ValueError("the user name can't be empty or contain spaces, colons or control characters")
    return user


def parse_code(value):
    """An ICAO code from the web UI: upper case, "" for "-" or blank. Raises ValueError for anything else."""
    code = str(value).strip().upper()
    if code in ("", NO_AIRPORT):
        return ""
    if not ICAO.match(code):
        raise ValueError(f"{value!r} is not an airport code (3 or 4 letters and digits)")
    return code


def airports_from_json(old):
    """
    The airport list from an older airports.json ({code: {"text": name, "display": bool}}, in LED order).
    NULL... codes were placeholders for LEDs with no airport; a "text" that isn't a string (older files have 0)
    becomes no name. Other keys are kept.
    """
    airports = []
    for code, props in (old.items() if isinstance(old, dict) else []):
        props = props if isinstance(props, dict) else {}
        text = props.get("text")
        airport = Airport(code="" if "NULL" in code.upper() else code, name=text if isinstance(text, str) else "",
                          display=bool(props.get("display", False)))
        airport._extra = {k: v for k, v in props.items() if k not in ("text", "display")}
        airports.append(airport)
    return airports
