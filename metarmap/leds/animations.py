"""
Turns a Look into an adafruit_led_animation animation. The only place visualizers meet the LED library.
"""
from adafruit_led_animation.animation.blink import Blink
from adafruit_led_animation.animation.chase import Chase
from adafruit_led_animation.animation.colorcycle import ColorCycle
from adafruit_led_animation.animation.pulse import Pulse
from adafruit_led_animation.animation.rainbow import Rainbow
from adafruit_led_animation.animation.solid import Solid

from metarmap.models import Look

OFF = (0, 0, 0)
PULSE_SPEED = 0.1  # seconds between pulse/rainbow frames


def animation_for(look: Look, pixel_object):
    """
    pixel_object is one LED (a PixelSubset) for per-airport looks, or the whole strip for rainbow/chase.
    """
    if look.effect == "solid":
        return Solid(pixel_object, color=look.color)
    if look.effect == "blink":
        # Blink's speed is the time each of on/off lasts
        return Blink(pixel_object, speed=look.period / 2, color=look.color)
    if look.effect == "pulse":
        return Pulse(pixel_object, speed=PULSE_SPEED, period=look.period, color=look.color)
    if look.effect == "cycle":
        return ColorCycle(pixel_object, speed=look.step, colors=list(look.colors))
    if look.effect == "rainbow":
        return Rainbow(pixel_object, period=look.period, speed=PULSE_SPEED, precompute_rainbow=True)
    if look.effect == "chase":
        return Chase(pixel_object, speed=look.step, size=look.size, spacing=look.spacing, color=look.color)
    if look.effect == "off":
        return Solid(pixel_object, color=OFF)
    raise ValueError(f"unknown effect {look.effect!r}")
