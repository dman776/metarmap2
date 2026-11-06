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
            "exclusive": active_vis.exclusive,
            "description": active_vis.description,
            "legend": services.renderer.legend(),
        },
        "visualizers": [
            {"index": i, "id": v.id, "name": v.name, "exclusive": v.exclusive}
            for i, v in enumerate(services.renderer.visualizers)
        ],
        "config": {
            "visualizer.active": cfg.visualizer.active,
            "visualizer.auto_rotate.enabled": cfg.visualizer.auto_rotate.enabled,
            "visualizer.auto_rotate.delay_seconds": cfg.visualizer.auto_rotate.delay_seconds,
            "visualizer.auto_rotate.skip": cfg.visualizer.auto_rotate.skip,
            "visualizer.missing_data_blink": cfg.visualizer.missing_data_blink,
            "visualizer.estimated_category_breathing": cfg.visualizer.estimated_category_breathing,
            "visualizer.legend_in_use_only": cfg.visualizer.legend_in_use_only,
            "lightning.animation": cfg.lightning.animation,
            "lightning.color": cfg.lightning.color,
            "display_screen.enabled": cfg.display_screen.enabled,
            "display_screen.locate_active": cfg.display_screen.locate_active,
            "display_screen.delay": cfg.display_screen.delay,
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
    return {"enabled": rotate.enabled, "seconds": rotate.delay_seconds, "next": next_rotation(services)}


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
            }
        )
    return {
        "now": now if now is not None else time.time(),
        "brightness": renderer.pixels().brightness,
        "visualizer": {
            "active": active_num,
            "id": active_vis.id,
            "name": active_vis.name,
            "exclusive": active_vis.exclusive,
            "areas": active_vis.areas,
            "autoRotate": auto_rotate(services),
            # the legend entries (keys) the LEDs show now, null for a whole-strip look; the pages hide the others when
            # legendInUseOnly (visualizer.legend_in_use_only)
            "legendInUse": renderer.legend_in_use(),
            "legendInUseOnly": services.config.data.visualizer.legend_in_use_only,
        },
        "strip": strip,
        "leds": leds,
        "locate": renderer.last_locate,
        "display": {
            "enabled": display is not None,
            "on": bool(display and display.on),
            "screen": display.screen if display else None,
        },
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


def add_routes(app, services: "App", site):
    app.route("/api/status", "GET", lambda: as_json(status(services, site.ip)))
    app.route("/api/live", "GET", lambda: as_json(live(services)))
    app.route(
        "/api/advisories", "GET", lambda: as_json(advisories(services) or bottle.abort(404, "No G-AIRMETs or SIGMETs"))
    )
    app.route("/api/tfrs", "GET", lambda: as_json(tfrs(services) or bottle.abort(404, "No TFRs")))
    app.route("/api/traffic", "GET", lambda: as_json(traffic(services) or bottle.abort(404, "No live traffic")))
    app.route(
        "/api/metar/<code>",
        "GET",
        lambda code: as_json(metar(services, code.upper()) or bottle.abort(404, f"{code} isn't on the map")),
    )
