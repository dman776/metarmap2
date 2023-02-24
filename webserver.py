import pprint

import bottle
from bottle import hook, route, run, request, abort, response, static_file
import metar
from renderer import Renderer
from neopixel import NeoPixel
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
        self._thread = threading.Thread(target=self._app.run, kwargs=dict(host=self._host, port=self._port))
        self._thread.daemon = True
        self._thread.start()

    def stop(self):
        if self._app is not None:
            self._app.close()

    def __init__(self, host, port, metars: metar.METAR, renderer: Renderer):
        self._port = port
        self._host = host
        self._app = bottle.Bottle()
        self._route()
        self._metarsObj = metars
        self._renderer = renderer
        self._config = renderer.config
        self._pixels: NeoPixel = renderer.pixels()
        self._thread = None
        bottle.TEMPLATE_PATH.insert(0, "./templates")

    def _route(self):
        self._app.route("/", method="GET", callback=self._index)
        self._app.route("/metars", method="GET", callback=self._metars)
        self._app.route("/raw", method="GET", callback=self._raw)
        self._app.route("/raw/<code>", method="GET", callback=self._rawcode)
        self._app.route("/fetch", method="GET", callback=self._fetch)
        self._app.route("/config", method="GET", callback=self._get_config)
        self._app.route("/config/edit/<key>/<value>", method="GET", callback=self._edit_config)
        self._app.route("/debug", method="GET", callback=self._debug)
        self._app.route("/brightness/<level>", method="GET", callback=self._brightness)
        self._app.route("/locate/<pixnum>", method="GET", callback=self._locate)
        self._app.route("/visualizer/<visnum>", method="GET", callback=self._visualizer)
        self._app.route("/visualizer/next", method="GET", callback=self._visualizernext)
        self._app.route("/visualizer/previous", method="GET", callback=self._visualizerprevious)

    def _index(self):
        return bottle.template('index.tpl', renderer=self._renderer)

    def _metars(self):
        return bottle.template('metars.tpl', metars=self._metarsObj)

    def _raw(self):
        buf = io.StringIO()
        for s in self._metarsObj.data.keys():
            if 'raw' in self._metarsObj.data[s]:
                buf.write("<b>" + s + "</b>: " + self._metarsObj.data[s]['raw'] + "<br />")
            else:
                buf.write("<b>" + s + "</b>: N/A<br />")
        buf.seek(0)
        return buf.read()

    def _rawcode(self, code):
        return "<b>" + code + "</b>: " + self._metarsObj.data[code]['raw'] + "<br />"

    def _get_config(self):
        return bottle.template('config.tpl', renderer=self._renderer)

    def _edit_config(self, key, value):
        self._renderer.config.edit(key, value)
        return bottle.template('config.tpl', renderer=self._renderer)

    def _fetch(self):
        self._metarsObj.fetch()
        while self._metarsObj.is_fetching():
            pass
        return bottle.template('index.tpl', renderer=self._renderer)

    def _debug(self):
        return bottle.template('debug.tpl', metars=self._metarsObj, renderer=self._renderer)

    def _brightness(self, level):
        self._renderer.brightness(float(level))
        return bottle.template('index.tpl', renderer=self._renderer)

    def _locate(self, pixnum):
        self._renderer.locate(pixnum)
        return bottle.template('metars.tpl', metars=self._metarsObj)

    def _visualizer(self, visnum):
        self._renderer.visualizer = int(visnum)
        return bottle.template('index.tpl', renderer=self._renderer)

    def _visualizernext(self):
        self._renderer.visualizer_next()
        return bottle.template('index.tpl', renderer=self._renderer)

    def _visualizerprevious(self):
        self._renderer.visualizer_previous()
        return bottle.template('index.tpl', renderer=self._renderer)
