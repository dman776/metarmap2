"""
The visualizers: ways of showing METAR data on the LEDs. Each is a module of functions that ends by declaring
itself as VISUALIZER (a visualizer.Visualizer); see visualizer.py.
"""

from metarmap.visualizers import (
    advisories,
    ceiling,
    chase,
    density_altitude,
    flightcategory,
    flightcategory_forecast,
    precipitation,
    pressure,
    rainbow,
    spread,
    temperature,
    tfr,
    visibility,
    wind,
    wind_direction,
    windgusts,
)

from metarmap.visualizers.visualizer import Visualizer

# one look per airport, from its METAR
WEATHER = tuple(
    m.VISUALIZER
    for m in (
        flightcategory,
        wind,
        windgusts,
        wind_direction,
        pressure,
        precipitation,
        temperature,
        visibility,
        density_altitude,
        ceiling,
        spread,
        advisories,
        tfr,
        flightcategory_forecast,
    )
)
# one look for the whole strip
PATTERNS = (rainbow.VISUALIZER, chase.VISUALIZER)

# in the order of the web UI and the API's numbers (/visualizer/<n>). config.json saves ids, so a new visualizer can
# go anywhere in the list
ALL = WEATHER + PATTERNS
BY_ID = {v.id: v for v in ALL}
assert len(BY_ID) == len(ALL), "two visualizers have the same id"


def index_of(key, among=ALL) -> int:
    """
    A visualizer's number in `among` from its id ("wind") or its number ("3", 3), as the API accepts them.
    Raises LookupError if there's no such visualizer.
    """
    if isinstance(key, int) or (isinstance(key, str) and key.isdigit()):
        number = int(key)
        if 0 <= number < len(among):
            return number
    else:
        for number, vis in enumerate(among):
            if vis.id == key:
                return number
    raise LookupError(f"no visualizer {key!r}")


__all__ = ["ALL", "BY_ID", "PATTERNS", "WEATHER", "Visualizer", "index_of"]
