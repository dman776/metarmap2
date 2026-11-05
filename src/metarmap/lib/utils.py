import logging
from datetime import datetime
import subprocess

log = logging.getLogger(__name__)


def wheel(pos):
    # Input a value 0 to 255 to get a color value.
    # The colours are a transition r - g - b - back to r.
    if pos < 0 or pos > 255:
        r = g = b = 0
    elif pos < 85:
        r = int(pos * 3)
        g = int(255 - pos * 3)
        b = 0
    elif pos < 170:
        pos -= 85
        r = int(255 - pos * 3)
        g = 0
        b = int(pos * 3)
    else:
        pos -= 170
        r = 0
        g = int(pos * 3)
        b = int(255 - pos * 3)
    return r, g, b


def get_location(city):
    """astral's LocationInfo for a city in its list (case doesn't matter), or None."""
    import astral.geocoder

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


def find_in_list(akey, avalue, alist):
    return list(filter(lambda alist: alist[akey] == avalue, alist))


def index_in_list(akey, alist):
    return list(alist.keys()).index(akey)


def get_proportion_between_floats(start: float, current: float, end: float):
    """
    Gets the "distance" (0.0 to 1.0) between the start and the end where the current is.
    IE:
        If the Current is the same as Start, then the result will be 0.0
        If the Current is the same as the End, then the result will be 1.0
        If the Current is halfway between Start and End, then the result will be 0.5
    Arguments:
        start {float} -- The starting temp.
        current {float} -- The temp we want to get the proportion for.
        end {float} -- The end temp to calculate the interpolaton for.
    Returns:
        float -- The amount of interpolaton for Current between Start and End
    """

    total_delta = end - start
    time_in = current - start

    return time_in / total_delta


def celsius_to_fahrenheit(temperature_celsius: float):
    """
    Converts a temperature in celsius to fahrenheit.
    Args:
        temperature_celsius (float): A temperature in C
    Returns:
        [type]: The temperature converted to F
    """
    if temperature_celsius is None:
        return 0

    return (temperature_celsius * (9.0 / 5.0)) + 32.0


def is_pingable(site="www.aviationweather.gov"):
    return subprocess.run(["ping", "-c", "1", site], capture_output=True).returncode
