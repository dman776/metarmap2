"""
What a visualizer is (Visualizer), and using one: its looks and legend, with the lightning every weather visualizer
shares added over them.
"""

import re
from dataclasses import dataclass
from typing import Callable, List, Optional

import metarmap.lib.colors as colors_lib
from metarmap.models import Look, Report

# Visualizer.areas: the areas the Map page can draw, each from /api/<areas>
AREAS = ("advisories", "tfrs")
ID = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class Visualizer:
    """
    One way of showing the map, declared once at the end of its module (VISUALIZER = Visualizer(...)) and listed in
    visualizers.ALL. Visualizers don't touch the LEDs: the renderer turns their looks into animations.

    id:          what config.json saves (visualizer.active, visualizer.auto_rotate.skip) and the API accepts; never
                 changes, so `name` can
    name, description: shown in the web UI, Home Assistant and on the OLED
    legend:      legend(settings) -> legend_item() entries describing what the LEDs mean
    look:        look(metar, settings) -> how one airport's LED looks (metar is {} when it has no report), or
    strip_look:  strip_look(settings) -> one look for the whole strip (rainbow, chase); exactly one of the two.
                 A strip look makes it exclusive: it has every LED, so /locate is ignored
    covers_virtual: with strip_look, whether the web map's virtual airports show it too (else they stay dark)
    barbs:       the Map page draws each airport's wind barb
    areas:       the areas the Map page draws (one of AREAS), or None
    Lightning isn't a visualizer's job: looks() and legend() below add it to every one with a look per airport.
    """

    id: str
    name: str
    description: str
    legend: Callable[..., List[dict]]
    look: Optional[Callable[[Optional[Report], object], Look]] = None
    strip_look: Optional[Callable[[object], Look]] = None
    covers_virtual: bool = False
    barbs: bool = False
    areas: Optional[str] = None

    def __post_init__(self):
        if not ID.fullmatch(self.id):
            raise ValueError(f"visualizer id {self.id!r}: lower case letters, digits and _, starting with a letter")
        if (self.look is None) == (self.strip_look is None):
            raise ValueError(f"visualizer {self.id}: needs either look or strip_look, not both")
        if self.covers_virtual and self.strip_look is None:
            raise ValueError(f"visualizer {self.id}: covers_virtual is for a strip look")
        if self.areas is not None and self.areas not in AREAS:
            raise ValueError(f"visualizer {self.id}: areas {self.areas!r} is not one of {', '.join(AREAS)}")

    @property
    def exclusive(self) -> bool:
        """Whether it has the whole strip (one strip look), so /locate and auto-rotate leave it alone."""
        return self.strip_look is not None


def legend_item(label, detail, *colors, effect="solid", period=None, low=None):
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


def strip_look(vis: Visualizer, settings) -> Optional[Look]:
    """The visualizer's look for the whole strip, or None if it has one look per airport."""
    return vis.strip_look(settings) if vis.strip_look is not None else None


def looks(vis, codes, data, settings) -> List[Look]:
    """
    One look per LED. codes: each LED's airport, in LED order ("" for none, which stays dark);
    data: airport code -> METAR.
    """
    return [look(vis, data.get(code), settings) if code else Look.off() for code in codes]


def shows_lightning(vis: Visualizer, settings) -> bool:
    return vis.look is not None and settings.lightning.animation


def look(vis, metar, settings) -> Look:
    """
    One airport's look: the visualizer's, with lightning over it when the airport has some. Missing data is off
    instead of a red blink with visualizer.missing_data_blink off.
    """
    from metarmap.visualizers import style  # style uses legend_item() from here

    base = vis.look(metar, settings)
    if not settings.visualizer.missing_data_blink and base == style.missing():
        base = Look.off()
    return (
        style.with_lightning(base, settings) if shows_lightning(vis, settings) and style.has_lightning(metar) else base
    )


def legend(vis, settings) -> List[dict]:
    """
    The visualizer's legend, with lightning before "METAR not available" (or last) when it shows lightning, and
    missing data as off with visualizer.missing_data_blink off.
    """
    from metarmap.visualizers import style

    items = list(vis.legend(settings))
    if shows_lightning(vis, settings):
        at = next((n for n, item in enumerate(items) if item["effect"] == "off"), len(items))
        items.insert(at, style.lightning_legend(settings))
    if not settings.visualizer.missing_data_blink:
        items = [legend_item(item["label"], "Off") if style.is_missing_legend(item) else item for item in items]
    return items


def info(vis, settings) -> dict:
    """What the web UI and API show about a visualizer."""
    return {
        "id": vis.id,
        "name": vis.name,
        "description": vis.description,
        "exclusive": vis.exclusive,
        "legend": legend(vis, settings),
    }
