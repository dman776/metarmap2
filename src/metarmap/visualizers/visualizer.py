from typing import List, Optional

import metarmap.lib.colors as colors_lib
from metarmap.models import Look


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


# ---- using a visualizer -----------------------------------------------------------------------------------------
#
# A visualizer is a module in this package with:
#   NAME, DESCRIPTION   shown in the web UI
#   EXCLUSIVE           True: it has the whole strip, so locate() is ignored
#   legend(settings)    legend_item() entries describing what the LEDs mean
#   look(metar, settings) -> Look        how one airport's LED looks ({} when it has no report), or
#   strip_look(settings) -> Look         one look for the whole strip (rainbow, chase)
# Visualizers don't touch the LEDs; the renderer turns their looks into animations.

def strip_look(vis, settings) -> Optional[Look]:
    """The visualizer's look for the whole strip, or None if it has one look per airport."""
    return vis.strip_look(settings) if hasattr(vis, "strip_look") else None


def looks(vis, codes, data, settings) -> List[Look]:
    """
    One look per LED. codes: each LED's airport, in LED order ("" for none, which stays dark);
    data: airport code -> METAR.
    """
    return [vis.look(data.get(code) or {}, settings) if code else Look.off() for code in codes]


def info(vis, settings) -> dict:
    """What the web UI and API show about a visualizer."""
    return {"name": vis.NAME, "description": vis.DESCRIPTION, "exclusive": vis.EXCLUSIVE,
            "legend": vis.legend(settings)}
