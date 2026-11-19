"""
A visualizer legend entry (legend_item): what one LED color or effect means, shown in the web UI.
"""

import metarmap.lib.colors as colors_lib


def legend_item(label, detail, *colors, effect="solid", period=None, low=None, key=None):
    """
    One entry of a visualizer legend, shown in the web UI.
    Args:
        label (str): what the entry represents (ie. "VFR", "5-10 kts")
        detail (str): how the LED looks (ie. "Green", "Purple to blue")
        colors: (green, red, blue) colors (lib/colors.py); two or more are drawn as a gradient. None/empty = LED off
        effect (str): solid, blink, pulse, flash (first color with flashes of the second), alternate (two colors in
            turn), chase or off
        period (float): seconds per blink/pulse cycle, if any
        low (float): a pulse's dimmest point (0.3: never dark)
        key (str): what a Look's legend names this entry by (Look.tagged); the label unless that changes with the
            settings or is shared by several visualizers (style.MISSING, ...)
    """
    css = [colors_lib.to_css(c) for c in colors if c is not None]
    return {
        "key": key if key is not None else label,
        "label": label,
        "detail": detail,
        "colors": css,
        "effect": effect if css else "off",
        "period": period,
        "low": low,
    }
