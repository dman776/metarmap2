"""
Saved plans on the Chart Planner page: what may be saved (a finished plan, never a running, cancelled or failed one),
what a Load does (the saved plan becomes the planner's current finished job, which Apply, Undo and the page then treat
like a fresh one) and the routes. The files are metarmap.planner.saves.PlanSaves.

A loaded plan gets a new job id, so the Apply token (which binds the job id, the Chart's airports now and the airports
after the plan) of any earlier preview is `stale`, and a preview of the loaded plan is computed against the Chart as it
is when it is asked for: a plan saved when the Chart had other airports is applied against the Chart's airports now.
"""

import logging
import math
import os
from typing import Any, Dict, Optional, Tuple

import bottle

from metarmap.config import MAX_LEDS
from metarmap.planner import saves
from metarmap.planner.saves import PlanSaves, SaveError
from metarmap.web.planner import Invalid, Planner, PlannerRoutes, parse
from metarmap.web.services import Services

log = logging.getLogger(__name__)


class _Maybe:
    """A shape that may also be null."""

    def __init__(self, shape):
        self.shape = shape


class _Opt:
    """A key that may be missing (older plans, or ones that do not have it); when there it has this shape."""

    def __init__(self, shape):
        self.shape = shape


NUM, INT, STR, BOOL = "num", "int", "str", "bool"  # NUM: a finite number; INT: a whole one; neither is a bool
ANY_MAP = "map"
POINT = [NUM]  # a [lat, lon] pair: a list of numbers
# What planner.js draws and the Applier reads of a result, as the planner makes it (see Planner._plan and
# buildsheet.build). A key not named here is left alone; one named must be there with this shape (_Opt: or missing).
PIXEL = {
    "code": _Maybe(STR),
    "skipped": BOOL,
    "x": NUM,
    "y": NUM,
    "number": _Opt(INT),
    "index": _Opt(INT),
    "string": _Opt(INT),
    "moved_mm": _Opt(NUM),
    "orig_x": _Opt(_Maybe(NUM)),
    "orig_y": _Opt(_Maybe(NUM)),
    "lat": _Opt(_Maybe(NUM)),
    "lon": _Opt(_Maybe(NUM)),
    "orig_lat": _Opt(_Maybe(NUM)),
    "orig_lon": _Opt(_Maybe(NUM)),
}
SHEET = {
    "board": {"width_mm": NUM, "height_mm": NUM, "width_in": NUM, "height_in": NUM},
    "settings": {"string_len": INT},
    "pixels": [PIXEL],
    "start": _Maybe({"index": INT, "code": _Maybe(STR)}),
    "route": [
        {
            "kind": STR,
            "status": STR,
            "from_index": INT,
            "to_index": INT,
            "length_mm": NUM,
            "extension_mm": _Opt(NUM),
            "slack_mm": _Opt(NUM),
        }
    ],
    "cuts": [{"between": [INT], "string": INT, "codes": [STR], "length_mm": NUM, "how": STR}],
    "joins": [ANY_MAP],
    "strings": [{"number": INT, "first": INT, "last": INT, "pixels": INT}],
    "shopping": {"strings": INT, "pixels": _Opt(INT), "extensions": _Opt(INT)},
    "problems": {
        "crowded": [[STR]],
        "drops": [ANY_MAP],
        "clipped": [STR],
        "skips_wanted": _Opt(INT),
        "skips_note": _Opt(STR),
    },
    "power": {
        "voltage": NUM,
        "reason": STR,
        "ma_per_pixel": NUM,
        "brightness": NUM,
        "margin": NUM,
        "estimated_amps": NUM,
        "supply_amps": NUM,
        "supply_watts": NUM,
        "feed_points": [INT],
        "notes": [STR],
    },
}
RESULT = {
    "message": STR,
    "chart": {
        "name": STR,
        "kind": STR,
        "outline": [POINT],
        "bounds": {"south": NUM, "west": NUM, "north": NUM, "east": NUM},
    },
    "sheet": SHEET,
    "airports": [{"code": STR, "name": STR, "display": BOOL, "skip": BOOL}],
    "names": {"*": STR},  # every value is text
    "left_out": [{"code": STR, "reason": STR}],
    "notes": [STR],
    "stale": _Opt(BOOL),
    "fetched_at": _Opt(_Maybe(STR)),
    "sizes": _Opt(
        _Maybe(
            {
                "best": [{"width_in": NUM, "height_in": NUM, "extensions": INT, "crowded": INT}],
                "current": {"width_in": NUM, "height_in": NUM, "extensions": INT, "crowded": INT},
            }
        )
    ),
}


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def fits(value: Any, shape: Any) -> bool:
    """Whether `value` has `shape` (see RESULT): a dict has every key its shape names, a list holds only items of its
    one shape, numbers are finite. Extra keys are allowed."""
    if isinstance(shape, _Maybe):
        return value is None or fits(value, shape.shape)
    if shape == NUM:
        return _number(value)
    if shape == INT:
        return isinstance(value, int) and not isinstance(value, bool)
    if shape == STR:
        return isinstance(value, str)
    if shape == BOOL:
        return isinstance(value, bool)
    if shape == ANY_MAP:
        return isinstance(value, dict)
    if isinstance(shape, list):
        return isinstance(value, list) and all(fits(item, shape[0]) for item in value)
    if isinstance(shape, dict):
        if not isinstance(value, dict):
            return False
        if "*" in shape:
            return all(isinstance(k, str) and fits(v, shape["*"]) for k, v in value.items())
        for key, sub in shape.items():
            if isinstance(sub, _Opt):
                if key in value and not fits(value[key], sub.shape):
                    return False
            elif key not in value or not fits(value[key], sub):
                return False
        return True
    return False


def saves_for(services: Services) -> PlanSaves:
    """The saved plans of this Chart: `planner-saves/` in the folder of its config.json."""
    return PlanSaves(os.path.join(services.config.folder(), saves.FOLDER))


def _unreadable() -> SaveError:
    return SaveError("unreadable", "That saved plan cannot be read: it is not a plan this version can show", 409)


def check_plan(params: Any, result: Any) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    (params, result) of a saved plan that the page can show and Apply can use: the params go through the same checks as
    the form's, and the result must have the shapes the page draws and Apply reads (RESULT), as many airports as
    pixels, and a number of strings that fits the pixels and string_len exactly, so nothing big is ever built from a
    number in a file. Raises SaveError("unreadable").
    """
    try:
        params = parse(params)
    except Invalid:
        raise _unreadable() from None
    if not fits(result, RESULT):
        raise _unreadable()
    pixels, strings = result["sheet"]["pixels"], result["sheet"]["shopping"]["strings"]
    length, count = params["string_len"], len(pixels)
    # the plan's own shape: the last string is the only one that is not full, so (strings - 1) x length < pixels <=
    # strings x length. A plan may have up to a string's spare pixels over MAX_LEDS (Apply's preview answers
    # over_limit, as for a fresh plan). strings x length is then under MAX_LEDS + 2 x length, at most about 3000
    # airports for plan_changes to build, whatever the file says; `strings` is also capped on its own
    if (
        count > MAX_LEDS + length
        or len(result["airports"]) != count
        or not 1 <= strings <= MAX_LEDS
        or (strings - 1) * length >= max(count, 1)
        or count > strings * length
    ):
        raise _unreadable()
    return params, result


def summary_of(result: Dict[str, Any]) -> Dict[str, Any]:
    """What a listing shows of a plan: the chart, the airports, the strings and the board, from the result."""
    sheet = result.get("sheet") or {}
    board = sheet.get("board") or {}
    return {
        "chart": (result.get("chart") or {}).get("name"),
        "airports": sum(1 for a in result.get("airports") or [] if a.get("code")),
        "pixels": len(sheet.get("pixels") or []),
        "strings": (sheet.get("shopping") or {}).get("strings"),
        "board_in": [board.get("width_in"), board.get("height_in")],
        "message": str(result.get("message") or "")[:200],
    }


class SavedPlans:
    """Save, list, load, rename and delete, each answering (status, body) like the Applier."""

    def __init__(self, services: Services, planner: Planner, store: Optional[PlanSaves] = None):
        self.services, self.planner = services, planner
        self._store = store

    @property
    def store(self) -> PlanSaves:
        """The files, found on first use (so a page that never saves a plan does not need a config folder)."""
        if self._store is None:
            self._store = saves_for(self.services)
        return self._store

    def _fail(self, e: SaveError):
        return e.status, {"error": str(e), "reason": e.reason}

    def listing(self):
        return 200, {"saves": self.store.listing(), "limit": saves.MAX_SAVES, "max_name": saves.MAX_NAME}

    def _finished(self, job_id):
        """
        (params, result, None) of the finished plan the planner holds, or (None, None, SaveError). `job_id` is the
        job the page showed: a different current job (another tab planned or loaded a plan) is "stale".
        """
        job = self.planner.job
        if job is None:
            return None, None, SaveError("nothing", "There is no plan to save: plan a chart first")
        snap = dict(job)
        if not snap["done"]:
            return None, None, SaveError("running", "A plan is still running")
        if snap.get("cancelled") or not snap.get("ok") or not snap.get("result") or not snap.get("params"):
            return None, None, SaveError("nothing", "There is no finished plan to save: plan a chart first")
        if snap["id"] != job_id:
            return (
                None,
                None,
                SaveError(
                    "stale",
                    "The plan on this page is not the Chart's current plan any more (another plan was made or "
                    "loaded): look at the current plan, then save it",
                ),
            )
        return snap["params"], snap["result"], None

    def save(self, name, job_id):
        params, result, err = self._finished(job_id)
        if err:
            return self._fail(err)
        try:
            saved = self.store.save(name, params, result, summary_of(result))
        except SaveError as e:
            return self._fail(e)
        log.info(f"saved the plan {saved['id']}")
        return 201, {"ok": True, "save": saved}

    def load(self, plan_id):
        try:
            header, params, result = self.store.read(plan_id)
            params, result = check_plan(params, result)
        except SaveError as e:
            return self._fail(e)
        loaded = {"id": header["id"], "name": header["name"], "saved_at": header["saved_at"]}
        job, adopted = self.planner.adopt(params, result, loaded)
        if not adopted:
            return 409, {"error": "A plan is running: wait for it to finish, or cancel it", "reason": "running"}
        log.info(f"loaded the saved plan {header['id']}")
        return 200, {"ok": True, "job": job}

    def rename(self, plan_id, name):
        try:
            saved = self.store.rename(plan_id, name)
        except SaveError as e:
            return self._fail(e)
        job = self.planner.job
        loaded = job.get("loaded") if job is not None else None
        if (
            job is not None and loaded and loaded.get("id") == plan_id
        ):  # the banner of a plan loaded from this file says its new name
            job["loaded"] = {**loaded, "name": saved["name"]}
        return 200, {"ok": True, "save": saved}

    def delete(self, plan_id):
        try:
            self.store.delete(plan_id)
        except SaveError as e:
            return self._fail(e)
        return 200, {"ok": True}


def install(routes: PlannerRoutes, app: bottle.Bottle, auth, planner: Planner) -> SavedPlans:
    """Adds the /config/planner/saves routes to the planner's. Every POST is JSON only, like the Undo."""
    plans = SavedPlans(routes.services, planner)

    def body_dict():
        data, bad = routes.json_body()
        if bad:
            return None, bad
        if not isinstance(data, dict):  # a form or text post (a cross-site form) is not JSON: refused
            return None, routes.refuse("invalid", "Send a JSON object")
        return data, None

    def with_body(call):
        data, bad = body_dict()
        return bad or routes.answer(lambda: call(data))

    def name_of(data):
        return data.get("name")

    app.route("/config/planner/saves", "GET", lambda: routes.answer(plans.listing), apply=auth)

    def save(data):
        job_id = data.get("job")
        if not isinstance(job_id, int) or isinstance(job_id, bool):
            return 400, {"error": "The request needs the number of the plan on the page (job)", "reason": "invalid"}
        return plans.save(name_of(data), job_id)

    app.route("/config/planner/saves", "POST", lambda: with_body(save), apply=auth)
    app.route(
        "/config/planner/saves/<plan_id>/load",
        "POST",
        lambda plan_id: with_body(lambda d: plans.load(plan_id)),
        apply=auth,
    )
    app.route(
        "/config/planner/saves/<plan_id>/rename",
        "POST",
        lambda plan_id: with_body(lambda d: plans.rename(plan_id, name_of(d))),
        apply=auth,
    )
    app.route(
        "/config/planner/saves/<plan_id>/delete",
        "POST",
        lambda plan_id: with_body(lambda d: plans.delete(plan_id)),
        apply=auth,
    )
    return plans
