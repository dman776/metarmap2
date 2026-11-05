"""Tests for lib/colors.py."""

import doctest

import pytest

import metarmap.lib.colors as colors


def test_doctests():
    result = doctest.testmod(colors)
    assert result.failed == 0
    assert result.attempted > 0


@pytest.mark.parametrize(
    "grb, css",
    [
        ((255, 0, 0), "#00ff00"),  # GRB order: first channel is green
        ((0, 255, 0), "#ff0000"),
        ((0, 0, 255), "#0000ff"),
        ((0, 0, 0), "#000000"),
        ((0, 125, 125), "#7d007d"),  # LIFR purple from the default config
        ((15, 15, 15), "#5a5a5a"),  # dim colors are lifted so they show on screen
    ],
)
def test_to_css(grb, css):
    assert colors.to_css(grb) == css


def test_named_colors_are_grb():
    named = colors.get_colors()
    assert colors.to_css(named[colors.RED]) == "#ff0000"
    assert colors.to_css(named[colors.GREEN]) == "#00ff00"
    assert colors.to_css(named[colors.BLUE]) == "#0000ff"


# every color in the strip's (green, red, blue) order, as it was when the palette was still written that way:
# writing it in RGB mustn't change a single LED
STRIP_COLORS = {
    colors.RED: (0, 255, 0),
    colors.DARK_RED: (0, 20, 0),
    colors.LIGHT_RED: (105, 255, 180),
    colors.GREEN: (255, 0, 0),
    colors.DARK_GREEN: (20, 0, 0),
    colors.BLUE: (0, 0, 255),
    colors.LIGHT_BLUE: (255, 51, 255),
    colors.MAGENTA: (0, 255, 255),
    colors.DARK_MAGENTA: (0, 125, 125),
    colors.CYAN: (255, 0, 255),
    colors.OFF: (0, 0, 0),
    colors.DARK_GRAY: (1, 1, 1),
    colors.GRAY: (50, 50, 50),
    colors.LIGHT_GRAY: (128, 128, 128),
    colors.YELLOW: (255, 255, 0),
    colors.DARK_YELLOW: (20, 20, 0),
    colors.WHITE: (255, 255, 255),
    colors.PURPLE: (0, 148, 211),
    colors.ORANGE: (126, 255, 0),
}


def test_the_strip_gets_the_same_colors():
    assert colors.get_colors() == STRIP_COLORS
    assert all(colors.color(name) == grb for name, grb in STRIP_COLORS.items())


def test_the_palette_reads_as_rgb():
    assert colors.PALETTE[colors.RED] == (255, 0, 0)
    assert colors.color(colors.RED) == (0, 255, 0)  # the strip's order
    assert colors.to_css(colors.color(colors.RED)) == "#ff0000"  # back to RGB for the web
    for name, rgb in colors.PALETTE.items():
        if max(rgb) >= 90:  # to_css lifts dimmer ones so they show on screen
            assert colors.to_css(colors.color(name)) == "#{:02x}{:02x}{:02x}".format(*rgb), name
