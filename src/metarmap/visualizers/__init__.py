"""
The visualizers: ways of showing METAR data on the LEDs. Each is a module of functions; see visualizer.py.
"""
from metarmap.visualizers import (ceiling, chase, density_altitude, flightcategory, precipitation, pressure, rainbow,
                                  spread, temperature, visibility, wind, windgusts)

# one look per airport, from its METAR; new ones go at the end of these
WEATHER = (flightcategory, wind, windgusts, pressure, precipitation, temperature, visibility, density_altitude, ceiling,
           spread)
# one look for the whole strip; always last
PATTERNS = (rainbow, chase)

# in the order of the visualizer.active setting and the web UI
ALL = WEATHER + PATTERNS
