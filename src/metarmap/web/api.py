"""
The JSON API: /api/status (used by the Home Assistant integration), /api/live (polled by the Map page) and
/api/traffic (the Map page's live traffic), /api/advisories (the G-AIRMET and SIGMET areas) and /api/tfrs (TFRs).
See API.md; the field names are part of the API.
"""

import json
import time

import bottle

from metarmap import __version__
from metarmap.decode import decode, summary
from metarmap.visualizers import advisories as advisories_vis, tfr as tfr_vis, visualizer, wind_direction
from metarmap.web import views


def status(services, ip):
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
        m = metars.data.get(airport.code, {})
        airports.append(
            {
                "code": airport.code,
                "pixel": index,
                "text": airport.name,
                "display": airport.display,
                "virtual": index >= cfg.led.count,  # on the web map and here only, no LED
                "mock": bool(m.get("mock")),  # a mock METAR (dev_mode) in place of the real one
                "flightCategory": m.get("flightCategory"),
                "raw": m.get("raw"),
                "windDir": m.get("windDir"),
                "windSpeed": m.get("windSpeed"),
                "windGustSpeed": m.get("windGustSpeed"),
                "vis": m.get("vis"),
                "obs": m.get("obs"),
                "tempC": m.get("tempC"),
                "dewpointC": m.get("dewpointC"),
                "altimHg": m.get("altimHg"),
                "lightning": m.get("lightning"),
                "obsTime": iso(m.get("obsTime")),
            }
        )

    return {
        "version": __version__,
        "ip": ip,
        "brightness": services.renderer.pixels().brightness,
        "visualizer": {
            "active": active_num,
            "name": active_vis.NAME,
            "exclusive": active_vis.EXCLUSIVE,
            "description": active_vis.DESCRIPTION,
            "legend": visualizer.legend(active_vis, cfg),
        },
        "visualizers": [
            {"index": i, "name": v.NAME, "exclusive": v.EXCLUSIVE} for i, v in enumerate(services.renderer.visualizers)
        ],
        "config": {
            "visualizer.active": cfg.visualizer.active,
            "visualizer.auto_rotate.enabled": cfg.visualizer.auto_rotate.enabled,
            "visualizer.auto_rotate.delay_seconds": cfg.visualizer.auto_rotate.delay_seconds,
            "visualizer.auto_rotate.skip": cfg.visualizer.auto_rotate.skip,
            "visualizer.missing_data_blink": cfg.visualizer.missing_data_blink,
            "visualizer.estimated_category_breathing": cfg.visualizer.estimated_category_breathing,
            "lightning.animation": cfg.lightning.animation,
            "lightning.color": cfg.lightning.color,
            "display_screen.enabled": cfg.display_screen.enabled,
            "display_screen.locate_active": cfg.display_screen.locate_active,
            "display_screen.delay": cfg.display_screen.delay,
            "led.inittest": cfg.led.inittest,
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
        "build": getattr(getattr(services, "releases", None), "build", None),
        "update": update_state(services),
        "lastFetchTime": iso(metars.lastFetchTime),
        "missingStations": metars.missing_stations(),
        "airports": airports,
    }


def update_state(services):
    """What's newest on GitHub (see metarmap.releases); null for a map without the check."""
    releases = getattr(services, "releases", None)
    if releases is None:
        return None
    state = releases.state()
    return {
        **{k: v for k, v in state.items() if k not in ("badge", "releases", "build")},
        "releases": [r["tag"] for r in state["releases"]],
    }


def wind_barb(metar):
    """An airport's wind for its barb on the Map page: {"dir": degrees, "kt": speed}, or None when calm or variable."""
    direction = wind_direction.heading(metar)
    speed = metar.get("windSpeed")
    if not isinstance(direction, float) or not speed:
        return None
    return {"dir": direction, "kt": speed}


def auto_rotate(services):
    """Auto-rotate: whether it's on, its delay, and when it next changes the visualizer (Unix time; None when off)."""
    rotate = services.config.data.visualizer.auto_rotate
    scheduler = getattr(services, "scheduler", None)
    runs = [j.next_run for j in scheduler.get_jobs("rotate_visualizer")] if scheduler is not None else []
    runs = [r for r in runs if r is not None]
    return {
        "enabled": rotate.enabled,
        "seconds": rotate.delay_seconds,
        "next": min(runs).timestamp() if runs else None,  # schedule's times are the map's local time
    }


def live(services, now=None):
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
    barbs = visualizer.shows_barbs(active_vis)
    leds = []
    for s in views.stations(
        services.config.airports,
        services.metars.data,
        getattr(services.metars, "position", None),
        services.config.data.led.count,
    ):
        m = services.metars.data.get(s["code"]) or {}
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
                "lightning": m.get("lightning", False),
                "look": led_looks.get(s["pixel"], {"effect": "off", "colors": []}),
                "wind": wind_barb(m) if barbs else None,
            }
        )
    return {
        "now": now if now is not None else time.time(),
        "brightness": renderer.pixels().brightness,
        "visualizer": {
            "active": active_num,
            "name": active_vis.NAME,
            "exclusive": active_vis.EXCLUSIVE,
            "areas": visualizer.shows_areas(active_vis),
            "autoRotate": auto_rotate(services),
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


def metar(services, code):
    """
    One airport's METAR, raw and decoded (the Map page's popup). None if the airport isn't on the map.
    """
    if code not in {a.code for a in services.config.airports if a.code}:
        return None
    m = services.metars.data.get(code) or {}
    obs = m.get("obsTime")
    return {
        "code": code,
        "raw": m.get("raw"),
        "mock": bool(m.get("mock")),
        "flightCategory": m.get("flightCategory"),
        "obsTime": obs.isoformat() if obs else None,
        "decoded": decode(m),
        "summary": summary(m),
    }


def traffic(services):
    """Live traffic around the airports (see metarmap.traffic); None for a map without it."""
    found = getattr(services, "traffic", None)
    return found.snapshot() if found is not None else None


def advisories(services):
    """The G-AIRMET and SIGMET areas below 18,000 ft (metarmap.advisories), each with its color, for the Map page."""
    found = getattr(services, "advisories", None)
    if found is None:
        return None
    state = found.state()
    state["areas"] = [{**area, "color": advisories_vis.css(area["hazard"], area["kind"])} for area in state["areas"]]
    return state


def tfrs(services):
    """The TFRs in effect or starting within 24 hours (metarmap.tfr), each with its type's color, for the Map page."""
    found = getattr(services, "tfrs", None)
    if found is None:
        return None
    state = found.state()
    state["areas"] = [{**area, "color": tfr_vis.css(area["type"])} for area in state["areas"]]
    return state


def as_json(data):
    bottle.response.content_type = "application/json"
    return json.dumps(data)


def add_routes(app, services, site):
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
