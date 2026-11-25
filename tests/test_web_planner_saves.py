"""
Tests for the Chart Planner's saved plans (web.planner_saves): save, list, load, rename and delete over the routes, what
a Load does to the planner's current job and to Apply and Undo, the refusals, and files that are damaged or edited.
The airport fetch is a fake: no network.
"""

import io
import json
import os
import re
import threading

import pytest
from test_planner_apply_web import APPLY, PREVIEW, UNDO, codes, config_dir, get, make, planned, post  # noqa: F401
from test_web import AUTH, Client
from test_web_planner import FakeLoad, run, wait

from metarmap.planner import saves
from metarmap.web import create_app
from metarmap.web import planner as planner_web

SAVES = "/config/planner/saves"
ROUTES = [
    (SAVES, "GET"),
    (SAVES, "POST"),
    (SAVES + "/20261125-120000-0123abcd/load", "POST"),
    (SAVES + "/20261125-120000-0123abcd/rename", "POST"),
    (SAVES + "/20261125-120000-0123abcd/delete", "POST"),
]


def raw(client, path, data, content_type="application/json", method="POST"):
    """POSTs bytes with the content type given: the Client always sends JSON."""
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "SERVER_NAME": "test",
        "SERVER_PORT": "80",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.url_scheme": "http",
        "wsgi.input": io.BytesIO(data),
        "wsgi.errors": io.StringIO(),
        "CONTENT_LENGTH": str(len(data)),
        "CONTENT_TYPE": content_type,
        "HTTP_AUTHORIZATION": AUTH,
    }
    out = []
    body = b"".join(client.app(environ, lambda status, headers, exc_info=None: out.append(status)))
    return int(out[0].split()[0]), json.loads(body)


def offer(client, name, job=None):
    """POSTs a save of the plan the page shows (the planner's current job unless `job` is given)."""
    if job is None:
        job = client.planner.job["id"] if client.planner.job else 0
    return post(client, SAVES, {"name": name, "job": job})


def folder(client):
    return os.path.join(config_dir(client), saves.FOLDER)


def keep(client, name="Houston 2026-11-25"):
    status, body = offer(client, name)
    assert status == 201, body
    return body["save"]


def progress(client):
    return client.json("/config/planner/progress")


def reopen(client):
    """The same Chart and its files with a new Planner and a new app: what a restart leaves."""
    planner = planner_web.Planner(client.services, load=FakeLoad())
    other = Client(create_app(client.services, ip="10.0.0.2", planner=planner))
    other.services, other.planner = client.services, planner
    return other


# ---- who and what -----------------------------------------------------------------------------------------------


def test_the_saved_plan_routes_need_a_login(make):  # noqa: F811
    client = make()
    for path, method in ROUTES:
        assert client(path, method=method, auth=False)[0] == 401, (path, method)


def test_the_list_starts_empty(make):  # noqa: F811
    client = make()
    status, body = get(client, SAVES)
    assert status == 200 and body["saves"] == [] and body["limit"] == saves.MAX_SAVES


def test_the_page_has_the_saved_plans_cards(make):  # noqa: F811
    body = make()("/config/planner")[1]
    for text in ("Saved plans", "Save this plan", 'id="pl-saves-list"', 'id="pl-save-form"', 'id="pl-loaded"'):
        assert text in body
    assert "confirm(" not in body and "alert(" not in body


def test_progress_says_a_fresh_plan_was_not_loaded(make):  # noqa: F811
    client = make()
    assert progress(client)["loaded"] is None
    planned(client)
    assert progress(client)["loaded"] is None


# ---- save -------------------------------------------------------------------------------------------------------


def test_nothing_to_save_before_a_plan_and_after_a_failed_or_cancelled_one(make):  # noqa: F811
    client = make(FakeLoad(airports=[], error="no network"))
    status, body = offer(client, "x")
    assert status == 409 and body["reason"] == "nothing" and body["error"]
    run(client, source="recommended", start_fresh=True)  # fails: no airports
    assert offer(client, "x")[1]["reason"] == "nothing"
    client.planner.job.update(ok=True, result={"message": "m"}, cancelled=True)
    assert offer(client, "x")[1]["reason"] == "nothing"
    assert get(client, SAVES)[1]["saves"] == []


def test_a_running_plan_cannot_be_saved(make):  # noqa: F811
    release = threading.Event()

    class Slow(FakeLoad):
        def __call__(self, box, clock=None, progress=None, **kwargs):
            release.wait(30)
            return super().__call__(box, clock=clock, progress=progress, **kwargs)

    client = make(Slow())
    try:
        assert (
            client("/config/planner/plan", method="POST", body={"chart": "Houston", "source": "recommended"})[0] == 202
        )
        status, body = offer(client, "x")
        assert status == 409 and body["reason"] == "running"
    finally:
        release.set()
        wait(client)


def test_save_keeps_the_plan_and_its_settings_in_a_file_beside_config_json(make):  # noqa: F811
    client = make()
    job = planned(client)
    status, body = offer(client, "  Houston   2026-11-25 ")
    assert status == 201 and body["ok"] is True
    saved = body["save"]
    assert saved["name"] == "Houston 2026-11-25" and saved["format"] == 1
    summary = saved["summary"]
    assert summary["chart"] == "Houston" and summary["airports"] == 50 and summary["pixels"] == 50
    assert summary["strings"] == 1 and summary["board_in"] == [32, job["result"]["sheet"]["board"]["height_in"]]
    assert os.listdir(folder(client)) == [saved["id"] + ".jsonl"]
    listing = get(client, SAVES)[1]["saves"]
    assert [s["id"] for s in listing] == [saved["id"]] and listing[0]["summary"] == summary
    assert "result" not in listing[0] and "params" not in listing[0]  # a listing is light


def test_saving_changes_nothing_else(make):  # noqa: F811
    client = make()
    job = planned(client)
    before = codes(client)
    keep(client)
    assert progress(client)["id"] == job["id"] and codes(client) == before
    assert not [n for n in os.listdir(config_dir(client)) if "before-plan" in n]  # no backup made


@pytest.mark.parametrize(
    "name", ["", "   ", "../x", "a/b", "a\\b", "x" * 61, "tab\t", "new\nline", "nul\x00", None, 7, ["x"], {"a": 1}]
)
def test_a_bad_name_is_a_400(make, name):  # noqa: F811
    client = make()
    planned(client)
    status, body = offer(client, name)
    assert status == 400 and body["reason"] == "invalid" and body["error"]
    assert not os.path.isdir(folder(client)) or os.listdir(folder(client)) == []


def test_a_name_with_unicode_and_a_reserved_word_is_only_text(make):  # noqa: F811
    client = make()
    planned(client)
    for name in ("Zürich ✈ 2026", "CON", "nul", "..", "天气 plan"):
        assert keep(client, name)["name"] == name
    assert all(saves.ID.match(n[:-6]) for n in os.listdir(folder(client)))


def test_a_name_that_exists_is_refused_and_nothing_is_overwritten(make):  # noqa: F811
    client = make()
    planned(client)
    first = keep(client, "Houston")
    status, body = offer(client, "houston")
    assert status == 409 and body["reason"] == "exists"
    assert [s["id"] for s in get(client, SAVES)[1]["saves"]] == [first["id"]]


def test_the_count_is_capped_at_the_limit(make, monkeypatch):  # noqa: F811
    client = make()
    planned(client)
    monkeypatch.setattr(saves, "MAX_SAVES", 3)
    for i in range(3):
        keep(client, f"plan {i}")
    status, body = offer(client, "one more")
    assert status == 409 and body["reason"] == "full" and "3" in body["error"]


def test_a_plan_over_the_size_limit_is_refused(make, monkeypatch):  # noqa: F811
    client = make()
    planned(client)
    monkeypatch.setattr(saves, "MAX_BYTES", 5000)
    status, body = offer(client, "big")
    assert status == 409 and body["reason"] == "too_big"
    assert not os.path.isdir(folder(client)) or os.listdir(folder(client)) == []


def test_a_save_that_cannot_be_written_is_a_json_500(make, monkeypatch):  # noqa: F811
    client = make()
    planned(client)
    monkeypatch.setattr(saves.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("read-only")))
    status, body = offer(client, "x")
    assert status == 500 and body["reason"] == "failed"
    assert [n for n in os.listdir(folder(client))] == []  # no file and no temporary


def test_every_post_needs_a_json_object(make):  # noqa: F811
    client = make()
    planned(client)
    save = keep(client)
    paths = [SAVES, f"{SAVES}/{save['id']}/load", f"{SAVES}/{save['id']}/rename", f"{SAVES}/{save['id']}/delete"]
    for path in paths:
        for content_type in ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data"):
            status, body = raw(client, path, b"name=x", content_type)
            assert status == 400 and body["reason"] == "invalid", (path, content_type)
        assert raw(client, path, b"not json")[0] == 400
        assert raw(client, path, b"[1, 2]")[0] == 400
        assert raw(client, path, b"")[0] == 400
        status, body = raw(client, path, b'{"name": "' + b"x" * 200000 + b'"}')
        assert status == 413 and body["reason"] == "invalid", path
    assert [s["id"] for s in get(client, SAVES)[1]["saves"]] == [save["id"]]  # nothing changed


def test_the_routes_refuse_other_verbs(make):  # noqa: F811
    client = make()
    assert client(SAVES, method="DELETE")[0] in (404, 405)
    assert client(SAVES + "/20261125-120000-0123abcd/delete", method="GET")[0] in (404, 405)
    assert client(SAVES + "/20261125-120000-0123abcd/load", method="GET")[0] in (404, 405)


# ---- load -------------------------------------------------------------------------------------------------------


def test_load_shows_the_saved_plan_as_the_current_finished_job(make):  # noqa: F811
    client = make()
    first = planned(client, width_in=30)
    save = keep(client, "wide")
    planned(client, width_in=24)  # a different plan is current now
    status, body = post(client, f"{SAVES}/{save['id']}/load", {})
    assert status == 200 and body["ok"] is True
    job = body["job"]
    assert (
        job["done"] and job["ok"] is True and job["idle"] is False and job["cancelled"] is False and job["error"] == ""
    )
    assert job["result"] == first["result"] and job["params"]["width_in"] == 30
    assert job["message"] == first["result"]["message"] and job["elapsed"] == 0 and job["fraction"] == 1.0
    assert job["loaded"] == {"id": save["id"], "name": "wide", "saved_at": save["saved_at"]}
    assert progress(client) == {**job, "elapsed": 0}  # the page's own poll sees the same job
    assert job["id"] not in (first["id"],) and job["id"] > first["id"]


def test_a_second_load_gets_a_new_id_each_time(make):  # noqa: F811
    client = make()
    planned(client)
    save = keep(client)
    ids = {post(client, f"{SAVES}/{save['id']}/load", {})[1]["job"]["id"] for _ in range(3)}
    assert len(ids) == 3


def test_a_load_needs_no_download_and_no_planning(make):  # noqa: F811
    load = FakeLoad()
    client = make(load)
    run(client, source="recommended", start_fresh=True)
    save = keep(client)
    boxes = len(load.boxes)
    assert post(client, f"{SAVES}/{save['id']}/load", {})[0] == 200
    assert len(load.boxes) == boxes


def test_a_plan_started_after_a_load_replaces_it(make):  # noqa: F811
    client = make()
    planned(client)
    save = keep(client)
    post(client, f"{SAVES}/{save['id']}/load", {})
    job = planned(client)
    assert job["loaded"] is None and progress(client)["loaded"] is None


def test_load_is_refused_while_a_plan_runs_and_leaves_that_plan_alone(make):  # noqa: F811
    release = threading.Event()

    class Slow(FakeLoad):
        def __call__(self, box, clock=None, progress=None, **kwargs):
            if release.is_set() is False and getattr(self, "slow", False):
                release.wait(30)
            return super().__call__(box, clock=clock, progress=progress, **kwargs)

    slow = Slow()
    client = make(slow)
    planned(client)
    save = keep(client)
    slow.slow = True
    try:
        status, _ = client("/config/planner/plan", method="POST", body={"chart": "Houston", "source": "recommended"})
        assert status == 202
        running = progress(client)
        results = []

        def attempt():
            results.append(post(client, f"{SAVES}/{save['id']}/load", {}))

        threads = [threading.Thread(target=attempt) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert [(s, b["reason"]) for s, b in results] == [(409, "running")] * 6
        assert progress(client)["id"] == running["id"] and progress(client)["done"] is False
        assert client.planner.job["loaded"] is None
    finally:
        release.set()
        wait(client)


def test_a_cancel_that_is_still_ending_counts_as_running(make):  # noqa: F811
    client = make()
    planned(client)
    save = keep(client)
    client.planner.job["done"] = False  # a plan that has been cancelled but has not stopped yet
    status, body = post(client, f"{SAVES}/{save['id']}/load", {})
    assert status == 409 and body["reason"] == "running"
    client.planner.job["done"] = True


def test_loading_an_unknown_or_bad_id_is_a_404(make):  # noqa: F811
    client = make()
    for plan_id in ("20261125-120000-0123abcd", "x", "..", "20261125-120000-0123abcg", "%2e%2e", "a b"):
        status, body = post(client, f"{SAVES}/{plan_id}/load", {})
        assert status == 404 and body["reason"] == "not_found", plan_id
    assert client(SAVES + "/../../config.json/load", method="POST", body={})[0] == 404


def edit_file(client, save, change):
    """Changes a saved file the way a hand-edit would: change(header, body) -> (header, body) or raw bytes."""
    path = os.path.join(folder(client), save["id"] + ".jsonl")
    with open(path) as f:
        head, body = f.read().splitlines()
    out = change(json.loads(head), json.loads(body))
    with open(path, "wb") as f:
        f.write(out if isinstance(out, bytes) else (json.dumps(out[0]) + "\n" + json.dumps(out[1]) + "\n").encode())


def test_a_hand_edited_or_damaged_file_is_a_clear_409_never_a_crash(make):  # noqa: F811
    client = make()
    first = planned(client)
    before = progress(client)

    def without(*keys, in_sheet=False):
        def change(h, b):
            target = b["result"]["sheet"] if in_sheet else b["result"]
            for key in keys:
                del target[key]
            return h, b

        return change

    def setkey(where, key, value):
        def change(h, b):
            (b[where] if where else b["result"])[key] = value
            return h, b

        return change

    cases = {
        "no sheet": without("sheet"),
        "no pixels": without("pixels", in_sheet=True),
        "no power": without("power", in_sheet=True),
        "no names": without("names"),
        "no message": without("message"),
        "airports not a list": setkey("result", "airports", 5),
        "airports and pixels differ": setkey("result", "airports", []),
        "pixels not dicts": lambda h, b: (
            h,
            {**b, "result": {**b["result"], "sheet": {**b["result"]["sheet"], "pixels": [1] * 50}}},
        ),
        "strings not a number": lambda h, b: (
            h,
            {**b, "result": {**b["result"], "sheet": {**b["result"]["sheet"], "shopping": {"strings": "1"}}}},
        ),
        "result a list": lambda h, b: (h, {**b, "result": []}),
        "params: bad chart": setkey("params", "chart", "Atlantis"),
        "params: a number out of range": setkey("params", "pitch", 5),
        "params a list": lambda h, b: (h, {**b, "params": [1]}),
        "cut short": lambda h, b: json.dumps(h).encode() + b'\n{"params": {"chart": "Hou',
        "empty": lambda h, b: b"",
        "binary": lambda h, b: b"\xff\xfe\x00\x01",
    }
    for label, change in cases.items():
        save = keep(client, label)
        edit_file(client, save, change)
        status, body = post(client, f"{SAVES}/{save['id']}/load", {})
        assert status == 409 and body["reason"] == "unreadable" and body["error"], label
        post(client, f"{SAVES}/{save['id']}/delete", {})
    after = progress(client)
    assert after == before and after["id"] == first["id"]  # a refused load changes nothing


def test_a_plan_saved_by_another_format_says_so(make):  # noqa: F811
    client = make()
    planned(client)
    save = keep(client)
    edit_file(client, save, lambda h, b: ({**h, "format": 2}, b))
    status, body = post(client, f"{SAVES}/{save['id']}/load", {})
    assert status == 409 and body["reason"] == "format" and "different version" in body["error"]
    assert get(client, SAVES)[1]["saves"][0]["format"] == 2  # still listed: it can be deleted
    assert post(client, f"{SAVES}/{save['id']}/delete", {})[0] == 200


def test_a_file_copied_in_under_another_id_is_ignored(make):  # noqa: F811
    client = make()
    planned(client)
    save = keep(client)
    src = os.path.join(folder(client), save["id"] + ".jsonl")
    copy = os.path.join(folder(client), "20200101-000000-deadbeef.jsonl")
    with open(src, "rb") as f, open(copy, "wb") as g:
        g.write(f.read())
    assert [s["id"] for s in get(client, SAVES)[1]["saves"]] == [save["id"]]
    assert post(client, f"{SAVES}/20200101-000000-deadbeef/load", {})[1]["reason"] == "unreadable"


# ---- a loaded plan through preview, apply and undo -------------------------------------------------------------


def test_a_loaded_plan_goes_through_preview_apply_backup_and_undo(make):  # noqa: F811
    client = make()
    job = planned(client)
    wanted = [p["code"] or "" for p in job["result"]["sheet"]["pixels"]]
    save = keep(client)
    config = client.services.config
    config.apply_plan(list(reversed(config.airports[:50])), 50, 0, backup=False)  # the Chart's order changed
    reversed_codes = codes(client)
    assert reversed_codes != wanted
    planned(client, width_in=20)  # another plan is current, then the saved one is loaded
    loaded = post(client, f"{SAVES}/{save['id']}/load", {})[1]["job"]
    status, preview = get(client, PREVIEW)
    assert status == 200 and preview["job"] == loaded["id"] and preview["summary"]["unchanged"] is False
    status, applied = post(client, APPLY, {"token": preview["token"]})
    assert status == 200 and applied["ok"] is True
    assert codes(client) == wanted
    assert applied["backup"] in os.listdir(config_dir(client))
    status, info = get(client, "/config/planner/apply/status")
    assert info["undo"]["available"] is True and info["undo"]["backup"] == applied["backup"]
    status, undone = post(client, UNDO, {"backup": applied["backup"]})
    assert status == 200 and undone["ok"] is True
    assert codes(client) == reversed_codes
    assert [s["id"] for s in get(client, SAVES)[1]["saves"]] == [save["id"]]  # the saved file is untouched


def test_a_loaded_plan_applies_the_airports_of_the_saved_plan(make):  # noqa: F811
    client = make()
    job = planned(client)
    wanted = [p["code"] or "" for p in job["result"]["sheet"]["pixels"]]
    save = keep(client)
    config = client.services.config
    swapped = list(config.airports[:50])
    config.apply_plan(list(reversed(swapped)), 50, 0, backup=False)  # the Chart's order changed since
    assert codes(client) != wanted
    post(client, f"{SAVES}/{save['id']}/load", {})
    status, preview = get(client, PREVIEW)
    assert status == 200 and preview["summary"]["unchanged"] is False
    assert post(client, APPLY, {"token": preview["token"]})[0] == 200
    assert codes(client) == wanted


def test_the_token_of_a_preview_is_stale_after_a_load(make):  # noqa: F811
    client = make()
    planned(client)
    save = keep(client)
    client.services.config.apply_plan(list(reversed(client.services.config.airports[:50])), 50, 0, backup=False)
    post(client, f"{SAVES}/{save['id']}/load", {})
    first = get(client, PREVIEW)[1]
    post(client, f"{SAVES}/{save['id']}/load", {})  # loaded again: a new job
    status, body = post(client, APPLY, {"token": first["token"]})
    assert status == 409 and body["reason"] == "stale"
    assert get(client, PREVIEW)[1]["token"] != first["token"]


def test_a_loaded_plan_is_stale_when_the_chart_changes_after_its_preview(make):  # noqa: F811
    client = make()
    planned(client)
    save = keep(client)
    client.services.config.apply_plan(list(reversed(client.services.config.airports[:50])), 50, 0, backup=False)
    post(client, f"{SAVES}/{save['id']}/load", {})
    token = get(client, PREVIEW)[1]["token"]
    client.services.config.set_airport(3, "name", "Changed since the preview")
    status, body = post(client, APPLY, {"token": token})
    assert status == 409 and body["reason"] == "stale"
    assert codes(client)[3] != ""  # nothing was written over the change
    assert client.services.config.airports[3].name == "Changed since the preview"


def test_a_load_while_an_apply_preview_is_open_makes_that_token_stale(make):  # noqa: F811
    client = make()
    planned(client)
    save = keep(client)
    client.services.config.apply_plan(list(reversed(client.services.config.airports[:50])), 50, 0, backup=False)
    planned(client)
    token = get(client, PREVIEW)[1]["token"]  # a preview of the fresh plan
    post(client, f"{SAVES}/{save['id']}/load", {})  # then a different plan becomes current
    assert post(client, APPLY, {"token": token})[1]["reason"] == "stale"


def test_a_saved_plan_for_the_chart_as_it_is_says_unchanged(make):  # noqa: F811
    client = make()
    planned(client)
    save = keep(client)
    config = client.services.config
    config.apply_plan(list(reversed(config.airports[:50])), 50, 0, backup=False)
    post(client, f"{SAVES}/{save['id']}/load", {})  # apply it, then load it again: the Chart already has it
    assert post(client, APPLY, {"token": get(client, PREVIEW)[1]["token"]})[0] == 200
    post(client, f"{SAVES}/{save['id']}/load", {})
    status, body = get(client, PREVIEW)
    assert status == 200 and body["summary"]["unchanged"] is True
    assert post(client, APPLY, {"token": body["token"]})[1]["reason"] == "unchanged"


def test_a_plan_with_a_code_twice_is_refused_at_preview_without_a_traceback(make, caplog):  # noqa: F811
    client = make()
    planned(client)
    save = keep(client)

    def twice(h, b):
        pixels = b["result"]["sheet"]["pixels"]
        pixels[1]["code"] = pixels[0]["code"]
        b["result"]["airports"][1]["code"] = pixels[0]["code"]
        return h, b

    edit_file(client, save, twice)
    assert post(client, f"{SAVES}/{save['id']}/load", {})[0] == 200
    status, body = get(client, PREVIEW)
    assert status == 409 and body["reason"] == "failed"
    records = [r for r in caplog.records if "cannot be applied" in r.getMessage()]
    assert records and all(r.exc_info is None for r in records)  # a warning, not log.exception


@pytest.mark.parametrize("strings", [0, -1, 20000, 1000000, 10**25, True, 1.5, "1", None])
def test_the_number_of_strings_is_bounded_before_anything_is_built(make, strings):  # noqa: F811
    client = make()
    planned(client)  # 50 pixels in strings of 50
    save = keep(client)
    edit_file(client, save, lambda h, b: (h, _set_strings(b, strings)))
    before = client.planner.job["id"]
    status, body = post(client, f"{SAVES}/{save['id']}/load", {})
    assert status == 409 and body["reason"] == "unreadable", strings
    assert client.planner.job["id"] == before


def _set_strings(body, strings):
    body["result"]["sheet"]["shopping"]["strings"] = strings
    return body


def test_strings_that_hold_the_pixels_load(make):  # noqa: F811
    client = make()
    planned(client)
    save = keep(client)
    edit_file(client, save, lambda h, b: (h, {**b, "params": {**b["params"], "string_len": 25}}))  # 1 x 25 < 50
    assert post(client, f"{SAVES}/{save['id']}/load", {})[1]["reason"] == "unreadable"
    edit_file(
        client,
        save,
        lambda h, b: (
            h,
            {
                **b,
                "params": {**b["params"], "string_len": 25},
                "result": _set_strings(b["result"] and {"result": b["result"]}, 2)["result"],
            },
        ),
    )
    assert post(client, f"{SAVES}/{save['id']}/load", {})[0] == 200  # 2 x 25 = 50 pixels


def test_the_strings_limit_is_the_chart_limit(make):  # noqa: F811
    client = make()
    planned(client)
    save = keep(client)
    # 1001 pixels' worth of strings is over the Chart's 1000
    edit_file(
        client,
        save,
        lambda h, b: (
            h,
            {
                **b,
                "params": {**b["params"], "string_len": 1000},
                "result": _set_strings({"result": b["result"]}, 2)["result"],
            },
        ),
    )
    assert post(client, f"{SAVES}/{save['id']}/load", {})[1]["reason"] == "unreadable"


def _mutate(path_keys, value):
    def change(h, b):
        target = b["result"]
        for key in path_keys[:-1]:
            target = target[key]
        target[path_keys[-1]] = value
        return h, b

    return change


@pytest.mark.parametrize(
    "path, value",
    [
        (["sheet", "board"], []),
        (["sheet", "board"], "wide"),
        (["sheet", "pixels"], "none"),
        (["sheet", "route"], {}),
        (["sheet", "route"], [5]),
        (["sheet", "cuts"], [{"between": "x"}]),
        (["sheet", "problems"], []),
        (["sheet", "problems", "crowded"], ["KHOU"]),
        (["sheet", "power", "feed_points"], ["a"]),
        (["sheet", "power", "notes"], [1]),
        (["sheet", "strings"], [None]),
        (["sheet", "start"], "KHOU"),
        (["sheet", "joins"], [1]),
        (["names"], {"KHOU": 5}),
        (["names"], []),
        (["notes"], [1]),
        (["notes"], "text"),
        (["left_out"], [{"code": "K"}]),
        (["left_out"], ["KHOU"]),
        (["airports"], [{"code": 5}]),
        (["chart", "outline"], [1, 2]),
        (["chart", "outline"], [["a", "b"]]),
        (["chart", "bounds"], {"south": "x"}),
        (["chart", "name"], 5),
        (["chart"], "Houston"),
        (["sizes"], {"best": 3}),
        (["message"], 5),
        (["stale"], "yes"),
    ],
)
def test_the_types_of_a_saved_result_are_checked(make, path, value):  # noqa: F811
    client = make()
    planned(client, suggest_sizes=True)
    save = keep(client)
    edit_file(client, save, _mutate(path, value))
    before = client.planner.job["id"]
    status, body = post(client, f"{SAVES}/{save['id']}/load", {})
    assert status == 409 and body["reason"] == "unreadable", (path, value)
    assert client.planner.job["id"] == before and client.planner.job["loaded"] is None


def test_a_number_in_a_saved_result_must_be_finite_and_not_a_bool(make):  # noqa: F811
    client = make()
    planned(client)
    save = keep(client)
    for value in (True, "5", None):
        edit_file(client, save, _mutate(["sheet", "board", "width_mm"], value))
        assert post(client, f"{SAVES}/{save['id']}/load", {})[1]["reason"] == "unreadable", value
    path = os.path.join(folder(client), save["id"] + ".jsonl")
    with open(path) as f:
        text = f.read()
    assert re.search(r'"width_mm": ?[^,}]+', text)
    with open(path, "w") as f:
        f.write(re.sub(r'"width_mm": ?[^,}]+', '"width_mm": 1e999', text, count=1))
    assert post(client, f"{SAVES}/{save['id']}/load", {})[1]["reason"] == "unreadable"


def test_real_plans_of_every_kind_pass_the_shape_check(make):  # noqa: F811
    """The check must accept what the planner makes: skips, the sizes, a pasted list, several strings, the wall."""
    client = make()
    kinds = [
        dict(source="current", suggest_sizes=True),
        dict(source="current", allow_skips=True, string_len=20),
        dict(source="paste", codes="KHOU KIAH KDWH"),
        dict(source="recommended", start_fresh=True, target=60, strings=2, string_len=30),
        dict(source="current", chart="US Wall Planning", width_in=100),
    ]
    for i, values in enumerate(kinds):
        job = run(client, **{**dict(suggest_sizes=False), **values}) if values.get("chart") else None
        if job is None:
            status, _ = client(
                "/config/planner/plan", method="POST", body={"chart": "Houston", "suggest_sizes": False, **values}
            )
            assert status == 202
            job = wait(client)
        assert job["ok"], (values, job["error"])
        status, body = offer(client, f"kind {i}")
        assert status == 201, body
        assert post(client, f"{SAVES}/{body['save']['id']}/load", {})[0] == 200, values


# ---- the plan on the page --------------------------------------------------------------------------------------


def test_a_save_needs_the_number_of_the_plan_on_the_page(make):  # noqa: F811
    client = make()
    planned(client)
    for body in (
        {"name": "x"},
        {"name": "x", "job": None},
        {"name": "x", "job": "1"},
        {"name": "x", "job": True},
        {"name": "x", "job": 1.5},
        {"name": "x", "job": [1]},
    ):
        status, answer = post(client, SAVES, body)
        assert status == 400 and answer["reason"] == "invalid", body
    assert get(client, SAVES)[1]["saves"] == []


def test_a_save_of_a_plan_that_is_not_the_current_one_is_stale(make):  # noqa: F811
    client = make()
    first = planned(client)  # tab A shows this plan
    other = keep(client, "other")
    post(client, f"{SAVES}/{other['id']}/load", {})  # tab B loads a plan: the current job is a new one
    status, body = offer(client, "from tab A", job=first["id"])
    assert status == 409 and body["reason"] == "stale" and "current plan" in body["error"]
    assert [s["name"] for s in get(client, SAVES)[1]["saves"]] == ["other"]
    planned(client)  # tab B plans something else
    assert offer(client, "again", job=first["id"])[1]["reason"] == "stale"
    assert offer(client, "right", job=client.planner.job["id"])[0] == 201


def test_a_save_while_nothing_is_current_says_nothing(make):  # noqa: F811
    client = make()
    status, body = post(client, SAVES, {"name": "x", "job": 1})
    assert status == 409 and body["reason"] == "nothing"


def test_renaming_the_loaded_plan_renames_its_banner(make):  # noqa: F811
    client = make()
    planned(client)
    save = keep(client, "old")
    post(client, f"{SAVES}/{save['id']}/load", {})
    post(client, f"{SAVES}/{save['id']}/rename", {"name": "new"})
    assert progress(client)["loaded"] == {"id": save["id"], "name": "new", "saved_at": save["saved_at"]}
    other = keep(client, "other")
    post(client, f"{SAVES}/{other['id']}/rename", {"name": "other 2"})
    assert progress(client)["loaded"]["name"] == "new"  # another plan's rename does not touch it


def test_an_answer_that_cannot_be_json_is_a_json_500(make, monkeypatch):  # noqa: F811
    client = make()
    monkeypatch.setattr(planner_web.Applier, "status", lambda self: (200, {"x": object()}))
    status, body = client("/config/planner/apply/status")
    assert status == 500 and json.loads(body)["reason"] == "failed"
