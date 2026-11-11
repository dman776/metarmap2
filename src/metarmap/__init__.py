"""MetarMap2: a Raspberry Pi METAR map with NeoPixel LEDs, an OLED screen and a web UI. Run it: python -m metarmap"""

__version__ = "26.11.10"

# who the map is, in every request to aviationweather.gov, the FAA's TFR list and adsb.fi
USER_AGENT = f"metarmap2/{__version__} (+https://github.com/dman776/metarmap2)"
