from typing import List, Optional

import metarmap.lib.colors as colors_lib
from metarmap.models import Look


def legend_item(label, detail, *colors, effect="solid", period=None, low=None):
    """
    One entry of a visualizer legend, shown in the web UI.
    Args:
        label (str): what the entry represents (ie. "VFR", "5-10 kts")
        detail (str): how the LED looks (ie. "Green", "Purple to blue")
        colors: GRB colors; two or more colors are drawn as a gradient. None/empty = LED off
        effect (str): solid, blink, pulse, flash (first color with flashes of the second), alternate (two colors in
            turn), chase or off
        period (float): seconds per blink/pulse cycle, if any
        low (float): a pulse's dimmest point (0.3: never dark)
    """
    css = [colors_lib.to_css(c) for c in colors if c is not None]
    return {
        "label": label,
        "detail": detail,
        "colors": css,
        "effect": effect if css else "off",
        "period": period,
        "low": low,
    }


# ---- using a visualizer -----------------------------------------------------------------------------------------
#
# A visualizer is a module in this package with:
#   NAME, DESCRIPTION   shown in the web UI
#   EXCLUSIVE           True: it has the whole strip, so locate() is ignored
#   legend(settings)    legend_item() entries describing what the LEDs mean
#   look(metar, settings) -> Look        how one airport's LED looks ({} when it has no report), or
#   strip_look(settings) -> Look         one look for the whole strip (rainbow, chase)
#   COVERS_VIRTUAL      with strip_look: True if the virtual airports show it too (default: they stay dark)
# Visualizers don't touch the LEDs; the renderer turns their looks into animations.
# Lightning isn't a visualizer's job: looks() and legend() add it to every one with a look per airport.

def strip_look(vis, settings) -> Optional[Look]:
    """The visualizer's look for the whole strip, or None if it has one look per airport."""
    return vis.strip_look(settings) if hasattr(vis, "strip_look") else None


def covers_virtual(vis) -> bool:
    """Whether the virtual airports show the visualizer's whole-strip look, or stay dark while it runs."""
    return getattr(vis, "COVERS_VIRTUAL", False)


def looks(vis, codes, data, settings) -> List[Look]:
    """
    One look per LED. codes: each LED's airport, in LED order ("" for none, which stays dark);
    data: airport code -> METAR.
    """
    return [look(vis, data.get(code) or {}, settings) if code else Look.off() for code in codes]


def shows_lightning(vis, settings) -> bool:
    return hasattr(vis, "look") and settings.lightning.animation


def look(vis, metar, settings) -> Look:
    """One airport's look: the visualizer's, with lightning over it when the airport has some."""
    from metarmap.visualizers import style  # style uses legend_item() from here
    base = vis.look(metar, settings)
    return style.with_lightning(base, settings) if shows_lightning(vis, settings) and style.has_lightning(metar) \
        else base


def legend(vis, settings) -> List[dict]:
    """The visualizer's legend, with lightning before "METAR not available" (or last) when it shows lightning."""
    from metarmap.visualizers import style
    items = list(vis.legend(settings))
    if shows_lightning(vis, settings):
        at = next((n for n, item in enumerate(items) if item["effect"] == "off"), len(items))
        items.insert(at, style.lightning_legend(settings))
    return items


def info(vis, settings) -> dict:
    """What the web UI and API show about a visualizer."""
    return {"name": vis.NAME, "description": vis.DESCRIPTION, "exclusive": vis.EXCLUSIVE,
            "legend": legend(vis, settings)}
