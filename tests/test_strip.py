"""Tests for the LED strip stand-in and opening the strip off the Pi."""

import pytest

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


def test_fake_strip_resizes():
    strip = FakeStrip(3)
    strip.fill([9, 9, 9])
    strip.resize(5)
    assert strip.colors == [(9, 9, 9)] * 3 + [(0, 0, 0)] * 2 and strip.n == 5
    strip.resize(2)
    assert strip.colors == [(9, 9, 9)] * 2 and strip.n == 2


def test_open_strip_without_hardware():
    led = Settings().led
    led.count = 12
    strip = open_strip(led)
    assert isinstance(strip, FakeStrip)
    assert len(strip) == 12
    assert strip.brightness == led.brightness.normal


class PixelBufLike:
    """What neopixel.NeoPixel is to SkipUnchangedShow: adafruit_pixelbuf.PixelBuf's buffers, show() and _transmit."""

    def __init__(self, n, brightness=1.0):
        self._pre = bytearray(3 * n)
        self._brightness = brightness
        self._post_brightness_buffer = bytearray(3 * n)
        self.sent = []

    def __len__(self):
        return len(self._pre) // 3

    def __setitem__(self, i, color):
        self._pre[3 * i : 3 * i + 3] = bytes(color)
        self._rescale()

    def fill(self, color):
        for i in range(len(self)):
            self[i] = color

    @property
    def brightness(self):
        return self._brightness

    @brightness.setter
    def brightness(self, value):
        self._brightness = value
        self._rescale()

    def _rescale(self):
        for i, b in enumerate(self._pre):
            self._post_brightness_buffer[i] = int(b * self._brightness)

    def show(self):
        return self._transmit(self._post_brightness_buffer)

    def _transmit(self, buffer):
        self.sent.append(bytes(buffer))


def skipping_strip(n=3, base=PixelBufLike):
    from metarmap.leds.strip import skipping_unchanged

    strip = skipping_unchanged(base)(n, brightness=0.5)
    strip.now = 100.0
    strip._monotonic = lambda: strip.now
    return strip


def test_skipping_strip_sends_once_until_something_changes():
    from metarmap.leds.strip import SETTLE_SECONDS

    strip = skipping_strip()
    strip[0] = (200, 100, 50)
    strip.show()
    strip.now += SETTLE_SECONDS + 0.01
    strip.show()
    strip.show()
    assert strip.sent == [bytes([100, 50, 25, 0, 0, 0, 0, 0, 0])]
    strip[1] = (2, 4, 6)
    strip.show()
    assert len(strip.sent) == 2 and strip.sent[-1][3:6] == bytes([1, 2, 3])
    strip.now += SETTLE_SECONDS + 0.01
    strip[1] = (2, 4, 6)  # the same color again: nothing to send
    strip.show()
    assert len(strip.sent) == 2


def test_skipping_strip_sends_every_frame_just_after_a_change():
    """A new color is sent again at the next frames for SETTLE_SECONDS, so a garbled send is put right at once."""
    from metarmap.leds.strip import SETTLE_SECONDS

    strip = skipping_strip()
    strip[0] = (200, 100, 50)
    strip.show()
    strip.now += SETTLE_SECONDS / 2
    strip.show()
    assert len(strip.sent) == 2
    strip.now += SETTLE_SECONDS / 2 + 0.01
    strip.show()
    assert len(strip.sent) == 2  # settled


def test_skipping_strip_sends_a_brightness_change_and_a_clear():
    strip = skipping_strip()
    strip.fill((100, 100, 100))
    strip.show()
    strip.brightness = 0.2
    strip.show()
    assert strip.sent[-1] == bytes([20] * 9)
    strip.fill((0, 0, 0))  # Renderer.clear()
    strip.show()
    assert strip.sent[-1] == bytes(9) and len(strip.sent) == 3


def test_skipping_strip_resends_now_and_then():
    """An LED that picked up a wrong color (a glitch on the data line) is put right within RESEND_SECONDS."""
    from metarmap.leds.strip import RESEND_SECONDS, SETTLE_SECONDS

    strip = skipping_strip()
    strip.show()
    strip.now += SETTLE_SECONDS + 0.01
    strip.show()
    assert len(strip.sent) == 1
    strip.now += RESEND_SECONDS - SETTLE_SECONDS - 0.11
    strip.show()
    assert len(strip.sent) == 1
    strip.now += 0.1
    strip.show()
    assert len(strip.sent) == 2
    strip.show()
    assert len(strip.sent) == 2  # and counts again from that send


def test_skipping_strip_sends_every_time_without_the_buffer(caplog):
    """A NeoPixel library without the post-brightness buffer (older or newer) sends at every show(), as before."""

    class OtherLibrary:
        def __init__(self, n, brightness=1.0):
            self.shows = 0

        def show(self):
            self.shows += 1

    strip = skipping_strip(base=OtherLibrary)
    for _ in range(3):
        strip.show()
    assert sum("_post_brightness_buffer" in r.message for r in caplog.records) == 1  # said once
    assert strip.shows == 3


def test_skipping_strip_sends_again_after_a_failed_send():
    class Flaky(PixelBufLike):
        fail = True

        def _transmit(self, buffer):
            if self.fail:
                self.fail = False
                raise OSError("busy")
            super()._transmit(buffer)

    strip = skipping_strip(base=Flaky)
    strip[0] = (2, 2, 2)
    with pytest.raises(OSError):
        strip.show()
    strip.show()
    assert strip.sent == [bytes([1, 1, 1, 0, 0, 0, 0, 0, 0])]


def test_open_strip_on_the_pi_skips_unchanged_sends(monkeypatch):
    """On the Pi open_strip gives a NeoPixel whose show() leaves out sends that change nothing."""
    import sys
    from types import ModuleType

    from metarmap.leds.strip import SkipUnchangedShow

    class NeoPixel(PixelBufLike):
        def __init__(self, pin, n, brightness=1.0, pixel_order=None, auto_write=True):
            super().__init__(n, brightness=brightness)
            self.pin, self.pixel_order, self.auto_write = pin, pixel_order, auto_write

    board, neopixel = ModuleType("board"), ModuleType("neopixel")
    board.D18 = "pin 18"
    neopixel.NeoPixel, neopixel.GRB = NeoPixel, "GRB"
    monkeypatch.setitem(sys.modules, "board", board)
    monkeypatch.setitem(sys.modules, "neopixel", neopixel)
    led = Settings().led
    led.count, led.pin, led.order = 4, 18, "GRB"
    strip = open_strip(led)
    assert isinstance(strip, NeoPixel) and isinstance(strip, SkipUnchangedShow)
    assert (len(strip), strip.pin, strip.pixel_order, strip.auto_write) == (4, "pin 18", "GRB", False)
    strip._monotonic = lambda: 100.0
    strip.show()
    strip._monotonic = lambda: 100.5  # after SETTLE_SECONDS, before RESEND_SECONDS
    strip.show()
    assert len(strip.sent) == 1
