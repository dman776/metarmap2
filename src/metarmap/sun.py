"""
Today's dawn, sunrise, sunset and dusk, and the LED brightness they set.
"""
from metarmap.lib import utils

# the brightness level (a led.brightness setting) that starts at each sun time
LEVEL_AT = {"dawn": "dimmed", "sunrise": "normal", "sunset": "dimmed", "dusk": "off"}


class SunTimes:
    """Today's sun times for the configured city, as {"dawn": datetime, ...}; reload() once a day."""

    def __init__(self, city: str, times=None):
        self.city = city
        self.times = times or {}

    def reload(self):
        self.times = utils.get_sun_times(self.city)


def level_at(now, times):
    """
    Which led.brightness setting is scheduled at `now` (timezone-aware): "dimmed", "normal" or "off".
    times: today's sun times.
    """
    periods = [
        (times['dawn'], times['sunrise'], "dimmed"),
        (times['sunrise'], times['sunset'], "normal"),
        (times['sunset'], times['dusk'], "dimmed"),
    ]
    for start, end, level in periods:
        if start < now < end:
            return level
    return "off"  # night, from dusk until dawn


def brightness_for(now, times, levels):
    """The scheduled LED brightness at `now`. levels: the led.brightness settings."""
    return getattr(levels, level_at(now, times))
