"""Smoke tests: every page and API endpoint renders for a whole map built on fake hardware."""
import base64
import io
import json

import pytest

from metarmap import __version__, webserver

AUTH = "Basic " + base64.b64encode(b"metar:map").decode()


@pytest.fixture
def client(make_app, monkeypatch):
    monkeypatch.setattr(webserver, "my_ip", lambda: "10.0.0.2")
    app = make_app()
    server = webserver.WebServer("127.0.0.1", 0, app)

    def get(path, auth=True):
        """Calls the bottle app directly (no socket); returns (status code, body)."""
        environ = {"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": "", "SERVER_NAME": "test",
                   "SERVER_PORT": "80", "wsgi.url_scheme": "http", "wsgi.input": io.BytesIO(),
                   "wsgi.errors": io.StringIO()}
        if auth:
            environ["HTTP_AUTHORIZATION"] = AUTH
        status = []
        body = b"".join(server._app(environ, lambda s, headers, exc_info=None: status.append(s)))
        return int(status[0].split()[0]), body.decode()
    get.app = app
    yield get
    if app.display:
        app.display.stop()


@pytest.mark.parametrize("path", ["/", "/metars", "/raw", "/map", "/debug", "/config", "/config/airports",
                                  "/static/app.js", "/update/progress"])
def test_pages(client, path):
    status, body = client(path)
    assert status == 200, body


def test_config_needs_a_login(client):
    assert client("/config", auth=False)[0] == 401


def test_pages_show_the_version(client):
    assert f"v{__version__}" in client("/")[1]


def test_api_status(client):
    status = json.loads(client("/api/status")[1])
    assert status["version"] == __version__
    assert status["ip"] == "10.0.0.2"
    assert set(status["suntimes"]) == {"dawn", "sunrise", "sunset", "dusk"}
    assert all(status["suntimes"].values())
    assert len(status["visualizers"]) == len(client.app.renderer.visualizers)


def test_api_live(client):
    live = json.loads(client("/api/live")[1])
    assert live["display"]["enabled"] is True
    assert live["visualizer"]["active"] == 0


def test_visualizer_and_brightness(client):
    assert client("/visualizer/next")[0] == 200
    assert client.app.renderer.visualizer[0] == 1
    assert client("/brightness/0.3")[0] == 200
    assert client.app.renderer.pixels().brightness == 0.3


def test_airport_edit_restarts_the_display(client):
    app = client.app
    app.display.start()
    old_thread = app.display.__thread__
    code = next(iter(app.config.airports))
    assert client(f"/config/airports/edit/prop/{code}/display/true")[0] in (302, 303)  # redirect
    assert app.config.airports[code]["display"] is True
    assert app.display.__thread__ is not old_thread and app.display.is_alive()  # restarted, for the new airports
