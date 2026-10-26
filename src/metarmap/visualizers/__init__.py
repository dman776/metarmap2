"""
The visualizers: ways of showing METAR data on the LEDs. Each is a module of functions; see visualizer.py.
"""
from metarmap.visualizers import (ceiling, chase, density_altitude, flightcategory, precipitation, pressure, rainbow,
                                  spread, temperature, visibility, wind, windgusts)

# in the order of the visualizer.active setting and the web UI (new ones go at the end, so the numbers stay)
ALL = (flightcategory, wind, windgusts, pressure, precipitation, temperature, visibility, density_altitude, rainbow,
       chase, ceiling, spread)
