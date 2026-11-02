"""
What the pages and API responses show, as plain data built from the map's parts. No bottle here.
"""

import json
import os
from datetime import datetime

from metarmap.metar import mock_text
from metarmap.sun import LEVEL_AT, brightness_for, night_off_active
from metarmap.visualizers.visualizer import info as visualizer_info

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
CATEGORIES = ("VFR", "MVFR", "IFR", "LIFR")
BELOW_VFR = ("LIFR", "IFR", "MVFR")  # worst first

# FAA AIS tile services: (service name, label, lowest zoom level the FAA has tiles for); all stop at 12
CHART_TYPES = {
    "sectional": ("VFR_Sectional", "VFR Sectional", 8),
    "terminal": ("VFR_Terminal", "VFR Terminal Area", 10),
    "ifr_low": ("IFR_AreaLow", "IFR Enroute Low", 7),
}


def load_sectionals():
    with open(os.path.join(STATIC_DIR, "sectionals.json")) as f:
        return json.load(f)["charts"]


def is_login(web_server, user, password):
    """Whether user/password match the web_server settings (the user name ignores case)."""
    return user.lower() == web_server.user and password == web_server.password


# ---- airports ------------------------------------------------------------------------------------------------


def stations(airports, data, position=None, count=None):
    """
    One entry per airport (in LED order, skipping LEDs with no airport) for the templates.
    airports: config.airports; data: metars.data;
    position: code -> (lat, lon) or None (metars.position), for airports without a report;
    count: led.count, the airports on the strip; the ones after it are virtual (web map and Home Assistant only)
    """
    result = []
    for pixel, airport in enumerate(airports):
        if not airport.code:
            continue
        m = data.get(airport.code) or {}
        lat, lon = m.get("latitude"), m.get("longitude")
        if not (lat and lon) and position:
            lat, lon = position(airport.code) or (None, None)
        result.append(
            {
                "code": airport.code,
                "pixel": pixel,
                "mock": bool(m.get("mock")),  # a mock METAR (dev_mode) in place of the real one
                "name": airport.name,
                "display": airport.display,
                "virtual": count is not None and pixel >= count,
                "has_data": bool(m),
                "cat": m.get("flightCategory") or None,
                "raw": m.get("raw"),
                "obsTime": m.get("obsTime"),
                "lat": lat,
                "lon": lon,
            }
        )
    return result


def leds(airports, count):
    """
    Every LED for the Airports page, with its airport (code "" for none), then the virtual airports after led.count.
    """
    return [
        {
            "pixel": pixel,
            "code": a.code,
            "name": a.name,
            "display": a.display,
            "virtual": pixel >= count,
            "mock": mock_text(a),
        }
        for pixel, a in enumerate(airports)
    ]


def summary(stations):
    """The home page's tiles: airports per flight category, those without one, and those below VFR (worst first)."""
    return {
        "counts": {c: len([s for s in stations if s["cat"] == c]) for c in CATEGORIES},
        "no_data": [s["code"] for s in stations if s["cat"] not in CATEGORIES],
        "below_vfr": sorted([s for s in stations if s["cat"] in BELOW_VFR], key=lambda s: BELOW_VFR.index(s["cat"])),
    }


# ---- visualizers ---------------------------------------------------------------------------------------------


def visualizer(renderer):
    """The active visualizer."""
    index, vis = renderer.visualizer
    return {"index": index, **visualizer_info(vis, renderer.config.data)}


def visualizer_names(renderer):
    return [v.NAME for v in renderer.visualizers]


def visualizer_choices(renderer):
    """Every visualizer with what the Remote page shows when it's picked, before its legend loads."""
    return [{"name": v.NAME, "description": v.DESCRIPTION, "exclusive": v.EXCLUSIVE} for v in renderer.visualizers]


def rotation(renderer, skip):
    """The visualizers with whether auto-rotate shows each (exclusive ones are never shown)."""
    return [{"name": v.NAME, "exclusive": v.EXCLUSIVE, "shown": v.NAME not in skip} for v in renderer.visualizers]


# ---- brightness schedule -------------------------------------------------------------------------------------


def sun_schedule(times, levels, now=None):
    """
    Today's brightness schedule, with the next change flagged.
    times: today's sun times; levels: the led.brightness settings.
    """
    if not times:
        return []
    schedule = [
        {"name": name.capitalize(), "time": times[name], "level": getattr(levels, level), "next": False}
        for name, level in LEVEL_AT.items()
    ]
    now = now or datetime.now(schedule[0]["time"].tzinfo)
    upcoming = [s for s in schedule if s["time"] > now]
    if upcoming:
        upcoming[0]["next"] = True
    return schedule


# ---- map page ------------------------------------------------------------------------------------------------

def brightness_schedule(times, levels, night_off, now=None):
    """Today's brightness events with the CURRENT scheduled mode highlighted.

    A sun event during a blackout is displayed at 0%, but doesn't become
    the current mode: the Night off row remains highlighted until resume.
    """
    if not times:
        return []
    tz = next(iter(times.values())).tzinfo
    now = now.astimezone(tz) if now is not None else datetime.now(tz)
    schedule = [{"name": name.capitalize(), "time": times[name], "level": getattr(levels, level), "next": False}
                for name, level in LEVEL_AT.items()]
    elapsed_sun = [event for event in schedule if event["time"] <= now]
    current_sun = max(elapsed_sun, key=lambda event: event["time"]) if elapsed_sun else schedule[-1]
    current_sun["next"] = True
    if not night_off.enabled or night_off.start == night_off.end:
        return schedule

    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_h, start_m = map(int, night_off.start.split(":"))
    end_h, end_m = map(int, night_off.end.split(":"))

    for event in schedule:
        if night_off_active(event["time"], night_off):
            event["level"] = 0.0
        event["next"] = False

    begins = midnight.replace(hour=start_h, minute=start_m)
    ends = midnight.replace(hour=end_h, minute=end_m)
    schedule.append({"name": "Night off", "time": begins, "level": 0.0,
                     "next": False, "night_event": True})
    schedule.append({"name": "Resume schedule", "time": ends,
                     "level": brightness_for(ends, times, levels),
                     "next": False, "night_event": True})

    if night_off_active(now, night_off):
        current = next(event for event in schedule if event["name"] == "Night off")
    else:
        # Ignore blackout-suppressed sun events and Night off itself when
        # choosing the currently active non-blackout brightness mode.
        elapsed = [event for event in schedule
                   if event["time"] <= now and event["name"] != "Night off"
                   and (event["name"] == "Resume schedule"
                        or not night_off_active(event["time"], night_off))]
        current = max(elapsed, key=lambda event: event["time"]) if elapsed else schedule[3]
    current["next"] = True
    return sorted(schedule, key=lambda event: event["time"])


# ---- map page ------------------------------------------------------------------------------------------------

def map_settings(m, sectionals, stations):
    """
    Map page settings from config.json (geo.map), with defaults for older config files.
    """
    chart = getattr(m, "chart", None)
    if not any(c["name"] == chart for c in sectionals):
        chart = chart_for_airports(sectionals, stations)
    chart_type = getattr(m, "chart_type", "sectional")
    if chart_type not in CHART_TYPES:
        chart_type = "sectional"
    return {
        "background": getattr(m, "background", "sectional"),
        "chart_type": chart_type,
        "chart_service": CHART_TYPES[chart_type][0],
        "chart_label": CHART_TYPES[chart_type][1],
        "chart_min_zoom": CHART_TYPES[chart_type][2],
        "chart": chart,
        "chart_bounds": next((c for c in sectionals if c["name"] == chart), None),
        "view": getattr(m, "view", "airports"),
        "center": list(m.center),
        "zoom": m.zoom,
    }


def chart_for_airports(sectionals, stations):
    """
    The sectional that covers the most airports, used when none is configured.
    """
    points = [(float(s["lat"]), float(s["lon"])) for s in stations if s["lat"] and s["lon"]]

    def covered(c):
        return sum(1 for lat, lon in points if c["south"] <= lat <= c["north"] and c["west"] <= lon <= c["east"])

    best = max(sectionals, key=covered)
    return best["name"] if covered(best) else None
