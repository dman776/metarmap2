"""
Rainbow: a rainbow across the whole strip; not based on weather.
"""
import metarmap.lib.colors as colors_lib
from metarmap.models import Look
from metarmap.visualizers.visualizer import legend_item

NAME = "Rainbow"
DESCRIPTION = "Display a rainbow pattern across all of the LEDS."
EXCLUSIVE = True


def legend(settings):
    c = colors_lib.get_colors()
    return [
        legend_item("All LEDs", "Cycle through the colors of the rainbow",
                    *(c[n] for n in (colors_lib.RED, colors_lib.ORANGE, colors_lib.YELLOW,
                                     colors_lib.GREEN, colors_lib.BLUE, colors_lib.PURPLE))),
    ]


def strip_look(settings) -> Look:
    return Look.rainbow(period=5)
