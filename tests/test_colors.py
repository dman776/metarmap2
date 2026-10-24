"""Tests for lib/colors.py."""
import doctest

import pytest

import lib.colors as colors


def test_doctests():
    result = doctest.testmod(colors)
    assert result.failed == 0
    assert result.attempted > 0


@pytest.mark.parametrize("grb, css", [
    ((255, 0, 0), "#00ff00"),  # GRB order: first channel is green
    ((0, 255, 0), "#ff0000"),
    ((0, 0, 255), "#0000ff"),
    ((0, 0, 0), "#000000"),
    ((0, 125, 125), "#7d007d"),  # LIFR purple from the default config
    ((15, 15, 15), "#5a5a5a"),  # dim colors are lifted so they show on screen
])
def test_to_css(grb, css):
    assert colors.to_css(grb) == css


def test_named_colors_are_grb():
    named = colors.get_colors()
    assert colors.to_css(named[colors.RED]) == "#ff0000"
    assert colors.to_css(named[colors.GREEN]) == "#00ff00"
    assert colors.to_css(named[colors.BLUE]) == "#0000ff"
