"""
The JSON API: /api/status (used by the Home Assistant integration), /api/live (polled by the Map page) and
/api/traffic (the Map page's live traffic), /api/advisories (the G-AIRMET and SIGMET areas) and /api/tfrs (TFRs).
See API.md; the field names are part of the API.
"""

import json
import time
from typing import TYPE_CHECKING, Optional

import bottle

from metarmap import __version__
from metarmap.decode import decode, summary
from metarmap.models import Report
from metarmap.atis import AtisError
from metarmap.atis_spoken import for_airport, lines as atis_lines
from metarmap.speech import SpeechError, configured
from metarmap.spoken import spoken
from metarmap.visualizers import advisories as advisories_vis, tfr as tfr_vis, wind_direction
from metarmap.web import views

if TYPE_CHECKING:  # app.py imports the web, so only for the type checker
    from metarmap.app import App

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


def status(services: "App", ip):
    """
    Read-only snapshot of the map state.
    """

    def iso(dt):
        return dt.isoformat() if dt is not None else None

    cfg = services.config.data
    metars = services.metars
    active_num, active_vis = services.renderer.visualizer
    suntimes = services.sun.times or {}

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

    return {
        "version": __version__,
        "ip": ip,
        "brightness": services.renderer.pixels().brightness,
        "visualizer": {
            "active": active_num,
            "id": active_vis.id,
            "name": active_vis.name,
            "shortName": active_vis.short_name,
            "icon": active_vis.icon,
            "exclusive": active_vis.exclusive,
            "description": active_vis.description,
            "legend": services.renderer.legend(),
        },
        "visualizers": [
            {
                "index": i,
                "id": v.id,
                "name": v.name,
                "shortName": v.short_name,
                "icon": v.icon,
                "exclusive": v.exclusive,
                "skipped": v.id in cfg.visualizer.auto_rotate.skip,  # left out of auto-rotate
            }
            for i, v in enumerate(services.renderer.visualizers)
        ],
        "config": {
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
        },
        "display": {"enabled": cfg.display_screen.enabled, "on": cfg.display_screen.enabled and services.display.on},
        "suntimes": {k: iso(suntimes.get(k)) for k in ("dawn", "sunrise", "sunset", "dusk")},
        "build": services.releases.build if services.releases else None,
        "update": update_state(services),
        "lastFetchTime": iso(metars.lastFetchTime),
        "missingStations": metars.missing_stations(),
        "airports": airports,
    }


def update_state(services: "App"):
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


def auto_rotate(services: "App"):
    """Auto-rotate: whether it's on, its delay, and when it next changes the visualizer (Unix time; None when off)."""
    from metarmap.app import next_rotation  # here: app.py imports the web

    rotate = services.config.data.visualizer.auto_rotate
    return {
        "enabled": rotate.enabled,
        "seconds": rotate.delay_seconds,
        "next": next_rotation(services),
        "skip": list(rotate.skip),  # the ids it leaves out (visualizer.auto_rotate.skip)
    }


def fetch_schedule(services: "App"):
    """When METARs are next fetched, that wait's length, and when they were last fetched (Unix times)."""
    from metarmap.app import next_fetch  # here: app.py imports the web

    return next_fetch(services)


def live(services: "App", now=None):
    """
    What the physical map is doing right now: every LED's effect, the OLED screen and the last locate pulse.
    """

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    renderer = services.renderer
    led_looks, strip = renderer.led_states()
    active_num, active_vis = renderer.visualizer
    display = services.display if services.config.data.display_screen.enabled else None
    barbs = active_vis.barbs
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
    return {
        "now": now if now is not None else time.time(),
        "brightness": renderer.pixels().brightness,
        "visualizer": {
            "active": active_num,
            "id": active_vis.id,
            "name": active_vis.name,
            "shortName": active_vis.short_name,
            "icon": active_vis.icon,
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
        "speech": services.speech is not None and configured(services.config.data.speech),
    }


def metar(services: "App", code):
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
    }


def spoken_report(services: "App", code):
    """One airport's METAR as text to be read aloud (see metarmap.spoken); None if the airport isn't on the map."""
    airports = {a.code: a for a in services.config.airports if a.code}
    if code not in airports:
        return None
    m = services.metars.data.get(code)
    tunings = for_airport(services.config.data.speech.tunings, code)
    return spoken(m, airports[code].name or (m.name if m else ""), code, tunings)


def atis_airports(services: "App"):
    """The map's airports with a spoken ATIS to ask for: speech on with a server, speech.atis on, and a D-ATIS."""
    atis = services.atis
    if atis is None or services.speech is None or not configured(services.config.data.speech):
        return set()
    return atis.available()


def atis_transcript(services: "App", code):
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


def atis_report(services: "App", code):
    """One airport's ATIS as text to be read aloud (see metarmap.atis_spoken). Raises AtisError."""
    return " ".join(line["said"] for line in atis_transcript(services, code)["lines"] if line["said"])


def atis_overview(services: "App"):
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


def spoken_reports(services: "App"):
    """Every airport's spoken METAR, {code: text}, in the map's order."""
    return {a.code: spoken_report(services, a.code) for a in services.config.airports if a.code}


def traffic(services: "App"):
    """Live traffic around the airports (see metarmap.traffic); None for a map without it."""
    found = services.traffic
    return found.snapshot() if found is not None else None


def advisories(services: "App"):
    """The G-AIRMET and SIGMET areas below 18,000 ft (metarmap.advisories), each with its color, for the Map page."""
    found = services.advisories
    if found is None:
        return None
    state = found.state()
    state["areas"] = [{**area, "color": advisories_vis.css(area["hazard"], area["kind"])} for area in state["areas"]]
    return state


def tfrs(services: "App"):
    """The TFRs in effect or starting within 24 hours (metarmap.tfr), each with its type's color, for the Map page."""
    found = services.tfrs
    if found is None:
        return None
    state = found.state()
    state["areas"] = [{**area, "color": tfr_vis.css(area["type"])} for area in state["areas"]]
    return state


def as_json(data):
    bottle.response.content_type = "application/json"
    return json.dumps(data)


def as_text(text, code):
    """A plain-text answer (404 when `text` is None: the airport isn't on the map)."""
    if text is None:
        bottle.abort(404, f"{code} isn't on the map")
    bottle.response.content_type = "text/plain; charset=utf-8"
    return text


def as_audio(services: "App", code):
    """An airport's METAR read aloud (WAV), by the speech server (speech.engine: Piper over Wyoming, or Kokoro). 404:
    not on the map; 503: no server is set; 502: the server failed or couldn't be reached. Errors are plain text."""
    text = spoken_report(services, code)
    if text is None:
        bottle.abort(404, f"{code} isn't on the map")
    speech = services.speech
    if speech is None:
        bottle.abort(503, "This map has no speech")
    try:
        clip = speech.audio(text)
    except SpeechError as e:
        return as_error(e)
    bottle.response.content_type = "audio/wav"
    bottle.response.set_header("Cache-Control", "no-store")  # the next METAR says something else
    return byte_range(clip)


# the most a Pronunciation page's Play reads: a tuning says at most 120 characters
SAY_MAX = 200


def as_said_audio(services: "App", text: str):
    """
    Some words read aloud (WAV), as the speech server says them: the Pronunciation page's Play beside a tuning, to
    hear a "say it as" before saving it. 400: no words, or too many; 503 and 502 as for as_audio().
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
        clip = speech.audio(text)
    except SpeechError as e:
        return as_error(e)
    bottle.response.content_type = "audio/wav"
    return byte_range(clip)


def as_error(e):
    """A SpeechError's or AtisError's message as a plain-text answer, with its status."""
    bottle.response.status = e.status
    bottle.response.content_type = "text/plain; charset=utf-8"
    return str(e)


def as_atis_text(services: "App", code):
    try:
        text = atis_report(services, code)
    except AtisError as e:
        return as_error(e)
    bottle.response.content_type = "text/plain; charset=utf-8"
    return text


def as_atis_audio(services: "App", code):
    """An airport's ATIS read aloud (WAV), by the speech server. 404: not on the map, or no ATIS; 503: speech or
    spoken ATIS is off; 502: atis.info or the speech server failed. Errors are plain text."""
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


def as_atis_transcript(services: "App", code):
    try:
        return as_json(atis_transcript(services, code))
    except AtisError as e:
        return as_error(e)


def as_atis_overview(services: "App"):
    try:
        return as_json(atis_overview(services))
    except AtisError as e:
        return as_error(e)


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


def add_routes(app, services: "App", site):
    app.route("/api/status", "GET", lambda: as_json(status(services, site.ip)))
    app.route("/api/live", "GET", lambda: as_json(live(services)))
    app.route(
        "/api/advisories", "GET", lambda: as_json(advisories(services) or bottle.abort(404, "No G-AIRMETs or SIGMETs"))
    )
    app.route("/api/tfrs", "GET", lambda: as_json(tfrs(services) or bottle.abort(404, "No TFRs")))
    app.route("/api/traffic", "GET", lambda: as_json(traffic(services) or bottle.abort(404, "No live traffic")))
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
