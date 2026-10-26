"""
The web UI and JSON API (see API.md).

create_app(services) builds the bottle app from the map's parts (metarmap.app.App: config, sun, metars, renderer
and display); serve() runs it in a background thread. The routes are in pages, api and control; what they show
is built in views.
"""
import socketserver
import threading
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

import bottle
from bottle import auth_basic

from metarmap.lib.safe_logging import safe_log
from metarmap.web import api, control, pages, views
from metarmap.web.site import Site, my_ip


def create_app(services, ip=None, updates=None) -> bottle.Bottle:
    """
    The web app for a map. ip: shown in the header and /api/status (default: this machine's address);
    updates: a control.Updates (tests pass one with a fake update).
    """
    site = Site(ip=ip if ip is not None else my_ip(), sectionals=views.load_sectionals(),
                releases=getattr(services, "releases", None))
    auth = auth_basic(lambda user, password: views.is_login(services.config.data.web_server, user, password))
    app = bottle.Bottle()
    pages.add_routes(app, services, site, auth)
    api.add_routes(app, services, site)
    control.add_routes(app, services, site, auth, updates)
    app.route("/static/<filename:path>", "GET", lambda filename: bottle.static_file(filename, root=views.STATIC_DIR))
    return app


class ThreadingServer(socketserver.ThreadingMixIn, WSGIServer):
    """
    Answers each request in its own thread, so a slow one (GET /fetch waits on aviationweather.gov) doesn't hold up
    the Map page's polling, Home Assistant or page loads.
    """
    daemon_threads = True  # don't wait for open requests when the map stops


class RequestHandler(WSGIRequestHandler):
    def address_string(self):
        return self.client_address[0]  # no reverse DNS lookup for each request's log line


def serve(app, host, port) -> ThreadingServer:
    """Runs the web app in a background thread. Stop it with shutdown(); server_port is the port it listens on."""
    server = make_server(host, port, app, ThreadingServer, RequestHandler)
    safe_log(f"localhost = {host}:{server.server_port}")
    threading.Thread(target=server.serve_forever, name="web", daemon=True).start()
    return server
