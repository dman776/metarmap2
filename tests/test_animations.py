"""Tests for turning Looks into LED animations (metarmap/leds/animations.py) and for the Look model."""
import pytest
from adafruit_led_animation.helper import PixelSubset

from adafruit_led_animation.animation.blink import Blink
from adafruit_led_animation.animation.colorcycle import ColorCycle
from adafruit_led_animation.animation.pulse import Pulse

from metarmap.leds.animations import PULSE_STEPS, animation_for
from metarmap.leds.strip import FakeStrip
from metarmap.models import FlightCategory, Look


@pytest.fixture
def pixel():
    return PixelSubset(FakeStrip(10), 0, 1)


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


# ---- effects built from ColorCycle, so they work with older versions of the LED library -------------------------

def test_two_color_blink_alternates(pixel):
    a = animation_for(Look.blink((0, 0, 255), period=1, background=(255, 255, 0)), pixel)
    assert isinstance(a, ColorCycle) and not isinstance(a, Blink)
    assert a.colors == [(0, 0, 255), (255, 255, 0)]


def test_plain_blink_is_unchanged(pixel):
    assert type(animation_for(Look.blink((0, 0, 255), period=2), pixel)) is Blink


def test_pulse_that_never_goes_dark(pixel):
    a = animation_for(Look.pulse((0, 0, 200), period=4, low=0.3), pixel)
    assert isinstance(a, ColorCycle)
    levels = [c[2] for c in a.colors]
    assert max(levels) == 200 and min(levels) == 60  # 30% at its dimmest
    assert a.speed == pytest.approx(4 / PULSE_STEPS)


def test_plain_pulse_is_unchanged(pixel):
    assert type(animation_for(Look.pulse((0, 0, 255), period=4), pixel)) is Pulse


def test_web_ui_gets_the_floor():
    assert Look.pulse((0, 0, 255), period=4, low=0.3).to_dict() == {"effect": "pulse", "colors": ["#0000ff"],
                                                                       "period": 4, "low": 0.3}
    assert len(Look.blink((0, 0, 255), period=1, background=(0, 0, 76)).to_dict()["colors"]) == 2
