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


def brightness_for(now, times, levels):
    """
    The scheduled LED brightness at `now` (timezone-aware).
    times: today's sun times; levels: the led.brightness settings.
    """
    periods = [
        (times['dawn'], times['sunrise'], levels.dimmed),
        (times['sunrise'], times['sunset'], levels.normal),
        (times['sunset'], times['dusk'], levels.dimmed),
    ]
    for start, end, level in periods:
        if start < now < end:
            return level
    return levels.off  # night, from dusk until dawn
