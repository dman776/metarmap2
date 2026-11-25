"""
Tests for the Chart Planner's saved plans (web.planner_saves): save, list, load, rename and delete over the routes, what
a Load does to the planner's current job and to Apply and Undo, the refusals, and files that are damaged or edited.
The airport fetch is a fake: no network.
"""

import io
import json
import os
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


def folder(client):
    return os.path.join(config_dir(client), saves.FOLDER)


def keep(client, name="Houston 2026-11-25"):
    status, body = post(client, SAVES, {"name": name})
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
    status, body = post(client, SAVES, {"name": "x"})
    assert status == 409 and body["reason"] == "nothing" and body["error"]
    run(client, source="recommended", start_fresh=True)  # fails: no airports
    assert post(client, SAVES, {"name": "x"})[1]["reason"] == "nothing"
    client.planner.job.update(ok=True, result={"message": "m"}, cancelled=True)
    assert post(client, SAVES, {"name": "x"})[1]["reason"] == "nothing"
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
        status, body = post(client, SAVES, {"name": "x"})
        assert status == 409 and body["reason"] == "running"
    finally:
        release.set()
        wait(client)


def test_save_keeps_the_plan_and_its_settings_in_a_file_beside_config_json(make):  # noqa: F811
    client = make()
    job = planned(client)
    status, body = post(client, SAVES, {"name": "  Houston   2026-11-25 "})
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
    status, body = post(client, SAVES, {"name": name})
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
    status, body = post(client, SAVES, {"name": "houston"})
    assert status == 409 and body["reason"] == "exists"
    assert [s["id"] for s in get(client, SAVES)[1]["saves"]] == [first["id"]]


def test_the_count_is_capped_at_the_limit(make, monkeypatch):  # noqa: F811
    client = make()
    planned(client)
    monkeypatch.setattr(saves, "MAX_SAVES", 3)
    for i in range(3):
        keep(client, f"plan {i}")
    status, body = post(client, SAVES, {"name": "one more"})
    assert status == 409 and body["reason"] == "full" and "3" in body["error"]


def test_a_plan_over_the_size_limit_is_refused(make, monkeypatch):  # noqa: F811
    client = make()
    planned(client)
    monkeypatch.setattr(saves, "MAX_BYTES", 5000)
    status, body = post(client, SAVES, {"name": "big"})
    assert status == 409 and body["reason"] == "too_big"
    assert not os.path.isdir(folder(client)) or os.listdir(folder(client)) == []


def test_a_save_that_cannot_be_written_is_a_json_500(make, monkeypatch):  # noqa: F811
    client = make()
    planned(client)
    monkeypatch.setattr(saves.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("read-only")))
    status, body = post(client, SAVES, {"name": "x"})
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


def test_a_plan_that_does_not_fit_its_strip_is_refused_at_preview_not_load(make):  # noqa: F811
    client = make()
    planned(client)
    save = keep(client)
    edit_file(client, save, lambda h, b: (h, {**b, "params": {**b["params"], "string_len": 10}}))  # 50 pixels, 10 x 1
    assert post(client, f"{SAVES}/{save['id']}/load", {})[0] == 200
    status, body = get(client, PREVIEW)
    assert status == 409 and body["reason"] == "failed"


def test_a_loaded_plan_can_be_saved_again_under_a_new_name(make):  # noqa: F811
    client = make()
    planned(client)
    save = keep(client, "original")
    post(client, f"{SAVES}/{save['id']}/load", {})
    again = keep(client, "copy")
    assert again["id"] != save["id"] and again["summary"] == save["summary"]
    loaded = post(client, f"{SAVES}/{again['id']}/load", {})[1]["job"]
    assert loaded["loaded"]["name"] == "copy"


# ---- rename and delete ------------------------------------------------------------------------------------------


def test_rename(make):  # noqa: F811
    client = make()
    planned(client)
    save = keep(client, "old")
    status, body = post(client, f"{SAVES}/{save['id']}/rename", {"name": " new  name "})
    assert status == 200 and body["save"]["name"] == "new name" and body["save"]["id"] == save["id"]
    assert [s["name"] for s in get(client, SAVES)[1]["saves"]] == ["new name"]
    loaded = post(client, f"{SAVES}/{save['id']}/load", {})[1]["job"]
    assert loaded["loaded"]["name"] == "new name"


def test_rename_refusals(make):  # noqa: F811
    client = make()
    planned(client)
    one, two = keep(client, "one"), keep(client, "two")
    status, body = post(client, f"{SAVES}/{one['id']}/rename", {"name": "Two"})
    assert status == 409 and body["reason"] == "exists"
    for bad in ("", "a/b", "../x", "x" * 61, None, 3):
        status, body = post(client, f"{SAVES}/{one['id']}/rename", {"name": bad})
        assert status == 400 and body["reason"] == "invalid", bad
    status, body = post(client, f"{SAVES}/20261125-120000-0123abcd/rename", {"name": "fresh"})
    assert status == 404 and body["reason"] == "not_found"
    assert post(client, f"{SAVES}/{two['id']}/rename", {})[0] == 400  # no name at all
    assert {s["name"] for s in get(client, SAVES)[1]["saves"]} == {"one", "two"}


def test_delete(make):  # noqa: F811
    client = make()
    planned(client)
    one, two = keep(client, "one"), keep(client, "two")
    status, body = post(client, f"{SAVES}/{one['id']}/delete", {})
    assert status == 200 and body == {"ok": True}
    assert [s["id"] for s in get(client, SAVES)[1]["saves"]] == [two["id"]]
    assert os.listdir(folder(client)) == [two["id"] + ".jsonl"]
    status, body = post(client, f"{SAVES}/{one['id']}/delete", {})
    assert status == 404 and body["reason"] == "not_found"
    assert post(client, f"{SAVES}/{one['id']}/load", {})[0] == 404


def test_deleting_the_loaded_plan_keeps_the_job_on_the_page(make):  # noqa: F811
    client = make()
    planned(client)
    save = keep(client)
    loaded = post(client, f"{SAVES}/{save['id']}/load", {})[1]["job"]
    post(client, f"{SAVES}/{save['id']}/delete", {})
    assert progress(client)["id"] == loaded["id"]
    assert get(client, PREVIEW)[0] == 200  # the plan in memory still applies


# ---- restart and threads ----------------------------------------------------------------------------------------


def test_saved_plans_survive_a_restart(make):  # noqa: F811
    client = make()
    first = planned(client)
    save = keep(client, "survives")
    other = reopen(client)
    assert progress(other)["idle"] is True  # the new Planner has no job
    assert [s["name"] for s in get(other, SAVES)[1]["saves"]] == ["survives"]
    status, body = post(other, f"{SAVES}/{save['id']}/load", {})
    assert status == 200 and body["job"]["result"] == first["result"] and body["job"]["id"] == 1
    status, preview = get(other, PREVIEW)
    assert status == 200 and preview["job"] == 1


def test_parallel_saves_of_one_name_make_one_file(make):  # noqa: F811
    client = make()
    planned(client)
    results = []

    def attempt():
        results.append(post(client, SAVES, {"name": "same"})[0])

    threads = [threading.Thread(target=attempt) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [201] + [409] * 9
    assert len(os.listdir(folder(client))) == 1


def test_parallel_loads_and_a_new_plan_leave_one_consistent_job(make):  # noqa: F811
    client = make()
    planned(client)
    save = keep(client)
    outcomes = []

    def load():
        outcomes.append(post(client, f"{SAVES}/{save['id']}/load", {})[0])

    def start():
        outcomes.append(
            client("/config/planner/plan", method="POST", body={"chart": "Houston", "suggest_sizes": False})[0]
        )

    threads = [threading.Thread(target=load) for _ in range(4)] + [threading.Thread(target=start)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    final = wait(client)
    assert set(outcomes) <= {200, 202, 409}
    job = progress(client)
    assert job["done"] and job["ok"] is True and job["id"] == final["id"]
    assert job["loaded"] is None or job["loaded"]["id"] == save["id"]
