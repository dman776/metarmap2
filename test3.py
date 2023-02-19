import time
import busio
from board import SCL, SDA

from oled_text import OledText, Layout64, BigLine, SmallLine

""" Examples for a 128x64 px SSD1306 oled display. """

i2c = busio.I2C(SCL, SDA)

# Instantiate the display, passing its dimensions (128x64 or 128x32)
oled = OledText(i2c, 128, 64)

# A single FontAwesome icon (https://fontawesome.com/cheatsheet/free/solid)
oled.layout = Layout64.layout_icon_only()
oled.text('\uf743', 1)  # cloud-sun-rain
time.sleep(2)

# # Output 5 lines (with auto_draw on, the display is painted after every line)
# oled.layout = Layout64.layout_5small()
# for i in range(1, 6):
#     oled.text("Hello Line {}".format(i), i)
# time.sleep(1)

# # Replacing a single line (keeps the other lines)
# oled.text("Brave new line", 2)
# time.sleep(1)

# Setting multiple lines with manual .show() (only one display refresh)
# oled.layout = Layout64.layout_1big_3small()
# oled.auto_show = False
# oled.text("METARMAP", 1)
# oled.text("Darryl Quinn", 2)
# oled.text("dman776@gmail.com", 3)
# oled.text("Aviation", 4)
# oled.show()
# oled.auto_show = True
# time.sleep(5)

offset = -3
page_layout = []
page_layout.append({
    1: BigLine(0, offset, size=20),                                         # AIRPORT
    2: BigLine(90, offset, size=16),                                        # CAT
    3: BigLine(0, 19 + offset),                                             # wind
    4: BigLine(110, 19 + offset, font="FontAwesomeSolid.ttf", size=14),     # wind ico
    5: BigLine(0, 36 + offset),                                             # vis
    6: BigLine(110, 36 + offset, font="FontAwesomeSolid.ttf", size=14),     # vis ico
    7: BigLine(0, 52 + offset),                                             # pressure
    8: BigLine(116, 52 + offset, font="FontAwesomeSolid.ttf", size=14)      # pressure ico
})

page_layout.append({
    1: BigLine(0, offset, size=20),                                         # AIRPORT
    2: BigLine(90, offset, size=16),                                        # CAT
    3: BigLine(0, 19 + offset),                                             # temp
    4: BigLine(110, 19 + offset, font="FontAwesomeSolid.ttf", size=14),     # temp ico
    5: BigLine(0, 36 + offset),                                             # dew
    6: BigLine(110, 36 + offset, font="FontAwesomeSolid.ttf", size=14),     # dew ico
    7: BigLine(0, 52 + offset),                                             # time
    8: BigLine(110, 52 + offset, font="FontAwesomeSolid.ttf", size=14)      # time ico
})



oled.layout = page_layout[0]
oled.auto_show = False
oled.text("KDWH")
oled.text("LIFR", 2)
oled.text("170@12G12", 3)
oled.text('\uf72e', 4)
oled.text("10 SM", 5)
oled.text('\uf0c2', 6)
oled.text("29.92", 7)
oled.text('\uf338', 8)
oled.show()
time.sleep(5)

oled.layout = page_layout[1]
oled.text("KDWH")
oled.text("LIFR", 2)
oled.text("10C / 50F", 3)
oled.text('\uf76b', 4)
oled.text("03C / 37F", 5)
oled.text('\uf73d', 6)
oled.text("12:34C 16:34Z", 7)
oled.text('\uf017', 8)
oled.show()
time.sleep(5)

oled.auto_show = True




# # A panel with 3 lines and 3 icons to the right
# oled.layout = Layout64.layout_3medium_3icons()
# oled.auto_show = False
# oled.text("170@12G12", 1)
# oled.text("10SM", 2)
# oled.text("12.3/02.2", 3)
# oled.text('\uf72e', 4)
# oled.text('\uf0c2', 5)
# oled.text('\uf76b', 6)
# oled.show()
# time.sleep(8)
# oled.auto_show = True


# # With a FontAwesome icon (https://fontawesome.com/cheatsheet/free/solid)
# oled.layout = Layout64.layout_icon_1big_2small()
# oled.auto_show = False
# oled.text('\uf58b', 1)
# oled.text("Meow!", 2)
# oled.text("I am the", 3)
# oled.text("cool cat", 4)
# oled.show()
# oled.auto_show = True
# time.sleep(3)

# Use a custom display layout
# Either use the provided fonts, or give a full path to your own
# oled.layout = {
#     1: SmallLine(0, 0),
#     2: BigLine(5, 15, font="Arimo.ttf", size=24),
#     3: BigLine(5, 40, font="Crisp.ttf", size=18)
# }
# oled.text("I want my layout!")
# oled.text("Custom 1", 2)
# oled.text("Custom 2", 3)
# time.sleep(5)

# Adding own graphics using an onDraw handler
# oled.layout = Layout64.layout_1big_center()
# oled.on_draw = lambda draw: draw.rectangle((0, 0, 127, 63), outline=255, fill=0)
# oled.text("The Fat Cat", 1)

time.sleep(4)
oled.clear()