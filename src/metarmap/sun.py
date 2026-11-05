"""
Today's dawn, sunrise, sunset and dusk, and the LED brightness they set; the configured city (geo.city) they're
for, which also gives the OLED its time zone.
"""

import logging
from datetime import datetime

log = logging.getLogger(__name__)

# the brightness level (a led.brightness setting) that starts at each sun time
LEVEL_AT = {"dawn": "dimmed", "sunrise": "normal", "sunset": "dimmed", "dusk": "off"}


class SunTimes:
    """Today's sun times for the configured city, as {"dawn": datetime, ...}; reload() once a day."""

    def __init__(self, city: str, times=None):
        self.city = city
        self.times = times or {}

    def reload(self):
        self.times = get_sun_times(self.city)


def get_location(city):
    """astral's LocationInfo for a city in its list (case doesn't matter), or None."""
    import astral.geocoder  # here, not at the top: it takes a second to import on a Pi

    try:
        return astral.geocoder.lookup(str(city), astral.geocoder.database())
    except KeyError:
        return None


def get_sun_times(city_name):
    """
    Today's {"dawn", "sunrise", "sunset", "dusk"} (and "noon") for a city in astral's list. geo.city's rule keeps
    config.json's city one it knows; any other raises ValueError.
    """
    import astral.sun

    city = get_location(city_name)
    if city is None:
        raise ValueError(f"{city_name!r} is not a city the sun times know (astral's list)")
    log.info(str(city))
    return astral.sun.sun(city.observer, date=datetime.now().date(), tzinfo=city.timezone)


def level_at(now, times):
    """
    Which led.brightness setting is scheduled at `now` (timezone-aware): "dimmed", "normal" or "off".
    times: today's sun times.
    """
    periods = [
        (times["dawn"], times["sunrise"], "dimmed"),
        (times["sunrise"], times["sunset"], "normal"),
        (times["sunset"], times["dusk"], "dimmed"),
    ]
    for start, end, level in periods:
        if start < now < end:
            return level
    return "off"  # night, from dusk until dawn


def brightness_for(now, times, levels):
    """The scheduled LED brightness at `now`. levels: the led.brightness settings."""
    return getattr(levels, level_at(now, times))


def quiet_hours_active(now, quiet_hours):
    """Whether local wall-clock time falls in the configured blackout interval (start inclusive, end exclusive)."""
    if not quiet_hours.enabled:
        return False
    start, end = quiet_hours.start, quiet_hours.end
    if start == end:
        return False  # equal endpoints are an empty interval, never an all-day blackout
    # Clock.now() is UTC; configured shutdown times use the Pi's local clock.
    # Convert before comparing, including on daylight-saving transitions.
    current = now.astimezone().strftime("%H:%M")
    return start <= current < end if start < end else current >= start or current < end
