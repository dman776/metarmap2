"""Tests for the LED strip stand-in and opening the strip off the Pi."""
from metarmap.leds.strip import FakeStrip, open_strip
from metarmap.settings import Settings


def test_fake_strip():
    strip = FakeStrip(3, brightness=0.4)
    assert len(strip) == 3 and strip.n == 3
    assert strip.brightness == 0.4
    strip[1] = (1, 2, 3)
    strip.fill([9, 9, 9])
    assert strip.colors == [(9, 9, 9)] * 3
    strip.show()
    assert strip.shows == 1


def test_open_strip_without_hardware():
    led = Settings().led
    led.count = 12
    strip = open_strip(led)
    assert isinstance(strip, FakeStrip)
    assert len(strip) == 12
    assert strip.brightness == led.brightness.normal
