"""
The visualizers: ways of showing METAR data on the LEDs. Each is a module of functions; see visualizer.py.
"""
from metarmap.visualizers import (chase, density_altitude, flightcategory, precipitation, pressure, rainbow,
                                  temperature, visibility, wind, windgusts)

# in the order of the visualizer.active setting and the web UI
ALL = (flightcategory, wind, windgusts, pressure, precipitation, temperature, visibility, density_altitude, rainbow,
       chase)
