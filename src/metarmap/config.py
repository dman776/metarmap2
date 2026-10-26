import functools
import json
import re
import threading

from metarmap.lib.safe_logging import safe_log
from metarmap.settings import Airport, Settings, parse_value

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
    The map's settings, including its airports (one per LED, in LED order), saved in config.json.

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
        # one entry per LED; LEDs without an entry show nothing
        airports = self._data.airports
        airports.extend(Airport() for _ in range(self._data.led.count - len(airports)))

    def _migrate(self, raw):
        path = raw.get("airports_file", "airports.json")
        try:
            with open(path) as f:
                old = json.load(f)
        except (OSError, ValueError) as e:
            safe_log(f"[cfg]no airports in {self._file} and can't read {path} ({e}); starting with none")
            return
        self._data.airports = airports_from_json(old)
        self._data._extra.pop("airports_file", None)
        self._data.save(self._file)
        safe_log(f"[cfg]moved {len(self._data.airports)} airports from {path} into {self._file}; "
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
        """The airports, one per LED in LED order (Airport; code is "" for an LED with no airport)."""
        return self._data.airports

    # ---- airports --------------------------------------------------------------------------------------------

    @locked
    def set_led_count(self, count):
        """
        Sets the number of LEDs (led.count) and gives the airport list the same length:
        new LEDs at the end have no airport; airports past the new end are removed.
        """
        count = parse_value(count, int, "led.count")
        if not 1 <= count <= MAX_LEDS:
            raise ValueError(f"led.count: {count} is not between 1 and {MAX_LEDS}")
        self._data.led.count = count
        del self._data.airports[count:]
        self.write()

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
            airport.code = code
        elif key == "name":
            airport.name = "" if value == NO_AIRPORT else str(value)
        elif key == "display":
            airport.display = parse_value(value, bool, "display")
        else:
            raise ValueError(f"unknown airport setting: {key}")
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
