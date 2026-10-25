"""
Tests for the web UI and API (metarmap.web): every page renders, the API's fields, the routes that change the map,
and the view data behind the pages.
"""
import base64
import io
import json
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from metarmap import __version__
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

    def __call__(self, path, method="GET", auth=True):
        environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": "", "SERVER_NAME": "test",
                   "SERVER_PORT": "80", "SERVER_PROTOCOL": "HTTP/1.1", "wsgi.url_scheme": "http",
                   "wsgi.input": io.BytesIO(), "wsgi.errors": io.StringIO()}
        if auth:
            environ["HTTP_AUTHORIZATION"] = AUTH
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
    assert "the new number takes effect after the map restarts" in client("/config/airports")[1]
    assert first != second


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
    display = SimpleNamespace(screen={"kind": "message", "title": "MAP"})
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
    assert live["display"] == {"enabled": True, "screen": {"kind": "message", "title": "MAP"}}
    services.config.data.display_screen.enabled = False
    assert api.live(services)["display"] == {"enabled": False, "screen": None}


def test_live_places_airports_without_a_report(services):
    """The Map page shows them as open rings, so they need a position from the station lookup."""
    kdkr = next(led for led in api.live(services)["leds"] if led["code"] == "KDKR")
    assert (kdkr["lat"], kdkr["lon"], kdkr["raw"]) == (None, None, None)
    services.metars.position = lambda code: (31.307, -95.404) if code == "KDKR" else None
    kdkr = next(led for led in api.live(services)["leds"] if led["code"] == "KDKR")
    assert (kdkr["lat"], kdkr["lon"], kdkr["raw"], kdkr["look"]["effect"]) == (31.307, -95.404, None, "off")
    khou = next(led for led in api.live(services)["leds"] if led["code"] == "KHOU")
    assert (khou["lat"], khou["lon"]) == (29.6, -95.3)  # a report's own position comes first


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

    def run_update(progress):
        progress(0.5, "Downloading the update")
        release.wait(5)
        return SimpleNamespace(ok=True, changed=True, errors=[])
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
                                          "ok": True, "changed": True, "errors": []}


def test_update_failure_is_reported():
    def run_update(progress):
        raise RuntimeError("no network")
    updates = control.Updates(run_update)
    job = updates.start()
    for _ in range(100):
        if job["done"]:
            break
        threading.Event().wait(0.01)
    assert job["ok"] is False and job["errors"] == ["no network"]


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
