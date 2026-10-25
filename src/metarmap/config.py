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
        with self.__lock__:
            return method(self, *args, **kwargs)
    return run


class Config(object):
    """
    The map's settings, including its airports (one per LED, in LED order), saved in config.json.

    Older maps kept the airports in a separate airports.json; read() moves them into config.json once and leaves
    airports.json as a backup.
    """
    def __init__(self, file):
        self.__file__ = file
        self.__lock__ = threading.RLock()
        self.__data__ = Settings()
        self.read()

    def read(self):
        with open(self.__file__) as f:
            raw = json.load(f)
        self.__data__ = Settings.from_dict(raw)
        if "airports" not in raw:
            self.__migrate__(raw)
        # one entry per LED; LEDs without an entry show nothing
        airports = self.__data__.airports
        airports.extend(Airport() for _ in range(self.__data__.led.count - len(airports)))

    def __migrate__(self, raw):
        path = raw.get("airports_file", "airports.json")
        try:
            with open(path) as f:
                old = json.load(f)
        except (OSError, ValueError) as e:
            safe_log(f"[cfg]no airports in {self.__file__} and can't read {path} ({e}); starting with none")
            return
        self.__data__.airports = airports_from_json(old)
        self.__data__._extra.pop("airports_file", None)
        self.__data__.save(self.__file__)
        safe_log(f"[cfg]moved {len(self.__data__.airports)} airports from {path} into {self.__file__}; "
                 f"{path} is kept as a backup")

    @locked
    def write(self):
        self.__data__.save(self.__file__)
        self.read()

    @locked
    def edit(self, key, value):
        """
        Saves one setting by its dotted path, e.g. edit("display_screen.delay", "5").
        Raises KeyError for an unknown setting and ValueError for a value of the wrong type.
        """
        if key == "led.count":
            return self.set_led_count(value)
        self.__data__.set(key, value)
        self.write()

    @property
    def data(self):
        return self.__data__

    @property
    def airports(self):
        """The airports, one per LED in LED order (Airport; code is "" for an LED with no airport)."""
        return self.__data__.airports

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
        self.__data__.led.count = count
        del self.__data__.airports[count:]
        self.write()

    @locked
    def set_airport(self, pixel, key, value):
        """
        Sets the code, name or display flag of the airport on LED `pixel` (counting from 0).
        "-" or "" clears the code or name. Raises IndexError for no such LED, and ValueError for another key or
        a code that isn't 3-4 letters and digits.
        """
        airport = self.airports[self.__pixel__(pixel)]
        if key == "code":
            airport.code = parse_code(value)
        elif key == "name":
            airport.name = "" if value == NO_AIRPORT else str(value)
        elif key == "display":
            airport.display = parse_value(value, bool, "display")
        else:
            raise ValueError(f"unknown airport setting: {key}")
        self.write()

    @locked
    def move_airport(self, src, dst):
        """Moves the airport on LED `src` to LED `dst`; the ones in between shift by one."""
        airports = self.airports
        airports.insert(self.__pixel__(dst), airports.pop(self.__pixel__(src)))
        self.write()

    def __pixel__(self, pixel):
        pixel = int(pixel)
        if not 0 <= pixel < len(self.airports):
            raise IndexError(f"no LED {pixel}")
        return pixel

    # the older, by-code edits (GET /config/airports/edit/...), for the first airport with that code

    @locked
    def edit_airport(self, oldkey, newkey):
        self.set_airport(self.__find__(oldkey), "code", newkey)

    @locked
    def edit_airport_property(self, airport, key, value):
        pixel = self.__find__(airport)
        if key in ("text", "name"):
            self.set_airport(pixel, "name", value)
        elif key == "display":
            self.set_airport(pixel, "display", value)
        else:
            # anything else is kept with the airport, as airports.json did
            self.airports[pixel]._extra[key] = value == "true" if value in ("true", "false") else value
            self.write()

    def __find__(self, code):
        for pixel, airport in enumerate(self.airports):
            if airport.code == code:
                return pixel
        raise KeyError(code)


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
