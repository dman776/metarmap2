"""
Turns a Look into an adafruit_led_animation animation. The only place visualizers meet the LED library.
"""
import math

from adafruit_led_animation.animation.blink import Blink
from adafruit_led_animation.animation.chase import Chase
from adafruit_led_animation.animation.colorcycle import ColorCycle
from adafruit_led_animation.animation.pulse import Pulse
from adafruit_led_animation.animation.rainbow import Rainbow
from adafruit_led_animation.animation.solid import Solid

from metarmap.models import Look

OFF = (0, 0, 0)
PULSE_SPEED = 0.1  # seconds between pulse/rainbow frames
PULSE_STEPS = 20  # brightness steps in a pulse that never goes dark


def pulse_colors(color, low):
    """
    One cycle of a pulse between full brightness and `low`, as colors for ColorCycle. (Pulse's own min_intensity
    and Blink's background_color only exist in newer versions of the LED library than older maps have.)
    """
    levels = [low + (1 - low) * (0.5 - 0.5 * math.cos(2 * math.pi * i / PULSE_STEPS)) for i in range(PULSE_STEPS)]
    return [tuple(int(round(c * level)) for c in color) for level in levels]


def animation_for(look: Look, pixel_object):
    """
    pixel_object is one LED (a PixelSubset) for per-airport looks, or the whole strip for rainbow/chase.
    """
    if look.effect == "solid":
        return Solid(pixel_object, color=look.color)
    if look.effect == "blink":
        if len(look.colors) > 1:  # alternating with a second color instead of off
            return ColorCycle(pixel_object, speed=look.period / 2, colors=list(look.colors[:2]))
        # Blink's speed is the time each of on/off lasts
        return Blink(pixel_object, speed=look.period / 2, color=look.color)
    if look.effect == "pulse":
        if look.low:  # never fully dark
            return ColorCycle(pixel_object, speed=look.period / PULSE_STEPS, colors=pulse_colors(look.color, look.low))
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
