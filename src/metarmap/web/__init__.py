"""
The web UI and JSON API (see API.md).

create_app(services) builds the bottle app from the map's parts (metarmap.app.App: config, sun, metars, renderer
and display); serve() runs it in a background thread. The routes are in pages, api and control; what they show
is built in views.
"""

import logging
import socketserver
import threading
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

import bottle
from bottle import auth_basic

from metarmap.web import api, control, pages, views
from metarmap.web import planner as planner_page
from metarmap.web.services import Services
from metarmap.web.site import Site, my_ip

log = logging.getLogger(__name__)


def create_app(services: Services, ip=None, updates=None, installs=None, planner=None) -> bottle.Bottle:
    """
    The web app for a map. ip: shown in the header and /api/status (default: this machine's address);
    updates: a control.Updates (tests pass one with a fake update); planner: a planner.Planner (tests pass one with a
    fake airport fetch).
    """
    site = Site(
        ip=ip if ip is not None else my_ip(),
        sectionals=views.load_sectionals(),
        releases=services.releases,
        discovery=services.discovery,
    )
    auth = auth_basic(lambda user, password: views.is_login(services.config.data.web_server, user, password))
    app = bottle.Bottle()
    pages.add_routes(app, services, site, auth)
    api.add_routes(app, services, site)
    control.add_routes(app, services, site, auth, updates, installs)
    planner_page.add_routes(app, services, site, auth, planner)
    app.route("/static/<filename:path>", "GET", static)
    return app


def static(filename):
    """
    A /static file. Without ?v= (the icon, the Home Screen icon) it carries Cache-Control: no-cache: keep a copy but ask
    the Chart before using it, so a changed one is a full answer and an unchanged one a cheap 304. The scripts and
    styles are linked with ?v=<assets_version> (a changed file is a new address), so they are left to the browser.
    The header goes on the response static_file returns, which bottle 0.12 and 0.13 both send as it is.
    """
    answer = bottle.static_file(filename, root=views.STATIC_DIR)
    if "v" not in bottle.request.query and "Cache-Control" not in answer.headers:
        answer.set_header("Cache-Control", "no-cache")
    return answer


class ThreadingServer(socketserver.ThreadingMixIn, WSGIServer):
    """
    Answers each request in its own thread, so a slow one (GET /fetch waits on aviationweather.gov) doesn't hold up
    the Map page's polling, Home Assistant or page loads.
    """

    daemon_threads = True  # don't wait for open requests when the map stops
    request_queue_size = 64  # connections wait instead of being dropped while a Pi Zero W is busy (socketserver: 5)


class RequestHandler(WSGIRequestHandler):
    def address_string(self):
        return self.client_address[0]  # no reverse DNS lookup for each request's log line


def serve(app, host, port) -> ThreadingServer:
    """Runs the web app in a background thread. Stop it with shutdown(); server_port is the port it listens on."""
    server = make_server(host, port, app, ThreadingServer, RequestHandler)
    log.info(f"localhost = {host}:{server.server_port}")
    threading.Thread(target=server.serve_forever, name="web", daemon=True).start()
    return server
