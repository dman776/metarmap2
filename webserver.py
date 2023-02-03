import pprint

import bottle
from bottle import hook, route, run, request, abort, response, static_file
import metar
from lib.safe_logging import safe_log
import threading
import io

CONFIGURATION_HOST_PORT = 8080


class WebServer(object):
    """
    Class to handle running a REST endpoint to handle configuration.
    """
    def run(
        self
    ):
        """
        Starts the server.
        """
        safe_log("localhost = {}:{}".format(self._host, self._port))
        threading.Thread(target=self._app.run, kwargs=dict(host=self._host, port=self._port)).start()
        # self._app.run(host=self._host, port=self._port)

    def stop(self):
        if self._app is not None:
            self._app = None

    def __init__(self, host, port, metars: metar.METAR):
        self._port = port
        self._host = host
        self._app = bottle.Bottle()
        self._route()
        self._metarsObj = metars
        bottle.TEMPLATE_PATH.insert(0,"./templates")

    def _route(self):
        self._app.route("/", method="GET", callback=self._index)
        self._app.route("/raw", method="GET", callback=self._raw)
        self._app.route("/raw/<code>", method="GET", callback=self._rawcode)
        self._app.route("/fetch", method="GET", callback=self._fetch)

    def _index(self):
        return bottle.template('index.tpl', metars=self._metarsObj)

    def _raw(self):
        buf = io.StringIO()
        for s in self._metarsObj.data.keys():
            buf.write("<b>" + s + "</b>: " + self._metarsObj.data[s]['raw'] + "<br />")
        buf.seek(0)
        return buf.read()

    def _rawcode(self, code):
        return "<b>" + code + "</b>: " + self._metarsObj.data[code]['raw'] + "<br />"

    def _fetch(self):
        self._metarsObj.fetch()
        while self._metarsObj.is_fetching():
            pass
        return bottle.template('index.tpl', metars=self._metarsObj)
