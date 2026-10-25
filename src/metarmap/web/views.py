"""
What the pages and API responses show, as plain data built from the map's parts. No bottle here.
"""
import json
import os
from datetime import datetime

from metarmap.sun import LEVEL_AT

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

def stations(airports, data):
    """
    One entry per airport (in LED order, skipping NULL placeholders) for the templates.
    airports: config.airports; data: metars.data
    """
    result = []
    for pixel, (code, props) in enumerate(airports.items()):
        if "NULL" in code:
            continue
        m = data.get(code) or {}
        text = props.get("text")
        result.append({
            "code": code,
            "pixel": pixel,
            "name": text if isinstance(text, str) else "",
            "display": props.get("display", False),
            "has_data": bool(m),
            "cat": m.get("flightCategory") or None,
            "raw": m.get("raw"),
            "obsTime": m.get("obsTime"),
            "lat": m.get("latitude"),
            "lon": m.get("longitude"),
        })
    return result


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
    return {"index": index, "name": vis.name, "description": vis.description, "exclusive": vis.exclusive,
            "legend": vis.legend}


def visualizer_names(renderer):
    return [v.name for v in renderer.visualizers]


# ---- brightness schedule -------------------------------------------------------------------------------------

def sun_schedule(times, levels, now=None):
    """
    Today's brightness schedule, with the next change flagged.
    times: today's sun times; levels: the led.brightness settings.
    """
    if not times:
        return []
    schedule = [{"name": name.capitalize(), "time": times[name], "level": getattr(levels, level), "next": False}
                for name, level in LEVEL_AT.items()]
    now = now or datetime.now(schedule[0]["time"].tzinfo)
    upcoming = [s for s in schedule if s["time"] > now]
    if upcoming:
        upcoming[0]["next"] = True
    return schedule


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
