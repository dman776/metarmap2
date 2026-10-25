"""
The web UI and JSON API (see API.md).

create_app(services) builds the bottle app from the map's parts (metarmap.app.App: config, sun, metars, renderer
and display); serve() runs it in a background thread. The routes are in pages, api and control; what they show
is built in views.
"""
import threading

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
    site = Site(ip=ip if ip is not None else my_ip(), sectionals=views.load_sectionals())
    auth = auth_basic(lambda user, password: views.is_login(services.config.data.web_server, user, password))
    app = bottle.Bottle()
    pages.add_routes(app, services, site, auth)
    api.add_routes(app, services, site)
    control.add_routes(app, services, site, auth, updates)
    app.route("/static/<filename:path>", "GET", lambda filename: bottle.static_file(filename, root=views.STATIC_DIR))
    return app


def serve(app, host, port) -> threading.Thread:
    """Runs the web app in a background thread."""
    safe_log(f"localhost = {host}:{port}")
    thread = threading.Thread(target=app.run, kwargs=dict(host=host, port=port), name="web", daemon=True)
    thread.start()
    return thread
