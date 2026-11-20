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
# and right after a change it's sent again: at the next frame whenever that comes, and at every frame for this long. A
# glitch that garbles a pixel in the send of a new color (a fade, a blink) is put right at once, not a second later.
# Shorter than the shortest animation step (lightning's 0.05 s; a forecast or a breath steps every 0.2 s), so the
# window ends between two steps: at 0.1 s it never did during lightning, and the render loop drew a frame at every
# tick (100 a second) for as long as an LED flickered. 0.03 s still takes in the frames right after the change (the
# loop's next one, 0.01-0.05 s later, is resent anyway, however slow the Pi's frames are)
SETTLE_SECONDS = 0.03

log = logging.getLogger(__name__)


class SkipUnchangedShow:
    """
    Mixed in before neopixel.NeoPixel: show() sends the strip only when the bytes it would send differ from what it
    last sent, or RESEND_SECONDS have passed since; after a change it sends once more at the next show(), and at every
    show() for SETTLE_SECONDS. The render loop calls show() every frame (up to 100 a second), but most frames change
    nothing, and on the Pi each send is a per-pixel Python loop plus a sleep inside the library.

    It compares the library's post-brightness buffer (adafruit_pixelbuf.PixelBuf._post_brightness_buffer: exactly
    what show() hands to the strip), so a new color, fill(), clear() or brightness change is always sent. A library
    without that buffer sends every time, as before.
    """

    _sent = None  # a copy of the bytes last sent
    _sent_at = 0.0  # when, by _monotonic()
    _changed_at = float("-inf")  # when the bytes sent last differed from the ones before
    _resent = True  # whether the last change has been sent again since (the settling resend)
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
        settled = self._resent and now - self._changed_at >= SETTLE_SECONDS
        if same and now - self._sent_at < RESEND_SECONDS and settled:
            return None
        # copied before it's sent: if another thread changes the buffer meanwhile, the next show() sees a difference
        sent = bytes(buffer)
        result = super().show()
        if same:
            self._resent = True
        else:
            self._changed_at, self._resent = now, False
        self._sent, self._sent_at = sent, now
        return result

    def settling(self):
        """
        Whether the last change is still to be sent again: the render loop draws its next frame soon (a tick, not
        when the next animation is due), and that frame's show() resends it. Ends there, between animation steps.
        """
        return not self._resent


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


class PixelGroup:
    """
    Some LEDs of a strip, anywhere along it, as one pixel object: the renderer draws one animation into it for every
    LED with the same look (Renderer._rebuild), so it runs once a frame instead of once per LED. Writes go straight to
    the strip (like adafruit_led_animation's PixelSubset, for LEDs that need not be next to each other); item i is the
    i-th LED in `leds`. What the per-airport animations use: fill(), indexing, len(), show() and auto_write.
    """

    def __init__(self, strip, leds: Sequence[int]):
        if not leds:
            raise ValueError("a PixelGroup needs at least one LED")
        self._strip = strip
        self.leds = tuple(leds)  # the LED numbers on the strip, in order
        self.n = len(self.leds)
        self.auto_write = False  # the renderer sends the strip once a frame

    def __len__(self) -> int:
        return self.n

    def __getitem__(self, i):
        if isinstance(i, slice):
            return [self._strip[n] for n in self.leds[i]]
        return self._strip[self.leds[i]]

    def __setitem__(self, i, color) -> None:
        if isinstance(i, slice):
            leds = self.leds[i]
            if len(color) != len(leds):
                raise ValueError("slice and colors differ in length")
            for n, c in zip(leds, color):
                self._strip[n] = c
        else:
            self._strip[self.leds[i]] = color

    def fill(self, color) -> None:
        strip = self._strip
        for n in self.leds:
            strip[n] = color

    def show(self) -> None:
        self._strip.show()

    def __repr__(self) -> str:
        return f"PixelGroup({list(self.leds)})"


class UnopenedStrip(FakeStrip):
    """The strip of a Pi with led.count 0: no NeoPixel is made, and it can't change length (a restart is needed)."""

    resize = None


def open_strip(led):
    """
    Opens the NeoPixel strip described by the `led` settings, or a FakeStrip when there's no LED hardware.
    """
    if led.count == 0:  # a map of virtual airports only: the pin is left alone, no NeoPixel is made
        try:
            import board
            import neopixel
        except (ImportError, NotImplementedError):
            return FakeStrip(0, brightness=led.brightness.normal)
        # on a Pi the strip can't grow: more pixels take effect after a restart, as with a NeoPixel strip
        return UnopenedStrip(0, brightness=led.brightness.normal)
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
