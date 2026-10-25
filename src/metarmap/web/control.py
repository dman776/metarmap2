"""
The routes that change the map: visualizer, brightness, locate, fetch, settings and airport edits, update and restart.
Most answer with the page the web UI shows next.
"""
import json
import threading

import bottle

from metarmap.lib import utils
from metarmap.lib.safe_logging import safe_log
from metarmap.web import pages

NO_UPDATE = {"fraction": 0.0, "label": "", "done": True, "ok": None, "changed": None, "errors": []}


class Updates:
    """The update started from the web UI. It runs in the background; the UI polls its progress."""

    def __init__(self, run_update=None):
        self.__run_update__ = run_update or utils.run_update
        self.__lock__ = threading.Lock()
        self.job = None

    def start(self):
        """Starts an update, unless one is already running. Returns the running job."""
        with self.__lock__:
            if self.job is None or self.job["done"]:
                job = {"fraction": 0.0, "label": "Starting", "done": False, "ok": None, "changed": None,
                       "errors": []}
                self.job = job

                def progress(fraction, label):
                    job["fraction"], job["label"] = fraction, label

                def run():
                    try:
                        result = self.__run_update__(progress=progress)
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

    def locate(pixnum):
        renderer.locate(pixnum)
        return pages.metars(services, site)

    def fetch():
        services.metars.fetch()
        renderer.update_data(services.metars)
        return pages.index(services, site)

    def edit_config(key, value):
        try:
            config.edit(key, value)
        except KeyError:
            bottle.abort(400, f"Unknown setting: {key}")
        except ValueError as e:
            bottle.abort(400, str(e))
        renderer.refresh()
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
        return edit_airports(lambda: config.set_airport(pixel, key, value), fetch=key == "code")

    def move_airport(src, dst):
        return edit_airports(lambda: config.move_airport(src, dst))

    def edit_airport(oldkey, newkey):
        return edit_airports(lambda: config.edit_airport(oldkey, newkey), fetch=True)

    def edit_airport_property(airport, key, value):
        return edit_airports(lambda: config.edit_airport_property(airport, key, value))

    def restart():
        if services.display:
            services.display.stop()
        renderer.clear()
        utils.restart()

    app.route("/visualizer/<visnum>", "GET", visualizer)
    app.route("/visualizer/next", "GET", visualizer_next)
    app.route("/visualizer/previous", "GET", visualizer_previous)
    app.route("/brightness/<level>", "GET", brightness)
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
