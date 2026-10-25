"""
Screen drivers: the real 128x64 SSD1306 OLED and an in-memory FakeScreen.

A driver only needs show(screen) and clear(); `screen` is a dict from metarmap.oled.screens.
"""
from typing import Callable, List, Optional

from metarmap.lib.safe_logging import safe_log

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

    def __init__(self):
        from board import SCL, SDA
        import busio
        from oled_text import OledText, BigLine
        import adafruit_ssd1306  # noqa: F401 (oled_text needs it; fail early if missing)

        self.__oled__ = OledText(busio.I2C(SCL, SDA), self.WIDTH, self.HEIGHT)
        self.__oled__.auto_show = False
        self.__layouts__ = self.__make_layouts__(BigLine)

    def __make_layouts__(self, BigLine):
        o = self.OFFSET
        icon = dict(font="FontAwesomeSolid.ttf", size=14)
        message = {
            1: BigLine(0, o, size=20),  # TITLE
            2: BigLine(110, o, font="FontAwesomeSolid.ttf", size=12),  # msg ico
            3: BigLine(0, 19 + o),  # line 1
            4: BigLine(0, 36 + o),  # line 2
            5: BigLine(0, 52 + o),  # line 3
        }

        def airport(last_icon_x):
            return {
                1: BigLine(0, o, size=20),  # AIRPORT
                2: BigLine(80, o, size=16),  # CAT
                3: BigLine(20, 19 + o),  # line 1
                4: BigLine(0, 19 + o, **icon),
                5: BigLine(20, 36 + o),  # line 2
                6: BigLine(0, 36 + o, **icon),
                7: BigLine(20, 52 + o),  # line 3
                8: BigLine(last_icon_x, 52 + o, **icon),
            }
        # page 1's pressure icon sits a little to the right; page 0 (no data) uses page 1's layout
        return {"message": message, 1: airport(6), 2: airport(0)}

    def show(self, screen: dict) -> None:
        oled = self.__oled__
        if screen["kind"] == "message":
            oled.layout = self.__layouts__["message"]
            oled.text(screen["title"])
            oled.text(GLYPHS.get(screen.get("icon", ""), ""), 2)
            for n, line in enumerate(screen["lines"]):
                oled.text(line["text"], 3 + n)
        else:
            oled.layout = self.__layouts__[2 if screen["page"] == 2 else 1]
            oled.text(screen["title"])
            oled.text(screen["badge"], 2)
            for n, line in enumerate(screen["lines"]):
                oled.text(line["text"], 3 + n * 2)
                oled.text(GLYPHS[line["icon"]], 4 + n * 2)
        oled.show()

    def clear(self) -> None:
        self.__oled__.clear()


def open_screen():
    """The real OLED on the Pi, or a FakeScreen when it isn't available."""
    try:
        return SSD1306Screen()
    except (ImportError, NotImplementedError, OSError, ValueError, RuntimeError) as e:
        safe_log(f"[d]no OLED screen ({type(e).__name__}: {e}); using an in-memory screen")
        return FakeScreen()
