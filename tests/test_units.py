"""Tests for lib/units.py."""

import pytest

from metarmap.lib.units import celsius_to_fahrenheit


@pytest.mark.parametrize("celsius, fahrenheit", [(0, 32), (100, 212), (-40, -40), (28, 82.4), (None, 0)])
def test_celsius_to_fahrenheit(celsius, fahrenheit):
    assert celsius_to_fahrenheit(celsius) == pytest.approx(fahrenheit)
