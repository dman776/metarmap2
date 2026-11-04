"""Tests for the city lookups behind the sun times and the OLED's time zone (lib/utils.py)."""

import pytest

from metarmap.lib import utils


def test_a_known_city_any_case():
    assert utils.get_location("houston").name == "Houston"
    assert utils.get_location("Houston").timezone == "US/Central"


def test_an_unknown_city_is_none():
    assert utils.get_location("Houstn") is None


def test_sun_times_of_a_known_city():
    times = utils.get_sun_times("Houston")
    assert times["dawn"] < times["sunrise"] < times["sunset"] < times["dusk"]


def test_sun_times_of_an_unknown_city_say_why():
    """It used to fail with AttributeError on None (geo.city's rule now keeps config.json's city a known one)."""
    with pytest.raises(ValueError, match="'Houstn' is not a city the sun times know"):
        utils.get_sun_times("Houstn")
