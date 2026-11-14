"""
Tests for the Chart Planner's Apply routes (web.planner.Applier): the preview and its token, applying the plan the
server holds, the backup, the refusals (nothing planned, still running, changed since the preview), and the Undo.
"""

import base64
import io
import json
import logging
import os
import re
import threading
from pathlib import Path

import pytest
from test_web import AUTH, Client
from test_web_planner import FakeLoad, run, spot, wait

from metarmap.config import MAX_LEDS, PLAN_BACKUPS
from metarmap.settings import Airport
from metarmap.web import create_app
from metarmap.web import planner as planner_web

PREVIEW = "/config/planner/apply/preview"
APPLY = "/config/planner/apply"
STATUS = "/config/planner/apply/status"
UNDO = "/config/planner/undo"


@pytest.fixture
def make(make_app, monkeypatch):
    """make(load=FakeLoad()) -> a client for a map whose airports all have a position on the Houston chart."""

    def build(load=None, **settings):
        services = make_app(**settings)
        codes = [a.code for a in services.config.airports if a.code]
        for k, code in enumerate(codes):
            lat, lon = spot(k, len(codes))
            services.metars.positions[code] = {"lat": lat, "lon": lon, "name": f"Name of {code}"}
        monkeypatch.setattr(services.metars, "_look_up", lambda codes, timeout=30: True)
        planner = planner_web.Planner(services, load=load or FakeLoad())
        client = Client(create_app(services, ip="10.0.0.2", planner=planner))
        client.services, client.planner = services, planner
        return client

    return build


def post(client, path, body):
    status, text = client(path, method="POST", body=body)
    return status, json.loads(text)


def get(client, path):
    status, text = client(path)
    return status, json.loads(text)


def raw_post(client, path, data):
    """POSTs bytes as they are (a body that is not JSON): the Client always encodes its body."""
    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "SERVER_NAME": "test",
        "SERVER_PORT": "80",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.url_scheme": "http",
        "wsgi.input": io.BytesIO(data),
        "wsgi.errors": io.StringIO(),
        "CONTENT_LENGTH": str(len(data)),
        "CONTENT_TYPE": "application/json",
        "HTTP_AUTHORIZATION": AUTH,
    }
    out = []
    body = b"".join(client.app(environ, lambda status, headers, exc_info=None: out.append(status)))
    return int(out[0].split()[0]), json.loads(body)


def codes(client, strip_only=True):
    config = client.services.config
    airports = config.airports[: config.data.led.count] if strip_only else config.airports
    return [a.code for a in airports]


def planned(client, **values):
    """Runs a plan of the Chart's own airports; returns the finished job."""
    job = run(client, source="current", **values)
    assert job["ok"], job
    return job


def plan_codes(job):
    return [p["code"] or "" for p in job["result"]["sheet"]["pixels"]]


def config_dir(client):
    return os.path.dirname(os.path.abspath(client.services.config._file))


def backups(client):
    return sorted(n for n in os.listdir(config_dir(client)) if re.search(r"before-plan-\d{8}-\d{6}$", n))


# ---- who may and what is there to apply -------------------------------------------------------------------------


def test_the_apply_routes_need_a_login(make):
    client = make()
    for path, method in [(PREVIEW, "GET"), (APPLY, "POST"), (STATUS, "GET"), (UNDO, "POST")]:
        assert client(path, method=method, auth=False)[0] == 401, path


def test_nothing_planned_yet(make):
    client = make()
    status, body = get(client, PREVIEW)
    assert status == 409 and body["reason"] == "no_result" and body["error"]
    assert post(client, APPLY, {"token": "x" * 64})[0] == 409


def test_a_plan_that_is_still_running_cannot_be_applied(make):
    release = threading.Event()

    class Slow(FakeLoad):
        def __call__(self, box, clock=None, progress=None, **kwargs):
            release.wait(30)
            return super().__call__(box, clock=clock, progress=progress, **kwargs)

    client = make(Slow())
    try:
        status, _ = client(
            "/config/planner/plan",
            method="POST",
            body={"chart": "Houston", "suggest_sizes": False, "source": "recommended", "start_fresh": True},
        )
        assert status == 202
        status, body = get(client, PREVIEW)
        assert status == 409 and body["reason"] == "running"
        assert post(client, APPLY, {"token": "x" * 64})[1]["reason"] == "running"
    finally:
        release.set()
        wait(client)


def test_a_cancelled_or_failed_plan_cannot_be_applied(make):
    client = make(FakeLoad(airports=[], error="no network"))
    job = run(client, source="recommended", start_fresh=True)
    assert job["ok"] is False
    assert get(client, PREVIEW)[1]["reason"] == "failed"
    client.planner.job["cancelled"] = True
    assert get(client, PREVIEW)[1]["reason"] == "cancelled"


# ---- the preview ------------------------------------------------------------------------------------------------


def test_the_preview_says_what_would_change(make):
    client = make()
    job = planned(client)
    status, body = get(client, PREVIEW)
    assert status == 200 and body["ok"] is True and body["job"] == job["id"]
    assert re.fullmatch(r"[0-9a-f]{64}", body["token"])
    assert re.fullmatch(r"config\.json\.before-plan-\d{8}-\d{6}", body["backup"])
    s = body["summary"]
    assert s["kept"] + s["moved"] == 50 and s["added"] == [] and s["over_limit"] is False
    assert s["led_count"] == {"from": 50, "to": 50} and s["airports_total"] == 50
    assert "LED 1 is" in s["wiring_note"]
    assert backups(client) == [] and codes(client) == plan_codes_before(client)  # a preview changes nothing


def plan_codes_before(client):
    return [a.code for a in client.services.config.airports[:50]]


def test_the_token_changes_when_the_chart_does(make):
    client = make()
    planned(client)
    first = get(client, PREVIEW)[1]["token"]
    assert get(client, PREVIEW)[1]["token"] == first
    client.services.config.set_airport(0, "name", "Renamed Field")
    assert get(client, PREVIEW)[1]["token"] != first


def test_the_preview_refuses_a_chart_that_would_have_too_many_airports(make):
    client = make()
    config = client.services.config
    strip = list(config.airports[:50])
    config.apply_plan(strip + [Airport(code=f"V{i:03d}") for i in range(940)], 50, 940, backup=False)
    job = planned(client, string_len=100)  # 100 LEDs and the 940 virtual airports are 1,040
    assert job["result"]["sheet"]["shopping"]["strings"] == 1
    status, body = get(client, PREVIEW)
    assert status == 409 and body["reason"] == "over_limit" and str(MAX_LEDS) in body["error"]


# ---- applying ---------------------------------------------------------------------------------------------------


def test_apply_puts_the_plan_into_the_airports_with_a_backup(make):
    client = make()
    job = planned(client)
    before = Path(client.services.config._file).read_text()
    token = get(client, PREVIEW)[1]["token"]
    status, body = post(client, APPLY, {"token": token})
    assert status == 200 and body["ok"] is True and body["restart_needed"] is False
    assert codes(client) == plan_codes(job)
    (name,) = backups(client)
    assert body["backup"] == name
    assert (Path(config_dir(client)) / name).read_text() == before
    assert body["summary"]["airports_total"] == 50


def test_apply_makes_the_strip_the_size_of_the_plan(make):
    client = make()
    planned(client, string_len=60)
    token = get(client, PREVIEW)[1]["token"]
    status, body = post(client, APPLY, {"token": token})
    assert status == 200
    assert body["restart_needed"] is False  # the in-memory strip followed the new count at once
    config = client.services.config
    assert config.data.led.count == 60 and len(config.airports) == 60
    assert [a.code for a in config.airports[50:]] == [""] * 10  # the spare LEDs have no airport


def test_a_strip_that_cannot_change_length_needs_a_restart_until_it_is_back_to_what_it_runs(make, monkeypatch):
    """A NeoPixel strip keeps its length until a restart: restart_needed is the new count against the pixels the strip
    runs with (the Airports page's banner), so an Undo back to the count it started with needs none."""
    client = make()
    monkeypatch.setattr(client.services.renderer, "resize", lambda count: False)  # what NeoPixel answers
    assert len(client.services.renderer.pixels()) == 50
    planned(client, string_len=60)
    status, body = post(client, APPLY, {"token": get(client, PREVIEW)[1]["token"]})
    assert status == 200 and body["restart_needed"] is True  # 60 pixels planned, 50 on the strip
    backup = get(client, STATUS)[1]["undo"]["backup"]
    status, body = post(client, UNDO, {"backup": backup})
    assert status == 200 and body["restored"]["led_count"] == 50
    assert body["restart_needed"] is False  # back to the 50 the strip is running: nothing to restart for


def test_a_plan_of_the_same_size_never_needs_a_restart(make, monkeypatch):
    client = make()
    monkeypatch.setattr(client.services.renderer, "resize", lambda count: False)
    planned(client)
    status, body = post(client, APPLY, {"token": get(client, PREVIEW)[1]["token"]})
    assert status == 200 and body["restart_needed"] is False


def test_the_airports_a_plan_drops_become_virtual(make):
    client = make()
    first = client.services.config.airports[0].code
    job = run(client, source="paste", codes=[a.code for a in client.services.config.airports[1:21]])
    assert job["ok"]
    token = get(client, PREVIEW)[1]["token"]
    assert post(client, APPLY, {"token": token})[0] == 200
    config = client.services.config
    assert config.data.led.count == 50 and config.data.led.virtual_count == 30
    assert first in [a.code for a in config.airports[50:]]  # dropped, not deleted


def test_one_publish_for_the_whole_apply(make):
    client = make()
    planned(client)
    heard = []
    client.services.config.subscribe("*", heard.append)
    summary = get(client, PREVIEW)[1]["summary"]
    post(client, APPLY, {"token": get(client, PREVIEW)[1]["token"]})
    assert summary["moved"] > 0  # this plan reorders the airports, so there is something to publish
    assert len(heard) == 1 and "airports.order" in heard[0]  # the OLED, the strip and the METAR fetch follow once


def test_a_token_is_used_once(make):
    client = make()
    planned(client)
    token = get(client, PREVIEW)[1]["token"]
    assert post(client, APPLY, {"token": token})[0] == 200
    status, body = post(client, APPLY, {"token": token})
    assert status == 409 and body["reason"] == "stale"
    assert len(backups(client)) == 1


def test_a_change_after_the_preview_is_not_overwritten(make):
    client = make()
    planned(client)
    token = get(client, PREVIEW)[1]["token"]
    client.services.config.set_airport(3, "name", "Renamed Field")
    before = Path(client.services.config._file).read_text()
    status, body = post(client, APPLY, {"token": token})
    assert status == 409 and body["reason"] == "stale"
    assert Path(client.services.config._file).read_text() == before and backups(client) == []


def test_a_new_plan_after_the_preview_makes_the_token_stale(make):
    client = make()
    planned(client)
    token = get(client, PREVIEW)[1]["token"]
    planned(client)
    assert post(client, APPLY, {"token": token})[1]["reason"] == "stale"


def test_a_wrong_token_is_refused(make):
    client = make()
    planned(client)
    status, body = post(client, APPLY, {"token": "0" * 64})
    assert status == 409 and body["reason"] == "stale" and backups(client) == []


def test_apply_never_takes_a_list_from_the_browser(make):
    client = make()
    job = planned(client)
    token = get(client, PREVIEW)[1]["token"]
    status, _ = post(client, APPLY, {"token": token, "airports": [{"code": "KEVIL"}], "led_count": 5})
    assert status == 200 and codes(client) == plan_codes(job)


def test_a_failing_save_changes_nothing_and_answers_json(make, monkeypatch):
    client = make()
    planned(client)
    token = get(client, PREVIEW)[1]["token"]
    before = codes(client)

    def broken(*args, **kwargs):
        raise OSError("read-only")

    monkeypatch.setattr("metarmap.config.shutil.copyfileobj", broken)
    status, body = post(client, APPLY, {"token": token})
    assert status == 500 and body["reason"] == "failed" and "nothing changed" in body["error"]
    assert codes(client) == before


def test_bad_bodies_are_400s_not_500s(make):
    client = make()
    planned(client)
    for body in ([], 5, "x", {}, {"token": 5}, {"token": ""}, {"token": None}, {"token": ["a"]}):
        status, answer = post(client, APPLY, body)
        assert status == 400 and answer["reason"] == "invalid", body
    for path in (APPLY, UNDO):
        status, answer = raw_post(client, path, b"{not json")
        assert status == 400 and answer["reason"] == "invalid"
    for body in ([], {}, {"backup": 3}, {"backup": ""}):
        assert post(client, UNDO, body)[0] == 400, body


def test_apply_logs_without_secrets(make, caplog, monkeypatch):
    secret = "very-secret-password"
    monkeypatch.setattr("test_web.AUTH", "Basic " + base64.b64encode(f"metar:{secret}".encode()).decode())
    client = make(**{"web_server.password": secret})
    planned(client)
    token = get(client, PREVIEW)[1]["token"]
    with caplog.at_level(logging.INFO):
        assert post(client, APPLY, {"token": token})[0] == 200
    assert "applied a plan" in caplog.text and secret not in caplog.text


# ---- undo -------------------------------------------------------------------------------------------------------


def test_status_before_and_after_an_apply(make):
    client = make()
    none = get(client, STATUS)[1]["undo"]
    assert none == {"available": False, "backup": None, "made_at": None, "summary": None}
    planned(client)
    done = post(client, APPLY, {"token": get(client, PREVIEW)[1]["token"]})[1]
    undo = get(client, STATUS)[1]["undo"]
    assert undo["available"] is True and undo["backup"] == done["backup"] and undo["made_at"]
    assert undo["summary"]["airports_total"] == 50


def test_undo_puts_the_airports_back(make):
    client = make()
    original = codes(client)
    planned(client, string_len=60)
    post(client, APPLY, {"token": get(client, PREVIEW)[1]["token"]})
    assert codes(client) != original
    backup = get(client, STATUS)[1]["undo"]["backup"]
    status, body = post(client, UNDO, {"backup": backup})
    assert status == 200 and body["ok"] is True and body["backup"] == backup
    assert body["restored"] == {"airports": 50, "led_count": 50, "virtual_count": 0}
    assert body["restart_needed"] is False  # the strip followed 50 -> 60 -> 50 and runs 50 again
    assert codes(client) == original
    assert get(client, STATUS)[1]["undo"]["available"] is False


def test_a_second_undo_and_an_unknown_backup_are_refused(make):
    client = make()
    planned(client)
    post(client, APPLY, {"token": get(client, PREVIEW)[1]["token"]})
    backup = get(client, STATUS)[1]["undo"]["backup"]
    status, body = post(client, UNDO, {"backup": "config.json.before-plan-19990101-000000"})
    assert status == 409 and body["reason"] == "stale"
    assert post(client, UNDO, {"backup": backup})[0] == 200
    status, body = post(client, UNDO, {"backup": backup})
    assert status == 409 and body["reason"] == "none"


def test_undo_leaves_other_settings_alone(make):
    client = make()
    planned(client)
    post(client, APPLY, {"token": get(client, PREVIEW)[1]["token"]})
    client.services.config.edit("led.brightness.normal", "0.2")
    post(client, UNDO, {"backup": get(client, STATUS)[1]["undo"]["backup"]})
    assert client.services.config.data.led.brightness.normal == 0.2


# ---- a plan the Chart already has ---------------------------------------------------------------------------


def hold_the_plan_the_chart_has(client):
    """Makes the plan the SERVER holds exactly what the Chart's strip is now (the job `planned` returns is a copy)."""
    planned(client)
    result = client.planner.job["result"]
    result["sheet"]["pixels"] = [{"code": a.code} for a in client.services.config.airports[:50]]
    result["names"] = {}  # a blank name the plan could fill in would be a change of its own


def test_a_plan_the_chart_already_has_says_so_and_makes_no_backup(make):
    client = make()
    hold_the_plan_the_chart_has(client)
    status, body = get(client, PREVIEW)
    assert status == 200 and body["summary"]["unchanged"] is True and body["summary"]["moved"] == 0
    status, reply = post(client, APPLY, {"token": body["token"]})
    assert status == 409 and reply["reason"] == "unchanged"
    assert "Nothing to apply" in reply["error"] and "already has this plan" in reply["error"]
    assert backups(client) == [] and get(client, STATUS)[1]["undo"]["available"] is False


def test_an_apply_that_changes_nothing_prunes_no_older_backup(make):
    client = make()
    config = client.services.config
    for _ in range(PLAN_BACKUPS):  # five backups from earlier applies
        config.apply_plan(config.layout()[0], 50, 0)
    before = backups(client)
    assert len(before) == PLAN_BACKUPS
    hold_the_plan_the_chart_has(client)
    token = get(client, PREVIEW)[1]["token"]
    assert post(client, APPLY, {"token": token})[1]["reason"] == "unchanged"
    assert backups(client) == before  # no new copy, and none of the old ones removed to make room


def test_the_wiring_note_names_the_led_numbers_of_the_plan(make):
    client = make()
    job = planned(client)
    note = get(client, PREVIEW)[1]["summary"]["wiring_note"]
    pixels = job["result"]["sheet"]["pixels"]
    last = max(i for i, p in enumerate(pixels) if p["code"])
    assert f"LED {last + 1} is {pixels[last]['code']}" in note


# ---- a write that fails after the backup was made ------------------------------------------------------------


def test_a_write_that_fails_after_the_backup_leaves_no_backup_and_no_undo(make, monkeypatch):
    client = make()
    planned(client)
    token = get(client, PREVIEW)[1]["token"]
    before = codes(client)
    real = os.replace

    def broken(src, dst, *args, **kwargs):
        if str(dst).endswith("config.json"):
            raise OSError("disk full")
        return real(src, dst, *args, **kwargs)

    with monkeypatch.context() as m:
        m.setattr("metarmap.settings.os.replace", broken)
        status, body = post(client, APPLY, {"token": token})
    assert status == 500 and body["reason"] == "failed" and "nothing changed" in body["error"]
    assert codes(client) == before
    assert backups(client) == [] and get(client, STATUS)[1]["undo"]["available"] is False
    assert not os.path.exists(os.path.join(config_dir(client), "config.json.tmp"))
    # and the same token still works once the disk is back
    assert post(client, APPLY, {"token": token})[0] == 200
