"""
Screen drivers: the real 128x64 SSD1306 OLED and an in-memory FakeScreen.

A driver only needs show(screen) and clear(); `screen` is a dict from metarmap.oled.screens.
"""

import logging
from typing import Callable, List, Optional

log = logging.getLogger(__name__)


# FontAwesome glyphs for the icon names in metarmap.oled.screens
GLYPHS = {
    "info": "",
    "wind": "",
    "visibility": "",
    "pressure": "",
    "temp": "",
    "dewpoint": "",
    "date": "",
    "": "",
}

# the splash screen's logo: the web UI's airplane (favicon.svg's path), drawn 1 px to a "#"
LOGO = (
    ".....................................#####..",
    "...................................########.",
    ".................................##########.",
    "................................#######.####",
    "...............................#####.....###",
    "..............................####......####",
    ".............................####.......###.",
    "............................####........###.",
    "...#######.................####........####.",
    "..#############...........####........####..",
    "..##################.....####.........####..",
    ".####....###################.........####...",
    ".####........##############.........####....",
    ".#####............########.........####.....",
    "..#####...............###.........####......",
    "...######........................####.......",
    "....######......................####........",
    "......######...................####.........",
    ".......######.................####..........",
    ".........######..............####...........",
    "..........######.............####...........",
    "............#####............####...........",
    ".............####.............###...........",
    "............####..............###...........",
    "............####..............####..........",
    "...........####...............####..........",
    "..........####.................###..........",
    "...###########.......##........###..........",
    "..###########......#####.......###..........",
    ".###########......#######......####.........",
    ".####...........#########......####.........",
    ".#####.........######.####......###.........",
    "..######......#####....####.....###.........",
    "...######.....####.....####.....###.........",
    ".....#####....###.......####....####........",
    "......#####...###........####....###........",
    "........####..###........####....###........",
    "........####..###.........####...###........",
    ".........####.###..........####..###........",
    "..........#######..........#########........",
    "..........#######...........########........",
    "...........#####.............######.........",
    "............###...............###...........",
)


class FakeScreen:
    """Keeps what would have been drawn. Used off the Pi, and in tests."""

    def __init__(self, on_show: Optional[Callable[[dict], None]] = None):
        self.shown: List[dict] = []
        self.current: Optional[dict] = None
        self.on_show = on_show  # called after each show(); tests use it to stop or fail on cue

    def show(self, screen: dict) -> None:
        self.current = screen
        self.shown.append(screen)
        if self.on_show:
            self.on_show(screen)

    def clear(self) -> None:
        self.current = None


class SSD1306Screen:
    """The 128x64 I2C OLED, drawn with oled_text."""

    WIDTH, HEIGHT = 128, 64
    OFFSET = -3
    TOP = 16  # rows 0-15 are yellow on a two-color OLED, the rest blue

    def __init__(self):
        from board import SCL, SDA
        import busio
        from oled_text import OledText, BigLine
        import adafruit_ssd1306  # noqa: F401 (oled_text needs it; fail early if missing)

        self._oled = OledText(busio.I2C(SCL, SDA), self.WIDTH, self.HEIGHT)
        self._oled.auto_show = False
        self._layouts = self._make_layouts(BigLine)

    def _make_layouts(self, BigLine):
        o = self.OFFSET
        icon = dict(font="FontAwesomeSolid.ttf", size=14)
        message = {
            1: BigLine(0, o, size=20),  # TITLE
            2: BigLine(110, o, font="FontAwesomeSolid.ttf", size=12),  # msg ico
            3: BigLine(0, 19 + o),  # line 1
            4: BigLine(0, 36 + o),  # line 2
            5: BigLine(0, 52 + o),  # line 3
        }

        def airport(last_icon_x, virtual=False):
            return {
                # a virtual airport's code is the category's size and moved in, to fit its dashed box at the top
                # (rows 0-15; see dashed_box)
                1: BigLine(2, o + 2, size=16) if virtual else BigLine(0, o, size=20),  # AIRPORT
                # x=76 leaves room for "MVFR*" (51 px) and still clears the widest K??? code (KWWW, 70 px)
                2: BigLine(76, o, size=16),  # CAT
                3: BigLine(20, 19 + o),  # line 1
                4: BigLine(0, 19 + o, **icon),
                5: BigLine(20, 36 + o),  # line 2
                6: BigLine(0, 36 + o, **icon),
                7: BigLine(20, 52 + o),  # line 3
                8: BigLine(last_icon_x, 52 + o, **icon),
            }

        # the splash: "MetarMap2" centered on the yellow rows (the logo is drawn below it, in show())
        title = BigLine(0, 0, size=18)
        left, top, right, bottom = title.font.getbbox("MetarMap2")
        title.x = (self.WIDTH - (right - left)) // 2 - left
        title.y = (self.TOP - (bottom - top)) // 2 - top

        # page 1's pressure icon sits a little to the right; page 0 (no data) uses page 1's layout
        return {
            "splash": {1: title},
            "message": message,
            1: airport(6),
            2: airport(0),
            (1, "virtual"): airport(6, virtual=True),
            (2, "virtual"): airport(0, virtual=True),
        }

    def show(self, screen: dict) -> None:
        oled = self._oled
        if screen.get("splash"):
            oled.layout = self._layouts["splash"]
            oled.text(screen["title"])
        elif screen["kind"] == "message":
            oled.layout = self._layouts["message"]
            oled.text(screen["title"])
            oled.text(GLYPHS.get(screen.get("icon", ""), ""), 2)
            for n, line in enumerate(screen["lines"]):
                oled.text(line["text"], 3 + n)
        else:
            page = 2 if screen["page"] == 2 else 1
            oled.layout = self._layouts[(page, "virtual") if screen.get("virtual") else page]
            oled.text(screen["title"])
            oled.text(screen["badge"], 2)
            for n, line in enumerate(screen["lines"]):
                oled.text(line["text"], 3 + n * 2)
                oled.text(GLYPHS[line["icon"]], 4 + n * 2)
        # drawn before the text, each time the screen is
        title = oled.layout[1]
        if screen.get("splash"):
            oled.on_draw = lambda draw: draw.point(logo_points(self.WIDTH, self.TOP, self.HEIGHT), fill=255)
        elif screen["kind"] == "airport" and screen.get("virtual"):
            oled.on_draw = lambda draw: dashed_rectangle(draw, dashed_box(title, screen["title"]))
        else:
            oled.on_draw = None
        oled.show()

    def clear(self) -> None:
        self._oled.clear()


def logo_points(width, top, bottom):
    """The logo's pixels as (x, y), centered across the screen and between rows `top` and `bottom`."""
    left = (width - len(LOGO[0])) // 2
    top += (bottom - top - len(LOGO)) // 2
    return [(left + x, top + y) for y, row in enumerate(LOGO) for x, c in enumerate(row) if c == "#"]


def dashed_box(line, text, pad=2):
    """
    The box around `text` drawn on `line` (an oled_text line: x, y, font), `pad` pixels clear of the letters, as
    (left, top, right, bottom). A virtual airport's 16 px code puts it in rows 0-15, 3 px above the first line's
    letters.
    """
    left, top, right, bottom = line.font.getbbox(text)
    return (
        max(0, line.x + left - pad),
        max(0, line.y + top - pad),
        line.x + right + pad - 1,
        line.y + bottom + pad - 1,
    )


def dashed_rectangle(draw, box, dash=2, gap=2):
    """A dashed outline (PIL's ImageDraw has none): `box` is (left, top, right, bottom), each pixel included."""
    left, top, right, bottom = box
    for x in range(left, right + 1, dash + gap):
        end = min(x + dash - 1, right)
        draw.line((x, top, end, top), fill=255)
        draw.line((x, bottom, end, bottom), fill=255)
    for y in range(top, bottom + 1, dash + gap):
        end = min(y + dash - 1, bottom)
        draw.line((left, y, left, end), fill=255)
        draw.line((right, y, right, end), fill=255)


def open_screen():
    """The real OLED on the Pi, or a FakeScreen when it isn't available."""
    try:
        return SSD1306Screen()
    except (ImportError, NotImplementedError, OSError, ValueError, RuntimeError) as e:
        log.info(f"no OLED screen ({type(e).__name__}: {e}); using an in-memory screen")
        return FakeScreen()
