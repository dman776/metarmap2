"""
Chase: one blue LED moving along the strip; useful for checking the wiring order.
"""

import metarmap.lib.colors as colors_lib
from metarmap.models import Look
from metarmap.visualizers.visualizer import Visualizer, legend_item

BLUE = colors_lib.color(colors_lib.BLUE)


def legend(settings):
    return [
        legend_item("All LEDs", "Blue, lighting in sequence", BLUE, effect="chase", period=1),
    ]


def strip_look(settings) -> Look:
    # one lit LED, then the rest of the strip dark, so it walks every LED in turn
    return Look.chase(BLUE, step=0.1, size=1, spacing=settings.led.count - 1)


VISUALIZER = Visualizer(
    id="chase",
    name="Chase",
    description="Display a simple chase pattern of BLUE LEDS in sequence. "
    "Runs one complete cycle across all of the LEDs, then repeats.",
    short_name="Chase",
    icon="chase",
    legend=legend,
    strip_look=strip_look,
    covers_virtual=False,  # a wiring check: the virtual airports have no wire, so they stay dark
)
