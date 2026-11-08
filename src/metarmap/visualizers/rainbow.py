"""
Rainbow: a rainbow across the whole strip; not based on weather.
"""

import metarmap.lib.colors as colors_lib
from metarmap.models import Look
from metarmap.visualizers.visualizer import Visualizer, legend_item


def legend(settings):
    return [
        legend_item(
            "All LEDs",
            "Cycle through the colors of the rainbow",
            *(
                colors_lib.color(n)
                for n in (
                    colors_lib.RED,
                    colors_lib.ORANGE,
                    colors_lib.YELLOW,
                    colors_lib.GREEN,
                    colors_lib.BLUE,
                    colors_lib.PURPLE,
                )
            ),
        ),
    ]


def strip_look(settings) -> Look:
    return Look.rainbow(period=5)


VISUALIZER = Visualizer(
    id="rainbow",
    name="Rainbow",
    description="Display a rainbow pattern across all of the LEDS.",
    short_name="Rainbow",
    icon="rainbow",
    legend=legend,
    strip_look=strip_look,
    covers_virtual=True,  # just colors: the web map's virtual airports join in
)
