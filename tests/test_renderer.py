"""Tests for the renderer, on an in-memory LED strip with a controllable clock."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from conftest import airports

from metarmap import visualizers as visualizer_module
from metarmap.clock import FakeClock
from metarmap.leds.strip import FakeStrip, PixelGroup, SkipUnchangedShow
from metarmap.models import Look, Report
from metarmap.renderer import Renderer
from metarmap.settings import Settings
from metarmap.sun import SunTimes
from metarmap.visualizers import chase, flightcategory, precipitation, rainbow, visualizer, wind

NOON = datetime(2026, 10, 24, 17, 0, tzinfo=timezone.utc)
SUN = {
    "dawn": NOON.replace(hour=11, minute=58),
    "sunrise": NOON.replace(hour=12, minute=23),
    "sunset": NOON.replace(hour=23, minute=41),
    "dusk": NOON.replace(hour=23, minute=59, second=59),
}


def metar(category, wind=5, weather=""):
    return Report(flight_category=category, wind_speed=wind, weather=weather)


CODES = ["KHOU", "KIAH", "", "KDKR", "KGLS"]  # LED 2 has no airport
# the visualizers the renderer runs (each module's functions stay as they were, e.g. flightcategory.COLORS)
FLIGHT, WIND, PRECIP, RAINBOW, CHASE = (m.VISUALIZER for m in (flightcategory, wind, precipitation, rainbow, chase))
DATA = {"KHOU": metar("VFR"), "KIAH": metar("IFR", wind=20), "KDKR": None, "KGLS": metar("LIFR")}


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
    visualizers = visualizers or [FLIGHT, WIND, PRECIP, RAINBOW]
    r = Renderer(strip, SimpleNamespace(data=data), config, visualizers, SunTimes("Houston", SUN), clock=clock)
    return r, strip


def draw_frame(renderer):
    for animation in renderer.animations:
        animation.animate()


def led_groups(renderer):
    """The LEDs each of the renderer's animations draws: one animation per distinct look."""
    out = []
    for animation in renderer.animations:
        pixels = animation.pixel_object
        if isinstance(pixels, PixelGroup):
            out.append(list(pixels.leds))
        else:  # one LED's PixelSubset
            out.append([renderer._pix.index(pixels)])
    return out


# ---- looks and what reaches the LEDs --------------------------------------------------------------------------


def test_looks_come_from_the_active_visualizer(config, clock):
    r, _ = make(config, clock)
    assert r.looks == visualizer.looks(FLIGHT, CODES, DATA, config.data)
    r.visualizer = 1
    assert r.looks == visualizer.looks(WIND, CODES, DATA, config.data)


def test_first_frame_lights_the_leds(config, clock):
    r, strip = make(config, clock)
    draw_frame(r)
    assert strip[0] == flightcategory.COLORS["VFR"]
    assert strip[1] == flightcategory.COLORS["IFR"]
    assert strip[2] == (0, 0, 0)  # no airport
    assert strip[3] == (0, 0, 0)  # no report
    assert strip[4] == flightcategory.COLORS["LIFR"]


def test_draw_frame_lights_the_leds_at_once(config, clock):
    r, strip = make(config, clock)
    r.draw_frame()
    assert strip[0] == flightcategory.COLORS["VFR"]
    assert strip[4] == flightcategory.COLORS["LIFR"]


def test_draw_frame_errors_are_logged_not_raised(config, clock, monkeypatch):
    r, strip = make(config, clock)
    monkeypatch.setattr(strip, "show", lambda: (_ for _ in ()).throw(RuntimeError("bus")))
    r.draw_frame()


def test_led_states_for_the_web_ui(config, clock):
    r, _ = make(config, clock)
    leds, strip = r.led_states()
    assert strip is None
    assert leds[0] == Look.solid(flightcategory.COLORS["VFR"]).to_dict()
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
    assert r.looks[0] == Look.solid(flightcategory.COLORS["MVFR"])


def test_refresh_picks_up_airport_changes(config, clock):
    r, _ = make(config, clock)
    config.data.airports[2].code = "KHOU"
    config.data.airports.insert(0, config.data.airports.pop(4))  # KGLS to the first LED
    r.refresh()
    assert r.looks[0] == Look.solid(flightcategory.COLORS["LIFR"])
    assert r.looks[3] == r.looks[1] == Look.solid(flightcategory.COLORS["VFR"])


def test_more_airports_than_leds(config, clock):
    r, strip = make(config, clock, leds=3)
    assert len(r.animations) == 3
    draw_frame(r)  # no IndexError
    assert len(strip) == 3


def test_resize(config, clock):
    """The in-memory strip can change length without a restart; each look's LEDs are those on the strip now."""
    r, strip = make(config, clock, leds=3)
    assert r.resize(5) is True
    # VFR, IFR, LIFR and off (LEDs 2 and 3: no airport, no report) share one animation
    assert len(strip) == 5 and led_groups(r) == [[0], [1], [2, 3], [4]]
    draw_frame(r)
    assert strip[4] == flightcategory.COLORS["LIFR"]
    assert r.resize(2) is True and led_groups(r) == [[0], [1]]
    draw_frame(r)  # no IndexError
    assert r.resize(4) is True and led_groups(r) == [[0], [1], [2, 3]]  # a group made again for the new length
    strip[3] = (9, 9, 9)
    r._animations[2]._next_update = 0  # due now
    draw_frame(r)
    assert strip[3] == (0, 0, 0)


def test_resize_a_strip_that_cant(config, clock):
    r, strip = make(config, clock, leds=3)
    r._pixels = [(0, 0, 0)] * 3  # like a NeoPixel strip: no resize()
    assert r.resize(5) is False


@pytest.mark.parametrize("number", range(len(visualizer_module.ALL)), ids=[v.id for v in visualizer_module.ALL])
def test_every_visualizer_runs_with_no_leds(config, clock, monkeypatch, number):
    """A map of virtual airports only (led.count 0): no visualizer, Chase included, breaks on the empty strip."""
    from metarmap import renderer

    monkeypatch.setattr(renderer, "RENDER_SECONDS", 0.05)  # render() still draws a frame, without sleeping a second
    config.data.led.count = 0
    r, strip = make(config, clock, leds=0, visualizers=list(visualizer_module.ALL))
    r.visualizer = number
    draw_frame(r)
    shows = strip.shows
    r.render()
    assert strip.shows > shows  # render() catches and only logs an error, so a frame drawn is what shows it worked
    r.visualizer = (number + 1) % len(visualizer_module.ALL)  # and on to the next one, as the main loop does
    draw_frame(r)
    r.render()
    assert len(strip) == 0 and r.animations == []


def test_lowering_to_no_leds_darkens_a_strip_that_cant_resize(config, clock):
    """A NeoPixel strip keeps its length until a restart: LEDs no longer drawn go dark, they don't freeze lit."""
    config.data.led.count = 5
    for vis in (FLIGHT, RAINBOW):
        r, strip = make(config, clock, leds=5, visualizers=[vis])
        draw_frame(r)
        assert any(color != (0, 0, 0) for color in strip)
        strip.resize = None  # like a NeoPixel strip
        config.data.led.count = 0
        r.resize(0)
        r.refresh()
        assert all(color == (0, 0, 0) for color in strip) and r.animations == []
        config.data.led.count = 5


def test_render_stops_when_the_animations_are_rebuilt(config, clock):
    """New data, a new visualizer or a new strip length shows at once, not after the old animations' cycle."""
    r, _ = make(config, clock, data={"KHOU": metar("VFR", weather="-RA")}, leds=1, visualizers=[PRECIP])
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
    up = seen[len(down) :]
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
    r = Renderer(strip, SimpleNamespace(data=DATA), config, [FLIGHT], SunTimes("Houston", SUN), clock=clock)
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
    with pytest.raises(RuntimeError), r.dimmed():
        raise RuntimeError("fetch failed")
    assert strip.brightness == 0.4


def test_clear(config, clock):
    r, strip = make(config, clock)
    draw_frame(r)
    r.clear()
    assert all(c == (0, 0, 0) for c in strip)


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


def test_auto_rotate_skips_listed_visualizers(config, clock):
    r, _ = make(config, clock, visualizers=[FLIGHT, WIND, RAINBOW])
    r.visualizer_next(skip_exclusive=True, skip=["wind"])
    assert r.active_visualizer == 0  # Wind skipped, Rainbow exclusive: back to the first
    r.visualizer_next()
    assert r.active_visualizer == 1  # the buttons still reach it


def test_nothing_to_rotate_to_stays_put(config, clock):
    r, _ = make(config, clock, visualizers=[CHASE, RAINBOW])
    r.visualizer_next(skip_exclusive=True)  # used to loop forever
    assert r.active_visualizer == 0
    r, _ = make(config, clock, visualizers=[FLIGHT, WIND])
    r.visualizer = "wind"
    r.visualizer_next(skip=["flight_category", "wind"])
    assert r.active_visualizer == 1
    r.visualizer_next(skip=["wind"])  # only itself left: it's what it is
    assert r.active_visualizer == 0


def test_subscribers_hear_of_a_new_visualizer_only(config, clock):
    r, _ = make(config, clock)
    heard = []
    r.subscribe(lambda: heard.append(r.visualizer[1].id))
    r.refresh()
    r.visualizer = 0  # already showing
    assert heard == []
    r.visualizer = "wind"
    r.visualizer_next()
    r.visualizer_previous()
    assert heard == ["wind", "precipitation", "wind"]


def test_choose_a_visualizer_by_id_or_number(config, clock):
    r, _ = make(config, clock)
    r.visualizer = "precipitation"
    assert r.visualizer == (2, PRECIP)
    r.visualizer = "1"
    assert r.visualizer == (1, WIND)
    for unknown in ("nope", 9, "9"):
        with pytest.raises(LookupError):
            r.visualizer = unknown
    assert r.visualizer == (1, WIND)


# ---- locate -------------------------------------------------------------------------------------------------


def test_locate_records(config, clock):
    r, _ = make(config, clock)
    r.locate(4)
    assert r.last_locate == {"pixel": 4, "at": NOON.timestamp()}


def test_locate_ignored_by_exclusive_visualizers(config, clock):
    r, strip = make(config, clock)
    r.visualizer = 3  # rainbow
    shows = strip.shows
    r.locate(0)
    assert r.last_locate is None
    assert strip.shows == shows and r._pulses == {}


def test_locate_an_led_past_the_strip_only_records(config, clock):
    config.data.led.count = 100  # longer than the strip
    r, _ = make(config, clock)
    r.locate(99)  # no such LED
    assert r.last_locate["pixel"] == 99 and r._pulses == {}


# ---- virtual airports -----------------------------------------------------------------------------------------


@pytest.fixture
def virtual(config):
    """The first 3 airports are on the strip; KDKR and KGLS are virtual."""
    config.data.led.count = 3
    config.data.led.virtual_count = 2
    return config


def test_virtual_airports_get_looks_but_no_leds(virtual, clock):
    r, strip = make(virtual, clock, leds=3)
    assert len(r.looks) == 5 and len(r.animations) == 3
    assert r.looks[4] == Look.solid(flightcategory.COLORS["LIFR"])  # for the web map
    assert set(r.led_states()[0]) == {0, 1, 2, 3, 4}


def test_a_longer_strip_leaves_its_extra_leds_dark(virtual, clock):
    """A NeoPixel strip keeps its length until a restart: a virtual airport mustn't light the LED it used to have."""
    r, strip = make(virtual, clock, leds=5)
    draw_frame(r)
    assert len(r.animations) == 3 and strip[4] == (0, 0, 0)


def test_virtual_airports_join_a_rainbow_but_not_a_chase(virtual, clock):
    r, _ = make(virtual, clock, leds=3, visualizers=[CHASE, RAINBOW])
    leds, strip = r.led_states()  # chase: a wiring check, so the virtual airports have nothing to show
    assert strip["effect"] == "chase"
    assert leds == {3: {"effect": "off", "colors": []}, 4: {"effect": "off", "colors": []}}
    r.visualizer = 1
    leds, strip = r.led_states()
    assert leds == {3: strip, 4: strip} and strip["effect"] == "rainbow"


def test_locate_a_virtual_airport_only_on_the_web_map(virtual, clock):
    r, strip = make(virtual, clock, leds=5)  # LEDs 3 and 4 exist, but aren't the virtual airports'
    shows = strip.shows
    r.locate(4)
    assert r.last_locate == {"pixel": 4, "at": NOON.timestamp()}  # the web map pulses it
    assert strip.shows == shows


# ---- brightness by sun time -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "when, level",
    [
        (SUN["dawn"] + timedelta(minutes=1), "dimmed"),
        (SUN["sunrise"] + timedelta(minutes=1), "normal"),
        (NOON, "normal"),
        (SUN["sunset"] + timedelta(minutes=1), "dimmed"),
        (SUN["dawn"] - timedelta(hours=2), "off"),
        (SUN["dusk"] + timedelta(seconds=0.5), "off"),
    ],
)
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


@pytest.mark.parametrize("sequence", ["center_out", "edges_in", "sweep", "radar", "sparkle"])
def test_a_fade_in_ends_on_the_visualizer(config, clock, sequence):
    config.data.led.init_sequence = sequence
    r, strip = make(config, clock)
    strip.fill((9, 9, 9))
    r.test_pattern()
    assert strip[0] == flightcategory.COLORS["VFR"]
    assert strip[1] == flightcategory.COLORS["IFR"]
    assert strip[2] == strip[3] == (0, 0, 0)  # no airport, no report
    assert strip[4] == flightcategory.COLORS["LIFR"]


def test_a_fade_in_follows_where_the_airports_are(config, clock):
    """Sweep from the west: halfway through, the western airport is lit and the eastern one still dark."""
    config.data.led.init_sequence = "sweep"
    where = {"KHOU": (29.6, -95.3), "KIAH": (30.0, -95.0), "KDKR": (31.3, -95.4), "KGLS": (29.3, -94.0)}
    strip = FakeStrip(5)
    metars = SimpleNamespace(data=DATA, position=where.get)
    r = Renderer(strip, metars, config, [FLIGHT], SunTimes("Houston", SUN), clock=clock)
    seen = []
    show = strip.show
    strip.show = lambda: (seen.append((clock.time(), list(strip))), show())
    r.test_pattern()
    begin = seen[0][0]
    halfway = next(colors for at, colors in seen if at - begin >= 1.5)
    assert halfway[0] == flightcategory.COLORS["VFR"]  # KHOU, the farthest west, is done
    assert halfway[4] == (0, 0, 0)  # KGLS, the farthest east, hasn't started


def test_a_whole_strip_visualizer_fades_in_white(config, clock):
    config.data.led.init_sequence = "center_out"
    r, strip = make(config, clock)
    r.visualizer = 3  # Rainbow
    r.test_pattern()
    assert all(strip[i] == (255, 255, 255) for i in range(5))


@pytest.mark.parametrize("sequence", ["comet", "center_out", "edges_in", "sweep", "radar", "sparkle"])
def test_a_fade_out_ends_dark(config, clock, sequence, monkeypatch):
    from metarmap import renderer

    monkeypatch.setattr(renderer, "FRAME_SECONDS", 0)
    config.data.led.init_sequence = sequence
    r, strip = make(config, clock)
    r.draw_frame()
    assert strip[0] == flightcategory.COLORS["VFR"]
    r.fade_out()
    assert all(color == (0, 0, 0) for color in strip)


def test_a_fade_out_follows_the_same_path(config, clock):
    """Sweep from the west: halfway through, the western airport is dark and the eastern one still lit."""
    config.data.led.init_sequence = "sweep"
    where = {"KHOU": (29.6, -95.3), "KIAH": (30.0, -95.0), "KDKR": (31.3, -95.4), "KGLS": (29.3, -94.0)}
    strip = FakeStrip(5)
    metars = SimpleNamespace(data=DATA, position=where.get)
    r = Renderer(strip, metars, config, [FLIGHT], SunTimes("Houston", SUN), clock=clock)
    r.draw_frame()
    seen = []
    show = strip.show
    strip.show = lambda: (seen.append((clock.time(), list(strip))), show())
    r.fade_out()
    begin = seen[0][0]
    halfway = next(colors for at, colors in seen if at - begin >= 1.5)
    assert halfway[0] == (0, 0, 0)  # KHOU, the farthest west, is dark
    assert halfway[4] == flightcategory.COLORS["LIFR"]  # KGLS, the farthest east, still shows its color
    assert seen[-1][1] == [(0, 0, 0)] * 5


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


def test_render_ticks_no_faster_than_the_looks_change(config, clock):
    """A look that changes every 0.2 s (Flight Category Forecast, on every LED) doesn't need 100 frames a second."""
    from metarmap import renderer

    r, _ = make(config, clock)
    r._looks = [Look.cycle([(0, 0, 0), (1, 1, 1)], step=0.2)] * 3
    assert r.frame_seconds() == 0.025
    r._looks = [Look.cycle([(0, 0, 0), (1, 1, 1)], step=0.2), Look.cycle([(0, 0, 0), (1, 1, 1)], step=0.02)]
    assert r.frame_seconds() == renderer.FRAME_SECONDS  # the fastest look sets the pace, not below FRAME_SECONDS


def test_a_still_map_ticks_at_the_slowest_rate(config, clock):
    """Every look solid or off: nothing moves, so 20 frames a second (a brightness change shows within 50 ms)."""
    from metarmap import renderer

    r, _ = make(config, clock, data={"KHOU": metar("VFR"), "KIAH": metar("IFR"), "KDKR": metar("MVFR")})
    assert {look.effect for look in r.looks} <= {"solid", "off"}
    assert r.frame_seconds() == renderer.MAX_FRAME_SECONDS
    r._looks = [Look.solid((1, 2, 3)), Look.off()]
    assert r.frame_seconds() == renderer.MAX_FRAME_SECONDS
    r._looks = []  # no airports
    assert r.frame_seconds() == renderer.MAX_FRAME_SECONDS


def test_moving_looks_tick_as_fast_as_they_need(config, clock):
    """One moving look among still ones sets the pace: blink, breathing, lightning."""
    from metarmap import renderer
    from metarmap.leds.animations import PULSE_SPEED, PULSE_STEPS
    from metarmap.visualizers import style

    r, _ = make(config, clock)
    solid = Look.solid((1, 2, 3))
    r._looks = [solid, Look.blink((9, 9, 9), period=1.0), Look.off()]  # 0.5 s on, 0.5 s off
    assert r.frame_seconds() == renderer.MAX_FRAME_SECONDS  # an eighth of 0.5 s, capped
    r._looks = [solid, Look.blink((9, 9, 9), period=0.2)]
    assert r.frame_seconds() == pytest.approx(0.1 / 8)
    r._looks = [solid, Look.pulse((9, 9, 9), period=4.0)]  # breathing to dark: PULSE_SPEED frames
    assert r.frame_seconds() == pytest.approx(max(renderer.FRAME_SECONDS, PULSE_SPEED / 8))
    r._looks = [solid, Look.pulse((9, 9, 9), period=4.0, low=0.3)]  # never dark: 20 steps a breath
    assert r.frame_seconds() == pytest.approx(min(renderer.MAX_FRAME_SECONDS, 4.0 / PULSE_STEPS / 8))
    r._looks = [solid, style.with_lightning(solid, config.data)]  # 0.05 s frames
    assert r.frame_seconds() == renderer.FRAME_SECONDS


def test_step_counts_from_when_the_leds_were_built(config, clock):
    """A stepping visualizer's step now, for the pages and the Micro; none for the others."""
    fcf = visualizer_module.BY_ID["flight_category_forecast"]
    r, _ = make(config, clock, visualizers=[FLIGHT, fcf])
    assert r.step() is None
    r.visualizer = 1
    seconds = fcf.steps(config.data)["seconds"]
    assert r.step() == {"labels": ["Now", "+3h", "+6h", "+12h"], "index": 0, "prefix": "FC"}
    clock.advance(seconds * 1.5)
    assert r.step()["index"] == 1
    clock.advance(seconds * 3)  # round again
    assert r.step()["index"] == 0
    r.refresh()  # rebuilt: counted from now
    clock.advance(seconds * 2.1)
    assert r.step()["index"] == 2


def forecast_data():
    """Reports whose forecast changes category at each step, so every LED steps (a cycle look)."""
    return {code: Report(flight_category="VFR", forecast=("MVFR", "IFR", "LIFR")) for code in ("KHOU", "KIAH", "KGLS")}


def test_new_data_keeps_the_forecast_step(config, clock):
    """A fetch landing mid-forecast doesn't take it back to Now: the step count and the LEDs' frames go on."""
    fcf = visualizer_module.BY_ID["flight_category_forecast"]
    r, strip = make(config, clock, data=forecast_data(), visualizers=[FLIGHT, fcf])
    r.visualizer = 1
    seconds = fcf.steps(config.data)["seconds"]
    clock.advance(seconds * 2.5)  # in the middle of +6h
    assert r.step()["index"] == 2

    r.update_data(SimpleNamespace(data=forecast_data()))
    assert r.step()["index"] == 2  # still +6h, not Now
    draw_frame(r)
    assert strip[0] == flightcategory.COLORS["IFR"]  # and the LED shows the +6h category at once
    assert r.looks[0].colors[0] == flightcategory.COLORS["VFR"]  # the look itself (the web map's) still starts at Now


def test_another_visualizer_starts_at_now(config, clock):
    """Only new data keeps the step: picking a visualizer (or a settings change) starts it over."""
    fcf = visualizer_module.BY_ID["flight_category_forecast"]
    r, strip = make(config, clock, data=forecast_data(), visualizers=[FLIGHT, fcf])
    r.visualizer = 1
    clock.advance(fcf.steps(config.data)["seconds"] * 2.5)
    r.refresh()
    assert r.step()["index"] == 0
    draw_frame(r)
    assert strip[0] == flightcategory.COLORS["VFR"]


def test_the_wall_clock_going_back_doesnt_stop_the_steps(config, clock):
    """NTP setting a Pi's clock back must not hold a forecast at Now: steps are counted on the monotonic clock."""
    fcf = visualizer_module.BY_ID["flight_category_forecast"]
    r, _ = make(config, clock, data=forecast_data(), visualizers=[FLIGHT, fcf])
    r.visualizer = 1
    seconds = fcf.steps(config.data)["seconds"]
    clock.advance(seconds * 1.5)
    clock.set_wall_clock(NOON - timedelta(hours=1))
    assert r.step()["index"] == 1
    r.update_data(SimpleNamespace(data=forecast_data()))
    clock.advance(seconds)
    assert r.step()["index"] == 2


def test_new_data_during_a_visualizer_change_doesnt_bring_the_old_one_back(config, clock, monkeypatch):
    """
    A fetch's rebuild that read the old visualizer, and a visualizer change that comes in while it builds: the
    change's looks stay (the rebuild started last wins), with the new data.
    """
    r, _ = make(config, clock)
    looks = visualizer.looks
    changed = []

    def looks_then_change(vis, *args):
        built = looks(vis, *args)
        if not changed:  # the fetch's rebuild has read Flight Category; now the web picks Wind
            changed.append(True)
            r.visualizer = 1
        return built

    monkeypatch.setattr(visualizer, "looks", looks_then_change)
    new = {**DATA, "KHOU": metar("MVFR", wind=30)}
    r.update_data(SimpleNamespace(data=new))
    assert r.visualizer[1] is WIND
    assert r.looks == looks(WIND, CODES, new, config.data)


def test_a_failed_newer_rebuild_leaves_the_older_one_in(config, clock, monkeypatch):
    """A rebuild that started later but failed doesn't throw away the new data of the one it overtook."""
    r, _ = make(config, clock)
    looks = visualizer.looks
    calls = []

    def looks_then_fail(vis, *args):
        calls.append(vis)
        if len(calls) == 2:  # the newer rebuild, started while the first was building
            raise RuntimeError("bad data")
        built = looks(vis, *args)
        if len(calls) == 1:
            with pytest.raises(RuntimeError):
                r.refresh()
        return built

    monkeypatch.setattr(visualizer, "looks", looks_then_fail)
    new = {**DATA, "KHOU": metar("MVFR")}
    r.update_data(SimpleNamespace(data=new))
    assert r.looks[0] == Look.solid(flightcategory.COLORS["MVFR"])


def test_the_step_and_legend_follow_the_new_visualizer_during_its_change(config, clock, monkeypatch):
    """
    A poll while a visualizer change builds its looks: the new visualizer is set (the pages already show its name),
    its looks and step count aren't in yet. Its own legend, every entry in use, and its first step: not its steps
    counted from the last one's start, nor its legend marked by the last one's looks.
    """
    fcf = visualizer_module.BY_ID["flight_category_forecast"]
    r, _ = make(config, clock, data=forecast_data(), visualizers=[FLIGHT, fcf])
    clock.advance(fcf.steps(config.data)["seconds"] * 2.5)  # Flight Category's start is long ago
    looks = visualizer.looks
    seen = []

    def looks_and_poll(vis, *args):
        seen.append((r.step(), r.legend(), r.legend_in_use()))
        return looks(vis, *args)

    monkeypatch.setattr(visualizer, "looks", looks_and_poll)
    r.visualizer = 1
    ((step, legend, in_use),) = seen
    assert step == {"labels": ["Now", "+3h", "+6h", "+12h"], "index": 0, "prefix": "FC"}
    assert [item["key"] for item in legend] == [item["key"] for item in visualizer.legend(fcf, config.data)]
    assert in_use == [] and all(item["inUse"] for item in legend)
    assert r.step()["index"] == 0  # in: counted from now
    assert r.legend_in_use() == visualizer.in_use(fcf, r.looks, config.data) != []


def test_the_legend_is_built_outside_the_lock(config, clock, monkeypatch):
    """The render loop takes the lock every frame (one core on a Pi Zero W): a poll holds it only to read."""
    import threading

    r, _ = make(config, clock)
    free = []

    def lock_is_free():
        taken = []
        thread = threading.Thread(target=lambda: taken.append(r._lock.acquire(timeout=1) and r._lock.release() is None))
        thread.start()
        thread.join()
        free.append(taken == [True])

    legend, in_use = visualizer.legend, visualizer.in_use
    monkeypatch.setattr(visualizer, "legend", lambda *args: lock_is_free() or legend(*args))
    monkeypatch.setattr(visualizer, "in_use", lambda *args: lock_is_free() or in_use(*args))
    r.legend()
    r.legend_in_use()
    assert len(free) >= 2 and all(free)


def test_virtual_airports_follow_the_strip_look_shown_during_a_visualizer_change(virtual, clock, monkeypatch):
    """Rainbow is on and Chase is being built: the virtual airports still join the Rainbow shown, not go dark."""
    r, _ = make(virtual, clock, leds=3, visualizers=[RAINBOW, CHASE])
    strip_look = visualizer.strip_look
    seen = []

    def strip_look_and_poll(vis, settings):
        if vis is CHASE:
            seen.append(r.led_states())
        return strip_look(vis, settings)

    monkeypatch.setattr(visualizer, "strip_look", strip_look_and_poll)
    r.visualizer = 1
    leds, strip = seen[0]
    assert strip["effect"] == "rainbow" and leds == {3: strip, 4: strip}
    leds, strip = r.led_states()
    assert strip["effect"] == "chase" and leds[3] == {"effect": "off", "colors": []}


def test_at_time_leaves_other_looks_alone():
    from metarmap.renderer import at_time

    solid = Look.solid((1, 2, 3))
    assert at_time(solid, 100) is solid
    cycle = Look.cycle([(1, 0, 0), (2, 0, 0), (3, 0, 0)], step=0.5)
    assert at_time(cycle, 0) is cycle
    assert at_time(cycle, 1.2).colors == ((3, 0, 0), (1, 0, 0), (2, 0, 0))  # 2 frames in
    assert at_time(cycle, 1.6).colors == cycle.colors  # a whole loop


def test_a_whole_strip_look_ticks_at_full_speed(config, clock):
    """Rainbow steps every 0.1 s: a slower tick makes the steps uneven, which shows as stutter."""
    from metarmap import renderer

    r, _ = make(config, clock)
    r.visualizer = 3  # rainbow
    assert r.strip_look is not None and r.frame_seconds() == renderer.FRAME_SECONDS


def test_led_states_are_converted_once_per_rebuild(config, clock, monkeypatch):
    """/api/live is polled by every open page every second: a look with ~140 colors must not be redone each time."""
    r, _ = make(config, clock)
    calls = []
    real = Look.to_dict
    monkeypatch.setattr(Look, "to_dict", lambda self: calls.append(1) or real(self))
    first = r.led_states()
    count = len(calls)
    assert count and r.led_states() == first and len(calls) == count
    r.refresh()  # rebuilt: converted again
    r.led_states()
    assert len(calls) > count


# ---- the render loop ------------------------------------------------------------------------------------------


LONGEST_SLEEP = 0.1  # the longest single sleep Darryl allows render() (it uses SLICE_SECONDS, shorter)


class AnimationTime:
    """
    The render loop's and the animations' clock (the LED library's monotonic_ms), moved on only by the loop's sleeps.
    after() runs something once the clock gets there, as another thread would (a fetch, the web UI, the OLED loop).
    """

    def __init__(self):
        self.ms = 1_000_000.0
        self.sleeps = []
        self._then = []

    def monotonic_ms(self):
        return int(self.ms)

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.ms += seconds * 1000
        for when, callback in [t for t in self._then if t[0] <= self.ms]:
            self._then.remove((when, callback))
            callback()

    def after(self, seconds, callback):
        self._then.append((self.ms + seconds * 1000, callback))


@pytest.fixture
def ticks(monkeypatch):
    """Fake time for render(): ask for it before make(), so the animations are built on it."""
    import adafruit_led_animation.animation as animation_module
    import adafruit_led_animation.animation.rainbow as rainbow_module
    import adafruit_led_animation.pulse_generator as pulse_module

    from metarmap import renderer

    t = AnimationTime()
    for module in (animation_module, rainbow_module, pulse_module, renderer):
        monkeypatch.setattr(module, "monotonic_ms", t.monotonic_ms)
    monkeypatch.setattr(renderer.time, "sleep", t.sleep)
    return t


def show_times(strip, ticks):
    """Records when (ms) the strip is sent."""
    times = []
    show = strip.show

    def recording_show():
        times.append(ticks.ms)
        show()

    strip.show = recording_show
    return times


def test_frame_due():
    from metarmap.renderer import frame_due

    def animation(at, paused=False):
        return SimpleNamespace(_next_update=at, _paused=paused)

    assert frame_due([animation(500), animation(200), animation(300)]) == 200  # no window: the first
    assert frame_due([animation(500), animation(200), animation(208)], window=10) == 208  # the last close to it
    assert frame_due([animation(500), animation(200), animation(211)], window=10) == 200  # too far: its own frame
    assert frame_due([animation(500), animation(100, paused=True)]) == 500  # frozen: not due
    assert frame_due([animation(100, paused=True)]) is None
    assert frame_due([]) is None
    for odd in (SimpleNamespace(), animation(None), animation(True), animation("soon")):
        with pytest.raises(LookupError):
            frame_due([animation(100), odd])


def test_a_still_map_sleeps_between_its_few_frames(config, clock, ticks):
    """Flight Category on a quiet day: every look solid or off. It used to draw 20 frames a second."""
    from metarmap import renderer

    r, strip = make(config, clock)
    shows = show_times(strip, ticks)
    start = ticks.ms
    r.render()
    assert ticks.ms - start == pytest.approx(renderer.RENDER_SECONDS * 1000, abs=1)  # then the main loop's jobs
    assert ticks.sleeps and max(ticks.sleeps) <= LONGEST_SLEEP
    # the first frame, and one IDLE_SECONDS later (the strip's resend needs a show() now and then); a solid look's
    # next redraw (each second) is the next render()'s
    assert [t - start for t in shows] == [0, renderer.IDLE_SECONDS * 1000]
    assert strip[0] == flightcategory.COLORS["VFR"]


def test_render_draws_into_the_buffer_and_sends_once_per_frame(config, clock, ticks):
    """Every LED has its own animation, and each one's show() would send the whole strip: 252 sends a frame."""
    r, strip = make(config, clock)
    shows = show_times(strip, ticks)
    drawn = []
    for animation in r.animations:
        animate = animation.animate
        animation.animate = lambda show=True, animate=animate: drawn.append(show) or animate(show=show)
    r.render()
    assert drawn and not any(drawn)  # the animations only draw into the strip's buffer
    assert len(drawn) == len(shows) * len(r.animations)  # and the renderer sends it, once a frame


def test_a_whole_strip_look_keeps_its_cadence(config, clock, ticks):
    """Rainbow steps every 0.1 s: one frame per step, none in between, none skipped."""

    r, strip = make(config, clock)
    r.visualizer = 3  # rainbow
    (animation,) = r.animations
    shows = show_times(strip, ticks)
    for _ in range(3):
        r.render()
    assert animation.draw_count == 30
    assert len(shows) == 30 and {round(b - a) for a, b in zip(shows, shows[1:])} == {100}
    assert max(ticks.sleeps) <= LONGEST_SLEEP


def test_leds_due_at_nearly_the_same_time_share_a_frame(config, clock, ticks):
    """Two LEDs due 5 ms apart are drawn in the same frame, every time, not in two frames 5 ms apart."""
    from metarmap.leds.animations import animation_for

    r, strip = make(config, clock, leds=2)
    blinks = [animation_for(Look.blink((255, 0, 0), period=1.0), pixel) for pixel in r._pix[:2]]
    blinks[1]._next_update += 5  # due 5 ms after the first
    r._animations = blinks
    drawn = {0: [], 1: []}
    for i, blink in enumerate(blinks):
        animate = blink.animate
        blink.animate = lambda show=True, i=i, animate=animate: animate(show=show) and drawn[i].append(ticks.ms)
    shows = show_times(strip, ticks)
    for _ in range(3):
        r.render()
    # the first frame comes at once, before the second LED is due; from then on both are drawn at the same frames
    assert len(drawn[0]) >= 6 and drawn[0][1:] == drawn[1][1:]
    assert set(drawn[0] + drawn[1]) <= set(shows)
    assert min(b - a for a, b in zip(shows, shows[1:])) >= r.frame_seconds() * 1000


def test_fifty_leds_stay_in_one_frame_when_frames_take_time(config, clock, ticks):
    """
    Each animation's draw takes a little time, so LEDs drawn later in a frame come due a little later: without
    sharing frames they drift apart into several frames per step (a Flight Category Forecast at 50 LEDs).
    """
    import random

    from metarmap.leds.animations import animation_for

    rand = random.Random(1)
    config.data.airports = airports(*[f"K{i:03d}" for i in range(50)])
    config.data.led.count = 50
    r, strip = make(config, clock, data={}, leds=50)
    colors = [(i, 0, 0) for i in range(1, 141)]
    animations = [animation_for(Look.cycle(colors, step=0.2), pixel) for pixel in r._pix]
    for animation in animations:
        animate = animation.animate

        def slow(show=True, animate=animate):
            ticks.ms += rand.uniform(0, 0.5)  # 0 to 0.5 ms to draw each one
            return animate(show=show)

        animation.animate = slow
    r._looks = [Look.cycle(colors, step=0.2)] * 50
    r._animations = animations
    shows = show_times(strip, ticks)
    for _ in range(10):
        r.render()
    steps = min(a.draw_count for a in animations)
    assert steps >= 40 and max(a.draw_count for a in animations) == steps  # all LEDs on the same step
    assert len(shows) <= steps + 12  # one frame per step (and a few idle ones), not one per LED or per group
    assert len({a._next_update for a in animations}) > 1  # the jitter is there; the frames gather it up


def test_the_main_loop_gets_back_each_second_during_a_long_cycle(config, clock, ticks):
    """
    A forecast cycle lasts 20-28 s. render() used to return only at its end, so a fetch, auto-rotate or the sunrise
    brightness could be that late. Now it returns about once a second, and the cycle goes on from where it was.
    """
    from metarmap import renderer
    from metarmap.leds.animations import animation_for

    colors = [(i, 0, 0) for i in range(1, 29)]  # 28 steps, one a second
    r, strip = make(config, clock, data={"KHOU": metar("VFR")}, leds=1)
    r._animations = [animation_for(Look.cycle(colors, step=1.0), r._pix[0])]
    start = ticks.ms
    returns = []
    for _ in range(12):
        r.render()  # the main loop: render(), then scheduler.run_pending()
        returns.append(ticks.ms)
    gaps = [b - a for a, b in zip([start] + returns, returns)]
    assert max(gaps) <= renderer.RENDER_SECONDS * 1000 + 1
    assert strip[0] == colors[11]  # 12 steps in 12 s: not back to the first color at each return
    assert max(ticks.sleeps) <= LONGEST_SLEEP


def test_new_animations_start_within_a_slice(config, clock, ticks):
    """New data, a new visualizer or a new strip length shows at once, not at the old animations' next step."""
    from metarmap import renderer

    r, strip = make(config, clock)
    rebuilt = []
    ticks.after(0.3, lambda: rebuilt.append(ticks.ms) or r.refresh())  # e.g. a fetch on the scheduler's thread
    r.render()
    assert rebuilt and ticks.ms - rebuilt[0] <= renderer.SLICE_SECONDS * 1000
    shows = show_times(strip, ticks)
    returned = ticks.ms
    r.render()  # the main loop's next call draws the new animations straight away
    assert shows[0] == returned


def test_a_brightness_change_is_sent_within_a_slice(config, clock, ticks):
    """The web UI's slider, the brightness schedule and quiet hours don't wait for an animation's next step."""
    from metarmap import renderer

    r, strip = make(config, clock)
    sent = []
    show = strip.show
    strip.show = lambda: sent.append((ticks.ms, strip.brightness)) or show()
    changed = []
    ticks.after(0.2, lambda: changed.append(ticks.ms) or r.brightness(0.3))
    r.render()
    first = next(t for t, level in sent if level == 0.3)
    assert first - changed[0] <= renderer.SLICE_SECONDS * 1000


def test_each_fade_step_wakes_the_loop(config, clock, ticks):
    """The fetch dim sends each step itself; the loop draws frames after it, for the strip's settling resends."""
    from metarmap import renderer

    r, _ = make(config, clock)
    woken = []
    wake = r._wake.set
    r._wake.set = lambda: woken.append(r.pixels().brightness) or wake()
    start = r.pixels().brightness
    r._fade(start, start / 2)
    assert len(woken) == renderer.FADE_STEPS and woken[-1] == start / 2


def test_the_end_of_a_locate_pulse_redraws_at_once(config, clock, ticks):
    """The pulsed LED goes back to its own look right away, not at its solid look's next redraw (a second)."""
    from metarmap import renderer

    r, strip = make(config, clock)
    ended = []

    def locate():
        r.locate(0)  # the OLED loop's thread: the pulse takes the strip for a second
        ended.append(ticks.ms)

    ticks.after(0.2, locate)
    shows = show_times(strip, ticks)
    r.render()
    r.render()
    assert strip[0] == flightcategory.COLORS["VFR"]
    after = [t for t in shows if t >= ended[0]]
    assert after and after[0] - ended[0] <= renderer.SLICE_SECONDS * 1000


def test_resume_draws_at_once(config, clock, ticks):
    """After a freeze (locate(), a startup sequence) the LEDs are drawn again at once, not at the next due frame."""
    from metarmap import renderer

    r, strip = make(config, clock)
    resumed = []
    ticks.after(0.2, lambda: (r.stop(), r.resume(), resumed.append(ticks.ms)))
    shows = show_times(strip, ticks)
    r.render()
    after = [t for t in shows if t >= resumed[0]]
    assert after and after[0] - resumed[0] <= renderer.SLICE_SECONDS * 1000 < renderer.IDLE_SECONDS * 1000 - 200


def test_frozen_animations_wait_for_resume(config, clock, ticks):
    r, _ = make(config, clock)
    r.render()
    counts = [a.draw_count for a in r.animations]
    r.stop()
    r.render()
    r.render()
    assert [a.draw_count for a in r.animations] == counts
    assert max(ticks.sleeps) <= LONGEST_SLEEP
    r.resume()
    resumed = ticks.ms
    shows = show_times(r.pixels(), ticks)
    r.render()
    assert shows[0] == resumed  # drawn at once
    assert all(a.draw_count > c for a, c in zip(r.animations, counts))


def test_a_settling_strip_is_sent_every_tick(config, clock, ticks):
    """Just after a change the strip resends at the next frame (SkipUnchangedShow.settling()): that frame comes."""
    r, strip = make(config, clock)
    start = ticks.ms
    strip.settling = lambda: ticks.ms - start < 100
    shows = show_times(strip, ticks)
    r.render()
    tick = r.frame_seconds() * 1000
    assert [t - start for t in shows[:3]] == [0, tick, 2 * tick]


class SendingStrip(SkipUnchangedShow, FakeStrip):
    """A FakeStrip that sends through SkipUnchangedShow as on a Pi: `shows` counts the frames really sent."""

    @property
    def _post_brightness_buffer(self):
        return bytes(v for color in self for v in color)


def breathing_renderer(config, clock, ticks, n=5):
    """A renderer whose LEDs all breathe (a 0.2 s step, as Flight Category's estimated categories), on SendingStrip."""
    from metarmap.leds.animations import animation_for
    from metarmap.visualizers import style

    strip = SendingStrip(n)
    strip._monotonic = lambda: ticks.ms / 1000  # the animations' clock
    r = Renderer(strip, SimpleNamespace(data=DATA), config, [FLIGHT], SunTimes("Houston", SUN), clock=clock)
    looks = [Look.pulse((0, 200, 0), period=style.LIGHT_PERIOD, low=style.LIGHT_LOW)] * n
    r._looks = looks
    r._animations = [animation_for(look, pixel) for look, pixel in zip(looks, r._pix)]
    return r, strip


def test_a_settling_strip_draws_one_more_frame_per_step(config, clock, ticks):
    """
    Breathing LEDs step every 0.2 s: each step is sent, and once more at the next frame (the settling resend), and
    then nothing until the next step. With a 0.1 s window it was sent at every tick, 0.1 s of each 0.2 s step.
    """
    r, strip = breathing_renderer(config, clock, ticks)
    frames = show_times(strip, ticks)
    r.render()
    r.render()
    steps = r.animations[0].draw_count
    assert steps >= 9
    assert len(frames) <= 2 * steps + 2  # a step and its resend (and an idle frame or so)
    assert strip.shows >= 2 * steps - 1  # every one of those really sent: the resend isn't lost
    assert not strip.settling()  # ended between two steps


# ---- locate() pulses over the running animations ---------------------------------------------------------------


def frames_of(strip, ticks):
    """Records (ms, colors) at each frame the render loop draws."""
    frames = []
    show = strip.show

    def recording_show():
        frames.append((ticks.ms, list(strip)))
        return show()

    strip.show = recording_show
    return frames


def white(color):
    return color[0] == color[1] == color[2] > 0


def test_other_leds_keep_animating_during_a_locate_pulse(config, clock, ticks):
    """The pulse stops nothing: the other LEDs breathe on, in the same frames, and the located LED stays in step."""
    r, strip = breathing_renderer(config, clock, ticks)
    frames = frames_of(strip, ticks)
    ticks.after(0.1, lambda: r.locate(0))  # the OLED loop's thread (the fake clock doesn't wait)
    for _ in range(3):
        r.render()
    pulsing = [colors for _, colors in frames if white(colors[0])]
    assert len(pulsing) >= 5
    assert len({colors[1] for colors in pulsing}) >= 3  # LED 1 went on breathing meanwhile
    assert all(not white(colors[1]) for colors in pulsing)  # and only LED 0 pulsed
    assert r._pulses == {}  # over
    assert strip[0] == strip[1]  # back to its own look, in step with the others: its animation never stopped
    assert r.animations[0].draw_count == r.animations[1].draw_count


def test_a_locate_pulse_rises_and_falls_once_and_the_led_comes_back(config, clock, ticks):
    r, strip = make(config, clock)
    frames = frames_of(strip, ticks)
    ticks.after(0.2, lambda: r.locate(0))
    r.render()
    r.render()
    levels = [colors[0][0] for _, colors in frames if white(colors[0])]
    peak = levels.index(max(levels))
    assert levels[: peak + 1] == sorted(levels[: peak + 1]) and levels[peak:] == sorted(levels[peak:], reverse=True)
    pulse_frames = [t for t, colors in frames if white(colors[0])]
    assert 800 <= pulse_frames[-1] - pulse_frames[0] <= 1100  # about LOCATE_SECONDS
    assert strip[0] == flightcategory.COLORS["VFR"] and strip[1] == flightcategory.COLORS["IFR"]


def test_a_rebuild_during_a_locate_pulse_keeps_it(config, clock, ticks):
    """New data rebuilds the animations mid-pulse: the pulse goes on (once, not again), then the new look shows."""
    r, strip = make(config, clock)
    frames = frames_of(strip, ticks)
    ticks.after(0.1, lambda: r.locate(0))
    rebuilt = []

    def new_data():
        rebuilt.append(ticks.ms)
        r.update_data(SimpleNamespace(data={**DATA, "KHOU": metar("MVFR")}))

    ticks.after(0.5, new_data)
    for _ in range(3):
        r.render()  # the main loop: render() returns at the rebuild and is called again
    assert any(white(colors[0]) for t, colors in frames if t > rebuilt[0])  # still pulsing after it
    levels = [colors[0][0] for _, colors in frames if white(colors[0])]
    peak = levels.index(max(levels))
    assert levels[peak:] == sorted(levels[peak:], reverse=True)  # one pulse, not started over
    assert r._pulses == {}
    assert strip[0] == flightcategory.COLORS["MVFR"]  # the new look, not the one from before the rebuild


def test_a_visualizer_that_ignores_locate_ends_its_pulse(config, clock, ticks):
    r, _ = make(config, clock)
    located = r._start_pulse(0)
    r.visualizer = 3  # rainbow: it has every LED
    assert r._pulses == {} and located.done.is_set()


def test_a_second_locate_of_the_same_led_takes_over(config, clock, ticks):
    """The web UI and the OLED loop both locate the same LED: the last one pulses, the first returns."""
    r, strip = make(config, clock)
    frames = frames_of(strip, ticks)
    first = []
    ticks.after(0.1, lambda: first.append(r._start_pulse(0)))
    ticks.after(0.6, lambda: r.locate(0))
    for _ in range(3):
        r.render()
    assert first[0].done.is_set()
    pulse_frames = [t for t, colors in frames if white(colors[0])]
    assert pulse_frames[-1] - pulse_frames[0] >= 1300  # the second ran its whole second
    assert r._pulses == {} and strip[0] == flightcategory.COLORS["VFR"]  # what was under the first


def pulse_until_white(r, strip, ticks):
    """Starts a locate() pulse on LED 0 and draws frames until it shows white; returns the pulse."""
    located = r._start_pulse(0)
    for _ in range(10):
        ticks.sleep(0.1)
        r.draw_frame()
        if white(strip[0]):
            return located
    raise AssertionError("the pulse never showed")


def test_an_overdue_pulse_ends_at_the_next_frame(config, clock, ticks):
    """No frames for longer than a pulse (a stalled loop): the next frame leaves the LED to its own look."""
    from metarmap import renderer

    r, strip = make(config, clock)
    located = pulse_until_white(r, strip, ticks)
    ticks.ms += (renderer.LOCATE_SECONDS + renderer.LOCATE_GRACE) * 1000
    r.draw_frame()
    assert r._pulses == {} and located.done.is_set()
    assert strip[0] == flightcategory.COLORS["VFR"]


@pytest.mark.parametrize("sequence", ["comet", "sweep"])
def test_a_startup_sequence_ends_a_pulse(config, clock, ticks, sequence):
    """The test pattern (stop(), then the sequence, then resume()) takes the whole strip: the pulse ends there."""
    config.data.led.init_sequence = sequence
    r, strip = make(config, clock)
    located = pulse_until_white(r, strip, ticks)
    r.test_pattern()
    assert r._pulses == {} and located.done.is_set()
    r.render()
    assert strip[0] == flightcategory.COLORS["VFR"]


def test_a_shorter_strip_drops_a_pulse_past_its_end(config, clock, ticks):
    r, strip = make(config, clock)
    located = r._start_pulse(4)
    r.resize(3)
    r.draw_frame()
    assert r._pulses == {} and located.done.is_set() and len(strip) == 3
    assert r._start_pulse(4) is None  # checked in the lock: a resize() just after locate() looked can't raise
    r.locate(4)  # past the strip now: recorded for the web map, no pulse, no IndexError
    assert r.last_locate["pixel"] == 4 and r._pulses == {}


def test_quiet_hours_fade_a_pulsing_led_from_its_own_color(config, clock, ticks, monkeypatch):
    """fade_out() mid-pulse: the located LED fades from its look, not from the pulse's white."""
    from metarmap.leds import intro

    config.data.led.init_sequence = "sweep"
    r, strip = make(config, clock)
    located = pulse_until_white(r, strip, ticks)
    faded_from = []
    colors_out_at = intro.colors_out_at
    monkeypatch.setattr(
        intro,
        "colors_out_at",
        lambda t, starts, sources: faded_from.append(list(sources)) or colors_out_at(t, starts, sources),
    )
    r.fade_out()
    assert faded_from[0][0] == flightcategory.COLORS["VFR"] and faded_from[0][1] == flightcategory.COLORS["IFR"]
    assert r._pulses == {} and located.done.is_set()


def test_locate_waits_for_the_pulse_on_its_own_thread(config):
    """Real time: locate() returns when the pulse is over (the OLED pages follow it), and the LEDs ran meanwhile."""
    import threading
    import time

    from metarmap.clock import Clock

    r, strip = make(config, Clock())
    stop = threading.Event()

    def main_loop():
        while not stop.is_set():
            r.render()

    loop = threading.Thread(target=main_loop, daemon=True)
    loop.start()
    try:
        shows = strip.shows
        started = time.monotonic()
        r.locate(0)
        took = time.monotonic() - started
    finally:
        stop.set()
        loop.join(3)
    assert 0.9 <= took <= 1.5
    assert strip.shows - shows >= 8  # the loop drew the pulse's frames while locate() waited
    assert r._pulses == {} and strip[0] == flightcategory.COLORS["VFR"]


def test_animations_that_dont_say_when_theyre_due_get_a_steady_tick(config, clock, ticks, caplog):
    """Another version of the LED library, without Animation._next_update: frames every frame_seconds(), as before."""
    from metarmap import renderer

    class Old:
        def __init__(self):
            self.calls = 0

        def animate(self, show=True):
            self.calls += 1

    r, _ = make(config, clock)
    old = Old()
    r._animations = [old]
    r.render()
    r.render()
    tick = r.frame_seconds()
    assert old.calls == pytest.approx(2 * renderer.RENDER_SECONDS / tick, abs=2)
    assert max(ticks.sleeps) <= LONGEST_SLEEP
    assert sum("next due" in record.getMessage() for record in caplog.records) == 1  # logged once


def test_render_does_not_pile_up_callbacks(config, clock, ticks):
    """
    render() used to group the LEDs' animations afresh at each call, and each group hooked a callback onto the last
    one (one a second, until the next rebuild). It hooks nothing now.
    """
    r, _ = make(config, clock)
    hooked = [len(a._also_notify) for a in r.animations]
    for _ in range(50):
        r.render()
    assert [len(a._also_notify) for a in r.animations] == hooked
    assert max(a.draw_count for a in r.animations) > 1  # it did run them


def test_render_rests_after_an_error(config, clock, ticks):
    from metarmap import renderer

    class Broken:
        def animate(self, show=True):
            raise RuntimeError("no such animation")

    r, _ = make(config, clock)
    r._animations = [Broken()]
    r.render()  # the main loop calls it again at once; it mustn't spin
    assert ticks.sleeps == [renderer.FRAME_SECONDS]


def test_no_leds_is_no_error(config, clock, ticks):
    """An empty airport list: nothing to animate, but render() still rests and returns."""

    config.data.airports = []
    r, _ = make(config, clock, leds=0)
    r.render()
    assert ticks.sleeps and max(ticks.sleeps) <= LONGEST_SLEEP


# ---- changing visualizers: cut, dissolve, dip (visualizer.transition) -----------------------------------------


def shown(strip):
    from metarmap.renderer import rgb

    return [rgb(c) for c in strip]


def colors_of(config, clock, number):
    """What the LEDs show for visualizer `number`, with no transition: the end of one."""
    r, strip = make(config, clock)
    r.visualizer = number
    r.draw_frame()
    return shown(strip)


def switched(config, clock, style, number=1):
    """A renderer showing Flight Category, then switched to visualizer `number` with `style`: (renderer, strip, old)."""
    r, strip = make(config, clock)
    r.draw_frame()
    old = shown(strip)
    config.data.visualizer.transition = style
    r.visualizer = number
    return r, strip, old


def blended(old, new, t):
    from metarmap.renderer import blend

    return [blend(a, b, t) for a, b in zip(old, new)]


def test_cut_changes_at_once(config, clock):
    new = colors_of(config, clock, 1)
    r, strip, old = switched(config, clock, "cut")
    assert not r.transitioning
    r.draw_frame()
    assert shown(strip) == new != old


@pytest.mark.parametrize("style", ["dissolve", "dip"])
def test_a_transition_starts_from_the_old_colors(config, clock, style):
    r, strip, old = switched(config, clock, style)
    assert r.transitioning
    r.draw_frame()
    assert shown(strip) == old  # the old animations are frozen as they were, not run on


def test_dissolve_blends_half_way_at_the_midpoint(config, clock):
    from metarmap.renderer import TRANSITION_SECONDS

    new = colors_of(config, clock, 1)
    r, strip, old = switched(config, clock, "dissolve")
    r.draw_frame()
    clock.advance(TRANSITION_SECONDS / 2)
    r.draw_frame()
    assert shown(strip) == blended(old, new, 0.5)
    assert shown(strip) != old and shown(strip) != new


def test_dip_is_dark_at_the_midpoint(config, clock):
    from metarmap.renderer import TRANSITION_SECONDS

    new = colors_of(config, clock, 1)
    r, strip, old = switched(config, clock, "dip")
    r.draw_frame()
    clock.advance(TRANSITION_SECONDS / 4)
    r.draw_frame()
    assert shown(strip) == blended(old, [(0, 0, 0)] * len(old), 0.5)  # half way down
    clock.advance(TRANSITION_SECONDS / 4)
    r.draw_frame()
    assert shown(strip) == [(0, 0, 0)] * len(old)
    clock.advance(TRANSITION_SECONDS / 4)
    r.draw_frame()
    assert shown(strip) == blended([(0, 0, 0)] * len(new), new, 0.5)  # half way up


@pytest.mark.parametrize("style", ["dissolve", "dip"])
def test_a_transition_ends_at_the_new_colors(config, clock, style):
    from metarmap.renderer import TRANSITION_SECONDS

    new = colors_of(config, clock, 1)
    r, strip, _ = switched(config, clock, style)
    r.draw_frame()
    clock.advance(TRANSITION_SECONDS)
    r.draw_frame()
    assert shown(strip) == new
    assert not r.transitioning  # nothing left running


@pytest.mark.parametrize("style", ["dissolve", "dip"])
def test_refresh_does_not_transition(config, clock, style):
    r, strip = make(config, clock)
    r.draw_frame()
    config.data.visualizer.transition = style
    r.refresh()
    assert not r.transitioning
    r.visualizer = r.active_visualizer  # picked again: the same one
    assert not r.transitioning


def test_no_transition_into_the_first_visualizer(config, clock):
    """At startup the visualizer from config.json is set before any frame: it shows at once."""
    config.data.visualizer.transition = "dissolve"
    r, strip = make(config, clock)
    r.visualizer = 1
    assert not r.transitioning
    r.draw_frame()
    assert shown(strip) == colors_of(config, clock, 1)


def test_a_second_switch_starts_from_the_colors_shown(config, clock):
    from metarmap.renderer import TRANSITION_SECONDS

    flight, wind = colors_of(config, clock, 0), colors_of(config, clock, 1)
    r, strip, _ = switched(config, clock, "dissolve")
    r.draw_frame()
    clock.advance(TRANSITION_SECONDS / 2)
    r.draw_frame()
    middle = shown(strip)
    r.visualizer = 0  # back to Flight Category, half way through
    assert r.transitioning
    r.draw_frame()
    assert shown(strip) == middle  # no jump back to Wind's or Flight Category's colors
    clock.advance(TRANSITION_SECONDS / 2)
    r.draw_frame()
    assert shown(strip) == blended(middle, flight, 0.5)
    clock.advance(TRANSITION_SECONDS / 2)
    r.draw_frame()
    assert shown(strip) == flight and middle != wind


def test_a_cut_mid_transition_ends_it(config, clock):
    r, strip, _ = switched(config, clock, "dissolve")
    r.draw_frame()
    config.data.visualizer.transition = "cut"
    r.visualizer = 2
    assert not r.transitioning
    r.draw_frame()
    assert shown(strip) == colors_of(config, clock, 2)


def test_brightness_still_applies_during_a_transition(config, clock):
    """The blend is in the colors; the strip's brightness (dim, quiet hours) goes on top, as always."""
    from metarmap.renderer import TRANSITION_SECONDS

    new = colors_of(config, clock, 1)
    r, strip, old = switched(config, clock, "dissolve")
    r.draw_frame()
    r.brightness(0.0)  # quiet hours
    clock.advance(TRANSITION_SECONDS / 2)
    r.draw_frame()
    assert strip.brightness == 0.0
    assert shown(strip) == blended(old, new, 0.5)
    r.brightness(0.3)
    clock.advance(TRANSITION_SECONDS / 2)
    r.draw_frame()
    assert strip.brightness == 0.3 and shown(strip) == new


def test_a_whole_strip_look_dissolves_in(config, clock):
    from metarmap.renderer import TRANSITION_SECONDS

    r, strip, old = switched(config, clock, "dissolve", number=3)  # rainbow
    r.draw_frame()
    clock.advance(TRANSITION_SECONDS / 2)
    r.draw_frame()
    live = r._transition.live  # what the rainbow drew this frame
    assert shown(strip) == blended(old, live, 0.5) != live
    clock.advance(TRANSITION_SECONDS / 2)
    r.draw_frame()
    assert not r.transitioning and shown(strip) != old


def test_a_hidden_pixel_stays_dark_through_a_transition(config, clock):
    from metarmap.renderer import TRANSITION_SECONDS

    config.data.airports[2].skip = True  # LED 2 has no airport: a Hidden Pixel
    r, strip, _ = switched(config, clock, "dissolve", number=3)  # rainbow would light it

    for _ in range(3):
        r.draw_frame()
        assert strip[2] == (0, 0, 0)
        clock.advance(TRANSITION_SECONDS / 2)


def test_a_startup_sequence_ends_a_transition(config, clock):
    r, strip, _ = switched(config, clock, "dip")
    r.stop()
    assert not r.transitioning
    r.resume()


def test_a_transition_draws_frames_at_the_normal_rate_and_then_rests(config, clock, ticks, monkeypatch):
    """A still map rests between frames; during the 0.5 s blend it draws a smooth series, then rests again."""
    from metarmap import renderer

    sleep = ticks.sleep
    monkeypatch.setattr(renderer.time, "sleep", lambda s: (sleep(s), clock.advance(s)))
    r, strip, _ = switched(config, clock, "dissolve")
    shows = show_times(strip, ticks)
    start = ticks.ms
    r.render()
    during = [t - start for t in shows if t - start < renderer.TRANSITION_SECONDS * 1000]
    after = [t - start for t in shows if t - start > renderer.TRANSITION_SECONDS * 1000 + 50]
    assert len(during) >= renderer.TRANSITION_SECONDS / renderer.TRANSITION_FRAME_SECONDS - 1
    assert max(b - a for a, b in zip(during, during[1:])) <= renderer.TRANSITION_FRAME_SECONDS * 1000 + 1
    assert not r.transitioning
    assert len(after) <= 2  # a still map again: the idle frames only
    assert shown(strip) == colors_of(config, clock, 1)


def white_pulse(r, n):
    """A locate() pulse on LED n, held at full white (its own steps follow the real clock)."""
    located = r._start_pulse(n)
    located.pulse.animate = lambda show=True: True
    located.held.color = (255, 255, 255)
    return located


def test_a_locate_pulse_during_a_transition(config, clock):
    """It goes over its LED's new color, not the blend, and the LED ends on its new color."""
    from metarmap.renderer import TRANSITION_SECONDS

    new = colors_of(config, clock, 1)
    r, strip, old = switched(config, clock, "dissolve")
    r.draw_frame()
    clock.advance(TRANSITION_SECONDS / 2)
    r.draw_frame()
    located = white_pulse(r, 0)
    assert located.under == new[0]  # the LED's own color, not the blend shown
    r.draw_frame()
    assert strip[0] == blended([old[0]], [(255, 255, 255)], 0.5)[0]  # the pulse blends in with the rest
    assert shown(strip)[1:] == blended(old, new, 0.5)[1:]
    r._end_pulse(0)
    clock.advance(TRANSITION_SECONDS / 2)
    r.draw_frame()
    assert not r.transitioning and shown(strip) == new


def test_fewer_leds_during_a_transition_go_dark(config, clock):
    """led.count lowered mid-dissolve: the LEDs past it fade out, not stay on the transition's last colors."""
    from metarmap.renderer import TRANSITION_SECONDS

    r, strip, _ = switched(config, clock, "dissolve")
    r.draw_frame()
    clock.advance(TRANSITION_SECONDS / 2)
    r.draw_frame()
    assert strip[4] != (0, 0, 0)
    config.data.led.count = 3
    r.refresh()
    for _ in range(3):
        clock.advance(TRANSITION_SECONDS / 2)
        r.draw_frame()
    assert not r.transitioning
    assert strip[3] == strip[4] == (0, 0, 0)


def test_a_pulse_past_fewer_leds_during_a_transition_goes_dark(config, clock):
    """A locate() pulse on an LED that's no longer lit ends without its white staying in the transition's colors."""
    from metarmap.renderer import TRANSITION_SECONDS

    r, strip, _ = switched(config, clock, "dissolve")
    r.draw_frame()
    white_pulse(r, 4)
    clock.advance(TRANSITION_SECONDS / 4)
    r.draw_frame()
    assert r._transition.live[4] == (255, 255, 255)
    config.data.led.count = 3
    r.refresh()
    assert 4 not in r._pulses
    for _ in range(3):
        clock.advance(TRANSITION_SECONDS / 2)
        r.draw_frame()
    assert not r.transitioning
    assert strip[4] == (0, 0, 0)


# ---- LEDs with equal looks share one animation (look_groups, PixelGroup) ------------------------------------------


def test_look_groups():
    from metarmap.renderer import look_groups

    red, green = Look.solid((255, 0, 0)), Look.pulse((0, 255, 0), period=2.0, low=0.3)
    rainbow_look = Look.rainbow(period=5)
    looks = [red, green, red.tagged("vfr"), Look.off(), green, rainbow_look, rainbow_look, Look.off()]
    assert look_groups(looks) == [
        (red, [0, 2]),  # the legend isn't part of how it looks
        (green, [1, 4]),
        (Look.off(), [3, 7]),
        (rainbow_look, [5]),  # a look spread along its LEDs: one each
        (rainbow_look, [6]),
    ]
    unhashable = Look("solid", [(1, 2, 3)])  # colors as a list: compared by hash, so its own group, never an error
    assert look_groups([unhashable, unhashable]) == [(unhashable, [0]), (unhashable, [1])]
    assert look_groups([]) == []


@pytest.mark.parametrize(
    "a, b",
    [
        (Look.pulse((0, 255, 0), period=2.0, low=0.3), Look.pulse((0, 255, 0), period=3.0, low=0.3)),  # period
        (Look.pulse((0, 255, 0), period=2.0, low=0.3), Look.pulse((0, 255, 0), period=2.0, low=0.5)),  # low
        (Look.pulse((0, 255, 0), period=2.0), Look.pulse((0, 255, 0), period=2.0, low=0.3)),  # dark or not
        (Look.cycle([(1, 0, 0), (2, 0, 0)], step=0.2), Look.cycle([(1, 0, 0), (2, 0, 0)], step=0.3)),  # step
        (Look.cycle([(1, 0, 0), (2, 0, 0)], step=0.2), Look.cycle([(2, 0, 0), (1, 0, 0)], step=0.2)),  # phase
        (Look.blink((255, 0, 0), period=1.0), Look.blink((255, 0, 0), period=2.0)),  # period
        (Look.blink((255, 0, 0)), Look.blink((255, 0, 0), background=(0, 0, 255))),  # second color
        (Look.solid((255, 0, 0)), Look.solid((254, 0, 0))),  # color
        (Look.solid((0, 0, 0)), Look.off()),  # effect, even when it looks the same
    ],
)
def test_looks_differing_in_any_drawn_field_get_their_own_animation(a, b):
    from metarmap.renderer import look_groups

    assert look_groups([a, b, a, b]) == [(a, [0, 2]), (b, [1, 3])]


def test_pixel_group_writes_through_to_its_leds():
    strip = FakeStrip(6)
    group = PixelGroup(strip, [4, 1, 3])
    assert len(group) == 3 and group.leds == (4, 1, 3)
    group.fill((1, 2, 3))
    assert strip == [(0, 0, 0), (1, 2, 3), (0, 0, 0), (1, 2, 3), (1, 2, 3), (0, 0, 0)]
    group[1] = (9, 9, 9)
    assert strip[1] == (9, 9, 9) and group[1] == (9, 9, 9) and group[-1] == (1, 2, 3)
    group[0:2] = [(5, 5, 5), (6, 6, 6)]
    assert strip[4] == (5, 5, 5) and strip[1] == (6, 6, 6) and group[:2] == [(5, 5, 5), (6, 6, 6)]
    with pytest.raises(ValueError):
        group[0:2] = [(1, 1, 1)]
    group.show()
    assert strip.shows == 1
    with pytest.raises(ValueError):
        PixelGroup(strip, [])


def test_one_animation_per_distinct_look(config, clock):
    """Two LEDs of each category: one animation per category, drawn over both, and the strip as before."""
    config.data.airports = airports("KHOU", "KIAH", "KHOU", "", "KIAH", "KGLS", "KDKR", "")
    config.data.led.count = 8
    r, strip = make(config, clock, leds=8)
    assert len(r.animations) == len(set(r.looks)) == 4
    assert led_groups(r) == [[0, 2], [1, 4], [3, 6, 7], [5]]
    r.draw_frame()
    vfr, ifr, lifr = (flightcategory.COLORS[c] for c in ("VFR", "IFR", "LIFR"))
    off = (0, 0, 0)
    assert strip == [vfr, ifr, vfr, off, ifr, lifr, off, off]
    assert r.led_states()[0] == {i: look.to_dict() for i, look in enumerate(r.looks)}  # the web map: per LED


def everything_settings():
    """Settings with every kind of motion on: lightning, blinking missing data, breathing estimates."""
    settings = Settings()
    settings.lightning.animation = True
    settings.lightning.forecast = True
    settings.visualizer.missing_data_blink = True
    settings.visualizer.estimated_category_breathing = True
    return settings


def many_airports():
    """(codes, data): every sample report on two LEDs, and LEDs with no airport, so most looks have several LEDs."""
    from test_visualizers import sample_reports

    reports = sample_reports()
    codes = [f"K{i:03d}" for i in range(len(reports))]
    data = dict(zip(codes, reports))
    return codes + [""] * 3 + codes[::-1], data


def grouped_and_ungrouped(monkeypatch, vis, other, transition="dissolve"):
    """
    Two renderers of `vis` (then `other`) on the same clocks over the same airports: one as it runs, and one that gives
    every LED its own animation, as it was before looks were grouped (SHARED_EFFECTS empty during its rebuilds).
    """
    from metarmap import renderer as renderer_module

    codes, data = many_airports()
    built = []
    clock = FakeClock(NOON)
    for shared in (renderer_module.SHARED_EFFECTS, frozenset()):
        settings = everything_settings()
        settings.airports = airports(*codes)
        settings.led.count = len(codes)
        settings.visualizer.transition = transition
        with monkeypatch.context() as m:
            m.setattr(renderer_module, "SHARED_EFFECTS", shared)
            strip = FakeStrip(len(codes))
            r = Renderer(
                strip, SimpleNamespace(data=data), SimpleNamespace(data=settings), [vis, other], SUN_TIMES, clock=clock
            )
        built.append((r, strip, shared))
    return clock, built


SUN_TIMES = SunTimes("Houston", SUN)


def each_frame(built, ticks, clock, frames, events=None, seed=3):
    """
    Draws `frames` frames of every renderer in `built` at the same irregular instants (5-60 ms apart), runs
    events[frame](renderer) on each first, and yields the strips' colors at each frame.
    """
    import random

    from metarmap import renderer as renderer_module

    rand = random.Random(seed)
    for frame in range(frames):
        step = rand.randint(5, 60)
        ticks.ms += step
        clock.advance(step / 1000)
        for r, _, shared in built:
            if events and frame in events:
                with pytest.MonkeyPatch.context() as m:  # its rebuilds group (or don't) as it was built
                    m.setattr(renderer_module, "SHARED_EFFECTS", shared)
                    events[frame](r)
            with r._lock:
                r._draw(r._animations)
        yield [list(strip) for _, strip, _ in built]


def switch_to_other(r):
    r.visualizer = 1


def locate_shared_led(r):
    r._start_pulse(1)  # LED 1 (the first sample report has no report: off, as many others)


def stop_and_resume(r):
    r.stop()


@pytest.mark.parametrize("vis", visualizer_module.ALL, ids=lambda v: v.id)
def test_grouped_looks_draw_exactly_what_one_animation_per_led_did(monkeypatch, ticks, vis):
    """
    Every visualizer over a few hundred LEDs (lightning, blinking missing data, breathing estimates on), frame by
    frame at irregular instants: the strip is the same as with one animation per LED, through a locate() pulse on a
    shared LED, a freeze and resume (a startup sequence), a dissolve to another visualizer and new data.
    """
    other = FLIGHT if vis is not FLIGHT else WIND
    clock, built = grouped_and_ungrouped(monkeypatch, vis, other)
    (grouped, _, _), (reference, _, _) = built
    assert grouped.looks == reference.looks
    if grouped.strip_look is None:
        lit = grouped.looks[: grouped._config.data.led.count]
        assert len(reference.animations) == len(lit)
        assert len(grouped.animations) == len(set(lit)) < len(lit)
    events = {
        30: locate_shared_led,
        60: stop_and_resume,
        64: lambda r: r.resume(),
        100: switch_to_other,
        110: locate_shared_led,
        140: lambda r: r.update_data(r._metars),  # new data: a forecast goes on at its step (at_time)
    }
    compared = 0
    for colors in each_frame(built, ticks, clock, 160, events):
        assert colors[0] == colors[1]
        compared += 1
    assert compared == 160
    assert grouped.looks == reference.looks  # on the other visualizer by now


def test_grouped_looks_render_the_same_frames(monkeypatch, ticks):
    """The render loop sends the same colors at the same moments (frame_due over fewer animations: same instants)."""
    clock, built = grouped_and_ungrouped(monkeypatch, FLIGHT, WIND)
    start = ticks.ms
    runs = []
    for r, strip, _ in built:
        ticks.ms = start
        frames = frames_of(strip, ticks)
        for _ in range(3):
            r.render()
        runs.append(frames)
    assert len(runs[0]) > 10 and runs[0] == runs[1]


def test_a_locate_pulse_on_a_shared_led_leaves_the_others_in_its_group(config, clock, ticks):
    """LEDs 0 and 2 share a breathing animation: a pulse on LED 0 whitens only it, and it comes back in step."""
    config.data.airports = airports("KHOU", "KIAH", "KHOU")
    config.data.led.count = 3
    data = {"KHOU": Report(flight_category=None, visibility_sm=10.0), "KIAH": metar("IFR")}  # KHOU's breathes
    r, strip = make(config, clock, data=data, leds=3)
    assert led_groups(r) == [[0, 2], [1]] and r.looks[0].effect in ("pulse", "cycle")
    frames = frames_of(strip, ticks)
    ticks.after(0.1, lambda: r.locate(0))
    for _ in range(3):
        r.render()
    pulsing = [colors for _, colors in frames if white(colors[0])]
    assert len(pulsing) >= 5 and not any(white(colors[2]) for colors in pulsing)
    assert len({colors[2] for colors in pulsing}) >= 3  # LED 2 went on breathing meanwhile
    assert r._pulses == {} and strip[0] == strip[2]  # back in step with the LED it shares its animation with


def test_a_transition_blends_each_led_of_a_group(config, clock):
    """A dissolve from Flight Category to Wind: LEDs sharing an animation each blend from their own old color."""
    from metarmap.renderer import TRANSITION_SECONDS

    config.data.airports = airports("KHOU", "KIAH", "KHOU", "KGLS")
    config.data.led.count = 4
    data = {"KHOU": metar("VFR", wind=25), "KIAH": metar("IFR", wind=5), "KGLS": metar("LIFR", wind=5)}
    r, strip = make(config, clock, data=data, leds=4)
    r.draw_frame()
    old = list(strip)
    config.data.visualizer.transition = "dissolve"
    r.visualizer = 1  # wind: KIAH and KGLS have the same wind, so one animation for LEDs 1 and 3
    assert led_groups(r) == [[0, 2], [1, 3]]
    r.draw_frame()
    new = r._transition.live
    assert new[1] == new[3] and old[1] != old[3]
    clock.advance(TRANSITION_SECONDS / 2)
    r.draw_frame()
    assert list(strip) == blended(old, new, 0.5)
    assert strip[1] != strip[3]  # each from its own old color
    clock.advance(TRANSITION_SECONDS)
    r.draw_frame()
    assert not r.transitioning and strip[1] == strip[3] == new[1]
