"""
Wind Direction: colors each airport by the compass direction its wind blows from (as the METAR reports it), in eight
45° sectors. Wind and Wind Gusts show how strong it is.
"""

from typing import Optional

import metarmap.lib.colors as colors_lib
from metarmap.models import Look, Report
from metarmap.visualizers import style
from metarmap.visualizers.visualizer import Visualizer, legend_item


# clockwise from north, 45° each, centered on the heading (north is 338-22°)
SECTORS = [
    ("North", colors_lib.RED, "Red"),
    ("Northeast", colors_lib.ORANGE, "Orange"),
    ("East", colors_lib.YELLOW, "Yellow"),
    ("Southeast", colors_lib.GREEN, "Green"),
    ("South", colors_lib.CYAN, "Cyan"),
    ("Southwest", colors_lib.BLUE, "Blue"),
    ("West", colors_lib.PURPLE, "Purple"),
    ("Northwest", colors_lib.MAGENTA, "Magenta"),
]
CALM = colors_lib.GRAY
VARIABLE = colors_lib.WHITE


def sector(degrees: float) -> int:
    """The SECTORS index for a heading in degrees."""
    return int((degrees % 360 + 22.5) // 45) % 8


def heading(metar: Report):
    """The direction in degrees, "VRB", or None when the report has none."""
    direction = str(metar.wind_dir or "").strip().upper()
    if direction == "VRB":
        return direction
    try:
        return float(direction)
    except ValueError:
        return None


def look(metar: Optional[Report], settings) -> Look:
    if not metar:
        return style.no_report()
    direction = heading(metar)
    if metar.wind_speed == 0 or (direction == 0 and not metar.wind_speed):
        return Look.solid(style.named(CALM)).tagged("Calm")
    if direction == "VRB":
        return Look.pulse(style.named(VARIABLE), period=style.LIGHT_PERIOD, low=style.LIGHT_LOW).tagged("Variable")
    if direction is None:
        return style.missing()
    name, color, _ = SECTORS[sector(direction)]
    return Look.solid(style.named(color)).tagged(name)


def legend(settings):
    items = []
    for i, (name, color, detail) in enumerate(SECTORS):
        low, high = (i * 45 - 22) % 360, i * 45 + 22
        items.append(legend_item(f"From the {name.lower()} ({low}-{high}°)", detail, style.named(color), key=name))
    return [
        *items,
        legend_item("Calm", "Dim white", style.named(CALM)),
        legend_item(
            "Variable",
            "Breathing white",
            style.named(VARIABLE),
            effect="pulse",
            period=style.LIGHT_PERIOD,
            low=style.LIGHT_LOW,
        ),
        style.missing_legend("wind direction"),
        style.no_report_legend(),
    ]


VISUALIZER = Visualizer(
    id="wind_direction",
    name="Wind Direction",
    description="Display the direction the wind blows from: red from the north, then orange, yellow, green, cyan, "
    "blue, purple and magenta around the compass.",
    short_name="Wind Dir",
    icon="compass",
    legend=legend,
    look=look,
    barbs=True,  # the Map page draws each airport's wind barb
)
