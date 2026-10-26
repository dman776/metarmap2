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
from metarmap.visualizers import flightcategory, precipitation, rainbow, visualizer, wind

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
    r.visualizer = 1
    r.visualizer_next(skip_exclusive=True)  # Precipitation and Rainbow are exclusive
    assert r.active_visualizer == 0


def test_skip_exclusive_when_every_visualizer_is_exclusive(config, clock):
    r, _ = make(config, clock, visualizers=[precipitation, rainbow])
    r.visualizer_next(skip_exclusive=True)  # used to loop forever
    assert r.active_visualizer in (0, 1)


# ---- locate -------------------------------------------------------------------------------------------------

def test_locate_pulses_and_records(config, clock):
    r, strip = make(config, clock)
    shows = strip.shows
    r.locate(4)
    assert r.last_locate == {"pixel": 4, "at": NOON.timestamp()}
    assert strip.shows > shows


def test_locate_ignored_by_exclusive_visualizers(config, clock):
    r, strip = make(config, clock)
    r.visualizer = 2  # precipitation
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
