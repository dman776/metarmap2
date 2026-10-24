from typing import List, Optional

from lib import safe_logging
import lib.colors as colors_lib
from metarmap.animations import animation_for
from metarmap.models import Look, Metar


def legend_item(label, detail, *colors, effect="solid", period=None):
    """
    One entry of a visualizer legend, shown in the web UI.
    Args:
        label (str): what the entry represents (ie. "VFR", "5-10 kts")
        detail (str): how the LED looks (ie. "Green", "Purple to blue")
        colors: GRB colors; two or more colors are drawn as a gradient. None/empty = LED off
        effect (str): solid, blink, pulse, flash (first color with flashes of the second), chase or off
        period (float): seconds per blink/pulse cycle, if any
    """
    css = [colors_lib.to_css(c) for c in colors if c is not None]
    return {
        "label": label,
        "detail": detail,
        "colors": css,
        "effect": effect if css else "off",
        "period": period,
    }


class Visualizer(object):
    """
    A way of showing METAR data on the map.

    Subclasses decide how each airport's LED looks, from its METAR, by overriding look() (or strip_look() to drive
    the whole strip). That part is pure and testable. This base class turns the looks into LED animations.
    """
    name = ""
    description = ""
    exclusive = False  # True: the visualizer has the whole strip, so locate() is ignored

    def __init__(self, data, pix, config):
        self.__data__ = data
        self.__pix__ = pix
        self.__config__ = config
        self.__effect__ = []

    @property
    def settings(self):
        return self.__config__.data

    def look(self, metar: Metar) -> Look:
        """How one airport's LED looks. metar is {} when the airport has no report."""
        return Look.off()

    def strip_look(self) -> Optional[Look]:
        """A look for the whole strip instead of one per airport (rainbow, chase); None for per-airport looks."""
        return None

    def looks(self, data) -> List[Look]:
        """One look per LED, in airport order. NULL airports are placeholders and stay dark."""
        return [Look.off() if "NULL" in code else self.look(metar or {}) for code, metar in data.items()]

    @property
    def legend(self):
        """
        List of legend_item() entries describing what the LEDs mean.
        """
        return []

    def get_effects(self):
        return self.__effect__

    def update_data(self, data):
        safe_logging.safe_log("[v]updating data in the visualizer ({0})".format(self.name))
        self.__data__ = data
        strip = self.strip_look()
        if strip is not None:
            self.__effect__ = [animation_for(strip, self.__pix__)]
        else:
            self.__effect__ = [animation_for(look, self.__pix__[i]) for i, look in enumerate(self.looks(data))]
