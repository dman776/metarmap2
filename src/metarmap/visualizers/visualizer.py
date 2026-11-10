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
# Visualizer.icon: what each visualizer's icon shows; each client draws the name its own way (the web pages:
# metarmap.web.icons)
ICONS = (
    "plane",
    "cloud",
    "eye",
    "wind",
    "gust",
    "compass",
    "thermometer",
    "droplet",
    "mountain",
    "gauge",
    "rain",
    "warning",
    "ban",
    "rainbow",
    "chase",
    "clock",
    "umbrella",
)
SHORT_NAME_MAX = 11  # characters: fits a tile of the touchscreen remote's visualizer picker


@dataclass(frozen=True)
class Visualizer:
    """
    One way of showing the map, declared once at the end of its module (VISUALIZER = Visualizer(...)) and listed in
    visualizers.ALL. Visualizers don't touch the LEDs: the renderer turns their looks into animations.

    id:          what config.json saves (visualizer.active, visualizer.auto_rotate.skip) and the API accepts; never
                 changes, so `name` can
    name, description: shown in the web UI, Home Assistant and on the OLED
    short_name:  the name where there's little room (the touchscreen remote's picker), at most SHORT_NAME_MAX characters
    icon:        what its icon shows (one of ICONS)
    legend:      legend(settings) -> legend_item() entries describing what the LEDs mean
    look:        look(metar, settings) -> how one airport's LED looks (metar is {} when it has no report), or
    strip_look:  strip_look(settings) -> one look for the whole strip (rainbow, chase); exactly one of the two.
                 A strip look makes it exclusive: it has every LED, so /locate is ignored
    covers_virtual: with strip_look, whether the web map's virtual airports show it too (else they stay dark)
    barbs:       the Map page draws each airport's wind barb
    areas:       the areas the Map page draws (one of AREAS), or None
    steps:       steps(settings) -> {"labels": [...], "seconds": s, "prefix": "FC"} for a visualizer whose looks go
                 through the same steps together (Flight Category Forecast), each lasting `seconds`, counted from when
                 the LEDs were built (Renderer.step()). The pages show which step is on, the Micro "<prefix> <label>".
                 None for the rest
    Lightning isn't a visualizer's job: looks() and legend() below add it to every one with a look per airport.
    """

    id: str
    name: str
    description: str
    short_name: str
    icon: str
    legend: Callable[..., List[dict]]
    look: Optional[Callable[[Optional[Report], object], Look]] = None
    strip_look: Optional[Callable[[object], Look]] = None
    covers_virtual: bool = False
    barbs: bool = False
    areas: Optional[str] = None
    steps: Optional[Callable[[object], dict]] = None

    def __post_init__(self):
        if not ID.fullmatch(self.id):
            raise ValueError(f"visualizer id {self.id!r}: lower case letters, digits and _, starting with a letter")
        if not 0 < len(self.short_name) <= SHORT_NAME_MAX:
            raise ValueError(
                f"visualizer {self.id}: short_name {self.short_name!r} needs 1-{SHORT_NAME_MAX} characters"
            )
        if self.icon not in ICONS:
            raise ValueError(f"visualizer {self.id}: icon {self.icon!r} is not one of {', '.join(ICONS)}")
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
    """
    Whether lightning goes over the visualizer's looks and into its legend: lightning.animation, for one with a look
    per airport. A forecast visualizer (one with steps) also needs lightning.forecast.
    """
    if vis.look is None or not settings.lightning.animation:
        return False
    return vis.steps is None or settings.lightning.forecast


def look(vis, metar, settings) -> Look:
    """
    One airport's look: the visualizer's, with lightning over it when the airport has some. Missing data is off
    instead of a red blink with visualizer.missing_data_blink off.
    """
    from metarmap.visualizers import style  # style uses legend_item() from here

    base = vis.look(metar, settings)
    if not settings.visualizer.missing_data_blink and base == style.missing():
        base = Look.off().tagged(*base.legend)  # still the "missing" entry, which then says Off
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
        items = [
            legend_item(item["label"], "Off", key=item["key"]) if style.is_missing_legend(item) else item
            for item in items
        ]
    return items


def in_use(vis, looks, settings) -> Optional[List[str]]:
    """
    The keys of the legend entries the LEDs (`looks`, one per airport) are showing, in the legend's order; None for a
    visualizer with one look for the whole strip, whose legend is always shown whole.
    """
    if vis.look is None:
        return None
    shown = {key for look in looks for key in look.legend}
    return [item["key"] for item in legend(vis, settings) if item["key"] in shown]


def info(vis, settings) -> dict:
    """What the web UI and API show about a visualizer."""
    return {
        "id": vis.id,
        "name": vis.name,
        "short_name": vis.short_name,
        "icon": vis.icon,
        "description": vis.description,
        "exclusive": vis.exclusive,
        "steps": vis.steps(settings)["labels"] if vis.steps else None,
        "legend": legend(vis, settings),
    }
