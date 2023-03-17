import pprint
import os, sys
import bottle
from bottle import auth_basic
import metar
from renderer import Renderer
from display import Display
from config import Config
from neopixel import NeoPixel
from lib import utils
from lib.safe_logging import safe_log
import threading
import io


class WebServer(object):
    """
    Class to handle running a REST endpoint to handle configuration.
    """

    def __init__(self, host, port, metars: metar.METAR, config: Config):
        self._port = port
        self._host = host
        self._app = bottle.Bottle()
        self._routes()
        self._metarsObj = metars
        self._config: Config = config
        self._renderer: Renderer = config.renderer
        self._display: Display = config.display
        self._pixels: NeoPixel = self._renderer.pixels()
        self._thread = None
        bottle.TEMPLATE_PATH.insert(0, "./templates")

    def run(
            self
    ):
        """
        Starts the server.
        """
        safe_log(f"localhost = {self._host}:{self._port}")
        self._thread = threading.Thread(target=self._app.run, kwargs=dict(host=self._host, port=self._port))
        self._thread.daemon = True
        self._thread.start()

    def stop(self):
        if self._app is not None:
            self._app.close()

    def _routes(self):
        self._app.route("/", method="GET", callback=self._index)
        self._app.route("/metars", method="GET", callback=self._metars)
        self._app.route("/raw", method="GET", callback=self._raw)
        self._app.route("/map", method="GET", callback=self._map)
        self._app.route("/raw/<code>", method="GET", callback=self._rawcode)
        self._app.route("/fetch", method="GET", callback=self._fetch)
        self._app.route("/debug", method="GET", callback=self._debug)
        self._app.route("/locate/<pixnum>", method="GET", callback=self._locate)
        self._app.route("/config", method="GET", callback=self._get_config, apply=auth_basic(self.is_auth))
        self._app.route("/config/edit/<key>/<value>", method="GET", callback=self._edit_config,
                        apply=auth_basic(self.is_auth))
        self._app.route("/config/airports", method="GET", callback=self._get_config_airports,
                        apply=auth_basic(self.is_auth))
        self._app.route("/config/airports/edit/<oldkey>/<newkey>", method="GET", callback=self._airport_edit,
                        apply=auth_basic(self.is_auth))
        self._app.route("/config/airports/edit/prop/<airport>/<key>/<value>", method="GET",
                        callback=self._airport_edit_prop, apply=auth_basic(self.is_auth))
        self._app.route("/update", method="GET", callback=self._update, apply=auth_basic(self.is_auth))
        self._app.route("/restart", method="GET", callback=self._restart, apply=auth_basic(self.is_auth))
        self._app.route("/brightness/<level>", method="GET", callback=self._brightness, apply=auth_basic(self.is_auth))
        self._app.route("/visualizer/<visnum>", method="GET", callback=self._visualizer, apply=auth_basic(self.is_auth))
        self._app.route("/visualizer/next", method="GET", callback=self._visualizernext, apply=auth_basic(self.is_auth))
        self._app.route("/visualizer/previous", method="GET", callback=self._visualizerprevious,
                        apply=auth_basic(self.is_auth))

    def is_auth(self, user, password):
        if user.lower() == self._config.data.web_server.user and password == self._config.data.web_server.password:
            return True
        else:
            return False

    def _index(self):
        return bottle.template('index.tpl', config=self._config)

    def _metars(self):
        return bottle.template('metars.tpl', metars=self._metarsObj, config=self._config)

    def _raw(self):
        buf = io.StringIO()
        raw_strs = (f"<b>{s}</b>: {self._metarsObj.data[s].get('raw', 'N/A')}<br />" for s in
                    self._metarsObj.data.keys())
        buf.write(''.join(raw_strs))
        buf.write(f"<pre><code>{pprint.pformat(self._metarsObj.data, indent=4)}</code></pre>")
        buf.seek(0)
        return buf.read()

    def _map(self):
        return bottle.template('map.tpl', metars=self._metarsObj, config=self._config)

    def _rawcode(self, code):
        return "<b>" + code + "</b>: " + self._metarsObj.data[code]['raw'] + "<br />"

    def _get_config(self):
        return bottle.template('config.tpl', config=self._config)

    def _get_config_airports(self):
        return bottle.template('airports.tpl', config=self._config)

    def _airport_edit(self, oldkey, newkey):
        self._config.edit_airport(oldkey, newkey)
        return bottle.redirect("/config/airports")

    def _airport_edit_prop(self, airport, key, value):
        self._config.edit_airport_property(airport, key, value)
        return bottle.redirect("/config/airports")

    def _edit_config(self, key, value):
        self._config.edit(key, value)
        self._renderer.refresh()
        return bottle.template('config.tpl', config=self._config)

    def _fetch(self):
        self._metarsObj.fetch()
        while self._metarsObj.is_fetching():
            pass
        self._renderer.update_data(self._metarsObj)
        return bottle.template('index.tpl', config=self._config)

    def _debug(self):
        return bottle.template('debug.tpl', metars=self._metarsObj, config=self._config)

    def _restart(self):
        if self._display:
            self._display.stop()
        self._renderer.clear()
        utils.restart()

    def _update(self):
        return utils.update()
        # return bottle.template('index.tpl', renderer=self._renderer)

    def _brightness(self, level):
        self._renderer.brightness(float(level))
        return bottle.template('index.tpl', renderer=self._renderer, config=self._config)

    def _locate(self, pixnum):
        self._renderer.locate(pixnum)
        return bottle.template('metars.tpl', metars=self._metarsObj, renderer=self._renderer, config=self._config)

    def _visualizer(self, visnum):
        self._renderer.visualizer = int(visnum)
        return bottle.template('index.tpl', renderer=self._renderer, config=self._config)

    def _visualizernext(self):
        self._renderer.visualizer_next()
        return bottle.template('index.tpl', renderer=self._renderer, config=self._config)

    def _visualizerprevious(self):
        self._renderer.visualizer_previous()
        return bottle.template('index.tpl', renderer=self._renderer, config=self._config)
