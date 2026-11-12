"""
The LED strip.

The renderer only needs what NeoPixel and adafruit_led_animation use: indexing, len(), fill(), show() and
brightness. On the Pi that's a real neopixel.NeoPixel; anywhere else it's a FakeStrip that keeps the colors in
memory, so the whole map (and its web UI) can run on a laptop.
"""

import logging
import time
from typing import List, Sequence

import metarmap.lib.colors as colors_lib

OFF = colors_lib.color(colors_lib.OFF)

# a strip whose colors haven't changed is still sent this often, so an LED that picked up a wrong color (a glitch on
# the data line) is put right
RESEND_SECONDS = 1.0
# and right after a change it's sent at every frame for this long: a glitch that garbles a pixel in the send of a new
# color (a slow fade, a blink) is put right at once, not a second later
SETTLE_SECONDS = 0.1

log = logging.getLogger(__name__)


class SkipUnchangedShow:
    """
    Mixed in before neopixel.NeoPixel: show() sends the strip only when the bytes it would send differ from what it
    last sent, or RESEND_SECONDS have passed since, and it keeps sending for SETTLE_SECONDS after a change. The render
    loop calls show() every frame (up to 100 a second), but most frames change nothing, and on the Pi each send is a
    per-pixel Python loop plus a sleep inside the library.

    It compares the library's post-brightness buffer (adafruit_pixelbuf.PixelBuf._post_brightness_buffer: exactly
    what show() hands to the strip), so a new color, fill(), clear() or brightness change is always sent. A library
    without that buffer sends every time, as before.
    """

    _sent = None  # a copy of the bytes last sent
    _sent_at = 0.0  # when, by _monotonic()
    _changed_at = float("-inf")  # when the bytes sent last differed from the ones before
    _monotonic = staticmethod(time.monotonic)
    _warned = False

    def show(self):
        buffer = getattr(self, "_post_brightness_buffer", None)
        if not isinstance(buffer, (bytearray, bytes, memoryview)):
            if not self._warned:
                self._warned = True
                log.warning("the LED library has no _post_brightness_buffer: sending the strip at every frame")
            return super().show()
        now = self._monotonic()
        same = self._sent is not None and buffer == self._sent
        if same and now - self._sent_at < RESEND_SECONDS and now - self._changed_at >= SETTLE_SECONDS:
            return None
        # copied before it's sent: if another thread changes the buffer meanwhile, the next show() sees a difference
        sent = bytes(buffer)
        result = super().show()
        if not same:
            self._changed_at = now
        self._sent, self._sent_at = sent, now
        return result

    def settling(self):
        """Whether the last change was sent less than SETTLE_SECONDS ago: the render loop keeps sending until then."""
        return self._monotonic() - self._changed_at < SETTLE_SECONDS


def skipping_unchanged(base):
    """`base` (neopixel.NeoPixel) with SkipUnchangedShow's show()."""
    return type(base.__name__, (SkipUnchangedShow, base), {"__module__": __name__})


class FakeStrip(list):
    """An in-memory LED strip. Each item is the color last set for that LED."""

    def __init__(self, count: int, brightness: float = 1.0):
        super().__init__([OFF] * count)
        self.n = count
        self.brightness = brightness
        self.auto_write = False
        self.shows = 0  # how many times show() was called

    def fill(self, color: Sequence[int]) -> None:
        self[:] = [tuple(color)] * len(self)

    def show(self) -> None:
        self.shows += 1

    def resize(self, count: int) -> None:
        """Changes the number of LEDs. New ones start dark. (A real strip's length is fixed until a restart.)"""
        self[:] = self[:count] + [OFF] * (count - len(self))
        self.n = count

    @property
    def colors(self) -> List:
        return list(self)


def open_strip(led):
    """
    Opens the NeoPixel strip described by the `led` settings, or a FakeStrip when there's no LED hardware.
    """
    try:
        import board
        import neopixel

        pin = getattr(board, f"D{led.pin}")
        order = getattr(neopixel, led.order)
    except (ImportError, NotImplementedError, AttributeError) as e:
        log.info(f"no LED hardware ({type(e).__name__}: {e}); using an in-memory strip")
        return FakeStrip(led.count, brightness=led.brightness.normal)
    strip = skipping_unchanged(neopixel.NeoPixel)
    return strip(pin, led.count, brightness=led.brightness.normal, pixel_order=order, auto_write=False)
