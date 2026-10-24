"""
Module to handle a chase pattern
"""
import lib.colors as colors_lib
from metarmap.models import Look
from visualizers.visualizer import Visualizer, legend_item


class Chase(Visualizer):
    """
    One blue LED moving along the strip; useful for checking the wiring order.
    """
    name = "Chase"
    description = ("Display a simple chase pattern of BLUE LEDS in sequence. "
                   "Runs one complete cycle across all of the LEDs, then repeats.")
    exclusive = True

    @property
    def legend(self):
        c = colors_lib.get_colors()
        return [
            legend_item("All LEDs", "Blue, lighting in sequence", c[colors_lib.BLUE], effect="chase", period=1),
        ]

    def strip_look(self) -> Look:
        # one lit LED, then the rest of the strip dark, so it walks every LED in turn
        return Look.chase([0, 0, 255], step=0.1, size=1, spacing=self.settings.led.count - 1)
