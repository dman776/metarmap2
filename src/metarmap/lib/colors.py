"""
The map's colors. The palette is written in ordinary RGB, (red, green, blue), the way colors are usually written.
The LED code has always kept colors as (green, red, blue): color() and get_colors() give that order, and everything
that goes to the LEDs comes from them, so nothing else needs to know it. With led.order at its default (GRB) the
LEDs show them right; RGB swaps red and green, for a strip wired the other way. to_css() turns a color back into
CSS for the web UI.
"""

RED = "RED"
LIGHT_RED = "LIGHT RED"
GREEN = "GREEN"
BLUE = "BLUE"
LIGHT_BLUE = "LIGHT BLUE"
GRAY = "GRAY"
YELLOW = "YELLOW"
WHITE = "WHITE"
MAGENTA = "MAGENTA"
DARK_MAGENTA = "DARK MAGENTA"
CYAN = "CYAN"
PURPLE = "PURPLE"
ORANGE = "ORANGE"
OFF = "OFF"

# (red, green, blue)
PALETTE = {
    RED: (255, 0, 0),
    LIGHT_RED: (255, 105, 180),
    GREEN: (0, 255, 0),
    BLUE: (0, 0, 255),
    LIGHT_BLUE: (51, 255, 255),
    MAGENTA: (255, 0, 255),
    DARK_MAGENTA: (125, 0, 125),  # LIFR
    CYAN: (0, 255, 255),
    OFF: (0, 0, 0),
    GRAY: (50, 50, 50),
    YELLOW: (255, 255, 0),
    WHITE: (255, 255, 255),
    PURPLE: (148, 0, 211),
    ORANGE: (255, 126, 0),
}


def strip_order(rgb):
    """A (red, green, blue) color in the LED code's order, (green, red, blue)."""
    r, g, b = rgb
    return g, r, b


COLORS = {name: strip_order(rgb) for name, rgb in PALETTE.items()}  # (green, red, blue)


def color(name):
    """A palette color by name, as the LEDs take it: color(RED) is (0, 255, 0)."""
    return COLORS[name]


def get_colors() -> dict:
    """Every palette color by name, as the LEDs take them."""
    return dict(COLORS)


def to_css(color) -> str:
    """
    Converts a (green, red, blue) color, as color() gives it, to a CSS hex string for the web UI.
    Very dim colors are lifted so they stay visible on screen.

    >>> to_css((255, 0, 0))
    '#00ff00'
    >>> to_css((0, 0, 15))
    '#00005a'
    """
    g, r, b = (int(c) for c in color)
    peak = max(r, g, b)
    if 0 < peak < 90:
        r, g, b = (int(c * 90 / peak) for c in (r, g, b))
    return "#{:02x}{:02x}{:02x}".format(r, g, b)
