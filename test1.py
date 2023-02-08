import neopixel
import board
from adafruit_led_animation.animation.blink import Blink
import adafruit_led_animation.color as color

pixel_pin = board.D18
num_pixels = 50
pixels = neopixel.NeoPixel(pixel_pin, num_pixels, led_order=neopixel.GRB)
blink = Blink(pixels, 0.5, color.PURPLE)

while True:
    blink.animate()

