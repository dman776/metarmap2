import time
import displaymetar

try:
    from board import SCL, SDA
    import busio
    from PIL import Image, ImageDraw, ImageFont
    import adafruit_ssd1306
    import time
    from pytz import timezone
    import pytz
    noDisplayLibraries = False
except ImportError as e:
    print("NO display libs!")
    print(e)
    noDisplayLibraries = True

fontLarge = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf', 20)
fontMed = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', 15)
fontSmall = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', 12)
fontXSmall = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', 10)

padding = -3
x = 0



disp = displaymetar.startDisplay()

width = disp.width
height = disp.height
image1 = Image.new("1", (width, height))
draw1 = ImageDraw.Draw(image1)
# Draw a black filled box to clear the image.
draw1.rectangle((0, 0, width, height), outline=0, fill=0)

top = padding
bottom = height - padding

# draw.line([(x + 85, top + 18), (x + 85, bottom)], fill=255, width=1)
central = timezone('US/Central')
draw1.text((x, top + 0), "KDWH-VFR", font=fontLarge, fill=255)  # StationID, Condition (VFR/IFR)
w, h = fontXSmall.getsize("KDWH")
draw1.text((width - w, top + 1), "Hooks", font=fontXSmall, fill=255)  # Custom text ("HOME", "CNTRL" etc)

draw1.text((x, top + 20), "170@5G10/10SM ", font=fontMed, fill=255)
draw1.text((x, top + 35), "29.92Hg 10/2C", font=fontMed, fill=255)
draw1.text((x, top + 50), "16:20 21:22Z", font=fontSmall, fill=255)
draw1.text((x, top + 65), "testline12345", font=fontSmall, fill=255)
disp.image(image1)
disp.show()


time.sleep(10)

displaymetar.shutdownDisplay(disp)



