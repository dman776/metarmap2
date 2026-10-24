"""Tests for turning Looks into LED animations (metarmap/animations.py) and for the Look model."""
import pytest
from adafruit_led_animation.helper import PixelSubset

from metarmap.animations import animation_for
from metarmap.models import FlightCategory, Look


class FakeStrip(list):
    """Enough of a NeoPixel object for the animation library."""
    def __init__(self, n=10):
        super().__init__([(0, 0, 0)] * n)
        self.n = n
        self.auto_write = False
        self.brightness = 1.0

    def show(self):
        pass

    def fill(self, color):
        for i in range(len(self)):
            self[i] = color


@pytest.fixture
def pixel():
    return PixelSubset(FakeStrip(), 0, 1)


def test_solid(pixel):
    a = animation_for(Look.solid([255, 0, 0]), pixel)
    assert type(a).__name__ == "Solid"
    assert tuple(a.color) == (255, 0, 0)


def test_off(pixel):
    a = animation_for(Look.off(), pixel)
    assert type(a).__name__ == "Solid"
    assert tuple(a.color) == (0, 0, 0)


def test_blink_period_is_one_on_off_cycle(pixel):
    a = animation_for(Look.blink([0, 255, 0], period=2), pixel)
    assert type(a).__name__ == "Blink"
    assert a.speed == 1  # each of on and off lasts half the period
    assert tuple(a.colors[0]) == (0, 255, 0)


def test_pulse(pixel):
    a = animation_for(Look.pulse([0, 0, 255], period=4), pixel)
    assert type(a).__name__ == "Pulse"
    assert a._period == 4


def test_cycle(pixel):
    a = animation_for(Look.cycle([[1, 2, 3], [4, 5, 6]], step=0.1), pixel)
    assert type(a).__name__ == "ColorCycle"
    assert [tuple(c) for c in a.colors] == [(1, 2, 3), (4, 5, 6)]
    assert a.speed == pytest.approx(0.1)


def test_rainbow_and_chase_use_the_whole_strip():
    strip = FakeStrip(50)
    rainbow = animation_for(Look.rainbow(period=5), strip)
    assert type(rainbow).__name__ == "Rainbow" and rainbow._period == 5
    chase = animation_for(Look.chase([0, 0, 255], step=0.1, size=1, spacing=49), strip)
    assert type(chase).__name__ == "Chase"
    assert (chase._size, chase._spacing) == (1, 49)


def test_animations_actually_draw(pixel):
    """Run one frame to make sure the arguments are ones the library accepts."""
    for look in (Look.solid([255, 0, 0]), Look.blink([255, 0, 0]), Look.pulse([255, 0, 0], 1),
                 Look.cycle([[255, 0, 0], [0, 0, 0]], 0.1), Look.off()):
        animation_for(look, pixel).animate()


def test_unknown_effect(pixel):
    with pytest.raises(ValueError):
        animation_for(Look("sparkle"), pixel)


def test_look_normalizes_colors():
    assert Look.solid([255.0, 0, 0]) == Look.solid((255, 0, 0))
    assert Look.solid([1, 2, 3]).color == (1, 2, 3)
    assert Look.off().color is None


def test_looks_are_hashable_and_immutable():
    assert len({Look.solid([1, 2, 3]), Look.solid((1, 2, 3))}) == 1
    with pytest.raises(AttributeError):
        Look.off().effect = "solid"


def test_flight_category_compares_to_strings():
    assert FlightCategory.VFR == "VFR"
    assert FlightCategory("LIFR") is FlightCategory.LIFR
