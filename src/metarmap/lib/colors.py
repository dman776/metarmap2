"""
The map's colors. The palette is written in ordinary RGB, (red, green, blue), the way colors are usually written.
The LED strip wants (green, red, blue): color() and get_colors() give that order, and everything that goes to the
LEDs comes from them, so nothing else needs to know it. to_css() turns a strip color back into CSS for the web UI.
"""

RED = "RED"
LIGHT_RED = "LIGHT RED"
DARK_RED = "DARK RED"
GREEN = "GREEN"
DARK_GREEN = "DARK GREEN"
BLUE = "BLUE"
LIGHT_BLUE = "LIGHT BLUE"
DARK_GRAY = "DARK GRAY"
GRAY = "GRAY"
LIGHT_GRAY = "LIGHT GRAY"
YELLOW = "YELLOW"
DARK_YELLOW = "DARK YELLOW"
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
    DARK_RED: (20, 0, 0),
    LIGHT_RED: (255, 105, 180),
    GREEN: (0, 255, 0),
    DARK_GREEN: (0, 20, 0),
    BLUE: (0, 0, 255),
    LIGHT_BLUE: (51, 255, 255),
    MAGENTA: (255, 0, 255),
    DARK_MAGENTA: (125, 0, 125),  # LIFR
    CYAN: (0, 255, 255),
    OFF: (0, 0, 0),
    DARK_GRAY: (1, 1, 1),
    GRAY: (50, 50, 50),
    LIGHT_GRAY: (128, 128, 128),
    YELLOW: (255, 255, 0),
    DARK_YELLOW: (20, 20, 0),
    WHITE: (255, 255, 255),
    PURPLE: (148, 0, 211),
    ORANGE: (255, 126, 0),
}


def strip_order(rgb):
    """An (red, green, blue) color in the LED strip's order, (green, red, blue)."""
    r, g, b = rgb
    return g, r, b


COLORS = {name: strip_order(rgb) for name, rgb in PALETTE.items()}  # in the strip's order


def color(name):
    """A palette color by name, in the strip's order: color(RED) is (0, 255, 0)."""
    return COLORS[name]


def get_colors() -> dict:
    """Every palette color by name, in the strip's order."""
    return dict(COLORS)


def clamp(minimum, value, maximum):
    """
    Makes sure the given value (middle param) is always between the maximum and minimum.

    Arguments:
        minimum {number} -- The smallest the value can be (inclusive).
        value {number} -- The value to clamp.
        maximum {number} -- The largest the value can be (inclusive).

    Returns:
        number -- The value within the allowable range.
    """

    if value < minimum:
        return minimum

    if value > maximum:
        return maximum

    return value


def interpolate(left_value, right_value, proportion):
    """
    Finds the spot between the two values.

    Arguments:
        left_value {number} -- The value on the "left" that 0.0 would return.
        right_value {number} -- The value on the "right" that 1.0 would return.
        proportion {float} -- The proportion from the left to the right hand side.

    >>> interpolate(0, 255, 0.5)
    127
    >>> interpolate(10, 20, 0.5)
    15
    >>> interpolate(0, 255, 0.0)
    0
    >>> interpolate(0, 255, 0)
    0
    >>> interpolate(0, 255, 1)
    255
    >>> interpolate(0, 255, 1.5)
    255
    >>> interpolate(0, 255, -0.5)
    0
    >>> interpolate(0, 255, 0.1)
    25
    >>> interpolate(0, 255, 0.9)
    229
    >>> interpolate(255, 0, 0.5)
    127
    >>> interpolate(20, 10, 0.5)
    15
    >>> interpolate(255, 0, 0.0)
    255
    >>> interpolate(255, 0, 0)
    255
    >>> interpolate(255, 0, 1)
    0
    >>> interpolate(255, 0, 1.5)
    0
    >>> interpolate(255, 0, -0.5)
    255
    >>> interpolate(255, 0, 0.1)
    229
    >>> interpolate(255, 0, 0.9)
    25

    Returns:
        float -- The number that is the given amount between the left and right.
    """

    left_value = clamp(0.0, left_value, 255.0)
    right_value = clamp(0.0, right_value, 255.0)
    proportion = clamp(0.0, proportion, 1.0)

    return clamp(0, int(float(left_value) + (float(right_value - float(left_value)) * float(proportion))), 255)


def get_color_mix(left_color: list, right_color: list, proportion) -> list:
    """
    Returns a color that is a mix between the two given colors.
    A given proportion of 0 would return the left color.
    A given proportion of 1 would return the right_color.
    A given proportion of 0.5 would return a 50/50 mix.

    Works for RGB or ARGB, but both sides MUST have matching number of components.

    >>> get_color_mix([0,0,0], [255, 255, 255], 0.0)
    [0, 0, 0]

    >>> get_color_mix([0,0,0], [255, 255, 255], 1.0)
    [255, 255, 255]

    >>> get_color_mix([0,0,0], [255, 255, 255], 0.5)
    [127, 127, 127]

    >>> get_color_mix([125,255,0], [125, 0, 255], 0.5)
    [125, 127, 127]

    >>> get_color_mix([255, 255, 255], [0,0,0], 0.5)
    [127, 127, 127]

    >>> get_color_mix([125, 0, 255], [125,255,0], 0.5)
    [125, 127, 127]

    Arguments:
        left_color {float[]} -- The starting color.
        right_color {float[]} -- The ending color.
        proportion {float} -- The mix between the two colors.

    Returns:
        float[] -- The new color.
    """

    array_length = len(left_color)
    if array_length != len(right_color):
        return left_color

    indices = range(0, array_length)
    new_color = [int(interpolate(left_color[index], right_color[index], proportion)) for index in indices]

    return new_color


def get_brightness_adjusted_color(color_to_render: list, brightness_adjustment: float) -> list:
    if brightness_adjustment < 0.0:
        brightness_adjustment = 0.0

    final_color = []

    for color in color_to_render:
        reduced_color = float(color) * brightness_adjustment

        # Some colors are floats, some are integers.
        # Make sure we keep everything the same.
        if isinstance(color, int):
            reduced_color = int(reduced_color)

        final_color.append(reduced_color)

    return final_color


def to_css(color) -> str:
    """
    Converts a color in the strip's (green, red, blue) order, as color() gives it, to a CSS hex string for the
    web UI.
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
