import copy
import filecmp
import fnmatch
import functools
import json
import logging
import os
import re
import shutil
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Sequence, Union

from metarmap.metar import MOCK_KEY, parse_raw
from metarmap.settings import Airport, Settings, parse_tunings, parse_value

log = logging.getLogger(__name__)

MAX_LEDS = 1000
ICAO = re.compile(r"^[A-Z0-9]{3,4}$")
NO_AIRPORT = "-"  # in a URL, stands for an empty code or name
PLAN_BACKUPS = 5  # the copies of config.json that applying a plan leaves beside it (the newest ones)
PLAN_STAMP = re.compile(r"^(\d{8}-\d{6})(-undone)?$")  # what follows ".before-plan-" in a backup's name


def locked(method):
    """
    Runs a change under the config's lock: web requests arrive in parallel, and each change saves config.json.
    When the outermost locked call ends, the lock is released and then the changes it made are published (see
    Config.subscribe), so a subscriber can read or change the config, and a nested call publishes nothing itself.
    """

    @functools.wraps(method)
    def run(self, *args, **kwargs):
        changes = []
        try:
            with self._lock:
                self._depth += 1
                try:
                    return method(self, *args, **kwargs)
                finally:
                    self._depth -= 1
                    if not self._depth:
                        changes, self._pending = self._pending, []
        finally:
            self._publish(changes)

    return run


# what Config.subscribe() takes: one pattern or several, e.g. "led.count", "led.quiet_hours.*" or "*"
Patterns = Union[str, Sequence[str]]


class Config:
    """
    The map's settings, including its airports (one per LED, in LED order, then the virtual ones), saved in
    config.json.

    Older maps kept the airports in a separate airports.json; read() moves them into config.json once and leaves
    airports.json as a backup.

    Every change is published as the keys that changed (subscribe()): a setting's dotted path ("led.pin"), or for
    the airport list airports.code, airports.name, airports.display, airports.order (moved), airports.mock and
    airports.other (keys of their own, set by the older by-code edits). led.count and led.virtual_count also add
    or remove airports. A change that leaves a value as it was isn't published.
    """

    def __init__(self, file):
        self._file = file
        self._lock = threading.RLock()
        self._depth = 0  # how deep in locked calls the thread holding the lock is
        self._pending: List[str] = []  # keys changed by the locked call in progress
        self._subscribers = []  # (patterns, callback)
        self._data = Settings()
        self.read()

    # ---- change events ---------------------------------------------------------------------------------------

    def subscribe(self, patterns: Patterns, callback: Callable[[List[str]], None]):
        """
        Calls callback(keys) after each change that touches a key matching one of `patterns` (shell-style: "led.*",
        "*"), with the matching keys, once per change. Subscribers run in the thread that made the change, in the
        order they subscribed; one that fails is logged and the others still run.
        """
        self._subscribers.append(((patterns,) if isinstance(patterns, str) else tuple(patterns), callback))

    def _changed(self, key):
        if key not in self._pending:
            self._pending.append(key)

    def _publish(self, changes):
        if not changes:
            return
        for patterns, callback in list(self._subscribers):
            keys = [k for k in changes if any(fnmatch.fnmatchcase(k, p) for p in patterns)]
            if not keys:
                continue
            try:
                callback(keys)
            except Exception as e:
                # the change is saved already; one part failing to follow it shouldn't stop the others
                log.exception(f"after changing {', '.join(keys)}: {e}")

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
            log.warning(f"no airports in {self._file} and can't read {path} ({e}); starting with none")
            return
        self._data.airports = airports_from_json(old)
        self._data._extra.pop("airports_file", None)
        self._data.save(self._file)
        log.info(f"moved {len(self._data.airports)} airports from {path} into {self._file}; {path} is kept as a backup")

    @locked
    def write(self):
        self._data.save(self._file)
        self.read()

    @locked
    def edit(self, key, value):
        """
        Saves one setting by its dotted path, e.g. edit("display_screen.delay", "5").
        Raises KeyError for an unknown setting and ValueError for a value its type or Rule (settings.py) doesn't
        allow.
        """
        if key == "led.count":
            return self.set_led_count(value)
        if key == "led.virtual_count":
            return self.set_virtual_count(value)
        rule = self._data.rule(key)
        if rule is not None and not rule.editable:
            raise ValueError(rule.message)
        old = self._data.get(key)
        if self._data.set(key, value) != old:
            self._changed(key)
        self.write()

    @locked
    def set_tunings(self, items):
        """Saves the Pronunciation page's list of tunings as a whole (settings.parse_tunings). Raises ValueError."""
        tunings = parse_tunings(items)
        if tunings != self._data.speech.tunings:
            self._data.speech.tunings = tunings
            self._changed("speech.tunings")
        self.write()

    @locked
    def set_login(self, user, password=None):
        """
        Sets the web UI's user name and (unless None or empty) password, saved together.
        The user name is stored in lower case, which is how logins are compared.
        """
        user = parse_user(user)
        if user != self._data.web_server.user:
            self._data.web_server.user = user
            self._changed("web_server.user")
        if password and password != self._data.web_server.password:
            self._data.web_server.password = password
            self._changed("web_server.password")
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
        if not 0 <= count <= MAX_LEDS - self._data.led.virtual_count:
            raise ValueError(
                f"led.count: {count} is not between 0 and {MAX_LEDS - self._data.led.virtual_count} "
                f"({MAX_LEDS} airports in all, with the virtual ones)"
            )
        old, airports = self._data.led.count, self._data.airports
        if count < old:
            del airports[count:old]
        else:
            airports[old:old] = [Airport() for _ in range(count - old)]
        if count != old:
            self._data.led.count = count
            self._changed("led.count")
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
            raise ValueError(
                f"led.virtual_count: {count} is not between 0 and {MAX_LEDS - self._data.led.count} "
                f"({MAX_LEDS} airports in all, with the LEDs)"
            )
        if count != self._data.led.virtual_count:
            self._data.led.virtual_count = count
            self._changed("led.virtual_count")
        del self._data.airports[self._data.led.count + count :]
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
                airport.code = code
                self._changed("airports.code")
                if airport.name:
                    airport.name = ""  # the old name was the old airport's; fill_names() gives the new one
                    self._changed("airports.name")
                if airport._extra.pop(MOCK_KEY, None) is not None:  # and so was its mock METAR
                    self._changed("airports.mock")
        elif key == "name":
            self._set(airport, "name", "" if value == NO_AIRPORT else str(value))
        elif key == "display":
            self._set(airport, "display", parse_value(value, bool, "display"))
        else:
            raise ValueError(f"unknown airport setting: {key}")
        self.write()

    def _set(self, airport, name, value):
        if getattr(airport, name) != value:
            setattr(airport, name, value)
            self._changed(f"airports.{name}")

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
        if airport._extra.get(MOCK_KEY) != (text or None):
            if text:
                airport._extra[MOCK_KEY] = text
            else:
                airport._extra.pop(MOCK_KEY, None)
            self._changed("airports.mock")
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
            self._changed("airports.name")
            self.write()
        return filled

    @locked
    def move_airport(self, src, dst):
        """Moves the airport on LED `src` to LED `dst`; the ones in between shift by one."""
        airports = self.airports
        src, dst = self._pixel(src), self._pixel(dst)
        if src != dst:
            airports.insert(dst, airports.pop(src))
            self._changed("airports.order")
        self.write()

    def _pixel(self, pixel):
        pixel = int(pixel)
        if not 0 <= pixel < len(self.airports):
            raise IndexError(f"no LED {pixel}")
        return pixel

    # ---- applying a plan (the Chart Planner) ------------------------------------------------------------------

    @locked
    def layout(self):
        """(copies of the airports, led.count, led.virtual_count): a consistent view for the planner's preview."""
        return copy.deepcopy(self._data.airports), self._data.led.count, self._data.led.virtual_count

    @locked
    def apply_plan(self, airports, led_count, virtual_count, *, backup=True, summary=None, check=None):
        """
        Replaces the airports (one per LED, then the virtual ones) and the two counts in ONE write; the changes are
        published once, so the OLED, the strip and the METAR fetch follow once. Before it writes, config.json is
        copied to config.json.before-plan-YYYYMMDD-HHMMSS and `summary` is kept beside it, for
        restore_plan_backup(); once the write is done only the newest PLAN_BACKUPS stay, and a write that fails
        takes its backup away again. `check(airports, led_count, virtual_count)` runs under the lock on the
        airports as they are now and can raise to refuse (the planner uses it so that a change made since its
        preview is not overwritten). Nothing is half applied: if the write fails the old airports stay.
        Raises ValueError for a count out of range, a list of the wrong length, a bad code or a code twice, and
        OSError when the backup cannot be made. Returns {"backup": file name or None, "keys": [changed keys],
        "led_count_changed": whether led.count changed}. A NeoPixel strip only changes length at a restart: whether
        one is needed is the caller's to say (the strip is the renderer's).
        """
        led_count = parse_value(led_count, int, "led.count")
        virtual_count = parse_value(virtual_count, int, "led.virtual_count")
        if led_count < 0 or virtual_count < 0 or led_count + virtual_count > MAX_LEDS:
            raise ValueError(
                f"{led_count} LEDs and {virtual_count} virtual airports are over {MAX_LEDS} airports in all"
            )
        new = []
        for airport in airports:
            clean = copy.deepcopy(airport)
            clean.code = parse_code(airport.code)
            clean.name = str(airport.name or "")
            clean.display = bool(airport.display)
            new.append(clean)
        if len(new) != led_count + virtual_count:
            raise ValueError(f"{len(new)} airports for {led_count} LEDs and {virtual_count} virtual airports")
        codes = [a.code for a in new if a.code]
        if len(set(codes)) != len(codes):
            raise ValueError(_twice(new, led_count))
        if check is not None:
            check(copy.deepcopy(self._data.airports), self._data.led.count, self._data.led.virtual_count)
        stamp = self._backup_before_plan(summary) if backup else None
        try:
            keys = self._replace_airports(new, led_count, virtual_count)
        except BaseException:
            if stamp:
                self._drop_failed_backup(stamp)  # an apply that did not happen offers no Undo
            raise
        if stamp:
            self._prune_plan_backups(keep=stamp)  # only now that the write is safe
        name = f"{os.path.basename(self._file)}.before-plan-{stamp}" if stamp else None
        log.info(
            f"applied a plan: {len(codes)} airports on {led_count} LEDs and {virtual_count} virtual "
            f"({', '.join(keys) or 'nothing changed'}); backup {name}"
        )
        return {"backup": name, "keys": keys, "led_count_changed": "led.count" in keys}

    def _replace_airports(self, new, led_count, virtual_count):
        """The one write: swaps in the list and the counts, publishes the keys that differ, and puts the old ones
        back if the file cannot be written. Returns the keys."""
        data = self._data
        old = (data.airports, data.led.count, data.led.virtual_count)
        keys = plan_keys(old[0], new, old[1], old[2], led_count, virtual_count)
        pending = list(self._pending)
        data.airports, data.led.count, data.led.virtual_count = new, led_count, virtual_count
        try:
            for key in keys:
                self._changed(key)
            self.write()
        except BaseException:
            self._data.airports, self._data.led.count, self._data.led.virtual_count = old
            self._pending = pending
            raise
        return keys

    def _plan_files(self):
        """[(stamp, undone, file name)] of the backups apply_plan made beside config.json, newest first."""
        folder, base = os.path.split(os.path.abspath(self._file))
        prefix = base + ".before-plan-"
        found = []
        try:
            names = os.listdir(folder)
        except OSError:
            return []
        for name in names:
            match = name.startswith(prefix) and PLAN_STAMP.match(name[len(prefix) :])
            if match:
                found.append((match.group(1), bool(match.group(2)), name))
        # the stamps only ever go up (see _backup_before_plan), so the newest is the highest, whatever the clock says
        return sorted(found, reverse=True)

    def next_plan_backup_name(self):
        """The name the next backup would get (the time may differ by a second when it is made)."""
        return f"{os.path.basename(self._file)}.before-plan-{self._next_stamp()[0]:%Y%m%d-%H%M%S}"

    def _next_stamp(self):
        """(the UTC time for the next backup's name, its time as made). The name's time never goes below the newest
        backup's: a Pi that booted before its clock was set would otherwise sort its new backup as the oldest, and
        prune it or undo the wrong apply."""
        now = datetime.now(timezone.utc).replace(microsecond=0)
        stamp = now
        files = self._plan_files()
        if files:
            newest = datetime.strptime(files[0][0], "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)
            if stamp <= newest:
                stamp = newest + timedelta(seconds=1)
        return stamp, now

    def _backup_before_plan(self, summary):
        """
        Copies config.json to config.json.before-plan-<stamp> and keeps the summary beside it. It holds the web
        password, so the copy is made private from the start (no moment when another user could read it) and then
        takes the original's mode. Does not remove old backups: apply_plan does that once the write is done.
        Returns the new stamp.
        """
        stamp_time, made = self._next_stamp()
        stamp = f"{stamp_time:%Y%m%d-%H%M%S}"
        dest = f"{self._file}.before-plan-{stamp}"
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as out, open(self._file, "rb") as source:
                shutil.copyfileobj(source, out)
            shutil.copystat(self._file, dest)
        except BaseException:
            self._remove_plan_files(stamp)
            raise
        try:
            fd = os.open(f"{dest}.summary.json", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump({"made_at": made.isoformat(), "summary": summary or {}}, f)
        except OSError as e:  # the backup is what matters; the Undo button just shows less
            log.warning(f"could not keep the summary of the plan backup {os.path.basename(dest)}: {e}")
        return stamp

    def _drop_failed_backup(self, stamp):
        """The write failed: take the backup made for it away, unless config.json changed after all (the save went
        through and only the read back failed): then the backup is the way back, so it stays."""
        dest = f"{self._file}.before-plan-{stamp}"
        try:
            same = filecmp.cmp(self._file, dest, shallow=False)
        except OSError:
            same = False
        if same:
            self._remove_plan_files(stamp)
        else:
            log.warning(f"config.json changed while the plan was applied and the save failed: keeping {dest}")

    def _prune_plan_backups(self, keep):
        """Removes all but the newest PLAN_BACKUPS, never the one called `keep`."""
        for old_stamp, _undone, _name in self._plan_files()[PLAN_BACKUPS:]:
            if old_stamp != keep:
                self._remove_plan_files(old_stamp)

    def _remove_plan_files(self, stamp):
        """Removes the files that belong to one backup and nothing else: its copy, the copy marked undone and their
        summaries (a file a user named like them, e.g. with ".mine" after it, stays)."""
        base = f"{self._file}.before-plan-{stamp}"
        for path in (base, base + "-undone", base + ".summary.json", base + "-undone.summary.json"):
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            except OSError as e:
                log.warning(f"could not remove the plan backup file {os.path.basename(path)}: {e}")

    def plan_backups(self):
        """
        The backups an Undo can restore, newest first: [{"file", "path", "made_at" (ISO time), "summary"}]; one that
        was restored already is not listed.
        """
        folder = os.path.dirname(os.path.abspath(self._file))
        out = []
        for stamp, undone, name in self._plan_files():
            if undone:
                continue
            path = os.path.join(folder, name)
            made_at, summary = None, None
            try:
                with open(f"{path}.summary.json") as f:
                    saved = json.load(f)
                made_at, summary = saved.get("made_at"), saved.get("summary")
            except (OSError, ValueError, AttributeError):
                pass
            if not made_at:
                made_at = datetime.strptime(stamp, "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc).isoformat()
            out.append({"file": name, "path": path, "made_at": made_at, "summary": summary})
        return out

    @locked
    def restore_plan_backup(self, name=None):
        """
        Undoes an applied plan: puts back the airports, led.count and led.virtual_count that a plan backup has
        (the newest one, or the one called `name`) and nothing else, so a setting changed since stays as it is. The
        backup is renamed "...-undone" so it is not offered twice. Raises LookupError when there is none to restore
        and ValueError (or OSError) for one that cannot be read. Returns {"airports", "led_count", "virtual_count",
        "backup", "keys", "led_count_changed"}.
        """
        backups = self.plan_backups()
        chosen = next((b for b in backups if name is None or b["file"] == name), None)
        if chosen is None:
            raise LookupError("there is no applied plan to undo")
        with open(chosen["path"]) as f:
            saved = Settings.from_dict(json.load(f))
        airports, led_count = saved.airports, saved.led.count
        virtual_count = max(saved.led.virtual_count, len(airports) - led_count, 0)
        airports.extend(Airport() for _ in range(led_count + virtual_count - len(airports)))
        if led_count + virtual_count > MAX_LEDS:
            raise ValueError(f"the backup has {led_count + virtual_count} airports: over {MAX_LEDS}")
        keys = self._replace_airports(airports, led_count, virtual_count)
        try:
            os.replace(chosen["path"], chosen["path"] + "-undone")
        except OSError as e:
            log.warning(f"restored {chosen['file']} but could not mark it undone: {e}")
        else:
            try:  # its summary goes with it, so no orphan is left behind
                os.replace(chosen["path"] + ".summary.json", chosen["path"] + "-undone.summary.json")
            except FileNotFoundError:
                pass
            except OSError as e:
                log.warning(f"could not rename the summary of {chosen['file']}: {e}")
        log.info(f"undid the plan: {led_count} LEDs and {virtual_count} virtual airports from {chosen['file']}")
        return {
            "airports": len([a for a in airports if a.code]),
            "led_count": led_count,
            "virtual_count": virtual_count,
            "backup": chosen["file"],
            "keys": keys,
            "led_count_changed": "led.count" in keys,
        }

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
            extra = self.airports[pixel]._extra
            value = value == "true" if value in ("true", "false") else value
            if extra.get(key, object()) != value:
                extra[key] = value
                self._changed("airports.other")
            self.write()

    def _find(self, code):
        for pixel, airport in enumerate(self.airports):
            if airport.code == code:
                return pixel
        raise KeyError(code)


def _twice(airports, led_count):
    """The refusal for a code in the list twice: which code, and where (LED numbers, then virtual airports)."""
    where = {}
    for index, airport in enumerate(airports):
        if airport.code:
            place = f"LED {index + 1}" if index < led_count else f"virtual airport {index - led_count + 1}"
            where.setdefault(airport.code, []).append(place)
    code, places = next((c, p) for c, p in where.items() if len(p) > 1)
    return f"the airport code {code} is in the list twice ({' and '.join(places)})"


def _other_keys(airports):
    """The keys an airport keeps of its own, besides its mock METAR (set by the older by-code edits)."""
    return [{k: v for k, v in a._extra.items() if k != MOCK_KEY} for a in airports]


def plan_keys(old, new, old_led, old_virtual, led, virtual):
    """
    The change keys (see Config) for swapping the airport list `old` for `new`, only for what differs: airports.order
    when the codes are in another order (or the list is another length), airports.code when airports came or went (it
    fetches their METARs), airports.name, airports.display, airports.mock, airports.other, led.count, led.virtual_count.
    """
    keys = []
    # a list that only grows or shrinks by blank LEDs has not changed for the ones that are there
    size = max(len(old), len(new))
    old = list(old) + [Airport() for _ in range(size - len(old))]
    new = list(new) + [Airport() for _ in range(size - len(new))]
    old_codes, new_codes = [a.code for a in old], [a.code for a in new]
    if old_codes != new_codes:
        keys.append("airports.order")
    if {c for c in old_codes if c} != {c for c in new_codes if c}:
        keys.append("airports.code")
    if [a.name for a in old] != [a.name for a in new]:
        keys.append("airports.name")
    if [a.display for a in old] != [a.display for a in new]:
        keys.append("airports.display")
    if [a._extra.get(MOCK_KEY) for a in old] != [a._extra.get(MOCK_KEY) for a in new]:
        keys.append("airports.mock")
    if _other_keys(old) != _other_keys(new):
        keys.append("airports.other")
    if old_led != led:
        keys.append("led.count")
    if old_virtual != virtual:
        keys.append("led.virtual_count")
    return keys


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
    for code, props in old.items() if isinstance(old, dict) else []:
        props = props if isinstance(props, dict) else {}
        text = props.get("text")
        airport = Airport(
            code="" if "NULL" in code.upper() else code,
            name=text if isinstance(text, str) else "",
            display=bool(props.get("display", False)),
        )
        airport._extra = {k: v for k, v in props.items() if k not in ("text", "display")}
        airports.append(airport)
    return airports
