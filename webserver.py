import pprint
import bottle
from bottle import auth_basic
import metar
from renderer import Renderer
from display import Display
from config import Config
from lib import utils
from lib.safe_logging import safe_log
import threading
import io
import json
import socket
import time
from datetime import datetime


# FAA AIS tile services: (service name, label, lowest zoom level the FAA has tiles for); all stop at 12
CHART_TYPES = {
    "sectional": ("VFR_Sectional", "VFR Sectional", 8),
    "terminal": ("VFR_Terminal", "VFR Terminal Area", 10),
    "ifr_low": ("IFR_AreaLow", "IFR Enroute Low", 7),
}


def load_sectionals():
    with open("./static/sectionals.json") as f:
        return json.load(f)["charts"]


def my_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(('8.8.8.8', 1))  # connect() for UDP doesn't send packets
    return s.getsockname()[0]


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
        self._pixels = self._renderer.pixels()
        self._thread = None
        self._myIP = my_ip()
        self._sectionals = load_sectionals()
        self._update_job = None  # progress of the update started from the web UI
        self._update_lock = threading.Lock()
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
        self._app.route("/update/start", method="POST", callback=self._update_start, apply=auth_basic(self.is_auth))
        self._app.route("/update/progress", method="GET", callback=self._update_progress,
                        apply=auth_basic(self.is_auth))
        self._app.route("/restart", method="GET", callback=self._restart, apply=auth_basic(self.is_auth))
        self._app.route("/brightness/<level>", method="GET", callback=self._brightness)
        self._app.route("/visualizer/<visnum>", method="GET", callback=self._visualizer)
        self._app.route("/visualizer/next", method="GET", callback=self._visualizernext)
        self._app.route("/visualizer/previous", method="GET", callback=self._visualizerprevious)
        self._app.route("/api/status", method="GET", callback=self._api_status)
        self._app.route("/api/live", method="GET", callback=self._api_live)
        self._app.route("/static/<filename:path>", method="GET", callback=self._static)

    def is_auth(self, user, password):
        if user.lower() == self._config.data.web_server.user and password == self._config.data.web_server.password:
            return True
        else:
            return False

    def _template(self, name, **kwargs):
        return bottle.template(name, config=self._config, myIP=self._myIP, **kwargs)

    def _stations(self):
        """
        One entry per airport (in LED order, skipping NULL placeholders) for the templates.
        """
        stations = []
        for pixel, (code, props) in enumerate(self._config.airports.items()):
            if "NULL" in code:
                continue
            m = self._metarsObj.data.get(code) or {}
            text = props.get("text")
            stations.append({
                "code": code,
                "pixel": pixel,
                "name": text if isinstance(text, str) else "",
                "display": props.get("display", False),
                "has_data": bool(m),
                "cat": m.get("flightCategory") or None,
                "raw": m.get("raw"),
                "obsTime": m.get("obsTime"),
                "lat": m.get("latitude"),
                "lon": m.get("longitude"),
            })
        return stations

    def _sun_schedule(self):
        """
        Today's brightness schedule, with the next change flagged.
        """
        suntimes = self._config.suntimes
        if not suntimes:
            return []
        levels = self._config.data.led.brightness
        schedule = [{"name": name.capitalize(), "time": suntimes[name], "level": level, "next": False}
                    for name, level in (("dawn", levels.dimmed), ("sunrise", levels.normal),
                                        ("sunset", levels.dimmed), ("dusk", levels.off))]
        now = datetime.now(schedule[0]["time"].tzinfo)
        upcoming = [s for s in schedule if s["time"] > now]
        if upcoming:
            upcoming[0]["next"] = True
        return schedule

    def _map_settings(self):
        """
        Map page settings from config.json (geo.map), with defaults for older config files.
        """
        m = self._config.data.geo.map
        chart = getattr(m, "chart", None)
        if not any(c["name"] == chart for c in self._sectionals):
            chart = self._chart_for_airports()
        chart_type = getattr(m, "chart_type", "sectional")
        if chart_type not in CHART_TYPES:
            chart_type = "sectional"
        return {
            "background": getattr(m, "background", "sectional"),
            "chart_type": chart_type,
            "chart_service": CHART_TYPES[chart_type][0],
            "chart_label": CHART_TYPES[chart_type][1],
            "chart_min_zoom": CHART_TYPES[chart_type][2],
            "chart": chart,
            "chart_bounds": next((c for c in self._sectionals if c["name"] == chart), None),
            "view": getattr(m, "view", "airports"),
            "center": list(m.center),
            "zoom": m.zoom,
        }

    def _chart_for_airports(self):
        """
        The sectional that covers the most airports, used when none is configured.
        """
        points = [(float(s["lat"]), float(s["lon"])) for s in self._stations() if s["lat"] and s["lon"]]

        def covered(c):
            return sum(1 for lat, lon in points if c["south"] <= lat <= c["north"] and c["west"] <= lon <= c["east"])
        best = max(self._sectionals, key=covered)
        return best["name"] if covered(best) else None

    def _render_config(self):
        return self._template('config.tpl', map_settings=self._map_settings(), sectionals=self._sectionals,
                              chart_types=CHART_TYPES)

    def _render_index(self):
        return self._template('index.tpl', metars=self._metarsObj, stations=self._stations(),
                              schedule=self._sun_schedule())

    def _static(self, filename):
        return bottle.static_file(filename, root="./static")

    def _index(self):
        return self._render_index()

    def _metars(self):
        return self._template('metars.tpl', metars=self._metarsObj, stations=self._stations())

    def _raw(self):
        buf = io.StringIO()
        raw_strs = (f"<b>{s}</b>: {self._metarsObj.data[s].get('raw', 'N/A')}<br />" for s in
                    self._metarsObj.data.keys())
        buf.write(''.join(raw_strs))
        buf.write(f"<pre><code>{pprint.pformat(self._metarsObj.data, indent=4)}</code></pre>")
        buf.seek(0)
        return buf.read()

    def _map(self):
        return self._template('map.tpl', settings=self._map_settings())

    def _rawcode(self, code):
        return "<b>" + code + "</b>: " + self._metarsObj.data[code]['raw'] + "<br />"

    def _get_config(self):
        return self._render_config()

    def _get_config_airports(self):
        return self._template('airports.tpl', stations=self._stations())

    def _airport_edit(self, oldkey, newkey):
        self._config.edit_airport(oldkey, newkey)
        return bottle.redirect("/config/airports")

    def _airport_edit_prop(self, airport, key, value):
        self._config.edit_airport_property(airport, key, value)
        return bottle.redirect("/config/airports")

    def _edit_config(self, key, value):
        try:
            self._config.edit(key, value)
        except KeyError:
            bottle.abort(400, f"Unknown setting: {key}")
        except ValueError as e:
            bottle.abort(400, str(e))
        self._renderer.refresh()
        return self._render_config()

    def _fetch(self):
        self._metarsObj.fetch()
        while self._metarsObj.is_fetching():
            pass
        self._renderer.update_data(self._metarsObj)
        return self._render_index()

    def _debug(self):
        return self._template('debug.tpl', metars=self._metarsObj, renderer=self._renderer)

    def _restart(self):
        if self._display:
            self._display.stop()
        self._renderer.clear()
        utils.restart()

    def _update(self):
        return utils.update()

    def _update_start(self):
        """
        Starts the update in the background; the web UI polls /update/progress for its progress bar.
        If an update is already running, reports that one instead of starting another.
        """
        with self._update_lock:
            if self._update_job is None or self._update_job["done"]:
                job = {"fraction": 0.0, "label": "Starting", "done": False, "ok": None, "changed": None,
                       "errors": []}
                self._update_job = job

                def progress(fraction, label):
                    job["fraction"], job["label"] = fraction, label

                def run():
                    try:
                        result = utils.run_update(progress=progress)
                        job.update(ok=result.ok, changed=result.changed, errors=result.errors)
                    except Exception as e:
                        safe_log(f"[w]update failed: {e}")
                        job.update(ok=False, changed=False, errors=[str(e)])
                    finally:
                        job["done"] = True

                threading.Thread(target=run, name="update", daemon=True).start()
        bottle.response.status = 202
        return self._update_progress()

    def _update_progress(self):
        bottle.response.content_type = "application/json"
        return json.dumps(self._update_job or {"fraction": 0.0, "label": "", "done": True, "ok": None,
                                               "changed": None, "errors": []})

    def _brightness(self, level):
        self._renderer.brightness(float(level))
        return self._render_index()

    def _locate(self, pixnum):
        self._renderer.locate(pixnum)
        return self._metars()

    def _visualizer(self, visnum):
        self._renderer.visualizer = int(visnum)
        return self._render_index()

    def _visualizernext(self):
        self._renderer.visualizer_next()
        return self._render_index()

    def _visualizerprevious(self):
        self._renderer.visualizer_previous()
        return self._render_index()

    def _api_live(self):
        """
        What the physical map is doing right now: every LED's effect, the OLED screen and the last locate pulse.
        Polled by the Map page.
        """
        def num(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        led_looks, strip = self._renderer.led_states()
        active_num, active_vis = self._renderer.visualizer
        display = self._display if self._config.data.display_screen.enabled else None
        leds = []
        for s in self._stations():
            m = self._metarsObj.data.get(s["code"]) or {}
            leds.append({
                "code": s["code"],
                "pixel": s["pixel"],
                "name": s["name"],
                "lat": num(s["lat"]),
                "lon": num(s["lon"]),
                "flightCategory": s["cat"],
                "raw": s["raw"],
                "lightning": m.get("lightning", False),
                "look": led_looks.get(s["pixel"], {"effect": "off", "colors": []}),
            })
        live = {
            "now": time.time(),
            "brightness": self._pixels.brightness,
            "visualizer": {"active": active_num, "name": active_vis.name, "exclusive": active_vis.exclusive},
            "strip": strip,
            "leds": leds,
            "locate": self._renderer.last_locate,
            "display": {"enabled": display is not None, "screen": display.screen if display else None},
        }
        bottle.response.content_type = "application/json"
        return json.dumps(live)

    def _api_status(self):
        """
        Read-only JSON snapshot of the map state (used by the Home Assistant integration).
        """
        def iso(dt):
            return dt.isoformat() if dt is not None else None

        cfg = self._config.data
        active_num, active_vis = self._renderer.visualizer
        suntimes = self._config.suntimes or {}

        airports = []
        for index, (code, props) in enumerate(self._config.airports.items()):
            if "NULL" in code:
                continue
            m = self._metarsObj.data.get(code, {})
            airports.append({
                "code": code,
                "pixel": index,
                "text": props.get("text"),
                "display": props.get("display", False),
                "flightCategory": m.get("flightCategory"),
                "raw": m.get("raw"),
                "windDir": m.get("windDir"),
                "windSpeed": m.get("windSpeed"),
                "windGustSpeed": m.get("windGustSpeed"),
                "vis": m.get("vis"),
                "obs": m.get("obs"),
                "tempC": m.get("tempC"),
                "dewpointC": m.get("dewpointC"),
                "altimHg": m.get("altimHg"),
                "lightning": m.get("lightning"),
                "obsTime": iso(m.get("obsTime")),
            })

        status = {
            "version": self._config.app_version,
            "ip": self._myIP,
            "brightness": self._pixels.brightness,
            "visualizer": {"active": active_num, "name": active_vis.name, "exclusive": active_vis.exclusive,
                           "description": active_vis.description, "legend": active_vis.legend},
            "visualizers": [{"index": i, "name": v.name, "exclusive": v.exclusive}
                            for i, v in enumerate(self._renderer.visualizers)],
            "config": {
                "visualizer.active": cfg.visualizer.active,
                "visualizer.auto_rotate.enabled": cfg.visualizer.auto_rotate.enabled,
                "visualizer.auto_rotate.delay_seconds": cfg.visualizer.auto_rotate.delay_seconds,
                "lightning.animation": cfg.lightning.animation,
                "display_screen.enabled": cfg.display_screen.enabled,
                "display_screen.locate_active": cfg.display_screen.locate_active,
                "display_screen.delay": cfg.display_screen.delay,
                "led.inittest": cfg.led.inittest,
                "led.brightness.normal": cfg.led.brightness.normal,
                "led.brightness.dimmed": cfg.led.brightness.dimmed,
                "led.brightness.off": cfg.led.brightness.off,
            },
            "suntimes": {k: iso(suntimes.get(k)) for k in ("dawn", "sunrise", "sunset", "dusk")},
            "lastFetchTime": iso(self._metarsObj.lastFetchTime),
            "missingStations": self._metarsObj.missing_stations(),
            "airports": airports,
        }
        bottle.response.content_type = "application/json"
        return json.dumps(status)
