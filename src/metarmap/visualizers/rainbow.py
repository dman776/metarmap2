"""
Module to handle a rainbow pattern
"""
import metarmap.lib.colors as colors_lib
from metarmap.models import Look
from metarmap.visualizers.visualizer import Visualizer, legend_item


class Rainbow(Visualizer):
    """
    A rainbow across the whole strip; not based on weather.
    """
    name = "Rainbow"
    description = "Display a rainbow pattern across all of the LEDS."
    exclusive = True

    @property
    def legend(self):
        c = colors_lib.get_colors()
        return [
            legend_item("All LEDs", "Cycle through the colors of the rainbow",
                        *(c[n] for n in (colors_lib.RED, colors_lib.ORANGE, colors_lib.YELLOW,
                                         colors_lib.GREEN, colors_lib.BLUE, colors_lib.PURPLE))),
        ]

    def strip_look(self) -> Look:
        return Look.rainbow(period=5)
