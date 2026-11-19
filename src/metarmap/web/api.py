"""
The JSON API: /api/status (used by the Home Assistant integration), /api/live (polled by the Map page) and
/api/traffic (the Map page's live traffic), /api/advisories (the G-AIRMET and SIGMET areas), /api/tfrs (TFRs) and
/api/icon/<name> (a visualizer icon as a mask, for the Copilot).
See API.md; the field names are part of the API.
"""

import gzip
import json
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import bottle

from metarmap.discovery import map_name
from metarmap import __version__
from metarmap.decode import decode, summary
from metarmap.delays import CLOSED, FOREVER, NORMAL, describe
from metarmap.models import Report
from metarmap.atis import AtisError
from metarmap.atis_spoken import for_airport, lines as atis_lines
from metarmap.speech import SpeechError, configured
from metarmap.spoken import spoken
from metarmap.visualizers import advisories as advisories_vis, tfr as tfr_vis, wind_direction
from metarmap.visualizers.visualizer import ID as ICON_NAME  # icon names look like visualizer ids
from metarmap.web import icons, views
from metarmap.web.services import Services

# each airport's report fields in /api/status (Report.to_api()'s names), in this order
STATUS_FIELDS = (
    "flightCategory",
    "raw",
    "windDir",
    "windSpeed",
    "windGustSpeed",
    "vis",
    "obs",
    "tempC",
    "dewpointC",
    "altimHg",
    "lightning",
    "obsTime",
)


def _iso(dt):
    return dt.isoformat() if dt is not None else None


def _status_airports(services):
    cfg = services.config.data
    metars = services.metars
    airports = []
    for index, airport in enumerate(services.config.airports):
        if not airport.code:
            continue
        m = metars.data.get(airport.code)
        report = m.to_api() if m else {}  # no report: every field null
        airports.append(
            {
                "code": airport.code,
                "pixel": index,
                "text": airport.name,
                "display": airport.display,
                "virtual": index >= cfg.led.count,  # on the web map and here only, no LED
                "mock": bool(m and m.mock),  # a mock METAR (dev_mode) in place of the real one
                **{field: report.get(field) for field in STATUS_FIELDS},
            }
        )
    return airports


def _status_visualizer(services):
    active_num, active_vis = services.renderer.visualizer
    return {
        "active": active_num,
        "id": active_vis.id,
        "name": active_vis.name,
        "shortName": active_vis.short_name,
        "icon": active_vis.icon,
        "iconRev": icons.mask_rev(active_vis.icon),  # its mask's ETag at /api/icon/<icon>
        "exclusive": active_vis.exclusive,
        "description": active_vis.description,
        "legend": services.renderer.legend(),
    }


def _status_visualizers(services):
    skip = services.config.data.visualizer.auto_rotate.skip
    return [
        {
            "index": i,
            "id": v.id,
            "name": v.name,
            "shortName": v.short_name,
            "icon": v.icon,
            "iconRev": icons.mask_rev(v.icon),
            "exclusive": v.exclusive,
            "skipped": v.id in skip,  # left out of auto-rotate
        }
        for i, v in enumerate(services.renderer.visualizers)
    ]


def _status_config(cfg):
    return {
        "visualizer.active": cfg.visualizer.active,
        "visualizer.auto_rotate.enabled": cfg.visualizer.auto_rotate.enabled,
        "visualizer.auto_rotate.delay_seconds": cfg.visualizer.auto_rotate.delay_seconds,
        "visualizer.auto_rotate.skip": cfg.visualizer.auto_rotate.skip,
        "visualizer.auto_rotate.skip_dark": cfg.visualizer.auto_rotate.skip_dark,
        "visualizer.missing_data_blink": cfg.visualizer.missing_data_blink,
        "visualizer.estimated_category_breathing": cfg.visualizer.estimated_category_breathing,
        "visualizer.forecast_step_seconds": cfg.visualizer.forecast_step_seconds,
        "visualizer.forecast_include_tempo": cfg.visualizer.forecast_include_tempo,
        "visualizer.legend_in_use_only": cfg.visualizer.legend_in_use_only,
        "lightning.animation": cfg.lightning.animation,
        "lightning.color": cfg.lightning.color,
        "lightning.forecast": cfg.lightning.forecast,
        "display_screen.enabled": cfg.display_screen.enabled,
        "display_screen.locate_active": cfg.display_screen.locate_active,
        "display_screen.delay": cfg.display_screen.delay,
        "display_screen.shows": cfg.display_screen.shows,
        "led.inittest": cfg.led.inittest,
        "led.init_sequence": cfg.led.init_sequence,
        "led.init_sweep_from": cfg.led.init_sweep_from,
        "led.dim_on_refresh": cfg.led.dim_on_refresh,
        "led.brightness.normal": cfg.led.brightness.normal,
        "led.brightness.dimmed": cfg.led.brightness.dimmed,
        "led.brightness.off": cfg.led.brightness.off,
        "led.quiet_hours.enabled": cfg.led.quiet_hours.enabled,
        "led.quiet_hours.start": cfg.led.quiet_hours.start,
        "led.quiet_hours.end": cfg.led.quiet_hours.end,
    }


def status(services: Services, ip):
    """
    Read-only snapshot of the map state.
    """
    cfg = services.config.data
    metars = services.metars
    suntimes = services.sun.times or {}
    return {
        "version": __version__,
        "ip": ip,
        "name": services.discovery.name() if services.discovery else map_name(cfg),
        "announcing": bool(services.discovery and services.discovery.announcing),
        "brightness": services.renderer.pixels().brightness,
        "visualizer": _status_visualizer(services),
        "visualizers": _status_visualizers(services),
        "config": _status_config(cfg),
        "display": {"enabled": cfg.display_screen.enabled, "on": cfg.display_screen.enabled and services.display.on},
        "suntimes": {k: _iso(suntimes.get(k)) for k in ("dawn", "sunrise", "sunset", "dusk")},
        "build": services.releases.build if services.releases else None,
        "update": update_state(services),
        "lastFetchTime": _iso(metars.lastFetchTime),
        "missingStations": metars.missing_stations(),
        "airports": _status_airports(services),
    }


def update_state(services: Services):
    """What's newest on GitHub (see metarmap.releases); null for a map without the check."""
    releases = services.releases
    if releases is None:
        return None
    state = releases.state()
    return {
        **{k: v for k, v in state.items() if k not in ("badge", "releases", "build")},
        "releases": [r["tag"] for r in state["releases"]],
    }


def wind_barb(metar: Optional[Report]):
    """
    An airport's wind for its barb on the Map page: {"dir": degrees, "kt": speed}, or None when calm, variable or
    not reporting.
    """
    if metar is None:
        return None
    direction = wind_direction.heading(metar)
    speed = metar.wind_speed
    if not isinstance(direction, float) or not speed:
        return None
    return {"dir": direction, "kt": speed}


def auto_rotate(services: Services):
    """Auto-rotate: whether it's on, its delay, and when it next changes the visualizer (Unix time; None when off)."""
    rotate = services.config.data.visualizer.auto_rotate
    return {
        "enabled": rotate.enabled,
        "seconds": rotate.delay_seconds,
        "next": services.next_rotation(),
        "skip": list(rotate.skip),  # the ids it leaves out (visualizer.auto_rotate.skip)
    }


def fetch_schedule(services: Services):
    """When METARs are next fetched, that wait's length, and when they were last fetched (Unix times)."""
    return services.next_fetch()


def live_leds(services: Services, led_looks, barbs):
    """Every airport's entry in /api/live's leds[]: report, position and look (`led_looks`: Renderer.led_states())."""

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    with_atis = atis_airports(services)
    leds = []
    for s in views.stations(
        services.config.airports,
        services.metars.data,
        services.metars.position,
        services.config.data.led.count,
    ):
        m = services.metars.data.get(s["code"])
        leds.append(
            {
                "code": s["code"],
                "pixel": s["pixel"],
                "name": s["name"],
                "virtual": s["virtual"],
                "mock": s["mock"],
                "lat": num(s["lat"]),
                "lon": num(s["lon"]),
                "flightCategory": s["cat"],
                "raw": s["raw"],
                "lightning": bool(m and m.lightning),
                "look": led_looks.get(s["pixel"], {"effect": "off", "colors": []}),
                "wind": wind_barb(m) if barbs else None,
                "atis": s["code"] in with_atis,  # a spoken ATIS can be asked for (/api/atis/<code>.audio)
            }
        )
    return leds


def live(services: Services, now=None, leds=None):
    """
    What the physical map is doing right now: every LED's effect, the OLED screen and the last locate pulse.
    leds: the leds[] entries when they're already made (see LiveLeds); else they're built here.
    """
    renderer = services.renderer
    led_looks, strip = renderer.led_states()
    speaks = services.speech is not None and configured(services.config.data.speech)
    speech_ok, speech_error = services.speech.health() if speaks else (None, "")
    active_num, active_vis = renderer.visualizer
    display = services.display if services.config.data.display_screen.enabled else None
    if leds is None:
        leds = live_leds(services, led_looks, active_vis.barbs)
    return {
        "now": now if now is not None else time.time(),
        "brightness": renderer.pixels().brightness,
        "visualizer": {
            "active": active_num,
            "id": active_vis.id,
            "name": active_vis.name,
            "shortName": active_vis.short_name,
            "icon": active_vis.icon,
            "iconRev": icons.mask_rev(active_vis.icon),
            "exclusive": active_vis.exclusive,
            "areas": active_vis.areas,
            "autoRotate": auto_rotate(services),
            # the legend entries (keys) the LEDs show now, null for a whole-strip look; the pages hide the others when
            # legendInUseOnly (visualizer.legend_in_use_only)
            "legendInUse": renderer.legend_in_use(),
            "legendInUseOnly": services.config.data.visualizer.legend_in_use_only,
            # a stepping visualizer's step now ({"labels": [...], "index": n}), else null
            "step": renderer.step(),
        },
        "fetch": fetch_schedule(services),
        "strip": strip,
        "leds": leds,
        "locate": renderer.last_locate,
        "display": {
            "enabled": display is not None,
            "on": bool(display and display.on),
            "screen": display.screen if display else None,
        },
        # spoken weather can be asked for (/api/speak/<code>.audio): on, with a server set. The AWOS buttons and the
        # touchscreen remote's hold-to-hear follow it
        "speech": speaks,
        # how the last clip went (no I/O: what the map remembers): speechOk null before any (or speech off), true once
        # one was made, false after one failed (and while the server is left alone); speechError its line, else ""
        "speechOk": speech_ok,
        "speechError": speech_error,
    }


class LiveLeds:
    """
    /api/live's leds[] as JSON text, made once and kept until something it shows changes: the renderer rebuilt its
    looks (Renderer.revision: a new visualizer, new data, a config change), or an input the looks don't cover did (an
    airport's name or report, a position, led.count, the wind barbs, which airports have an ATIS). Most polls then
    reuse the text instead of building and dumping ~330 bytes of dicts per pixel. Thread safe: pages and the Copilot
    poll from several threads.
    """

    def __init__(self, services: Services):
        self._services = services
        self._lock = threading.Lock()
        self._key = None
        self._text = ""
        self.builds = 0  # how many times it was made (for the tests)

    def _inputs(self, barbs):
        services = self._services
        data = services.metars.data
        position = services.metars.position
        cfg = services.config
        return (
            services.renderer.revision,
            cfg.data.led.count,
            bool(barbs),
            frozenset(atis_airports(services)),
            # the Reports themselves (kept here, so the same object means no new report); a position only when the
            # airport has no report to place it
            tuple(self._airport(a, pixel, data, position) for pixel, a in enumerate(cfg.airports) if a.code),
        )

    @staticmethod
    def _airport(a, pixel, data, position):
        # as views.stations places it: position() only when there's no report or it has no lat/lon. The pixel is in
        # the key: a Hidden Pixel (no code) inserted or removed before an airport moves it
        m = data.get(a.code)
        placed = bool(m and m.latitude and m.longitude)
        return (pixel, a.code, a.name, m, None if placed else position(a.code))

    def text(self):
        """The leds[] JSON text now."""
        renderer = self._services.renderer
        barbs = renderer.visualizer[1].barbs
        with self._lock:
            key = self._inputs(barbs)  # read before the build: a change during it is seen at the next poll
            if self._key != key:
                led_looks, _ = renderer.led_states()
                self._text = dumps(live_leds(self._services, led_looks, barbs))
                self._key = key
                self.builds += 1
            return self._text


LEDS_PLACEHOLDER = "leds-" + uuid.uuid4().hex  # unguessable: no airport or setting can spell it


def live_json(services: Services, cache: LiveLeds):
    """/api/live as compact JSON text, with leds[] from `cache`."""
    body = dumps(live(services, leds=LEDS_PLACEHOLDER))
    marker = f'"{LEDS_PLACEHOLDER}"'
    if body.count(marker) != 1:
        raise RuntimeError("/api/live's leds placeholder is not in the body exactly once")
    return body.replace(marker, cache.text(), 1)


def metar(services: Services, code):
    """
    One airport's METAR, raw and decoded (the Map page's popup). None if the airport isn't on the map.
    """
    if code not in {a.code for a in services.config.airports if a.code}:
        return None
    m = services.metars.data.get(code)
    return {
        "code": code,
        "raw": m.raw if m else None,
        "mock": bool(m and m.mock),
        "flightCategory": m.flight_category if m else None,
        "obsTime": m.obs_time.isoformat() if m and m.obs_time else None,
        "decoded": decode(m),
        "summary": summary(m),
        "faa": faa_status(m),
    }


def faa_status(m):
    """
    What the FAA says about a report's airport, for the Map page's popup: {"kind", "text", "reason", "minutes",
    "until"} (see /api/metar), or None when it's normal, not listed, or not known yet.
    """
    status = m.faa_status if m else None
    if not status or status["kind"] == NORMAL:
        return None
    until = status.get("until")
    return {
        "kind": status["kind"],
        "text": describe(status),
        "reason": status.get("reason", ""),
        "minutes": status["minutes"],
        "until": datetime.fromtimestamp(until, timezone.utc).isoformat()
        if status["kind"] == CLOSED and until not in (None, FOREVER)
        else None,
    }


def spoken_report(services: Services, code):
    """One airport's METAR as text to be read aloud (see metarmap.spoken); None if the airport isn't on the map."""
    airports = {a.code: a for a in services.config.airports if a.code}
    if code not in airports:
        return None
    m = services.metars.data.get(code)
    tunings = for_airport(services.config.data.speech.tunings, code)
    return spoken(m, airports[code].name or (m.name if m else ""), code, tunings)


def atis_airports(services: Services):
    """The map's airports with a spoken ATIS to ask for: speech on with a server, speech.atis on, and a D-ATIS."""
    atis = services.atis
    if atis is None or services.speech is None or not configured(services.config.data.speech):
        return set()
    return atis.available()


def atis_transcript(services: Services, code):
    """
    One airport's ATIS line by line, for reading along: {"code", "lines": [{"raw": the FAA's text, "said": how it's
    read}], "entries": [{"type", "code" (its letter), "time", "updatedAt"}]}. Raises AtisError.
    """
    airports = {a.code: a for a in services.config.airports if a.code}
    if code not in airports:
        raise AtisError(f"{code} isn't on the map", 404)
    atis = services.atis
    if atis is None:
        raise AtisError("This map has no ATIS", 503)
    entries = atis.entries(code)
    m = services.metars.data.get(code)
    name = airports[code].name or (m.name if m else "")
    tunings = services.config.data.speech.tunings
    found = atis_lines(entries, name, code, atis.available() | set(airports), tunings)
    return {
        "code": code,
        "lines": [{"raw": raw, "said": said} for raw, said in found],
        "entries": [{k: e[k] for k in ("type", "code", "time", "updatedAt")} for e in entries],
    }


def atis_report(services: Services, code):
    """One airport's ATIS as text to be read aloud (see metarmap.atis_spoken). Raises AtisError."""
    return " ".join(line["said"] for line in atis_transcript(services, code)["lines"] if line["said"])


def atis_overview(services: Services):
    """The map's airports with an ATIS: {code: [{"type", "code" (its letter), "time", "updatedAt"}]}."""
    atis = services.atis
    if atis is None:
        raise AtisError("This map has no ATIS", 503)
    found = {}
    for code in (a.code for a in services.config.airports if a.code):
        try:
            entries = atis.entries(code)
        except AtisError as e:
            if e.status == 404:
                continue
            raise
        found[code] = [{k: e[k] for k in ("type", "code", "time", "updatedAt")} for e in entries]
    return found


def spoken_reports(services: Services):
    """Every airport's spoken METAR, {code: text}, in the map's order."""
    return {a.code: spoken_report(services, a.code) for a in services.config.airports if a.code}


def traffic_view(query):
    """
    The view a page sends, (lat, lon, radius in NM), from ?lat=&lon=&nm=; None when it sends none (the airports'
    circle then). A 400 for a partial or impossible one.
    """
    if not any(key in query for key in ("lat", "lon", "nm")):
        return None
    try:
        lat, lon, nm = float(query["lat"]), float(query["lon"]), float(query["nm"])
    except (KeyError, ValueError):
        bottle.abort(400, "lat, lon and nm are all needed, as numbers")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180 and 0 < nm < float("inf")):
        bottle.abort(400, "lat, lon or nm is out of range")
    return lat, lon, nm


def traffic(services: Services, view=None):
    """Live traffic around the view, or the airports (see metarmap.traffic), as JSON text; None for a map without it."""
    found = services.traffic
    return found.snapshot_json(view) if found is not None else None


def advisories(services: Services):
    """The G-AIRMET and SIGMET areas below 18,000 ft (metarmap.advisories), each with its color, for the Map page."""
    found = services.advisories
    if found is None:
        return None
    state = found.state()
    state["areas"] = [{**area, "color": advisories_vis.css(area["hazard"], area["kind"])} for area in state["areas"]]
    return state


def tfrs(services: Services):
    """The TFRs in effect or starting within 24 hours (metarmap.tfr), each with its type's color, for the Map page."""
    found = services.tfrs
    if found is None:
        return None
    state = found.state()
    state["areas"] = [{**area, "color": tfr_vis.css(area["type"])} for area in state["areas"]]
    return state


def dumps(data):
    """JSON without the spaces after , and : (a fifth smaller; the same data)."""
    return json.dumps(data, separators=(",", ":"))


def as_json(data):
    bottle.response.content_type = "application/json"
    return dumps(data)


def version(services: Services):
    """
    What the Chart runs, {"version", "commit"}: what every page polls to see an update (a few bytes, /api/status is
    90 KB). commit is the running code's 7-character commit, null without git; a branch install keeps its version
    while the code changes, so a page compares both.
    """
    bottle.response.set_header("Cache-Control", "no-store")
    build = services.releases.build if services.releases else None
    return as_json({"version": __version__, "commit": build["commit"] if build else None})


def as_json_text(text):
    """JSON that's already text, gzipped when the client asks (a busy circle is 85 KB, about 20 KB gzipped)."""
    bottle.response.content_type = "application/json"
    bottle.response.set_header("Vary", "Accept-Encoding")
    if "gzip" in bottle.request.headers.get("Accept-Encoding", ""):
        bottle.response.set_header("Content-Encoding", "gzip")
        return gzip.compress(text.encode(), 1)  # level 1: 12 ms on a Pi Zero for the biggest answer, 57 ms at 6
    return text


def as_text(text, code):
    """A plain-text answer (404 when `text` is None: the airport isn't on the map)."""
    if text is None:
        bottle.abort(404, f"{code} isn't on the map")
    bottle.response.content_type = "text/plain; charset=utf-8"
    return text


def as_audio(services: Services, code, force=False):
    """An airport's METAR read aloud (WAV), by the speech server (speech.engine: Piper over Wyoming, or Kokoro). 404:
    not on the map; 503: no server is set, or the server is left alone a while after it didn't answer; 504: it didn't
    answer in speech.timeout; 502: the server failed or couldn't be reached. Errors are plain text. force: ask the
    server even while it's left alone (Config's Test, /config/speak/<code>.audio: after restarting it)."""
    text = spoken_report(services, code)
    if text is None:
        bottle.abort(404, f"{code} isn't on the map")
    speech = services.speech
    if speech is None:
        bottle.abort(503, "This map has no speech")
    try:
        clip = speech.audio(text, force=force)
    except SpeechError as e:
        return as_error(e)
    bottle.response.content_type = "audio/wav"
    bottle.response.set_header("Cache-Control", "no-store")  # the next METAR says something else
    return byte_range(clip)


# the most a Pronunciation page's Play reads: a tuning says at most 120 characters
SAY_MAX = 200


def as_said_audio(services: Services, text: str):
    """
    Some words read aloud (WAV), as the speech server says them: the Pronunciation page's Play beside a tuning, to
    hear a "say it as" before saving it. 400: no words, or too many; 502, 503 and 504 as for as_audio(). It asks the
    server even while it's left alone (as_audio's force), so it's a way to try a server just restarted.
    """
    text = " ".join((text or "").split())
    if not text:
        bottle.abort(400, "Nothing to say")
    if len(text) > SAY_MAX:
        bottle.abort(400, f"At most {SAY_MAX} characters")
    speech = services.speech
    if speech is None:
        bottle.abort(503, "This map has no speech")
    try:
        clip = speech.audio(text, force=True)
    except SpeechError as e:
        return as_error(e)
    bottle.response.content_type = "audio/wav"
    return byte_range(clip)


def as_error(e):
    """A SpeechError's or AtisError's message as a plain-text answer, with its status."""
    bottle.response.status = e.status
    bottle.response.content_type = "text/plain; charset=utf-8"
    return str(e)


def as_atis_text(services: Services, code):
    try:
        text = atis_report(services, code)
    except AtisError as e:
        return as_error(e)
    bottle.response.content_type = "text/plain; charset=utf-8"
    return text


def as_atis_audio(services: Services, code):
    """An airport's ATIS read aloud (WAV), by the speech server. 404: not on the map, or no ATIS; 503: speech or
    spoken ATIS is off, or the speech server is left alone a while; 504: it didn't answer in speech.timeout; 502:
    atis.info or the speech server failed. Errors are plain text."""
    speech = services.speech
    if speech is None:
        bottle.abort(503, "This map has no speech")
    try:
        clip = speech.audio(atis_report(services, code))
    except (AtisError, SpeechError) as e:
        return as_error(e)
    bottle.response.content_type = "audio/wav"
    bottle.response.set_header("Cache-Control", "no-store")  # the next ATIS says something else
    return byte_range(clip)


def as_atis_transcript(services: Services, code):
    try:
        return as_json(atis_transcript(services, code))
    except AtisError as e:
        return as_error(e)


def as_atis_overview(services: Services):
    try:
        return as_json(atis_overview(services))
    except AtisError as e:
        return as_error(e)


def icon_mask(name):
    """
    A visualizer icon as a 20x20 alpha mask (icons.mask): 400 bytes, row by row, 0 clear to 255 solid, drawn ahead
    of time (the Pi draws nothing). It changes only with the Chart's code, so a client may keep it: its ETag is the
    mask's rev (iconRev in /api/status), and a matching If-None-Match is a 304. 404: no such icon; 400: not a name.
    Errors are JSON, {"error", "reason"}. A query (?v=) is ignored.
    """
    if not ICON_NAME.fullmatch(name):
        bottle.response.status = 400
        return as_json({"error": "Not an icon name", "reason": "invalid"})
    data = icons.mask(name)
    if data is None:
        bottle.response.status = 404
        return as_json({"error": f"No icon {name}", "reason": "unknown"})
    etag = f'"{icons.mask_rev(name)}"'
    bottle.response.set_header("ETag", etag)
    bottle.response.set_header("Cache-Control", "public, max-age=86400")
    bottle.response.set_header("X-Icon-Size", "20")
    asked = bottle.request.get_header("If-None-Match") or ""
    if asked.strip() == "*" or etag in (tag.strip().replace("W/", "", 1) for tag in asked.split(",")):
        bottle.response.status = 304
        return b""
    bottle.response.content_type = "application/octet-stream"
    return data


def byte_range(body: bytes) -> bytes:
    """`body`, or the part a Range header asks for (206). Safari (iPhone, iPad) plays an <audio> only from a server
    that answers ranges: it asks for bytes 0-1 first, then the rest. The speech cache keeps the repeats cheap."""
    bottle.response.set_header("Accept-Ranges", "bytes")
    header = bottle.request.get_header("Range")
    if not header:
        return body
    ranges = list(bottle.parse_range_header(header, len(body)))
    if not ranges:
        bottle.response.status = 416
        bottle.response.set_header("Content-Range", f"bytes */{len(body)}")
        return b""
    start, end = ranges[0]  # end is exclusive
    bottle.response.status = 206
    bottle.response.set_header("Content-Range", f"bytes {start}-{end - 1}/{len(body)}")
    return body[start:end]


def add_routes(app, services: Services, site):
    leds = LiveLeds(services)
    app.route("/api/status", "GET", lambda: as_json_text(dumps(status(services, site.ip))))
    app.route("/api/version", "GET", lambda: version(services))
    # :path, so a name with a / in it is a 400 here rather than some other route's 404
    app.route("/api/icon/<name:path>", "GET", icon_mask)
    app.route("/api/live", "GET", lambda: as_json_text(live_json(services, leds)))
    app.route(
        "/api/advisories", "GET", lambda: as_json(advisories(services) or bottle.abort(404, "No G-AIRMETs or SIGMETs"))
    )
    app.route("/api/tfrs", "GET", lambda: as_json(tfrs(services) or bottle.abort(404, "No TFRs")))
    app.route(
        "/api/traffic",
        "GET",
        lambda: as_json_text(
            traffic(services, traffic_view(bottle.request.query)) or bottle.abort(404, "No live traffic")
        ),
    )
    app.route("/api/speak", "GET", lambda: as_json(spoken_reports(services)))
    # .audio before the text route: <code> would take "KHOU.audio" too
    app.route("/api/speak/<code>.audio", "GET", lambda code: as_audio(services, code.upper()))
    app.route("/api/speak/<code>", "GET", lambda code: as_text(spoken_report(services, code.upper()), code))
    app.route("/api/atis", "GET", lambda: as_atis_overview(services))
    # .audio before the text route, as for /api/speak
    app.route("/api/atis/<code>.audio", "GET", lambda code: as_atis_audio(services, code.upper()))
    app.route("/api/atis/<code>", "GET", lambda code: as_atis_text(services, code.upper()))
    app.route("/api/atis/<code>/lines", "GET", lambda code: as_atis_transcript(services, code.upper()))
    app.route(
        "/api/metar/<code>",
        "GET",
        lambda code: as_json(metar(services, code.upper()) or bottle.abort(404, f"{code} isn't on the map")),
    )
