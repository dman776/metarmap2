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
    colors.LIGHT_RED: (105, 255, 180),
    colors.GREEN: (255, 0, 0),
    colors.BLUE: (0, 0, 255),
    colors.LIGHT_BLUE: (255, 51, 255),
    colors.MAGENTA: (0, 255, 255),
    colors.DARK_MAGENTA: (0, 125, 125),
    colors.CYAN: (255, 0, 255),
    colors.OFF: (0, 0, 0),
    colors.GRAY: (50, 50, 50),
    colors.YELLOW: (255, 255, 0),
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


def test_the_visualizers_named_colors_are_the_tuples_they_replaced():
    """Each was a raw (green, red, blue) tuple in its visualizer; the named colors give the same LEDs."""
    from metarmap.leds import animations, intro
    from metarmap.models import FlightCategory as Category
    from metarmap.visualizers import flightcategory, precipitation, style

    assert flightcategory.COLORS == {
        Category.VFR: (255, 0, 0),
        Category.MVFR: (0, 0, 255),
        Category.IFR: (0, 255, 0),
        Category.LIFR: (0, 125, 125),
    }
    p = precipitation
    assert (p.RAIN, p.SNOW, p.ICE, p.HAZARD, p.UNKNOWN) == (
        (0, 0, 255),
        (255, 255, 255),
        (255, 0, 255),
        (0, 255, 255),
        (126, 255, 0),
    )
    assert (p.FOG, p.SMOKE, p.HAZE, p.MIST) == ((15, 15, 15), (75, 75, 75), (5, 5, 5), (0, 0, 15))
    assert style.LIGHTNING_COLORS == {"yellow": (255, 255, 0), "white": (255, 255, 255)}
    assert flightcategory.OFF == animations.OFF == intro.OFF == (0, 0, 0) and intro.WHITE == (255, 255, 255)
