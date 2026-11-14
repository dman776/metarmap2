"""
Tests for the Hidden Pixel (settings.Airport.skip): an LED wired into the string that shows nothing and is not an
airport. The config rules, what the renderer does with one (Rainbow and Chase leave it dark), what Apply writes for a
plan's hidden pixels, and that the live API does not list them.
"""

import json
import logging
import threading
from types import SimpleNamespace

import pytest
from test_planner_apply_web import APPLY, PREVIEW, get, planned, post
from test_planner_apply_web import make as apply_make  # noqa: F401  (a fixture: a client for a map with a planner)

from metarmap.clock import FakeClock
from metarmap.config import MAX_LEDS, Config, tidy_hidden
from metarmap.leds.strip import FakeStrip, SkipUnchangedShow
from metarmap.models import Report
from metarmap.planner import apply as plan_apply
from metarmap.renderer import Renderer
from metarmap.settings import Airport, Settings
from metarmap.sun import SunTimes
from metarmap.visualizers import chase, flightcategory, rainbow
from metarmap.web import views

FLIGHT, RAINBOW, CHASE = (m.VISUALIZER for m in (flightcategory, rainbow, chase))


def hidden():
    return Airport(skip=True)


@pytest.fixture
def plan_client(request):
    """A client for a map with a planner, its airports all on the Houston chart (see test_planner_apply_web)."""
    return request.getfixturevalue("apply_make")()


def make_config(tmp_path, airports, led_count=None, virtual=0, **settings):
    """A Config on a file in tmp_path: `airports` in LED order, led_count of them on the strip (default: all)."""
    st = Settings()
    st.airports = list(airports)
    st.led.count = len(airports) - virtual if led_count is None else led_count
    st.led.virtual_count = virtual
    for key, value in settings.items():
        st.set(key, value)
    path = tmp_path / "config.json"
    st.save(path)
    return Config(str(path))


def keys_of(config):
    """The keys the config publishes from now on (a list the test reads)."""
    seen = []
    config.subscribe("*", lambda keys: seen.extend(keys))
    return seen


# ---- the file ---------------------------------------------------------------------------------------------------


def test_skip_is_only_written_when_it_is_true(tmp_path):
    config = make_config(tmp_path, [Airport(code="KHOU"), hidden(), Airport()])
    config.write()
    saved = json.loads((tmp_path / "config.json").read_text())["airports"]
    assert saved[0] == {"code": "KHOU", "name": "", "display": False}  # an older config.json stays as it was
    assert saved[1]["skip"] is True
    assert "skip" not in saved[2]
    assert [a.skip for a in Config(str(tmp_path / "config.json")).airports] == [False, True, False]


def test_an_older_config_has_no_hidden_pixels(tmp_path):
    config = make_config(tmp_path, [Airport(code="KHOU"), Airport(), Airport(code="KIAH")])
    assert not any(a.skip for a in config.airports)
    assert config.airports[1].code == ""  # a blank LED is still just a blank LED


# ---- the switch -------------------------------------------------------------------------------------------------


def test_the_switch_turns_on_and_off_and_publishes_only_a_change(tmp_path):
    config = make_config(tmp_path, [Airport(code="KHOU"), Airport(), Airport(code="KIAH")])
    seen = keys_of(config)
    config.set_airport(1, "skip", "true")
    assert config.airports[1].skip is True and seen == ["airports.skip"]
    config.set_airport(1, "skip", "true")  # already on: nothing changes
    assert seen == ["airports.skip"]
    config.set_airport(1, "skip", "false")
    assert config.airports[1].skip is False and seen == ["airports.skip", "airports.skip"]
    assert json.loads((tmp_path / "config.json").read_text())["airports"][1].get("skip") is None


def test_the_switch_is_refused_for_an_led_with_an_airport(tmp_path):
    config = make_config(tmp_path, [Airport(code="KHOU"), Airport()])
    seen = keys_of(config)
    with pytest.raises(ValueError, match=r"pixel 1 has the airport KHOU: remove the airport first"):
        config.set_airport(0, "skip", "true")
    assert not config.airports[0].skip and seen == []


def test_the_switch_is_refused_for_a_virtual_airport(tmp_path):
    config = make_config(tmp_path, [Airport(code="KHOU"), Airport(), Airport()], led_count=2, virtual=1)
    with pytest.raises(ValueError, match=r"virtual airport 1 has no pixel"):
        config.set_airport(2, "skip", "true")
    assert not config.airports[2].skip


def test_turning_it_on_takes_the_oled_flag_off(tmp_path):
    config = make_config(tmp_path, [Airport(), Airport(code="KHOU")])
    config.set_airport(0, "display", "true")
    assert config.airports[0].display
    config.set_airport(0, "skip", "true")
    assert config.airports[0].skip and not config.airports[0].display


def test_a_code_on_a_hidden_pixel_is_refused_until_the_switch_is_off(tmp_path):
    config = make_config(tmp_path, [hidden(), Airport(code="KHOU")])
    with pytest.raises(
        ValueError, match=r"pixel 1 is a Hidden Pixel: turn Hidden Pixel off before giving it the airport KIAH"
    ):
        config.set_airport(0, "code", "kiah")
    assert config.airports[0].code == "" and config.airports[0].skip
    config.set_airport(0, "code", "-")  # clearing a code that is not there is fine
    config.set_airport(0, "skip", "false")
    config.set_airport(0, "code", "kiah")
    assert config.airports[0].code == "KIAH" and not config.airports[0].skip


def test_a_hidden_pixel_takes_no_oled_flag_and_no_mock_metar(tmp_path):
    config = make_config(tmp_path, [hidden(), Airport(code="KHOU")], dev_mode=False)
    with pytest.raises(ValueError, match="it has no airport to show on the OLED"):
        config.set_airport(0, "display", "true")
    config._data.dev_mode = True
    with pytest.raises(ValueError, match="this LED has no airport"):
        config.set_mock_metar(0, "KHOU 121753Z 18005KT 10SM CLR 25/15 A3000")
    config.set_airport(0, "display", "false")  # off is how it already is


def test_the_by_code_edit_cannot_give_a_hidden_pixel_an_airport(tmp_path):
    config = make_config(tmp_path, [hidden(), Airport(code="KHOU")])
    with pytest.raises(ValueError, match="is a Hidden Pixel"):
        config.edit_airport("", "KIAH")  # the older by-code route finds the first LED with no airport: this one
    assert config.airports[0].code == "" and config.airports[0].skip


# ---- moving rows, counting LEDs, hand-edited files --------------------------------------------------------------


def test_a_hidden_pixel_moves_with_its_row(tmp_path):
    config = make_config(tmp_path, [Airport(code="KHOU"), hidden(), Airport(code="KIAH"), Airport()])
    config.move_airport(1, 3)
    assert [(a.code, a.skip) for a in config.airports] == [("KHOU", False), ("KIAH", False), ("", False), ("", True)]


def test_a_hidden_pixel_cannot_be_moved_among_the_virtual_airports(tmp_path):
    config = make_config(
        tmp_path, [Airport(code="KHOU"), hidden(), Airport(code="KIAH"), Airport(code="KGLS")], led_count=2, virtual=2
    )
    before = [(a.code, a.skip) for a in config.airports]
    seen = keys_of(config)
    with pytest.raises(ValueError, match="push a Hidden Pixel off the strip"):
        config.move_airport(1, 3)
    # and a move that shifts the last LED (a hidden one) past the strip's end is refused the same way
    with pytest.raises(ValueError, match="push a Hidden Pixel off the strip"):
        config.move_airport(3, 0)
    assert [(a.code, a.skip) for a in config.airports] == before and seen == []


def test_the_strip_grows_with_plain_blanks_and_shrinks_from_the_end(tmp_path):
    config = make_config(tmp_path, [Airport(code="KHOU"), hidden(), Airport(code="KIAH"), hidden()])
    config.set_led_count(5)
    assert [a.skip for a in config.airports] == [False, True, False, True, False]  # the new LED is a plain blank
    config.set_led_count(2)
    assert [(a.code, a.skip) for a in config.airports] == [("KHOU", False), ("", True)]


def test_hand_edited_flags_are_tidied(tmp_path, caplog):
    path = tmp_path / "config.json"
    st = Settings()
    st.led.count = 3
    st.led.virtual_count = 1
    st.airports = [Airport(code="KHOU", skip=True), Airport(skip=True, display=True), Airport(), Airport(skip=True)]
    st.save(path)
    with caplog.at_level(logging.WARNING):
        config = Config(str(path))
    assert [(a.code, a.skip, a.display) for a in config.airports] == [
        ("KHOU", False, False),  # it has an airport: the flag goes, the airport stays
        ("", True, False),  # a hidden pixel with an OLED flag: the flag is dropped
        ("", False, False),
        ("", False, False),  # past the strip: there is no LED to hide
    ]
    assert "is not a Hidden Pixel any more" in caplog.text
    assert "OLED flag is cleared" in caplog.text  # the dropped flag is said, not silent
    assert tidy_hidden(config.airports, 3) == 0  # and it stays tidy


ODD_FLAGS = [
    (True, True),  # the real thing: left alone, no warning
    ("true", True),
    ("TRUE", True),
    (" True ", True),
    (1, True),
    (1.0, True),
    (False, False),
    ("false", False),  # someone typing "false" to un-hide a pixel must not hide it
    ("False", False),
    (0, False),
    (None, False),
    ("", False),
    ("yes please", False),
    (2, False),
    ([], False),
    ({}, False),
]


@pytest.mark.parametrize("raw, hidden_after", ODD_FLAGS, ids=repr)
def test_a_skip_that_is_not_a_true_or_false_is_read_as_one(tmp_path, caplog, raw, hidden_after):
    path = tmp_path / "config.json"
    st = Settings()
    st.led.count = 2
    st.airports = [Airport(), Airport()]
    st.save(path)
    data = json.loads(path.read_text())
    data["airports"][0]["skip"] = raw  # what a hand-edited file can hold
    path.write_text(json.dumps(data))
    with caplog.at_level(logging.WARNING):
        config = Config(str(path))
    assert config.airports[0].skip is hidden_after  # a real bool, whatever the file said
    assert ("skip is" in caplog.text) == (raw is not hidden_after)  # a changed value is warned about, once
    config.write()
    saved = json.loads(path.read_text())["airports"][0]
    assert ("skip" in saved) == hidden_after  # only written while true: a null does not come back every time
    assert saved.get("skip", False) is hidden_after
    first = path.read_text()
    config.write()
    assert path.read_text() == first  # and the file is stable


def test_the_airports_page_rows_carry_the_switch():
    rows = views.leds([Airport(code="KHOU"), hidden(), Airport(), hidden()], 3)
    assert [r["skip"] for r in rows] == [False, True, False, False]  # the last is virtual: there is no LED to hide
    assert [r["virtual"] for r in rows] == [False, False, False, True]


# ---- writing a whole plan (Config.apply_plan) -------------------------------------------------------------------


def test_apply_plan_carries_the_hidden_pixels_and_says_so_once(tmp_path):
    config = make_config(tmp_path, [Airport(code="KHOU"), Airport(code="KIAH"), Airport()])
    seen = keys_of(config)
    new = [Airport(code="KHOU"), hidden(), Airport(code="KIAH"), Airport()]
    result = config.apply_plan(new, 4, 0, backup=False)
    assert [(a.code, a.skip) for a in config.airports] == [("KHOU", False), ("", True), ("KIAH", False), ("", False)]
    assert result["keys"] == seen
    assert seen.count("airports.skip") == 1 and "airports.skip" in seen
    # the same list again changes nothing
    seen.clear()
    config.apply_plan([Airport(code="KHOU"), hidden(), Airport(code="KIAH"), Airport()], 4, 0, backup=False)
    assert seen == []


@pytest.mark.parametrize(
    "bad, message",
    [
        (Airport(code="KHOU", skip=True), "is a Hidden Pixel"),
        (Airport(skip=True, display=True), "is a Hidden Pixel"),
    ],
)
def test_apply_plan_refuses_a_hidden_pixel_that_has_an_airport(tmp_path, bad, message):
    config = make_config(tmp_path, [Airport(code="KIAH"), Airport()])
    with pytest.raises(ValueError, match=message):
        config.apply_plan([Airport(code="KIAH"), bad], 2, 0, backup=False)
    assert [a.code for a in config.airports] == ["KIAH", ""]


def test_apply_plan_refuses_a_hidden_pixel_among_the_virtual_airports(tmp_path):
    config = make_config(tmp_path, [Airport(code="KIAH"), Airport()])
    with pytest.raises(ValueError, match=r"virtual airport 1 is a Hidden Pixel"):
        config.apply_plan([Airport(code="KIAH"), hidden()], 1, 1, backup=False)


def test_undo_gives_the_hidden_pixels_back(tmp_path):
    config = make_config(tmp_path, [Airport(code="KHOU"), hidden(), Airport(code="KIAH")])
    config.apply_plan([Airport(code="KIAH"), Airport(code="KHOU"), Airport(), Airport()], 3, 1, summary={})
    assert not any(a.skip for a in config.airports)
    config.restore_plan_backup()
    assert [(a.code, a.skip) for a in config.airports] == [("KHOU", False), ("", True), ("KIAH", False)]


def test_undo_tidies_a_backup_whose_hidden_pixel_has_an_airport(tmp_path, caplog):
    config = make_config(tmp_path, [Airport(code="KHOU"), hidden(), Airport(code="KIAH")])
    config.apply_plan([Airport(code="KIAH"), Airport(code="KHOU"), Airport(), Airport()], 3, 1, summary={})
    backup = config.plan_backups()[0]["path"]
    with open(backup) as f:
        saved = json.load(f)
    saved["airports"][1]["code"] = "KDKR"  # a backup edited by hand: the Hidden Pixel got an airport
    with open(backup, "w") as f:
        json.dump(saved, f)
    with caplog.at_level(logging.WARNING):
        config.restore_plan_backup()
    assert [(a.code, a.skip) for a in config.airports] == [("KHOU", False), ("KDKR", False), ("KIAH", False)]
    assert "airport 2 is not a Hidden Pixel any more: it has the airport KDKR" in caplog.text


# ---- what a plan makes of its hidden pixels (planner.apply) ------------------------------------------------------


def pixel(code=None, skipped=False):
    return {"code": code, "skipped": skipped}


NAMES = {"KHOU": "Hobby", "KIAH": "Bush", "KGLS": "Galveston"}


def change(current, pixels, led=3, virtual=0, strings=1, string_len=6):
    return plan_apply.plan_changes(current, led, virtual, pixels, string_len, strings, NAMES)


def test_a_planned_hidden_pixel_becomes_a_hidden_pixel_row():
    out = change(
        [Airport(code="KHOU"), Airport(code="KIAH"), Airport()],
        [pixel("KHOU"), pixel(skipped=True), pixel("KIAH")],
    )
    assert [(a.code, a.skip) for a in out.airports] == [
        ("KHOU", False),
        ("", True),  # between two airports: it bridges the gap
        ("KIAH", False),
        ("", False),  # the spare pixels of the last string are plain blanks
        ("", False),
        ("", False),
    ]
    assert out.led_count == 6
    s = out.summary
    assert s["hidden"] == 1 and s["blank_leds"] == 3 and s["moved"] == 1  # KIAH is on LED 3 now
    assert s["blank_leds"] + s["hidden"] + 2 == out.led_count  # every LED is an airport, hidden or blank
    assert "Pixel 2 is a hidden pixel" in s["wiring_note"] and "pixel 3 is KIAH" in s["wiring_note"]


def test_a_skipped_pixel_after_the_last_airport_is_a_plain_blank():
    out = change([Airport(code="KHOU")], [pixel("KHOU"), pixel(skipped=True)], led=1)
    assert [a.skip for a in out.airports] == [False] * 6
    assert out.summary["hidden"] == 0 and out.summary["blank_leds"] == 5
    assert "hidden pixel" not in out.summary["wiring_note"]


def test_the_wiring_note_counts_hidden_pixels_in_the_led_numbers():
    pixels = [pixel("KAUS"), pixel(skipped=True), pixel(skipped=True), pixel("KHOU")]
    note = plan_apply.wiring_note(pixels, 50)
    assert "pixel 1 is KAUS, pixel 4 is KHOU, 50 pixels in all." in note
    assert "Pixel 2 and pixel 3 are hidden pixels" in note
    one = plan_apply.wiring_note([pixel("KAUS"), pixel(skipped=True), pixel("KHOU")], 50)
    assert "Pixel 2 is a hidden pixel: wire it into the string" in one and "pixel 3 is KHOU" in one


def test_a_plan_without_hidden_pixels_replaces_the_ones_the_chart_has():
    """The strip is rebuilt from the plan: an old Hidden Pixel the plan does not hide is a plain blank."""
    current = [Airport(code="KHOU"), hidden(), Airport(code="KIAH")]
    out = change(current, [pixel("KHOU"), pixel("KIAH")], led=3)
    assert not any(a.skip for a in out.airports) and out.summary["hidden"] == 0
    assert out.summary["unchanged"] is False  # LED 2 is KIAH now


def test_the_same_plan_twice_is_unchanged_hidden_pixels_included():
    pixels = [pixel("KHOU"), pixel(skipped=True), pixel("KIAH")]
    first = change([Airport(code="KHOU"), Airport(code="KIAH"), Airport()], pixels)
    again = change(first.airports, pixels, led=first.led_count, virtual=first.virtual_count)
    assert again.summary["unchanged"] is True and again.summary["moved"] == 0
    # but turning one hidden pixel into a blank LED is a change to apply
    flat = change(first.airports, [pixel("KHOU"), pixel(), pixel("KIAH")], led=first.led_count)
    assert flat.summary["unchanged"] is False and flat.summary["hidden"] == 0


def test_the_token_changes_with_a_hidden_pixel():
    current = [Airport(code="KHOU"), Airport(code="KIAH"), Airport()]
    with_hidden = change(current, [pixel("KHOU"), pixel(skipped=True), pixel("KIAH")])
    without = change(current, [pixel("KHOU"), pixel(), pixel("KIAH")])
    assert plan_apply.fingerprint("job", current, 3, 0, with_hidden) != plan_apply.fingerprint(
        "job", current, 3, 0, without
    )


def test_hidden_pixels_count_toward_the_strip():
    with pytest.raises(ValueError, match="the plan has 4 pixels but 1 strings of 3 are 3"):
        change(
            [Airport(code="KHOU")],
            [pixel("KHOU"), pixel(skipped=True), pixel(skipped=True), pixel("KIAH")],
            strings=1,
            string_len=3,
        )


# ---- the renderer -----------------------------------------------------------------------------------------------

NOON = __import__("datetime").datetime(2026, 10, 24, 17, 0, tzinfo=__import__("datetime").timezone.utc)
SUN = {
    "dawn": NOON.replace(hour=11, minute=58),
    "sunrise": NOON.replace(hour=12, minute=23),
    "sunset": NOON.replace(hour=23, minute=41),
    "dusk": NOON.replace(hour=23, minute=59, second=59),
}
DATA = {"KHOU": Report(flight_category="VFR"), "KDKR": Report(flight_category="IFR")}


class AnimationTime:
    """The LED library's clock and the render loop's sleeps, moved on only by those sleeps (as in test_renderer)."""

    def __init__(self):
        self.ms = 1_000_000.0

    def monotonic_ms(self):
        return int(self.ms)

    def sleep(self, seconds):
        self.ms += seconds * 1000


@pytest.fixture
def ticks(monkeypatch):
    import adafruit_led_animation.animation as animation_module
    import adafruit_led_animation.animation.rainbow as rainbow_module
    import adafruit_led_animation.pulse_generator as pulse_module
    from metarmap import renderer

    t = AnimationTime()
    for module in (animation_module, rainbow_module, pulse_module, renderer):
        monkeypatch.setattr(module, "monotonic_ms", t.monotonic_ms)
    monkeypatch.setattr(renderer.time, "sleep", t.sleep)
    return t


def renderer_for(airports, visualizer, leds=None, strip=None):
    """A Renderer on a FakeStrip (or `strip`), with `airports` on the strip, running `visualizer`; its shows are
    recorded."""
    settings = Settings()
    settings.airports = [Airport(code=a.code, skip=a.skip) for a in airports]  # a copy: a test may change a flag
    settings.led.count = len(airports)
    strip = strip if strip is not None else FakeStrip(leds or len(airports))
    shows = []
    show = strip.show
    strip.show = lambda: (shows.append(list(strip)), show())
    r = Renderer(
        strip,
        SimpleNamespace(data=DATA),
        SimpleNamespace(data=settings),
        [FLIGHT, RAINBOW, CHASE],
        SunTimes("Houston", SUN),
        clock=FakeClock(NOON),
    )
    r.visualizer = visualizer.id
    return r, strip, shows


OFF = (0, 0, 0)
AIRPORTS = [Airport(code="KHOU"), hidden(), Airport(code="KDKR"), hidden(), Airport(code="KIAH")]


def test_rainbow_never_lights_a_hidden_pixel(ticks):
    r, strip, shows = renderer_for(AIRPORTS, RAINBOW)
    r.render()
    assert len(shows) > 1
    assert all(frame[1] == OFF and frame[3] == OFF for frame in shows)
    assert all(frame[0] != OFF and frame[2] != OFF and frame[4] != OFF for frame in shows[1:])  # the rest is lit


def test_chase_never_lights_a_hidden_pixel_and_still_walks_the_others(ticks):
    r, strip, shows = renderer_for(AIRPORTS, CHASE)
    r.render()
    assert all(frame[1] == OFF and frame[3] == OFF for frame in shows)
    lit = {i for frame in shows for i, color in enumerate(frame) if color != OFF}
    assert lit == {0, 2, 4}  # it walks the airports and shows nothing where a hidden pixel is


def test_the_first_frame_is_masked_too(ticks):
    r, strip, shows = renderer_for([hidden(), Airport(code="KHOU")], CHASE)
    r.draw_frame()
    assert strip[0] == OFF  # the chase starts on LED 0, a Hidden Pixel: dark


def test_a_visualizer_per_airport_is_unchanged_by_the_flag(ticks):
    r, strip, shows = renderer_for(AIRPORTS, FLIGHT)
    r.render()
    assert strip[0] == flightcategory.COLORS["VFR"] and strip[2] == flightcategory.COLORS["IFR"]
    assert strip[1] == strip[3] == OFF and r._hidden == ()  # a look per airport already draws off for a blank


def test_switching_visualizer_keeps_the_mask_right(ticks):
    r, strip, shows = renderer_for(AIRPORTS, RAINBOW)
    assert r._hidden == (1, 3)
    r.visualizer = "flight_category"
    assert r._hidden == ()
    r.visualizer = "chase"
    assert r._hidden == (1, 3)
    r._config.data.airports[1].skip = False  # switched off on the Airports page: the Chart refreshes the LEDs
    r.refresh()
    assert r._hidden == (3,)


def test_leaving_a_strip_look_swaps_the_animations_and_the_mask_together(ticks):
    """A web thread that switches visualizer waits for the frame in progress (the lock): a frame never draws the old
    animations with the new, empty mask, which would light a Hidden Pixel for a frame."""
    r, strip, shows = renderer_for(AIRPORTS, RAINBOW)
    old = r._animations
    assert r._hidden == (1, 3)
    with r._lock:  # the render loop is in the middle of a frame
        switcher = threading.Thread(target=lambda: setattr(r, "visualizer", "flight_category"), daemon=True)
        switcher.start()
        switcher.join(0.3)
        assert switcher.is_alive()  # it waits for the frame...
        assert r._animations is old and r._hidden == (1, 3)  # ...and nothing is half swapped
    switcher.join(5)
    assert not switcher.is_alive()
    assert r._animations is not old and r._hidden == ()


def test_a_hidden_pixel_beyond_the_strip_is_ignored(ticks):
    r, strip, shows = renderer_for(AIRPORTS, CHASE, leds=3)  # a strip shorter than led.count: no IndexError
    r.render()
    assert r._hidden == (1,)
    assert all(frame[1] == OFF for frame in shows)


class SendingStrip(SkipUnchangedShow, FakeStrip):
    """
    A FakeStrip that sends through SkipUnchangedShow like the strip on a Pi: its `shows` counts the frames really
    sent, the render loop's own show() calls (recorded by renderer_for) the frames it drew.
    """

    @property
    def _post_brightness_buffer(self):  # what the LED library hands to the strip (the colors are never scaled here)
        return bytearray(v for color in self for v in _rgb(color))


def _rgb(color):
    return (color >> 16 & 255, color >> 8 & 255, color & 255) if isinstance(color, int) else tuple(color[:3])


def sent_and_drawn(ticks, visualizer, airports):
    """(frames really sent, frames drawn) when `visualizer` runs one render() on a strip that skips unchanged frames."""
    strip = SendingStrip(len(airports))
    strip._monotonic = lambda: ticks.ms / 1000  # the same clock as the animations
    r, strip, drawn = renderer_for(airports, visualizer, strip=strip)
    r.render()
    return strip.shows, len(drawn)


PLAIN = [Airport(code=a.code) for a in AIRPORTS]  # the same strip with plain blanks: nothing is hidden


@pytest.mark.parametrize("vis", [RAINBOW, CHASE], ids=["rainbow", "chase"])
def test_a_mask_sends_no_more_frames_than_the_same_strip_without_one(ticks, vis):
    """The mask runs before show(), so the strip sees the final colors: it must not make a still frame look new."""
    masked, drawn = sent_and_drawn(ticks, vis, AIRPORTS)
    plain, _ = sent_and_drawn(ticks, vis, PLAIN)
    assert drawn > 10 and masked <= plain


def test_a_masked_chase_still_skips_the_frames_that_did_not_change(ticks):
    # two Hidden Pixels side by side: the chase is dark for two steps in a row, so the second frame is the same
    side_by_side = [Airport(code="KHOU"), hidden(), hidden(), Airport(code="KDKR"), Airport(code="KIAH")]
    sent, drawn = sent_and_drawn(ticks, CHASE, side_by_side)
    assert 0 < sent < drawn  # frames were drawn that the strip did not send again


def test_a_still_masked_frame_is_sent_once(ticks):
    """The mask must write the same thing every frame: a frame the animations did not change stays a skipped frame."""
    strip = SendingStrip(len(AIRPORTS))
    strip._monotonic = lambda: ticks.ms / 1000
    r, strip, drawn = renderer_for(AIRPORTS, RAINBOW, strip=strip)
    r.draw_frame()  # one rainbow frame with the Hidden Pixels dark, sent
    sent = strip.shows
    for _ in range(4):
        ticks.sleep(0.2)  # past the strip's settling time, inside its once-a-second resend
        with r._lock:
            r._darken_hidden()  # the animations are not due: what the loop does with the frame it did not change
            strip.show()
    assert strip.shows == sent


def test_locate_ignores_a_hidden_pixel(ticks):
    r, strip, shows = renderer_for(AIRPORTS, FLIGHT)
    before = len(shows)
    r.locate(1)
    assert r.last_locate is None and len(shows) == before  # nothing pulses, on the strip or on the web map
    r.locate(0)
    assert r.last_locate["pixel"] == 0 and len(shows) > before


def test_the_startup_comet_still_lights_every_led(ticks):
    """The sequences check the hardware: they light the hidden pixels too."""
    r, strip, shows = renderer_for(AIRPORTS, RAINBOW)
    r._config.data.led.init_sequence = "comet"
    shows.clear()
    r.test_pattern()
    assert any(frame[1] != OFF for frame in shows) and any(frame[3] != OFF for frame in shows)


# ---- what the web and the live API show ---------------------------------------------------------------------------


def hide_in_config(client, pixels):
    """Makes LEDs `pixels` Hidden Pixels (blank first), then returns the airports' codes by LED."""
    config = client.services.config
    for p in pixels:
        config.set_airport(p, "code", "-")
        config.set_airport(p, "skip", "true")
    return [a.code for a in config.airports]


def test_hidden_pixels_are_not_in_the_live_api_and_the_others_keep_their_numbers(plan_client):
    client = plan_client
    config = client.services.config
    with_codes = [(i, a.code) for i, a in enumerate(config.airports) if a.code]
    status, live_before = get(client, "/api/live")
    status, api_before = get(client, "/api/status")
    hide_in_config(client, [1, 2])
    status, live = get(client, "/api/live")
    status, api = get(client, "/api/status")
    expected = [(i, code) for i, code in with_codes if i not in (1, 2)]
    assert [(a["pixel"], a["code"]) for a in api["airports"]] == expected
    assert [(s["pixel"], s["code"]) for s in live["leds"]] == expected
    # nothing in the API says a Hidden Pixel exists: no skip flag, no entry with an empty code
    assert all("skip" not in a for a in api["airports"]) and all("skip" not in s for s in live["leds"])
    assert not any(not a["code"] for a in api["airports"]) and not any(not s["code"] for s in live["leds"])
    assert len(live["leds"]) == len(live_before["leds"]) - len([1 for i, _ in with_codes if i in (1, 2)])


def test_a_plan_with_a_hidden_pixel_applies_and_stays_out_of_the_api(plan_client):
    client = plan_client
    planned(client)
    held = client.planner.job["result"]["sheet"]  # the plan the server holds
    pixels = held["pixels"]
    held["shopping"]["strings"] += 1  # (the planner adds a string when the skips need the room)
    # a plan that hid a pixel between its first two airports (what allow_skips makes when a gap needs one)
    pixels.insert(1, {"number": 2, "code": None, "skipped": True, "string": 1, "position": 2})
    for n, p in enumerate(pixels):
        p["number"] = n + 1
    status, preview = get(client, PREVIEW)
    assert status == 200 and preview["summary"]["hidden"] == 1
    assert "Pixel 2 is a hidden pixel" in preview["summary"]["wiring_note"]
    status, done = post(client, APPLY, {"token": preview["token"]})
    assert status == 200, done
    airports = client.services.config.airports
    assert (airports[1].code, airports[1].skip) == ("", True)
    assert sum(a.skip for a in airports) == 1
    # on the strip it is a blank LED that shows nothing; in the API it is not there and the LED numbers hold
    status, live = get(client, "/api/live")
    assert 1 not in [s["pixel"] for s in live["leds"]] and live["leds"][0]["pixel"] == 0
    assert live["leds"][1]["pixel"] == 2 and live["leds"][1]["code"] == airports[2].code


def test_the_airports_page_shows_the_switch_state(plan_client):
    client = plan_client
    hide_in_config(client, [1])
    rows = views.leds(client.services.config.airports, client.services.config.data.led.count)
    assert rows[1]["skip"] is True and rows[0]["skip"] is False


def test_a_hidden_pixel_is_one_of_the_1000_and_cannot_be_a_virtual_airport():
    airports = [Airport(code=f"K{i:03d}") for i in range(MAX_LEDS - 1)] + [hidden()]
    assert len(airports) == MAX_LEDS  # a full Chart: the last pixel is a Hidden Pixel, one of the 1000 like any pixel
    assert tidy_hidden(airports, MAX_LEDS) == 0 and airports[-1].skip is True
    airports.append(hidden())  # one more, past the strip: a virtual airport has no pixel to hide
    assert tidy_hidden(airports, MAX_LEDS) == 1 and airports[-1].skip is False and airports[MAX_LEDS - 1].skip is True
