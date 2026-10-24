"""
What the OLED shows, as plain data. The screen drivers draw it; the web UI mirrors it.

A screen is a dict:
  kind     "airport" (an airport's page) or "message" (startup and other messages)
  airport  the station shown, or None for a message
  title    big text at the top left
  badge    flight category at the top right ("" if none)
  page     1 (wind, visibility, pressure), 2 (temperature, dewpoint, time) or 0 (no data / a message)
  icon     message icon name (messages only)
  lines    three {"icon": name, "text": str} lines
"""
import lib.utils as utils

MISSING = "--"

# icon names used in screens; each driver maps them to its own glyphs
ICON_NAMES = ("wind", "visibility", "pressure", "temp", "dewpoint", "date", "info")


def safe_text(fn, data):
    """
    Runs one line's formatter; a value that can't be shown becomes "--" instead of failing the page.
    """
    try:
        text = fn(data)
        return MISSING if text in (None, "") else str(text)
    except (KeyError, TypeError, ValueError, AttributeError):
        return MISSING


def wind_text(data):
    speed = data.get('windSpeed')
    if not isinstance(speed, int):
        return speed
    if speed <= 0:
        return "CALM"
    wind_dir = str(data.get("windDir", "")).upper()
    wind_dir = "VRB" if wind_dir in ("VRB", "") else "{0:03d}".format(int(wind_dir))
    gust = "G{0:02d}".format(int(data["windGustSpeed"])) if data.get("windGust") else ""
    return "{0}@{1:02d}{2}".format(wind_dir, speed, gust)


def temp_text(celsius):
    if celsius is None:
        return None
    return "{0}\N{DEGREE SIGN}C / {1:.0f}\N{DEGREE SIGN}F".format(celsius, utils.celsius_to_fahrenheit(celsius))


def time_text(obs, tz):
    return "{0} {1}".format(obs.astimezone(tz).strftime("%H:%MC"), obs.strftime("%H:%MZ"))


def screen_for(station, data, page, tz=None):
    """
    What the screen shows for one airport: page 1 (wind, visibility, pressure),
    page 2 (temperature, dewpoint, time) or page 0 (no data).
    """
    if page == 0:
        return {"kind": "airport", "airport": station, "title": station, "badge": "", "page": 0,
                "lines": [{"icon": "", "text": "Data"}, {"icon": "", "text": "Unavailable"}, {"icon": "", "text": ""}]}
    if page == 1:
        lines = [{"icon": "wind", "text": safe_text(wind_text, data)},
                 {"icon": "visibility", "text": safe_text(lambda d: "{0}SM".format(d['vis']), data)},
                 {"icon": "pressure", "text": safe_text(lambda d: "{0:2.2f}".format(d['altimHg']), data)}]
    else:
        lines = [{"icon": "temp", "text": safe_text(lambda d: temp_text(d['tempC']), data)},
                 {"icon": "dewpoint", "text": safe_text(lambda d: temp_text(d['dewpointC']), data)},
                 {"icon": "date", "text": safe_text(lambda d: time_text(d['obsTime'], tz), data)}]
    return {"kind": "airport", "airport": station, "title": station, "badge": data.get("flightCategory") or "",
            "page": page, "lines": lines}


def message_screen(title, icon="", line1="", line2="", line3=""):
    """A message such as "MAP / Starting.."."""
    return {"kind": "message", "airport": None, "title": title, "badge": "", "page": 0, "icon": icon,
            "lines": [{"icon": "", "text": t} for t in (line1, line2, line3)]}


# ---- which airports, which pages -------------------------------------------------------------------------------

def airports_to_show(airports):
    """
    The airports set to show on the OLED, in LED order, as (pixel, code).
    `airports` is the airports.json dict (code -> {"display": bool, ...}).
    """
    return [(pixel, code) for pixel, (code, props) in enumerate(airports.items()) if props.get("display")]


def pages_for(metar):
    """An airport with a report shows pages 1 and 2; one without shows the "Data Unavailable" page."""
    return (1, 2) if metar else (0,)
