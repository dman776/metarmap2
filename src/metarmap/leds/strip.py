"""
The LED strip.

The renderer only needs what NeoPixel and adafruit_led_animation use: indexing, len(), fill(), show() and
brightness. On the Pi that's a real neopixel.NeoPixel; anywhere else it's a FakeStrip that keeps the colors in
memory, so the whole map (and its web UI) can run on a laptop.
"""
from typing import List, Sequence

from metarmap.lib.safe_logging import safe_log


class FakeStrip(list):
    """An in-memory LED strip. Each item is the color last set for that LED."""

    def __init__(self, count: int, brightness: float = 1.0):
        super().__init__([(0, 0, 0)] * count)
        self.n = count
        self.brightness = brightness
        self.auto_write = False
        self.shows = 0  # how many times show() was called

    def fill(self, color: Sequence[int]) -> None:
        self[:] = [tuple(color)] * len(self)

    def show(self) -> None:
        self.shows += 1

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
        safe_log(f"[l]no LED hardware ({type(e).__name__}: {e}); using an in-memory strip")
        return FakeStrip(led.count, brightness=led.brightness.normal)
    return neopixel.NeoPixel(pin, led.count, brightness=led.brightness.normal, pixel_order=order, auto_write=False)
