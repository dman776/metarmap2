"""
Saved plans on the Chart Planner page: what may be saved (a finished plan, never a running, cancelled or failed one),
what a Load does (the saved plan becomes the planner's current finished job, which Apply, Undo and the page then treat
like a fresh one) and the routes. The files are metarmap.planner.saves.PlanSaves.

A loaded plan gets a new job id, so the Apply token (which binds the job id, the Chart's airports now and the airports
after the plan) of any earlier preview is `stale`, and a preview of the loaded plan is computed against the Chart as it
is when it is asked for: a plan saved when the Chart had other airports is applied against the Chart's airports now.
"""

import logging
import os
from typing import Any, Dict, Optional, Tuple

import bottle

from metarmap.config import MAX_LEDS
from metarmap.planner import saves
from metarmap.planner.saves import PlanSaves, SaveError
from metarmap.web.planner import Invalid, Planner, PlannerRoutes, parse
from metarmap.web.services import Services

log = logging.getLogger(__name__)

SHEET_KEYS = (
    "board",
    "settings",
    "pixels",
    "start",
    "route",
    "cuts",
    "joins",
    "strings",
    "shopping",
    "problems",
    "power",
)
RESULT_LISTS = ("airports", "notes", "left_out")


def saves_for(services: Services) -> PlanSaves:
    """The saved plans of this Chart: `planner-saves/` in the folder of its config.json."""
    return PlanSaves(os.path.join(services.config.folder(), saves.FOLDER))


def _unreadable() -> SaveError:
    return SaveError("unreadable", "That saved plan cannot be read: it is not a plan this version can show", 409)


def check_plan(params: Any, result: Any) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    (params, result) of a saved plan that the page can show and Apply can use: the params go through the same checks as
    the form's, and the result must have the parts the page draws and Apply reads. Raises SaveError("unreadable").
    """
    try:
        params = parse(params)
    except Invalid:
        raise _unreadable() from None
    sheet = result.get("sheet") if isinstance(result, dict) else None
    if not isinstance(sheet, dict) or not all(k in sheet for k in SHEET_KEYS):
        raise _unreadable()
    shopping, pixels = sheet["shopping"], sheet["pixels"]
    if (
        not isinstance(result.get("message"), str)
        or not isinstance(result.get("names"), dict)
        or not isinstance(result.get("chart"), dict)
        or not all(isinstance(result.get(k), list) for k in RESULT_LISTS)
        or not isinstance(shopping, dict)
        or not isinstance(shopping.get("strings"), int)
        or isinstance(shopping.get("strings"), bool)
        or not isinstance(pixels, list)
        or len(pixels) > MAX_LEDS
        or not all(isinstance(p, dict) for p in pixels)
        or len(result["airports"]) != len(pixels)
        or not all(isinstance(a, dict) for a in result["airports"])
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

    def _finished(self):
        """(params, result, None) of the finished plan the planner holds, or (None, None, SaveError)."""
        job = self.planner.job
        if job is None:
            return None, None, SaveError("nothing", "There is no plan to save: plan a chart first")
        snap = dict(job)
        if not snap["done"]:
            return None, None, SaveError("running", "A plan is still running")
        if snap.get("cancelled") or not snap.get("ok") or not snap.get("result") or not snap.get("params"):
            return None, None, SaveError("nothing", "There is no finished plan to save: plan a chart first")
        return snap["params"], snap["result"], None

    def save(self, name):
        params, result, err = self._finished()
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
            return 200, {"ok": True, "save": self.store.rename(plan_id, name)}
        except SaveError as e:
            return self._fail(e)

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
    app.route("/config/planner/saves", "POST", lambda: with_body(lambda d: plans.save(name_of(d))), apply=auth)
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
