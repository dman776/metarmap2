"""
The web pages' visualizer icons (metarmap.visualizers.visualizer.ICONS), drawn as SVG: sprite() puts them in a page
once, as <symbol id="vi-<name>">, and use(name) draws one, so the pages' scripts can switch icons by name.
"""

from metarmap.visualizers.visualizer import ICONS

# icon name -> the inside of a 24x24 SVG, drawn in the text color (stroke) unless it sets its own
SHAPES = {
    "plane": '<path fill="currentColor" stroke="none" d="M21 15.5v-2l-8-5V3.5a1.5 1.5 0 0 0-3 0v5l-8 5v2l8-2.5V18'
    'l-2 1.5V21l3.5-1 3.5 1v-1.5L13 18v-5l8 2.5Z"/>',
    "cloud": '<path d="M7 18h10a4 4 0 0 0 .5-8 6 6 0 0 0-11.4 1.5A3.3 3.3 0 0 0 7 18Z"/>',
    "eye": '<path d="M2 12s3.5-6.5 10-6.5S22 12 22 12s-3.5 6.5-10 6.5S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
    "wind": '<path d="M3 8h11a3 3 0 1 0-3-3M3 12h16a3 3 0 1 1-3 3M3 16h7"/>',
    "gust": '<path d="M3 7h9M3 12h15M3 17h11M15 4l3 3-3 3"/>',
    "compass": '<circle cx="12" cy="12" r="9"/><path fill="currentColor" d="m15.5 8.5-2 5-5 2 2-5 5-2Z"/>',
    "thermometer": '<path d="M10 14V4a2 2 0 0 1 4 0v10a4 4 0 1 1-4 0Z"/>',
    "droplet": '<path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11Z"/>',
    "mountain": '<path d="m2 20 7-12 4 6 3-4 6 10H2Z"/>',
    "gauge": '<path d="M4 18a9 9 0 1 1 16 0"/><path d="m12 13 4-4"/>',
    "rain": '<path d="M7 14h10a4 4 0 0 0 .5-8 6 6 0 0 0-11.4 1.5A3.3 3.3 0 0 0 7 14Z"/>'
    '<path d="M8 18l-1 3M12 18l-1 3M16 18l-1 3"/>',
    "warning": '<path d="M12 3 2 21h20L12 3Z"/><path d="M12 10v5M12 18v.5"/>',
    "ban": '<circle cx="12" cy="12" r="9"/><path d="m6 6 12 12"/>',
    "rainbow": '<path d="M2 18a10 10 0 0 1 20 0" stroke="#ff5a5a"/>'
    '<path d="M5.5 18a6.5 6.5 0 0 1 13 0" stroke="#f5b544"/>'
    '<path d="M9 18a3 3 0 0 1 6 0" stroke="#4ea8ff"/>',
    "chase": '<g fill="currentColor" stroke="none"><circle cx="4" cy="12" r="2" opacity=".25"/>'
    '<circle cx="10" cy="12" r="2" opacity=".5"/><circle cx="16" cy="12" r="2.5" opacity=".8"/>'
    '<circle cx="21" cy="12" r="2"/></g>',
}
assert set(SHAPES) == set(ICONS), "every visualizer icon needs a shape"

ATTRS = (
    'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"'
    ' stroke-linejoin="round"'
)


def sprite() -> str:
    """Every icon, as symbols in one hidden SVG, for a page's use() and its scripts."""
    symbols = "".join(f'<symbol id="vi-{name}" {ATTRS}>{shape}</symbol>' for name, shape in SHAPES.items())
    return f'<svg width="0" height="0" style="position:absolute" aria-hidden="true">{symbols}</svg>'


def use(name: str, size: int = 16) -> str:
    """One icon from the page's sprite(); nothing for a name it doesn't know."""
    if name not in SHAPES:
        return ""
    return f'<svg class="vi" width="{size}" height="{size}" aria-hidden="true"><use href="#vi-{name}"/></svg>'
