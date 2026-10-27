"""
Tests for the web UI and API (metarmap.web): every page renders, the API's fields, the routes that change the map,
and the view data behind the pages.
"""
import base64
import io
import json
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from metarmap import __version__
from metarmap import app as app_module
from metarmap.leds.strip import FakeStrip
from metarmap.models import Look
from metarmap.renderer import Renderer
from metarmap.settings import Airport, Settings
from metarmap.sun import SunTimes
from metarmap.visualizers import flightcategory, rainbow
from metarmap.web import api, control, create_app, views

AUTH = "Basic " + base64.b64encode(b"metar:map").decode()
OBS = datetime(2026, 10, 24, 17, 53, tzinfo=timezone.utc)
NOON = datetime(2026, 10, 24, 17, 0, tzinfo=timezone.utc)
SUN = {"dawn": NOON.replace(hour=11), "sunrise": NOON.replace(hour=12), "sunset": NOON.replace(hour=23),
       "dusk": NOON.replace(hour=23, minute=30)}


def metar(category, **extra):
    return {"flightCategory": category, "raw": f"METAR {category}", "obsTime": OBS, "windSpeed": 5, "windDir": "100",
            "windGust": False, "windGustSpeed": 0, "lightning": False, "obs": "", "latitude": "29.6",
            "longitude": "-95.3", **extra}


class Client:
    """Calls a bottle app directly (no socket)."""

    def __init__(self, app):
        self.app = app

    def __call__(self, path, method="GET", auth=True, body=None):
        data = json.dumps(body).encode() if body is not None else b""
        environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": "", "SERVER_NAME": "test",
                   "SERVER_PORT": "80", "SERVER_PROTOCOL": "HTTP/1.1", "wsgi.url_scheme": "http",
                   "wsgi.input": io.BytesIO(data), "wsgi.errors": io.StringIO(), "CONTENT_LENGTH": str(len(data)),
                   "CONTENT_TYPE": "application/json"}
        if auth is True:
            environ["HTTP_AUTHORIZATION"] = AUTH
        elif auth:
            environ["HTTP_AUTHORIZATION"] = "Basic " + base64.b64encode(auth.encode()).decode()
        status, headers = [], []

        def start_response(s, h, exc_info=None):
            status.append(s)
            headers.extend(h)
        body = b"".join(self.app(environ, start_response)).decode()
        self.headers = dict(headers)
        return int(status[0].split()[0]), body

    def json(self, path, **kwargs):
        status, body = self(path, **kwargs)
        assert status in (200, 202), body
        assert self.headers["Content-Type"] == "application/json"
        return json.loads(body)


# ---- a whole map on fake hardware -------------------------------------------------------------------------------

@pytest.fixture
def client(make_app):
    app = make_app()
    c = Client(create_app(app, ip="10.0.0.2"))
    c.services = app
    yield c
    if app.display:
        app.display.stop()


@pytest.mark.parametrize("path", ["/", "/metars", "/raw", "/map", "/debug", "/config", "/config/airports",
                                  "/static/app.js", "/update/progress"])
def test_pages(client, path):
    status, body = client(path)
    assert status == 200, body


def test_config_needs_a_login(client):
    for path in ("/config", "/config/airports", "/config/edit/display_screen.delay/7", "/update/progress"):
        assert client(path, auth=False)[0] == 401


def test_pages_show_the_version(client):
    assert f"10.0.0.2 · v{__version__}" in client("/")[1]


def test_visualizer_routes(client):
    renderer = client.services.renderer
    assert client("/visualizer/next")[0] == 200
    assert renderer.visualizer[0] == 1
    assert client("/visualizer/previous")[0] == 200
    assert renderer.visualizer[0] == 0
    assert client("/visualizer/3")[0] == 200
    assert renderer.visualizer[0] == 3


def test_brightness(client):
    assert client("/brightness/0.3")[0] == 200
    assert client.services.renderer.pixels().brightness == 0.3


def test_config_edit(client):
    assert client("/config/edit/display_screen.delay/7")[0] == 200
    assert client.services.config.data.display_screen.delay == 7
    assert client("/config/edit/no.such/1")[0] == 400
    assert client("/config/edit/display_screen.delay/soon")[0] == 400


def test_airport_edit_restarts_the_display(client):
    app = client.services
    app.display.start()
    old_thread = app.display._thread
    code = app.config.airports[1].code
    status, _ = client(f"/config/airports/edit/prop/{code}/display/true")
    assert status == 303 and client.headers["Location"].endswith("/config/airports")
    assert app.config.airports[1].display is True
    assert app.display._thread is not old_thread and app.display.is_alive()  # restarted, for the new airports


def test_airports_page(client):
    app = client.services
    body = client("/config/airports")[1]
    assert body.count('data-field="code"') == app.config.data.led.count
    assert "50 LEDs in the order they're wired: 50 with an airport." in body
    client("/config/edit/led.count/52")
    client("/config/airports/0/code/-")
    assert "52 LEDs in the order they're wired: 49 with an airport, 3 without." in client("/config/airports")[1]
    assert 'id="restart-banner" role="status" hidden' in body


def test_auto_rotate_changes_without_a_restart(client):
    scheduler = client.services.scheduler
    assert not scheduler.get_jobs("rotate_visualizer")
    assert client("/config/edit/visualizer.auto_rotate.enabled/true")[0] == 200
    (job,) = scheduler.get_jobs("rotate_visualizer")
    assert job.interval == client.services.config.data.visualizer.auto_rotate.delay_seconds
    assert client("/config/edit/visualizer.auto_rotate.delay_seconds/20")[0] == 200
    assert [j.interval for j in scheduler.get_jobs("rotate_visualizer")] == [20]
    assert client("/config/edit/visualizer.auto_rotate.enabled/false")[0] == 200
    assert not scheduler.get_jobs("rotate_visualizer")
    body = client("/config")[1]
    assert 'data-key="visualizer.auto_rotate.enabled"' in body
    assert 'data-key="visualizer.auto_rotate.enabled" data-restart' not in body.replace(' checked', '')


def test_brightness_levels_apply_without_a_restart(client, monkeypatch):
    app = client.services
    monkeypatch.setattr(app.renderer, "scheduled_level", lambda: "normal")  # daytime, whatever time the test runs
    monkeypatch.setattr(app.renderer, "brightness_for", lambda now: app.config.data.led.brightness.normal)
    assert client("/config/edit/led.brightness.normal/0.3")[0] == 200
    assert app.renderer.pixels().brightness == 0.3  # the level in use: right away
    assert client("/config/edit/led.brightness.off/0.02")[0] == 200
    assert app.renderer.pixels().brightness == 0.3  # night's level: at dusk
    assert app.config.data.led.brightness.off == 0.02
    body = client("/config")[1]
    assert 'data-key="led.brightness.normal" data-label="led-brightness-normal-val" data-format="pct">' in body
    assert "data-restart" not in body and "Brightness levels load at midnight" not in body


def test_turning_on_the_test_pattern_runs_it(client, monkeypatch):
    app = client.services
    ran = threading.Event()
    monkeypatch.setattr(app.renderer, "test_pattern", ran.set)
    assert client("/config/edit/led.inittest/false")[0] == 200
    assert not ran.wait(0.2)  # turning it off doesn't
    assert client("/config/edit/led.inittest/true")[0] == 200
    assert ran.wait(5)


def test_choose_visualizers_for_auto_rotate(client):
    app = client.services
    body = client("/config")[1]
    assert 'data-rotate="Wind" checked' in body and 'data-rotate="Flight Category" checked' in body
    assert 'data-rotate="Rainbow"' not in body  # exclusive ones are never in the rotation
    assert 'data-rotate="Precipitation" checked' in body
    assert "Rainbow and Chase are always left out" in body

    # (the paths are as the server decodes them)
    assert client('/config/edit/visualizer.auto_rotate.skip/["Wind","Wind Gusts"]')[0] == 200
    assert app.config.data.visualizer.auto_rotate.skip == ["Wind", "Wind Gusts"]
    body = client("/config")[1]
    assert 'data-rotate="Wind" checked' not in body and 'data-rotate="Wind"' in body
    assert client.json("/api/status", auth=False)["config"]["visualizer.auto_rotate.skip"] == ["Wind", "Wind Gusts"]

    assert client("/config/edit/visualizer.auto_rotate.skip/[]")[0] == 200  # [] = leave none out
    assert app.config.data.visualizer.auto_rotate.skip == []
    assert client("/config/edit/visualizer.auto_rotate.skip/Wind")[0] == 400  # a list, not a name


def test_set_move_and_count_airports(client, monkeypatch):
    app = client.services
    fetched = threading.Event()
    monkeypatch.setattr(app.metars, "fetch", fetched.set)
    first, second = app.config.airports[0].code, app.config.airports[1].code

    assert client("/config/airports/0/code/kdwh")[0] == 303
    assert app.config.airports[0].code == "KDWH"
    assert fetched.wait(5)  # a new code gets its METAR right away, in the background
    assert client("/config/airports/0/name/Hooks Memorial")  # as the server decodes it[0] == 303
    assert app.config.airports[0].name == "Hooks Memorial"
    assert client("/config/airports/1/display/true")[0] == 303 and app.config.airports[1].display is True

    assert client("/config/airports/move/1/0")[0] == 303
    assert [a.code for a in app.config.airports[:2]] == [second, "KDWH"]

    assert client("/config/edit/led.count/3")[0] == 200
    assert len(app.config.airports) == 3
    # the in-memory strip changes length now: no restart
    assert len(app.renderer.pixels()) == 3 and len(app.renderer.looks) == 3
    assert 'id="restart-banner" role="status" hidden' in client("/config/airports")[1]
    assert first != second


def test_virtual_airports_page(client):
    app = client.services
    assert client("/config/edit/led.virtual_count/2")[0] == 200
    assert client("/config/airports/50/code/KDWH")[0] == 303
    assert client("/config/airports/50/display/true")[0] == 303  # saved, but a virtual airport is never on the OLED
    body = client("/config/airports")[1]
    assert "50 LEDs in the order they're wired and 2 virtual airports: 51 with an airport, 1 without." in body
    assert body.count('class="ap-divider"') == 1 and body.count('<span class="tag">virtual</span>') == 2
    assert 'data-led="50" data-field="display" disabled>' in body  # no OLED switch, and not shown as on
    assert 'id="led-count" class="led-count" type="number" inputmode="numeric" min="1" max="998"' in body
    assert len(app.renderer.looks) == 52 and len(app.renderer.animations) == 50

    assert client("/config/edit/led.count/3")[0] == 200  # the virtual airports stay, after the strip
    assert [a.code for a in app.config.airports[3:]] == ["KDWH", ""]
    assert client("/config/edit/led.virtual_count/998")[0] == 400  # 1000 airports at most, with the LEDs


def test_led_count_on_a_strip_that_cant_resize(client):
    """A NeoPixel strip's length is fixed when it opens: the new count waits for a restart."""
    app = client.services
    class FixedStrip(FakeStrip):
        resize = None

    app.renderer._pixels = FixedStrip(len(app.renderer.pixels()))
    assert client("/config/edit/led.count/3")[0] == 200
    assert len(app.renderer.pixels()) == 50
    assert "the new number takes effect after the map restarts" in client("/config/airports")[1]


@pytest.mark.parametrize("path, status", [
    ("/config/airports/0/code/NOT-AN-AIRPORT", 400),
    ("/config/airports/0/colour/red", 400),
    ("/config/airports/999/code/KDWH", 404),
    ("/config/airports/move/0/999", 404),
    ("/config/airports/edit/KXXX/KDWH", 404),
    ("/config/edit/led.count/0", 400),
])
def test_bad_airport_edits(client, path, status):
    before = list(client.services.config.airports)
    assert client(path)[0] == status
    assert client.services.config.airports == before


def test_led_changes_show_right_away(client):
    app = client.services
    app.metars.data = {"KDWH": metar("LIFR")}
    client("/config/airports/2/code/KDWH")
    assert app.renderer.looks[2] == Look.solid(app.config.data.color.cat.lifr)


def test_fetch(client, monkeypatch):
    app = client.services
    code = app.config.airports[0].code
    monkeypatch.setattr(app.metars, "fetch", lambda: setattr(app.metars, "data", {code: metar("IFR")}))
    assert client("/fetch")[0] == 200
    assert app.renderer.looks[0] == Look.solid(app.config.data.color.cat.ifr)


# ---- the API, against fake services with known data ----------------------------------------------------------

@pytest.fixture
def services():
    settings = Settings()
    settings.airports = [Airport(code="KHOU", name="Hobby", display=True), Airport(), Airport(code="KIAH"),
                         Airport(code="KDKR", name="Crockett")]
    config = SimpleNamespace(data=settings, airports=settings.airports)
    data = {"KHOU": metar("VFR", lightning=True), "KIAH": metar("IFR"), "KDKR": {}}
    metars = SimpleNamespace(data=data, lastFetchTime=datetime(2026, 10, 24, 12, 55), missing_stations=lambda: ["KDKR"])
    sun = SunTimes("Houston", SUN)
    renderer = Renderer(FakeStrip(4), metars, config, [flightcategory, rainbow], sun)
    display = SimpleNamespace(screen={"kind": "message", "title": "MAP"}, on=True)
    return SimpleNamespace(config=config, metars=metars, sun=sun, renderer=renderer, display=display)


def test_status(services):
    status = api.status(services, "10.0.0.2")
    assert status["version"] == __version__ and status["ip"] == "10.0.0.2"
    assert status["visualizer"]["active"] == 0 and status["visualizer"]["name"] == "Flight Category"
    assert [v["name"] for v in status["visualizers"]] == ["Flight Category", "Rainbow"]
    assert status["visualizers"][1]["exclusive"] is True
    assert status["config"]["display_screen.delay"] == 5.0
    assert status["suntimes"]["dawn"] == SUN["dawn"].isoformat()
    assert status["lastFetchTime"] == "2026-10-24T12:55:00"
    assert status["missingStations"] == ["KDKR"]
    # LEDs with no airport are skipped, but the others keep their LED number
    assert [(a["code"], a["pixel"]) for a in status["airports"]] == [("KHOU", 0), ("KIAH", 2), ("KDKR", 3)]
    khou = status["airports"][0]
    assert khou["text"] == "Hobby" and khou["flightCategory"] == "VFR" and khou["lightning"] is True
    assert khou["obsTime"] == OBS.isoformat()
    assert status["airports"][2]["flightCategory"] is None
    json.dumps(status)


def test_live(services):
    live = api.live(services, now=123.0)
    assert live["now"] == 123.0
    assert [(led["code"], led["pixel"]) for led in live["leds"]] == [("KHOU", 0), ("KIAH", 2), ("KDKR", 3)]
    assert live["leds"][1]["look"] == Look.solid(services.config.data.color.cat.ifr).to_dict()
    assert live["leds"][1]["lat"] == 29.6
    assert live["leds"][2]["look"]["effect"] == "off"  # no report
    assert live["strip"] is None
    assert live["display"] == {"enabled": True, "on": True, "screen": {"kind": "message", "title": "MAP"}}
    services.config.data.display_screen.enabled = False
    assert api.live(services)["display"] == {"enabled": False, "on": False, "screen": None}


def test_live_places_airports_without_a_report(services):
    """The Map page shows them as open rings, so they need a position from the station lookup."""
    kdkr = next(led for led in api.live(services)["leds"] if led["code"] == "KDKR")
    assert (kdkr["lat"], kdkr["lon"], kdkr["raw"]) == (None, None, None)
    services.metars.position = lambda code: (31.307, -95.404) if code == "KDKR" else None
    kdkr = next(led for led in api.live(services)["leds"] if led["code"] == "KDKR")
    assert (kdkr["lat"], kdkr["lon"], kdkr["raw"], kdkr["look"]["effect"]) == (31.307, -95.404, None, "off")
    khou = next(led for led in api.live(services)["leds"] if led["code"] == "KHOU")
    assert (khou["lat"], khou["lon"]) == (29.6, -95.3)  # a report's own position comes first


def test_virtual_airports_in_the_api(services):
    services.config.data.led.count = 3  # KDKR, on the 4th, is virtual
    assert [a["virtual"] for a in api.status(services, "")["airports"]] == [False, False, True]
    live = api.live(services)
    assert [led["virtual"] for led in live["leds"]] == [False, False, True]
    services.renderer.visualizer = 1  # rainbow: the virtual airport joins in, in its own look
    assert api.live(services)["leds"][2]["look"]["effect"] == "rainbow"


def test_live_whole_strip_visualizer(services):
    services.renderer.visualizer = 1  # rainbow
    live = api.live(services)
    assert live["strip"]["effect"] == "rainbow"
    assert live["visualizer"] == {"active": 1, "name": "Rainbow", "exclusive": True}


def test_metar(services):
    m = api.metar(services, "KHOU")
    assert (m["code"], m["raw"], m["flightCategory"], m["obsTime"]) == ("KHOU", "METAR VFR", "VFR", OBS.isoformat())
    assert {"label": "Wind", "text": "100° at 5 kt"} in m["decoded"]
    assert api.metar(services, "KDKR")["decoded"] == []  # on the map, not reporting
    assert api.metar(services, "KXXX") is None  # not on the map


def test_metar_summary(services):
    services.metars.data["KHOU"].update(skyConditions=[{"cover": "BKN", "cloudBaseFt": 2500}], obs="-RA")
    summary = api.metar(services, "KHOU")["summary"]
    assert summary[:2] == ["VFR: ceiling above 3,000 ft and visibility over 5 miles", "Light rain"]
    assert "Ceiling 2,500 ft (broken)" in summary
    assert api.metar(services, "KDKR")["summary"] == []


def test_map_legend_follows_the_visualizer(services):
    """The Map page swaps in the new legend when the visualizer changes, without reloading (or losing its zoom)."""
    c = Client(create_app(services, ip=""))
    status, body = c("/map/legend", auth=False)
    assert status == 200 and 'class="legend"' in body and "<html" not in body
    assert 'data-then="none"' in c("/map", auth=False)[1]
    assert 'data-active="0"' in c("/map", auth=False)[1]


def test_metar_route(services):
    c = Client(create_app(services, ip=""))
    assert c.json("/api/metar/khou", auth=False)["code"] == "KHOU"
    assert c("/api/metar/KXXX", auth=False)[0] == 404


def test_api_routes(services):
    c = Client(create_app(services, ip="10.0.0.2"))
    assert c.json("/api/status", auth=False)["airports"][0]["code"] == "KHOU"
    assert c.json("/api/live", auth=False)["leds"][0]["code"] == "KHOU"


# ---- update ---------------------------------------------------------------------------------------------------

def test_update_runs_in_the_background(services):
    release = threading.Event()

    def run_update(progress, **kwargs):
        progress(0.5, "Downloading the update")
        release.wait(5)
        return SimpleNamespace(ok=True, changed=True, target="v9.0.0", message="Installed v9.0.0", errors=[])
    c = Client(create_app(services, ip="", updates=control.Updates(run_update)))
    assert c.json("/update/progress") == control.NO_UPDATE

    started = c.json("/update/start", method="POST")
    again = c.json("/update/start", method="POST")  # already running: reports the same job
    assert started["done"] is False and again["label"] == "Downloading the update"
    release.set()
    for _ in range(100):
        if c.json("/update/progress")["done"]:
            break
        threading.Event().wait(0.01)
    assert c.json("/update/progress") == {"fraction": 0.5, "label": "Downloading the update", "done": True,
                                          "ok": True, "changed": True, "target": "v9.0.0",
                                          "message": "Installed v9.0.0", "errors": []}


def test_update_failure_is_reported():
    def run_update(progress, **kwargs):
        raise RuntimeError("no network")
    updates = control.Updates(run_update)
    job = updates.start()
    for _ in range(100):
        if job["done"]:
            break
        threading.Event().wait(0.01)
    assert job["ok"] is False and job["errors"] == ["no network"]


# ---- releases: "Update available", the update channel and picking a release ---------------------------------

SHA = "1234567" + "0" * 33


def fake_git(tags=("v2.8.4", "v2.8.5", "v2.7.0", "v2.9.0-rc1"), newest="abcdef1234", described="v2.8.4-0-g1234567",
             modified=False):
    """
    git for a ReleaseCheck: GitHub has these tags; this copy is on commit 1234567, `described` by git describe
    (on the v2.8.4 release by default), from github.com/dman776/metarmap2.
    """
    def run(*args):
        if args[0] == "describe":
            return subprocess.CompletedProcess(args, 0, described + "\n", "")
        if args[:2] == ("remote", "get-url"):
            return subprocess.CompletedProcess(args, 0, "https://github.com/dman776/metarmap2.git\n", "")
        if args[0] == "diff":
            return subprocess.CompletedProcess(args, 1 if modified else 0, "", "")
        if args == ("rev-parse", "HEAD"):
            return subprocess.CompletedProcess(args, 0, SHA + "\n", "")
        if args[:2] == ("ls-remote", "--tags"):
            out = "".join(f"{n:040d}\trefs/tags/{tag}\n" for n, tag in enumerate(tags))
        elif args[:2] == ("ls-remote", "origin"):
            out = f"{newest}\tHEAD\n"
        elif args[0] == "rev-parse":
            out = "1234567\n"
        else:  # merge-base --is-ancestor: GitHub's newest commit isn't in this copy
            return subprocess.CompletedProcess(args, 1, "", "")
        return subprocess.CompletedProcess(args, 0, out, "")
    return run


@pytest.fixture
def release_client(make_app):
    from metarmap.releases import ReleaseCheck
    app = make_app()
    app.releases = ReleaseCheck(channel=lambda: app.config.data.update.channel, current="2.8.4", git=fake_git())
    app.releases.load_build()
    started = []

    def run_update(progress, **kwargs):
        started.append(kwargs)
        return SimpleNamespace(ok=True, changed=True, target=kwargs["version"] or "v2.8.5", message="Installed",
                               errors=[])
    c = Client(create_app(app, ip="10.0.0.2", updates=control.Updates(run_update)))
    c.services, c.started = app, started
    yield c
    app.display.stop()


def wait_for_update(c):
    for _ in range(200):
        if c.json("/update/progress")["done"]:
            return c.json("/update/progress")
        threading.Event().wait(0.01)


def test_no_badge_before_a_check(release_client):
    assert "update-badge" not in release_client("/")[1]


def test_badge_and_home_button_when_a_release_is_newer(release_client):
    release_client.services.releases.check()
    home = release_client("/")[1]
    assert '<a class="update-badge" href="/#update">Update available: v2.8.5</a>' in home
    assert "Update to v2.8.5" in home
    assert "Update available: v2.8.5" in release_client("/map")[1]  # every page's header


def test_config_lists_releases_to_pick(release_client):
    release_client.services.releases.check()
    body = release_client("/config")[1]
    assert '<option value="v2.8.5">v2.8.5</option>' in body
    assert '<option value="v2.8.4" selected>v2.8.4 (running)</option>' in body
    assert '<option value="v2.7.0" data-older="true">v2.7.0</option>' in body
    assert "v2.9.0-rc1" not in body  # pre-releases aren't offered
    assert "v2.8.5 is available." in body
    assert f'<a class="mono" href="https://github.com/dman776/metarmap2/commit/{SHA}"' in body
    assert '<option value="releases" selected>Releases</option>' in body


def test_install_a_picked_release(release_client):
    c = release_client
    assert c.json("/update/start", method="POST", body={"version": "v2.7.0"})["target"] == "v2.7.0"
    job = wait_for_update(c)
    assert job["ok"] and c.started == [{"channel": "releases", "version": "v2.7.0"}]
    assert c.services.releases.installed == "v2.7.0"
    assert "Restart to use v2.7.0" in c("/")[1]


def test_update_follows_the_channel(release_client):
    c = release_client
    assert c("/config/edit/update.channel/latest")[0] == 200
    state = c.services.releases.check()
    assert state["available"] == "abcdef1" and state["badge"] == "New commit available"
    assert "New commit available" in c("/")[1] and ">\n            Update\n" in c("/")[1]  # no version to name
    c.json("/update/start", method="POST")
    wait_for_update(c)
    assert c.started == [{"channel": "latest", "version": None}]
    assert c.services.releases.badge() == "Restart to use v2.8.5"  # installed: it runs after a restart


@pytest.mark.parametrize("path, body", [("/update/start", {"version": "latest"}),
                                        ("/update/start", {"version": "v2.9.0-rc1"}),
                                        ("/update/start", ["v2.7.0"])])
def test_bad_release_picks_are_400s(release_client, path, body):
    assert release_client(path, method="POST", body=body)[0] == 400


def test_update_start_without_a_content_length(release_client):
    """curl -X POST sends no Content-Length header; that's the channel's update, not a bad body."""
    c = release_client

    def post_without_length(path):
        status = []
        environ = {"REQUEST_METHOD": "POST", "PATH_INFO": path, "QUERY_STRING": "", "SERVER_NAME": "test",
                   "SERVER_PORT": "80", "SERVER_PROTOCOL": "HTTP/1.1", "wsgi.url_scheme": "http",
                   "wsgi.input": io.BytesIO(b""), "wsgi.errors": io.StringIO(), "HTTP_AUTHORIZATION": AUTH}
        b"".join(c.app(environ, lambda s, h, exc_info=None: status.append(s)))
        return int(status[0].split()[0])
    assert post_without_length("/update/start") == 202
    wait_for_update(c)
    assert c.started == [{"channel": "releases", "version": None}]


def test_unknown_update_channel_is_a_400(release_client):
    assert release_client("/config/edit/update.channel/nightly")[0] == 400
    assert release_client.services.config.data.update.channel == "releases"


def test_check_now_and_status(release_client):
    c = release_client
    assert c("/update/check", auth=False)[0] == 401
    assert c.json("/update/check")["available"] == "v2.8.5"
    update = c.json("/api/status", auth=False)["update"]
    assert update["current"] == "2.8.4" and update["available"] == "v2.8.5" and update["channel"] == "releases"
    assert update["releases"] == ["v2.8.5", "v2.8.4", "v2.7.0"] and update["error"] is None


def unreleased_client(make_app, **git):
    from metarmap.releases import ReleaseCheck
    app = make_app()
    app.releases = ReleaseCheck(channel=lambda: "releases", current="2.8.4", git=fake_git(**git))
    app.releases.load_build()
    c = Client(create_app(app, ip="10.0.0.2"))
    c.services = app
    return c


def test_header_on_a_release(release_client):
    home = release_client("/")[1]
    assert "build-pill" not in home and "unreleased" not in home
    assert '<span class="host">10.0.0.2 · v2.8.4</span>' in home


def test_header_on_unreleased_commits(make_app):
    c = unreleased_client(make_app, described="v2.8.4-3-g1234567")
    for path in ("/", "/map", "/config"):
        body = c(path)[1]
        assert (f'<a class="build-pill" href="https://github.com/dman776/metarmap2/commit/{SHA}" target="_blank" '
                'rel="noopener" title="This commit on GitHub">Unreleased: 3 commits after v2.8.4</a>') in body
        assert '<span class="host unreleased">10.0.0.2 · v2.8.4 +3 · 1234567</span>' in body
    assert "Version 2.9" in c("/")[1] and "(v2.8.4+3, commit 1234567)" in c("/")[1]  # the footer
    assert c.json("/api/status", auth=False)["build"]["pill"] == "Unreleased: 3 commits after v2.8.4"
    c.services.display.stop()


def test_header_with_local_changes(make_app):
    c = unreleased_client(make_app, modified=True)
    body = c("/")[1]
    assert "Modified: local changes to v2.8.4</a>" in body and "v2.8.4 · 1234567*" in body
    assert "commit 1234567, modified)" in body
    c.services.display.stop()


def test_status_without_the_check(services):
    assert api.status(services, "")["update"] is None


# ---- view data ------------------------------------------------------------------------------------------------

def test_stations_and_summary(services):
    s = views.stations(services.config.airports, services.metars.data)
    assert [x["code"] for x in s] == ["KHOU", "KIAH", "KDKR"]
    assert views.summary(s) == {"counts": {"VFR": 1, "MVFR": 0, "IFR": 1, "LIFR": 0}, "no_data": ["KDKR"],
                                "below_vfr": [s[1]]}


def test_below_vfr_is_worst_first():
    s = [{"code": c, "cat": cat} for c, cat in (("A", "MVFR"), ("B", "LIFR"), ("C", "VFR"), ("D", "IFR"))]
    assert [x["code"] for x in views.summary(s)["below_vfr"]] == ["B", "D", "A"]


def test_sun_schedule_flags_the_next_change():
    levels = Settings().led.brightness
    schedule = views.sun_schedule(SUN, levels, now=SUN["sunrise"] + timedelta(minutes=1))
    assert [(s["name"], s["level"], s["next"]) for s in schedule] == [
        ("Dawn", levels.dimmed, False), ("Sunrise", levels.normal, False), ("Sunset", levels.dimmed, True),
        ("Dusk", levels.off, False)]
    assert not any(s["next"] for s in views.sun_schedule(SUN, levels, now=SUN["dusk"] + timedelta(hours=1)))
    assert views.sun_schedule({}, levels) == []


def test_map_settings_pick_the_chart_covering_the_airports(services):
    sectionals = views.load_sectionals()
    stations = views.stations(services.config.airports, services.metars.data)
    m = Settings().geo.map
    m.chart, m.chart_type = "", "nonsense"
    settings = views.map_settings(m, sectionals, stations)
    assert settings["chart"] == "Houston"
    assert settings["chart_bounds"]["name"] == "Houston"
    assert settings["chart_type"] == "sectional" and settings["chart_service"] == "VFR_Sectional"


def test_is_login():
    web_server = Settings().web_server
    assert views.is_login(web_server, "METAR", "map")
    assert not views.is_login(web_server, "metar", "MAP")


# ---- the server answers requests in parallel ------------------------------------------------------------------

def test_a_slow_fetch_does_not_hold_up_other_requests(services):
    import urllib.request
    from metarmap.web import serve

    release, started = threading.Event(), threading.Event()

    def slow_fetch():
        started.set()
        release.wait(10)  # like aviationweather.gov taking its time
    services.metars.fetch = slow_fetch
    server = serve(create_app(services, ip="10.0.0.2"), "127.0.0.1", 0)
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        fetch = threading.Thread(target=lambda: urllib.request.urlopen(base + "/fetch", timeout=15).read())
        fetch.start()
        assert started.wait(5)
        with urllib.request.urlopen(base + "/api/live", timeout=3) as response:  # answers while /fetch waits
            assert json.loads(response.read())["leds"][0]["code"] == "KHOU"
        assert fetch.is_alive()
        release.set()
        fetch.join(10)
        assert not fetch.is_alive()
    finally:
        release.set()
        server.shutdown()
        server.server_close()


# ---- Config > Access: the login and Wi-Fi -----------------------------------------------------------------------

@pytest.fixture
def linux(monkeypatch):
    """Records Linux password changes instead of making them; fail=True makes chpasswd fail."""
    calls = SimpleNamespace(passwords=[], fail=False)

    def set_login_password(password):
        if calls.fail:
            raise control.system.ChangeFailed("chpasswd failed: simulated")
        calls.passwords.append(password)
        return "changed for pi"
    monkeypatch.setattr(control.system, "set_login_password", set_login_password)
    return calls


def test_change_the_login(client, linux):
    status, body = client("/config/login", method="POST", body={"user": "Pilot", "password": "n3w pass"})
    assert status == 200 and json.loads(body) == {"user": "pilot", "linux_password": "changed for pi"}
    assert linux.passwords == ["n3w pass"]  # the Pi's login user gets the same password
    web = client.services.config.data.web_server
    assert (web.user, web.password) == ("pilot", "n3w pass")
    assert client("/config", auth=True)[0] == 401  # the old login no longer works
    assert client("/config", auth="pilot:n3w pass")[0] == 200


def test_change_only_the_user_name(client, linux):
    assert client("/config/login", method="POST", body={"user": "pilot"})[0] == 200
    assert linux.passwords == []
    assert client.services.config.data.web_server.password == "map"


def test_nothing_changes_if_the_linux_password_fails(client, linux):
    linux.fail = True
    status, body = client("/config/login", method="POST", body={"user": "pilot", "password": "n3w pass"})
    assert status == 500 and "nothing was changed" in body
    web = client.services.config.data.web_server
    assert (web.user, web.password) == ("metar", "map")


@pytest.mark.parametrize("body", [{"user": "two words", "password": "n3w pass"}, {"user": "a:b"},
                                  {"user": "pilot", "password": "line\nbreak"}, ["not", "an", "object"]])
def test_bad_logins_change_nothing(client, linux, body):
    assert client("/config/login", method="POST", body=body)[0] == 400
    assert linux.passwords == []  # checked before the Linux password is touched
    assert client.services.config.data.web_server.user == "metar"


def test_login_and_wifi_need_a_login(client):
    assert client("/config/login", method="POST", body={"user": "x"}, auth=False)[0] == 401
    assert client("/config/wifi", method="POST", body={"ssid": "x"}, auth=False)[0] == 401
    assert client("/config/login")[0] == 405  # never by GET, so passwords stay out of URLs


def test_switch_wifi(client, monkeypatch):
    switched = threading.Event()
    calls = []
    monkeypatch.setattr(control, "WIFI_DELAY", 0)
    monkeypatch.setattr(control.system, "current_wifi", lambda: "HomeNet")
    monkeypatch.setattr(control.system, "set_wifi",
                        lambda ssid, password: calls.append((ssid, password)) or switched.set() or "switching")
    status, body = client("/config/wifi", method="POST", body={"ssid": " Cabin ", "password": "pinecones"})
    assert status == 202 and json.loads(body) == {"ssid": "Cabin", "current": "HomeNet", "delay": 0}
    assert switched.wait(5)  # after answering, in the background
    assert calls == [("Cabin", "pinecones")]


def test_bad_wifi_is_refused(client, monkeypatch):
    monkeypatch.setattr(control.system, "set_wifi", lambda *a: pytest.fail("must not switch"))
    assert client("/config/wifi", method="POST", body={"ssid": "Cabin", "password": "short"})[0] == 400
    assert client("/config/wifi", method="POST", body={"ssid": ""})[0] == 400


def test_config_page_shows_access(client, monkeypatch):
    monkeypatch.setattr(control.system, "current_wifi", lambda: "HomeNet")
    monkeypatch.setattr(control.system, "login_user", lambda: "pi")
    monkeypatch.setattr(control.system, "is_root", lambda: True)
    monkeypatch.setattr(control.system, "is_raspberry_pi", lambda: False)  # e.g. another Linux machine as root
    assert "login gets the same password" not in client("/config")[1]
    monkeypatch.setattr(control.system, "is_raspberry_pi", lambda: True)
    body = client("/config")[1]
    assert 'data-form="/config/login"' in body and 'data-form="/config/wifi"' in body
    assert "Now on <b>HomeNet</b>" in body and "<b>pi</b> login gets the same password" in body
    monkeypatch.setattr(control.system, "is_root", lambda: False)  # e.g. on a laptop: it won't change
    monkeypatch.setattr(control.system, "current_wifi", lambda: None)
    body = client("/config")[1]
    assert "login gets the same password" not in body and "Now on" not in body


# ---- the OLED on and off, live ----------------------------------------------------------------------------------

def test_turn_the_oled_off_and_on(client):
    app = client.services
    app.display.start()
    assert client("/config/edit/display_screen.enabled/false")[0] == 200
    app.display._thread.join(5)
    assert not app.display.is_alive() and app.display.screen is None
    assert client.json("/api/live")["display"] == {"enabled": False, "on": False, "screen": None}
    assert client("/config/edit/display_screen.enabled/true")[0] == 200  # e.g. from Home Assistant
    assert app.display.is_alive()
    assert client.json("/api/live")["display"]["enabled"] is True


def test_turning_off_an_airports_oled_switch(client):
    """The Airports page's switch sends false, which the server must take (it used to get "-": a 400)."""
    app = client.services
    assert client("/config/airports/0/display/true")[0] == 303
    assert client("/config/airports/0/display/false")[0] == 303
    assert app.config.airports[0].display is False
    assert client("/config/airports/0/display/-")[0] == 400  # what the page used to send


# ---- the Home page's OLED switch (not saved, like the brightness) -----------------------------------------------

def test_home_page_oled_switch(client):
    app = client.services
    app.display.start()
    assert 'id="oled-on"' in client("/")[1] and "checked" in client("/")[1].split('id="oled-on"')[1][:40]

    assert client("/display/off")[0] == 200
    app.display._thread.join(5)
    assert not app.display.is_alive() and app.display.screen is None
    live = client.json("/api/live")["display"]
    assert live == {"enabled": True, "on": False, "screen": None}  # the Map page shows the screen as off
    assert client.json("/api/status")["display"] == {"enabled": True, "on": False}
    assert app.config.data.display_screen.enabled is True  # not saved: Config still says enabled

    app_module.watch_display(app)  # the watchdog leaves it off
    assert not app.display.is_alive()

    assert client("/display/on")[0] == 200
    assert app.display.is_alive() and client.json("/api/live")["display"]["on"] is True
    assert client("/display/maybe")[0] == 400


def test_no_oled_switch_when_turned_off_in_config(client):
    client("/config/edit/display_screen.enabled/false")
    assert 'id="oled-on"' not in client("/")[1]
    assert client("/display/on")[0] == 409
    assert not client.services.display.is_alive()


# ---- airport names ----------------------------------------------------------------------------------------------

def test_a_new_code_gets_its_name(client, monkeypatch):
    app = client.services
    monkeypatch.setattr(app.metars, "fetch", lambda: None)
    monkeypatch.setattr(app.metars, "name_for", lambda code: {"KDWH": "Houston/D W Hooks Mem"}.get(code, ""))
    client("/config/airports/0/name/My%20field")
    assert client("/config/airports/0/code/kdwh")[0] == 303
    assert (app.config.airports[0].code, app.config.airports[0].name) == ("KDWH", "Houston/D W Hooks Mem")
    assert client("/config/airports/0/code/KXXX")[0] == 303  # unknown: no name
    assert app.config.airports[0].name == ""
