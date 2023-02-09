import neopixel
import board
from adafruit_led_animation.helper import PixelSubset
from adafruit_led_animation.animation.blink import Blink
from adafruit_led_animation.animation.sparklepulse import SparklePulse
from adafruit_led_animation.animation.comet import Comet
from adafruit_led_animation.animation.chase import Chase
from adafruit_led_animation.animation.pulse import Pulse
from adafruit_led_animation.animation.sparkle import Sparkle
from adafruit_led_animation.animation.rainbowchase import RainbowChase
from adafruit_led_animation.animation.rainbowsparkle import RainbowSparkle
from adafruit_led_animation.animation.rainbowcomet import RainbowComet
from adafruit_led_animation.animation.solid import Solid
from adafruit_led_animation.animation.colorcycle import ColorCycle
from adafruit_led_animation.animation.rainbow import Rainbow
from adafruit_led_animation.animation.customcolorchase import CustomColorChase
from adafruit_led_animation.sequence import AnimationSequence
from adafruit_led_animation.group import AnimationGroup
from adafruit_led_animation.color import PURPLE, WHITE, AMBER, JADE, MAGENTA, ORANGE, BLUE, AQUA, RED, GREEN, YELLOW

pixel_pin = board.D18
num_pixels = 50
pixels = neopixel.NeoPixel(pixel_pin, num_pixels, pixel_order=neopixel.GRB, auto_write=False)

pix=[]
effect=[]

try:
    for i in range(0, 49):
        pix[i] = PixelSubset(pixels, i, i+1)
except IndexError as e:
    print(str(i) + " " + str(e.args))

effect0 = Pulse(pix[0], speed=0.05, period=1, color=WHITE)
effect1 = Pulse(pix[1], speed=0.07, period=1, color=YELLOW)
effect2 = Solid(pix[2], color=GREEN)


blink = Blink(pixels, speed=0.5, color=RED)
colorcycle = ColorCycle(pixels, speed=0.4, colors=[BLUE, AQUA])
comet = Comet(pixels, speed=0.01, color=PURPLE, tail_length=10, bounce=True)
chase = Chase(pixels, speed=0.1, size=3, spacing=6, color=WHITE)
pulse = Pulse(pixels, speed=0.1, period=3, color=BLUE)
sparkle = Sparkle(pixels, speed=0.1, color=PURPLE, num_sparkles=10)
solid = Solid(pixels, color=GREEN)
rainbow = Rainbow(pixels, speed=0.1, period=2)
sparkle_pulse = SparklePulse(pixels, speed=0.1, period=3, color=JADE)
rainbow_comet = RainbowComet(pixels, speed=0.1, tail_length=7, bounce=True)
rainbow_chase = RainbowChase(pixels, speed=0.1, size=3, spacing=2, step=8)
rainbow_sparkle = RainbowSparkle(pixels, speed=0.1, num_sparkles=15)
custom_color_chase = CustomColorChase(
    pixels, speed=0.1, size=2, spacing=3, colors=[ORANGE, WHITE, JADE]
)

animations = AnimationSequence(
    AnimationGroup(
        effect0,
        effect1,
        effect2,
    ),
    # comet,
    # one_pulse,
    # blink,
    # rainbow_sparkle,
    # chase,
    # pulse,
    # sparkle,
    # rainbow,
    # solid,
    # rainbow_comet,
    # sparkle_pulse,
    # rainbow_chase,
    # custom_color_chase,
    advance_interval=5,
    auto_clear=True,
)

while True:
    animations.animate()




