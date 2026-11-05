"""Tests for the startup sequences' math (leds/intro.py): the order the LEDs fade in, and their colors."""

import math
import random

import pytest

from metarmap.leds import intro
from metarmap.models import Look
from metarmap.settings import INIT_SEQUENCES, SWEEP_SIDES

# a plus sign of airports around Houston, each arm the same distance on the map, and one in the middle: (lat, lon).
# A degree of longitude is shorter than one of latitude away from the equator (cos 30 = 0.87 of it here)
ARM = 1 / math.cos(math.radians(30))
CENTER = (30.0, -95.0)
NORTH = (31.0, -95.0)
EAST = (30.0, -95.0 + ARM)
SOUTH = (29.0, -95.0)
WEST = (30.0, -95.0 - ARM)
PLUS = [CENTER, NORTH, EAST, SOUTH, WEST]


def order(starts):
    """The LEDs, first to fade in to last."""
    return sorted(range(len(starts)), key=lambda i: starts[i])


def test_the_choices_match_the_settings():
    assert tuple(intro.NAMES) == INIT_SEQUENCES
    assert tuple(intro.SWEEP_FROM) == SWEEP_SIDES


def test_center_out():
    starts = intro.start_times("center_out", PLUS)
    assert starts[0] == 0.0  # the middle first
    assert starts[1:] == pytest.approx([1.0] * 4)  # then the four edges together


def test_edges_in():
    starts = intro.start_times("edges_in", PLUS)
    assert starts[0] == 1.0
    assert starts[1:] == pytest.approx([0.0] * 4)


def test_the_center_is_the_middle_of_the_box_not_the_average():
    # three airports bunched in the west and one far east: the middle of the box is between them
    west = [(30.0, -96.0), (30.1, -96.0), (29.9, -96.0)]
    starts = intro.start_times("center_out", [*west, (30.0, -94.0)])
    assert starts[0] == pytest.approx(starts[3])  # the same distance from the middle (-95)


def test_distance_counts_a_degree_of_longitude_as_shorter():
    # 1 degree east is about 0.87 of a degree north at 30 degrees north
    starts = intro.start_times("center_out", [CENTER, (30.0, -94.0), (31.0, -95.0), (29.0, -95.0), (30.0, -96.0)])
    assert starts[2] == starts[3] == pytest.approx(1.0)  # north and south are the farthest
    assert starts[1] == starts[4] == pytest.approx(0.866, abs=0.001)


@pytest.mark.parametrize(
    "side, first, last",
    [
        ("W", WEST, EAST),
        ("E", EAST, WEST),
        ("N", NORTH, SOUTH),
        ("S", SOUTH, NORTH),
    ],
)
def test_sweep(side, first, last):
    starts = intro.start_times("sweep", PLUS, side)
    assert starts[PLUS.index(first)] == 0.0
    assert starts[PLUS.index(last)] == 1.0
    assert starts[0] == pytest.approx(0.5)  # the middle half way


def test_a_diagonal_sweep():
    w, e = -95.0 - ARM, -95.0 + ARM
    corners = [(31.0, w), (31.0, e), (29.0, w), (29.0, e)]  # NW, NE, SW, SE: a square on the map
    starts = intro.start_times("sweep", corners, "NW")
    assert starts[0] == 0.0 and starts[3] == 1.0  # northwest to southeast
    assert starts[1] == pytest.approx(starts[2])  # the other two corners together


def test_radar_turns_clockwise_from_north():
    starts = intro.start_times("radar", [NORTH, EAST, SOUTH, WEST])
    assert starts == pytest.approx([0.0, 0.25, 0.5, 0.75])


def test_sparkle_lights_each_led_once_in_random_order():
    starts = intro.start_times("sparkle", [None] * 10, rng=random.Random(4))
    assert sorted(starts) == pytest.approx([i / 9 for i in range(10)])
    assert starts != sorted(starts)


def test_leds_without_a_position_come_last():
    starts = intro.start_times("center_out", [CENTER, None, NORTH, None])
    assert starts[1] == starts[3] == 1.0
    assert intro.start_times("sweep", [None, None]) == [1.0, 1.0]  # no positions at all: one fade, together


def test_one_airport():
    assert intro.start_times("center_out", [CENTER]) == [0.0]
    assert intro.start_times("sweep", [CENTER]) == [0.0]


def test_an_unknown_sequence():
    with pytest.raises(ValueError):
        intro.start_times("spiral", PLUS)


def test_fades_in_to_each_target_by_the_end():
    targets = [(10, 200, 40), (255, 255, 255)]
    starts = [0.0, 1.0]
    assert intro.colors_at(0, starts, targets) == [(0, 0, 0), (0, 0, 0)]
    halfway = intro.colors_at(intro.FADE_SECONDS / 2, starts, targets)
    assert 0 < halfway[0][1] < 200 and halfway[1] == (0, 0, 0)  # the first fading, the last not started
    assert intro.colors_at(intro.SECONDS, starts, targets) == targets


def test_target_colors():
    assert intro.target(Look.solid((1, 2, 3))) == (1, 2, 3)
    assert intro.target(Look.blink((4, 5, 6))) == (4, 5, 6)
    assert intro.target(Look.off()) == (0, 0, 0)
