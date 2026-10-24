from lib import safe_logging
import lib.colors as colors_lib
from config import Config


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
    def __init__(self, data, pix, config):
        self.__data__ = data
        self.__pix__ = pix
        self.__config__: Config = config
        self.__effect__ = []
        self.__exclusive__ = False  # used to have exclusive control of renderer (ie. no locate() function!)

    @property
    def exclusive(self):
        return self.__exclusive__

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
        self.__effect__ = []  # clear existing effects
