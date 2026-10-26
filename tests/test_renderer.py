"""Tests for the renderer, on an in-memory LED strip with a controllable clock."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from conftest import airports
from metarmap.clock import FakeClock
from metarmap.leds.strip import FakeStrip
from metarmap.models import Look
from metarmap.settings import Settings
from metarmap.sun import SunTimes
from metarmap.renderer import Renderer
from metarmap.visualizers import chase, flightcategory, precipitation, rainbow, visualizer, wind

NOON = datetime(2026, 10, 24, 17, 0, tzinfo=timezone.utc)
SUN = {"dawn": NOON.replace(hour=11, minute=58), "sunrise": NOON.replace(hour=12, minute=23),
       "sunset": NOON.replace(hour=23, minute=41), "dusk": NOON.replace(hour=23, minute=59, second=59)}


def metar(category, wind=5, obs=""):
    return {"flightCategory": category, "lightning": False, "windSpeed": wind, "windGust": False, "windGustSpeed": 0,
            "obs": obs}


CODES = ["KHOU", "KIAH", "", "KDKR", "KGLS"]  # LED 2 has no airport
DATA = {"KHOU": metar("VFR"), "KIAH": metar("IFR", wind=20), "KDKR": {}, "KGLS": metar("LIFR")}


@pytest.fixture
def config():
    settings = Settings()
    settings.airports = airports(*CODES)
    return SimpleNamespace(data=settings)


@pytest.fixture
def clock():
    return FakeClock(NOON)


def make(config, clock, data=DATA, leds=5, visualizers=None):
    strip = FakeStrip(leds)
    visualizers = visualizers or [flightcategory, wind, precipitation, rainbow]
    r = Renderer(strip, SimpleNamespace(data=data), config, visualizers, SunTimes("Houston", SUN), clock=clock)
    return r, strip


def draw_frame(renderer):
    for animation in renderer.animations:
        animation.animate()


# ---- looks and what reaches the LEDs --------------------------------------------------------------------------

def test_looks_come_from_the_active_visualizer(config, clock):
    r, _ = make(config, clock)
    assert r.looks == visualizer.looks(flightcategory, CODES, DATA, config.data)
    r.visualizer = 1
    assert r.looks == visualizer.looks(wind, CODES, DATA, config.data)


def test_first_frame_lights_the_leds(config, clock):
    r, strip = make(config, clock)
    draw_frame(r)
    cat = config.data.color.cat
    assert strip[0] == tuple(cat.vfr)
    assert strip[1] == tuple(cat.ifr)
    assert strip[2] == (0, 0, 0)  # no airport
    assert strip[3] == (0, 0, 0)  # no report
    assert strip[4] == tuple(cat.lifr)


def test_led_states_for_the_web_ui(config, clock):
    r, _ = make(config, clock)
    leds, strip = r.led_states()
    assert strip is None
    assert leds[0] == Look.solid(config.data.color.cat.vfr).to_dict()
    assert leds[2] == {"effect": "off", "colors": []}
    assert set(leds) == {0, 1, 2, 3, 4}


def test_whole_strip_visualizer(config, clock):
    r, _ = make(config, clock)
    r.visualizer = 3  # rainbow
    leds, strip = r.led_states()
    assert leds == {}
    assert strip == {"effect": "rainbow", "colors": [], "period": 5}
    assert r.strip_look == Look.rainbow(period=5)
    assert len(r.animations) == 1


def test_update_data_rebuilds_looks(config, clock):
    r, _ = make(config, clock)
    r.update_data(SimpleNamespace(data={**DATA, "KHOU": metar("MVFR")}))
    assert r.looks[0] == Look.solid(config.data.color.cat.mvfr)


def test_refresh_picks_up_airport_changes(config, clock):
    r, _ = make(config, clock)
    config.data.airports[2].code = "KHOU"
    config.data.airports.insert(0, config.data.airports.pop(4))  # KGLS to the first LED
    r.refresh()
    assert r.looks[0] == Look.solid(config.data.color.cat.lifr)
    assert r.looks[3] == r.looks[1] == Look.solid(config.data.color.cat.vfr)


def test_more_airports_than_leds(config, clock):
    r, strip = make(config, clock, leds=3)
    assert len(r.animations) == 3
    draw_frame(r)  # no IndexError
    assert len(strip) == 3


def test_resize(config, clock):
    """The in-memory strip can change length without a restart; each LED keeps its own animation."""
    r, strip = make(config, clock, leds=3)
    assert r.resize(5) is True
    assert len(strip) == 5 and len(r.animations) == 5
    draw_frame(r)
    assert strip[4] == tuple(config.data.color.cat.lifr)
    assert r.resize(2) is True and len(r.animations) == 2
    draw_frame(r)  # no IndexError


def test_resize_a_strip_that_cant(config, clock):
    r, strip = make(config, clock, leds=3)
    r._pixels = [(0, 0, 0)] * 3  # like a NeoPixel strip: no resize()
    assert r.resize(5) is False


def test_render_rests_between_frames(config, clock, monkeypatch):
    """Without a rest the loop asks the animations "is it time yet?" non-stop, using a whole CPU core."""
    from metarmap import renderer

    class Frames:
        """An animation loop that has three frames to draw."""
        def __init__(self, *args, **kwargs):
            self.left = 3

        def animate(self):
            self.left -= 1
            return self.left > 0

        def freeze(self):
            pass

        def resume(self):
            pass

    rests = []
    monkeypatch.setattr(renderer, "AnimateOnce", Frames)
    monkeypatch.setattr(renderer.time, "sleep", rests.append)
    r, _ = make(config, clock)
    r.render()
    assert rests == [renderer.FRAME_SECONDS] * 2  # after each frame that kept going, not after the last
    rests.clear()
    r.animate_once(object())
    assert rests == [renderer.FRAME_SECONDS] * 2


def test_render_rests_after_an_error(config, clock, monkeypatch):
    from metarmap import renderer

    def broken(*args, **kwargs):
        raise RuntimeError("no such animation")

    rests = []
    monkeypatch.setattr(renderer, "AnimationGroup", broken)
    monkeypatch.setattr(renderer.time, "sleep", rests.append)
    r, _ = make(config, clock)
    r.render()  # the main loop calls it again at once; it mustn't spin
    assert rests == [renderer.FRAME_SECONDS]


def test_render_stops_when_the_animations_are_rebuilt(config, clock):
    """New data, a new visualizer or a new strip length shows at once, not after the old animations' cycle."""
    r, _ = make(config, clock, data={"KHOU": metar("VFR", obs="-RA")}, leds=1, visualizers=[precipitation])
    frames = []
    animation = r.animations[0]
    animate = animation.animate

    def animate_then_rebuild(*args, **kwargs):
        frames.append(1)
        r.refresh()
        return animate(*args, **kwargs)
    animation.animate = animate_then_rebuild
    r.render()
    assert len(frames) == 1


def watch_brightness(strip):
    """Records the strip's brightness each time it's shown."""
    seen = []
    show = strip.show

    def recording_show():
        seen.append(round(strip.brightness, 6))
        show()
    strip.show = recording_show
    return seen


def test_dimmed_while_fetching_fades(config, clock, monkeypatch):
    from metarmap import renderer
    monkeypatch.setattr(renderer, "DIM_SECONDS", 1)
    monkeypatch.setattr(renderer, "FADE_SECONDS", 0.6)
    r, strip = make(config, clock)
    strip.brightness = 0.4
    seen = watch_brightness(strip)
    start = clock.time()
    with r.dimmed():
        down = list(seen)
        assert strip.brightness == 0.2  # faded all the way before the fetch
        faded_at = clock.time()
    up = seen[len(down):]
    assert len(down) == renderer.FADE_STEPS and down == sorted(down, reverse=True) and down[-1] == 0.2
    assert len(up) == renderer.FADE_STEPS and up == sorted(up) and up[-1] == 0.4
    assert strip.brightness == 0.4
    assert faded_at - start == pytest.approx(0.55)  # 11 waits between 12 steps
    assert clock.time() - faded_at == pytest.approx(1 + 0.55)  # a quick fetch still dims for a second, then fades up


class DeadbandStrip(FakeStrip):
    """Like the Pi's NeoPixel strip: a brightness change under 0.001 is ignored."""

    @property
    def brightness(self):
        return self._brightness

    @brightness.setter
    def brightness(self, value):
        if not -0.001 < value - getattr(self, "_brightness", -1) < 0.001:
            self._brightness = value


@pytest.mark.parametrize("night", [0.01, 0.0058, 0.0024, 0.002])
def test_fade_at_night_brightness_ends_exactly(config, clock, night):
    """At 1% the fade takes fewer, bigger steps the Pi's strip won't ignore, so the level never drifts."""
    strip = DeadbandStrip(5, brightness=night)
    r = Renderer(strip, SimpleNamespace(data=DATA), config, [flightcategory], SunTimes("Houston", SUN), clock=clock)
    strip.brightness = night
    for _ in range(20):  # 20 fetches
        with r.dimmed():
            assert strip.brightness < night
    assert strip.brightness == night


def test_a_change_during_the_fade_down_wins(config, clock, monkeypatch):
    r, strip = make(config, clock)
    strip.brightness = 0.4
    waits = []

    def slider_moves(event, seconds):
        waits.append(seconds)
        if len(waits) == 3:
            r.brightness(0.9)  # the Home page slider, mid-fade
    monkeypatch.setattr(clock, "wait", slider_moves)
    with r.dimmed():
        pass
    assert strip.brightness == 0.9 and len(waits) == 3  # stopped fading; no hold, no fade back


def test_dimmed_keeps_a_brightness_changed_meanwhile(config, clock):
    r, strip = make(config, clock)
    strip.brightness = 0.4
    with r.dimmed():
        r.brightness(0.1)  # the web UI's slider, or the brightness schedule
    assert strip.brightness == 0.1


def test_dimmed_turned_off(config, clock):
    config.data.led.dim_on_refresh = False
    r, strip = make(config, clock)
    strip.brightness = 0.4
    with r.dimmed():
        assert strip.brightness == 0.4


def test_dimmed_comes_back_after_an_error(config, clock):
    r, strip = make(config, clock)
    strip.brightness = 0.4
    with pytest.raises(RuntimeError):
        with r.dimmed():
            raise RuntimeError("fetch failed")
    assert strip.brightness == 0.4


def test_clear(config, clock):
    r, strip = make(config, clock)
    draw_frame(r)
    r.clear()
    assert all(c == tuple(config.data.color.clear) for c in strip)


def test_render_runs_one_cycle(config, clock):
    r, strip = make(config, clock, data={"KHOU": metar("VFR")}, leds=1)
    shows = strip.shows
    r.render()
    assert strip[0] == tuple(config.data.color.cat.vfr)
    assert strip.shows > shows


# ---- switching visualizers ------------------------------------------------------------------------------------

def test_next_and_previous_wrap(config, clock):
    r, _ = make(config, clock)
    r.visualizer_previous()
    assert r.active_visualizer == 3
    r.visualizer_next()
    assert r.active_visualizer == 0


def test_auto_rotate_skips_exclusive_visualizers(config, clock):
    r, _ = make(config, clock)
    r.visualizer = 2
    r.visualizer_next(skip_exclusive=True)  # Rainbow is exclusive
    assert r.active_visualizer == 0


def test_auto_rotate_skips_named_visualizers(config, clock):
    r, _ = make(config, clock, visualizers=[flightcategory, wind, rainbow])
    r.visualizer_next(skip_exclusive=True, skip=["Wind"])
    assert r.active_visualizer == 0  # Wind skipped, Rainbow exclusive: back to the first
    r.visualizer_next()
    assert r.active_visualizer == 1  # the buttons still reach it


def test_nothing_to_rotate_to_stays_put(config, clock):
    r, _ = make(config, clock, visualizers=[chase, rainbow])
    r.visualizer_next(skip_exclusive=True)  # used to loop forever
    assert r.active_visualizer == 0
    r, _ = make(config, clock, visualizers=[flightcategory, wind])
    r.visualizer = 1
    r.visualizer_next(skip=["Flight Category", "Wind"])
    assert r.active_visualizer == 1
    r.visualizer_next(skip=["Wind"])  # only itself left: it's what it is
    assert r.active_visualizer == 0


# ---- locate -------------------------------------------------------------------------------------------------

def test_locate_pulses_and_records(config, clock):
    r, strip = make(config, clock)
    shows = strip.shows
    r.locate(4)
    assert r.last_locate == {"pixel": 4, "at": NOON.timestamp()}
    assert strip.shows > shows


def test_locate_ignored_by_exclusive_visualizers(config, clock):
    r, strip = make(config, clock)
    r.visualizer = 3  # rainbow
    shows = strip.shows
    r.locate(0)
    assert r.last_locate is None
    assert strip.shows == shows


def test_locate_errors_are_logged_not_raised(config, clock):
    r, _ = make(config, clock)
    r.locate(99)  # no such LED
    assert r.last_locate["pixel"] == 99


# ---- brightness by sun time -----------------------------------------------------------------------------------

@pytest.mark.parametrize("when, level", [
    (SUN["dawn"] + timedelta(minutes=1), "dimmed"),
    (SUN["sunrise"] + timedelta(minutes=1), "normal"),
    (NOON, "normal"),
    (SUN["sunset"] + timedelta(minutes=1), "dimmed"),
    (SUN["dawn"] - timedelta(hours=2), "off"),
    (SUN["dusk"] + timedelta(seconds=0.5), "off"),
])
def test_brightness_for(config, clock, when, level):
    r, _ = make(config, clock)
    assert r.brightness_for(when) == getattr(config.data.led.brightness, level)


def test_scheduled_level(config, clock):
    r, _ = make(config, clock)  # noon
    assert r.scheduled_level() == "normal"
    clock.advance(12 * 3600)
    assert r.scheduled_level() == "off"


def test_test_pattern_runs_once(config, clock, monkeypatch):
    from metarmap import renderer
    monkeypatch.setattr(renderer, "FRAME_SECONDS", 0)
    r, strip = make(config, clock)
    shows = strip.shows
    r.test_pattern()
    assert strip.shows > shows


def test_brightness_follows_the_clock(config):
    clock = FakeClock(SUN["dawn"] + timedelta(minutes=5))
    r, strip = make(config, clock)
    assert strip.brightness == config.data.led.brightness.dimmed
    clock.advance(3600)
    r.adjust_brightness_for_time()
    assert strip.brightness == config.data.led.brightness.normal


def test_brightness_ignores_out_of_range(config, clock):
    r, strip = make(config, clock)
    r.brightness(0.3)
    r.brightness(1.5)
    assert strip.brightness == 0.3
