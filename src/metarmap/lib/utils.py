"""Small helpers: the sun times and time zone of the configured city, Celsius to Fahrenheit, and a ping."""

import logging
from datetime import datetime
import subprocess

log = logging.getLogger(__name__)


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
