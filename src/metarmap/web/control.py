"""
The routes that change the map: visualizer, brightness, locate, fetch, settings and airport edits, update and restart.
Most answer with the page the web UI shows next.
"""
import json
import subprocess
import threading
import time

import bottle

from metarmap import system
from metarmap.config import parse_code, parse_user
from metarmap.lib import utils
from metarmap.lib.safe_logging import safe_log
from metarmap.web import pages

WIFI_DELAY = 3  # seconds between answering a Wi-Fi change and making it

NO_UPDATE = {"fraction": 0.0, "label": "", "done": True, "ok": None, "changed": None, "errors": []}


class Updates:
    """The update started from the web UI. It runs in the background; the UI polls its progress."""

    def __init__(self, run_update=None):
        self._run_update = run_update or utils.run_update
        self._lock = threading.Lock()
        self.job = None

    def start(self):
        """Starts an update, unless one is already running. Returns the running job."""
        with self._lock:
            if self.job is None or self.job["done"]:
                job = {"fraction": 0.0, "label": "Starting", "done": False, "ok": None, "changed": None,
                       "errors": []}
                self.job = job

                def progress(fraction, label):
                    job["fraction"], job["label"] = fraction, label

                def run():
                    try:
                        result = self._run_update(progress=progress)
                        job.update(ok=result.ok, changed=result.changed, errors=result.errors)
                    except Exception as e:
                        safe_log(f"[w]update failed: {e}")
                        job.update(ok=False, changed=False, errors=[str(e)])
                    finally:
                        job["done"] = True

                threading.Thread(target=run, name="update", daemon=True).start()
            return self.job

    def progress(self):
        return self.job or NO_UPDATE


def as_json(data, status=200):
    bottle.response.status = status
    bottle.response.content_type = "application/json"
    return json.dumps(data)


def add_routes(app, services, site, auth, updates=None):
    renderer, config = services.renderer, services.config
    updates = updates or Updates()

    def visualizer(visnum):
        renderer.visualizer = int(visnum)
        return pages.index(services, site)

    def visualizer_next():
        renderer.visualizer_next()
        return pages.index(services, site)

    def visualizer_previous():
        renderer.visualizer_previous()
        return pages.index(services, site)

    def brightness(level):
        renderer.brightness(float(level))
        return pages.index(services, site)

    def display_power(state):
        """The Home page's OLED switch: on or off until changed again or the map restarts (not saved)."""
        if state not in ("on", "off"):
            bottle.abort(400, "Use /display/on or /display/off")
        if not config.data.display_screen.enabled:
            bottle.abort(409, "The OLED screen is turned off in Config (display_screen.enabled)")
        services.display.turn_on() if state == "on" else services.display.turn_off()
        return pages.index(services, site)

    def locate(pixnum):
        renderer.locate(pixnum)
        return pages.metars(services, site)

    def fetch():
        services.metars.fetch()
        renderer.update_data(services.metars)
        config.fill_names(services.metars.station_names())
        return pages.index(services, site)

    def edit_config(key, value):
        try:
            config.edit(key, value)
        except KeyError:
            bottle.abort(400, f"Unknown setting: {key}")
        except ValueError as e:
            bottle.abort(400, str(e))
        if key == "led.count":  # the in-memory strip changes now; a NeoPixel strip after a restart
            renderer.resize(config.data.led.count)
        renderer.refresh()
        if key.startswith("visualizer.auto_rotate."):  # the new timer starts now, no restart needed
            services.schedule_rotation()
        if key == "display_screen.enabled":  # the OLED turns on or off now, no restart needed
            services.display.turn_on() if config.data.display_screen.enabled else services.display.turn_off()
        return pages.config(services, site)

    def airports_changed(fetch=False):
        # show the change on the LEDs and the OLED; a new airport code needs its METAR
        renderer.refresh()
        if services.display:
            services.display.restart(timeout=15)
        if fetch:
            threading.Thread(target=fetch_metars, name="fetch", daemon=True).start()
        return bottle.redirect("/config/airports")

    def fetch_metars():
        services.metars.fetch()
        renderer.update_data(services.metars)
        config.fill_names(services.metars.station_names())

    def name_new_code(code):
        """A changed airport gets its new airport's name now, so the page shows it when it reloads."""
        name = services.metars.name_for(code)
        if name:
            config.fill_names({code: name})

    def edit_airports(change, fetch=False):
        """Runs one airport change; unknown LEDs and airports are 404s, bad values 400s."""
        try:
            change()
        except (IndexError, KeyError) as e:
            bottle.abort(404, f"No such LED or airport: {e}")
        except ValueError as e:
            bottle.abort(400, str(e))
        return airports_changed(fetch)

    def set_airport(pixel, key, value):
        def change():
            config.set_airport(pixel, key, value)
            new_code = config.airports[int(pixel)].code
            if key == "code" and new_code:
                name_new_code(new_code)
        return edit_airports(change, fetch=key == "code")

    def move_airport(src, dst):
        return edit_airports(lambda: config.move_airport(src, dst))

    def edit_airport(oldkey, newkey):
        def change():
            config.edit_airport(oldkey, newkey)
            name_new_code(parse_code(newkey))
        return edit_airports(change, fetch=True)

    def edit_airport_property(airport, key, value):
        return edit_airports(lambda: config.edit_airport_property(airport, key, value))

    def body():
        """The JSON body of a POST (passwords never go in a URL)."""
        try:
            data = bottle.request.json
        except ValueError:
            data = None
        if not isinstance(data, dict):
            bottle.abort(400, "Send the values as a JSON object")
        return data

    def set_login():
        """
        Changes the web UI login, and the Pi login user's Linux password to the same password. The Linux password
        changes first; if that fails, nothing changes.
        """
        data = body()
        password = str(data.get("password") or "")
        try:
            user = parse_user(data.get("user") or config.data.web_server.user)
            if password:
                system.check_password(password)
                linux = system.set_login_password(password)  # first: if it fails, nothing has changed
            else:
                linux = "unchanged"
            config.set_login(user, password or None)
        except ValueError as e:
            bottle.abort(400, str(e))
        except system.ChangeFailed as e:
            bottle.abort(500, f"The Pi's password couldn't be changed, so nothing was changed: {e}")
        safe_log(f"[w]web UI login changed (user {config.data.web_server.user}); Linux password: {linux}")
        return as_json({"user": config.data.web_server.user, "linux_password": linux})

    def set_wifi():
        """Switches the Pi to another Wi-Fi network a few seconds after answering; the current one stays a fallback."""
        data = body()
        ssid, password = str(data.get("ssid") or "").strip(), str(data.get("password") or "")
        try:
            system.check_wifi(ssid, password)
        except ValueError as e:
            bottle.abort(400, str(e))

        def switch():
            time.sleep(WIFI_DELAY)  # let the answer reach the browser before the connection drops
            try:
                safe_log(f"[w]Wi-Fi: {system.set_wifi(ssid, password)}")
            except (system.ChangeFailed, OSError, subprocess.SubprocessError) as e:
                safe_log(f"[w]Wi-Fi change to {ssid} failed: {e}")
        threading.Thread(target=switch, name="wifi", daemon=True).start()
        return as_json({"ssid": ssid, "current": system.current_wifi(), "delay": WIFI_DELAY}, status=202)

    def restart():
        if services.display:
            services.display.stop()
        renderer.clear()
        utils.restart()

    app.route("/visualizer/<visnum>", "GET", visualizer)
    app.route("/visualizer/next", "GET", visualizer_next)
    app.route("/visualizer/previous", "GET", visualizer_previous)
    app.route("/brightness/<level>", "GET", brightness)
    app.route("/display/<state>", "GET", display_power)
    app.route("/locate/<pixnum>", "GET", locate)
    app.route("/fetch", "GET", fetch)
    app.route("/config/edit/<key>/<value>", "GET", edit_config, apply=auth)
    app.route("/config/airports/<pixel:int>/<key>/<value>", "GET", set_airport, apply=auth)
    app.route("/config/airports/move/<src:int>/<dst:int>", "GET", move_airport, apply=auth)
    # the older by-code edits, still used by anything written for airports.json
    app.route("/config/airports/edit/<oldkey>/<newkey>", "GET", edit_airport, apply=auth)
    app.route("/config/airports/edit/prop/<airport>/<key>/<value>", "GET", edit_airport_property, apply=auth)
    app.route("/update", "GET", lambda: utils.update(), apply=auth)
    # 202: started; the web UI polls /update/progress for its progress bar
    app.route("/update/start", "POST", lambda: as_json(updates.start(), status=202), apply=auth)
    app.route("/update/progress", "GET", lambda: as_json(updates.progress()), apply=auth)
    app.route("/restart", "GET", restart, apply=auth)
    app.route("/config/login", "POST", set_login, apply=auth)
    app.route("/config/wifi", "POST", set_wifi, apply=auth)
