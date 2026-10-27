"""
Chase: one blue LED moving along the strip; useful for checking the wiring order.
"""
import metarmap.lib.colors as colors_lib
from metarmap.models import Look
from metarmap.visualizers.visualizer import legend_item

NAME = "Chase"
DESCRIPTION = ("Display a simple chase pattern of BLUE LEDS in sequence. "
               "Runs one complete cycle across all of the LEDs, then repeats.")
EXCLUSIVE = True
COVERS_VIRTUAL = False  # a wiring check: the virtual airports have no wire, so they stay dark


def legend(settings):
    c = colors_lib.get_colors()
    return [
        legend_item("All LEDs", "Blue, lighting in sequence", c[colors_lib.BLUE], effect="chase", period=1),
    ]


def strip_look(settings) -> Look:
    # one lit LED, then the rest of the strip dark, so it walks every LED in turn
    return Look.chase([0, 0, 255], step=0.1, size=1, spacing=settings.led.count - 1)
