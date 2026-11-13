"""
Tests for the Chart Planner page (metarmap.web.planner): the page and its form, the background job from POST to result,
its progress, cancel and resume, bad input, and what the plan keeps. The airport fetch is a fake: no network.
"""

import io
import json
import math
import re
import sys
import threading
from datetime import datetime, timedelta, timezone
import time

import pytest

from metarmap.planner import airports as live_airports
from metarmap.planner import layout
from metarmap.web import create_app
from metarmap.web import planner as planner_web
from test_web import AUTH, Client

HOUSTON = (-97.8728, 27.5573, -90.4408, 32.2747)  # west, south, east, north


def spot(k, total):
    """k of `total` places spread over the Houston chart (lat, lon), the same every time."""
    columns = math.ceil(math.sqrt(total * 1.6))
    row, column = divmod(k, columns)
    rows = math.ceil(total / columns)
    lon = HOUSTON[0] + (column + 0.5) / columns * (HOUSTON[2] - HOUSTON[0])
    lat = HOUSTON[3] - (row + 0.5) / rows * (HOUSTON[3] - HOUSTON[1])
    return lat, lon


def station(k, total, rank=None):
    lat, lon = spot(k, total)
    return {
        "code": f"K{k:03d}",
        "name": f"Field {k}",
        "lat": lat,
        "lon": lon,
        "rank": rank if rank is not None else float(total - k),
    }


def fake_airports(total):
    return [station(k, total) for k in range(total)]


class FakeLoad:
    """Stands for planner.airports.load: answers with its list, or what `result` says; records the boxes asked."""

    def __init__(self, airports=None, stale=False, error=None):
        self.airports = fake_airports(120) if airports is None else airports
        self.stale, self.error = stale, error
        self.boxes = []

    def __call__(self, box, clock=None, progress=None, **kwargs):
        self.boxes.append(box)
        if progress:  # a real download reports its tiles and batches; only a cache that answers as it is does not
            progress("stations", 1, 1)
            progress("details", 1, 1)
        return live_airports.Result(self.airports, self.stale, "2026-11-12T10:00:00+00:00", self.error)


@pytest.fixture
def make(make_app, monkeypatch):
    """make(load=FakeLoad()) -> a client for a map whose airports all have a position on the Houston chart."""

    def build(load=None):
        services = make_app()
        codes = [a.code for a in services.config.airports if a.code]
        for k, code in enumerate(codes):
            lat, lon = spot(k, len(codes))
            services.metars.positions[code] = {"lat": lat, "lon": lon, "name": f"Name of {code}"}
        looked_up = []
        monkeypatch.setattr(
            services.metars, "_look_up", lambda codes, timeout=30: looked_up.append(list(codes)) or True
        )
        planner = planner_web.Planner(services, load=load or FakeLoad())
        client = Client(create_app(services, ip="10.0.0.2", planner=planner))
        client.services, client.planner, client.looked_up, client.codes = services, planner, looked_up, codes
        return client

    return build


def wait(client, seconds=60):
    """Polls the job's progress until it is done; returns the last answer."""
    end = time.time() + seconds
    while time.time() < end:
        job = client.json("/config/planner/progress")
        if job["done"]:
            return job
        time.sleep(0.02)
    raise AssertionError("the planner job did not finish")


def post(client, **values):
    return client("/config/planner/plan", method="POST", body={"chart": "Houston", "suggest_sizes": False, **values})


def run(client, **values):
    status, body = post(client, **values)
    assert status == 202, body
    return wait(client)


# ---- the page ----------------------------------------------------------------------------------------------


def test_planner_needs_a_login(make):
    client = make()
    for path, method in (
        ("/config/planner", "GET"),
        ("/config/planner/plan", "POST"),
        ("/config/planner/progress", "GET"),
        ("/config/planner/cancel", "POST"),
    ):
        assert client(path, method=method, auth=False)[0] == 401


def test_airports_page_links_to_the_planner(make):
    client = make()
    body = client("/config/airports")[1]
    assert 'href="/config/planner"' in body
    assert "Plan a new chart" in body


def test_form_defaults(make):
    client = make()
    status, body = client("/config/planner")
    assert status == 200
    assert "<title>Plan a new chart · MetarMap2 Web</title>" in body
    assert body.count("<option value=") >= 56 + 3 + 3 + 5  # charts, sources, targets, corners
    assert '<option value="Houston" selected>' in body  # the Chart's own sectional
    assert "US Wall Planning (whole US)" in body
    assert 'id="pl-width" class="num" type="number" inputmode="decimal" min="1" step="0.1" value="32"' in body
    assert 'id="pl-pitch"' in body and 'value="80"' in body
    assert 'id="pl-gap"' in body and 'id="pl-move"' in body and 'value="18"' in body
    assert 'id="pl-len"' in body and 'value="50"' in body
    assert 'id="pl-strings"' in body and "A number of strings" in body and "Fill whole strings" not in body
    assert 'id="pl-tol"' in body and 'value="5"' in body
    assert 'id="pl-bright"' in body and 'value="0.5"' in body  # led.brightness.normal
    assert 'id="pl-sizes" class="switch" type="checkbox" checked' in body
    assert 'id="pl-skips" class="switch" type="checkbox" disabled' in body
    assert "Needs Chart support" in body
    for code in client.codes[:3]:
        assert f'value="{code}"' in body  # the must-keep list
    assert "/static/planner.js" in body
    assert "@media print" in client("/static/style.css")[1]


def test_the_print_stylesheet_prints_the_lists_under_the_map(make):
    css = make()("/static/style.css")[1]
    printing = css[css.index("@media print") :]
    hidden = re.findall(r"([^{}]*)\{[^}]*display:\s*none", printing)
    assert hidden, "the page's chrome is hidden when printing"
    assert not any(".planner-side" in h or "#pl-lists" in h or "#pl-summary" in h for h in hidden)
    assert ".no-print" in "".join(hidden) and ".planner-form" in "".join(hidden)
    assert "break-after: page" in printing and ".planner-side .card" in printing


def boards_of(body):
    """The page's chart -> [height / width, note] table."""
    return json.loads(re.search(r'data-boards="([^"]*)"', body).group(1).replace("&quot;", '"'))


def test_the_height_note_follows_the_chart(make):
    client = make()
    body = client("/config/planner")[1]
    boards = boards_of(body)
    assert "32 x 22 in" in boards["Houston"][1] and "estimate" not in boards["Houston"][1]
    assert "59 x 36 in" in boards["US Wall Planning"][1] and "estimate" not in boards["US Wall Planning"][1]
    assert "estimate" in boards["Albuquerque"][1]
    assert abs(boards["US Wall Planning"][0] - 36 / 59) < 1e-6
    # the first paint is for the chart the page starts on, not for Houston
    assert (
        boards["Houston"][1] in body
        and 'id="pl-height" class="num" type="number" inputmode="decimal" min="1" step="0.1" value="22"' in body
    )
    client.services.config.edit("geo.map.chart", "Albuquerque")
    again = client("/config/planner")[1]
    assert f'id="pl-height-note">{boards["Albuquerque"][1]}' in again
    assert 'value="22"' not in again.split('id="pl-height"')[1].split("</span>")[0]


def test_form_starts_on_the_chart_with_the_airports(make):
    client = make()
    client.services.config.edit("geo.map.chart", "Albuquerque")
    assert '<option value="Albuquerque" selected>' in client("/config/planner")[1]
    client.services.config.edit("geo.map.chart", "")  # none set: the sectional with most of the airports
    assert '<option value="Houston" selected>' in client("/config/planner")[1]


def test_form_flags_airports_with_no_known_position(make):
    client = make()
    del client.services.metars.positions[client.codes[0]]
    body = client("/config/planner")[1]
    assert f'value="{client.codes[0]}" data-unlocated="1"' in body


# ---- a job from POST to result -----------------------------------------------------------------------------


def test_a_plan_of_the_current_airports(make):
    client = make()
    status, body = post(client)
    assert status == 202
    started = json.loads(body)
    assert started["done"] is False and started["id"] == 1 and started["params"]["chart"] == "Houston"
    assert client.headers["Content-Type"] == "application/json"
    job = wait(client)
    assert job["ok"] is True and job["error"] == "" and job["fraction"] == 1.0
    result = job["result"]
    assert result["recommended"] is False and result["left_out"] == []
    sheet = result["sheet"]
    assert set(sheet) >= {
        "board",
        "pixels",
        "start",
        "route",
        "cuts",
        "joins",
        "strings",
        "shopping",
        "problems",
        "power",
    }
    assert set(sheet["board"]) == {"width_mm", "height_mm", "width_in", "height_in"}
    assert sheet["board"]["width_in"] == 32.0 and sheet["board"]["height_in"] == 22.0  # Houston's measured board
    assert len(sheet["pixels"]) == len(client.codes)
    assert {p["code"] for p in sheet["pixels"]} == set(client.codes)
    assert set(sheet["shopping"]) >= {"airports", "pixels", "strings", "extensions", "joins", "slack_gaps", "moved"}
    assert set(sheet["power"]) >= {"voltage", "reason", "estimated_amps", "supply_amps", "feed_points", "notes"}
    assert set(sheet["problems"]) >= {"crowded", "drops", "clipped", "skips_wanted", "ok"}
    assert result["chart"]["name"] == "Houston" and result["chart"]["margins"]["left"] > 0
    assert result["sizes"] is None  # not asked for
    assert not client.looked_up  # every airport's position was known


def test_the_config_snippet_is_the_airports_in_the_new_order(make):
    client = make()
    client.services.config.set_airport(0, "display", "true")
    result = run(client)["result"]
    snippet = result["airports"]
    assert [a["code"] for a in snippet] == [p["code"] for p in result["sheet"]["pixels"]]
    assert all(set(a) == {"code", "name", "display"} for a in snippet)
    assert next(a for a in snippet if a["code"] == client.codes[0]) == {
        "code": client.codes[0],
        "name": client.services.config.airports[0].name,
        "display": True,
    }
    json.dumps(snippet)


def test_a_pasted_list_looks_up_unknown_codes(make):
    client = make()
    codes = client.codes[:4]
    result = run(client, source="paste", codes=f"{codes[0].lower()}, {codes[1]}\n{codes[2]} KZZZ")["result"]
    assert {p["code"] for p in result["sheet"]["pixels"]} == set(codes[:3])
    assert result["left_out"] == [{"code": "KZZZ", "reason": "no known position"}]
    assert client.looked_up == [["KZZZ"]]  # only the one the Chart doesn't know


def test_a_failed_lookup_is_not_reported_as_an_unknown_code(make, monkeypatch):
    client = make()
    monkeypatch.setattr(client.services.metars, "_look_up", lambda codes, timeout=30: False)  # offline
    result = run(client, source="paste", codes=[client.codes[0], "KZZZ"])["result"]
    assert result["left_out"] == [{"code": "KZZZ", "reason": "the position lookup failed (offline?)"}]


def test_must_keep_codes_that_are_not_being_planned_are_listed(make):
    client = make()
    codes = client.codes
    result = run(client, source="paste", codes=codes[:3], must_keep=[codes[0], codes[5]])["result"]
    assert {"code": codes[5], "reason": "not one of the airports being planned"} in result["left_out"]
    assert {p["code"] for p in result["sheet"]["pixels"]} == set(codes[:3])
    current = run(client, must_keep=["KZZZ"])["result"]
    assert current["left_out"] == [{"code": "KZZZ", "reason": "not one of the airports being planned"}]


def test_airports_off_the_chart_are_left_out(make):
    client = make()
    client.services.metars.positions["KJFK"] = {"lat": 40.6, "lon": -73.8, "name": "New York"}
    result = run(client, source="paste", codes=[client.codes[0], client.codes[1], "KJFK"])["result"]
    assert result["left_out"] == [{"code": "KJFK", "reason": "outside the Houston chart"}]


def test_a_plan_with_no_known_position_says_so(make):
    client = make()
    job = run(client, source="paste", codes="KZZZ")
    assert job["ok"] is False and "no airports to plan" in job["error"].lower() and job["result"] is None


def test_sizes_to_try(make):
    client = make()
    result = run(client, source="paste", codes=client.codes[:6], suggest_sizes=True)["result"]
    sizes = result["sizes"]
    assert 1 <= len(sizes["best"]) <= 3
    for row in sizes["best"] + [sizes["current"]]:
        assert set(row) == {"width_in", "height_in", "extensions", "crowded", "drops"}
        assert 28.7 <= row["width_in"] <= 36.9  # 90% to 115% of 32 in
        assert abs(row["height_in"] / row["width_in"] - 22 / 32) < 0.01  # the shape is kept
    assert sizes["current"]["width_in"] == 32.0
    keys = [(r["crowded"], r["drops"], r["extensions"]) for r in sizes["best"]]
    assert keys == sorted(keys)


def test_the_board_s_own_width_is_not_planned_twice(make, monkeypatch):
    client = make()
    calls = []
    real = layout.plan

    def counting(pins, settings, cancel=None):
        calls.append(settings.board_w)
        return real(pins, settings, cancel)

    monkeypatch.setattr(planner_web.layout, "plan", counting)
    result = run(client, source="paste", codes=client.codes[:6], suggest_sizes=True)["result"]
    sizes = result["sizes"]
    assert len(calls) == 11  # the plan, and the ten other widths: not 12
    assert calls.count(calls[0]) == 1
    # the board's own row is the plan that was made, not a second one
    assert sizes["current"]["width_in"] == 32.0
    assert sizes["current"]["extensions"] == result["sheet"]["shopping"]["extensions"]
    assert sizes["current"]["crowded"] == len(result["sheet"]["problems"]["crowded"])
    assert all(r["width_in"] != 32.0 or r == sizes["current"] for r in sizes["best"])  # if it ranks, it is that row


def test_the_sizes_are_not_tried_for_a_big_plan(make, monkeypatch):
    client = make()
    monkeypatch.setattr(planner_web, "SWEEP_MAX_PINS", 5)
    result = run(client, source="paste", codes=client.codes[:6], suggest_sizes=True)["result"]
    assert result["sizes"] is None
    assert any("Board sizes were not tried" in n for n in result["notes"])
    small = run(client, source="paste", codes=client.codes[:5], suggest_sizes=True)["result"]
    assert small["sizes"] is not None


def test_the_board_height_is_the_one_entered(make):
    client = make()
    sheet = run(client, height_in=20, width_in=30)["result"]["sheet"]
    assert sheet["board"]["width_in"] == 30 and sheet["board"]["height_in"] == 20


def test_skipped_pixels_are_always_off(make):
    client = make()
    job = run(client, allow_skips=True)
    assert job["params"]["allow_skips"] is False
    assert job["result"]["skips_allowed"] is False
    assert job["result"]["sheet"]["settings"]["allow_skips"] is False
    assert not any(p["skipped"] for p in job["result"]["sheet"]["pixels"])
    assert "skips_wanted" in job["result"]["sheet"]["problems"]


def test_the_start_corner_and_power_settings_reach_the_sheet(make):
    client = make()
    sheet = run(client, start_corner="tr", brightness=1.0, ma_white_5v=30)["result"]["sheet"]
    assert sheet["start"]["corner"] == "tr"
    assert sheet["power"]["brightness"] == 1.0
    assert sheet["power"]["options"][0]["ma_white"] == 30


def test_a_failure_in_the_plan_is_shown_not_raised(make, monkeypatch):
    client = make()

    def explode(*args, **kwargs):
        raise RuntimeError("the sheet broke")

    monkeypatch.setattr(planner_web, "make_sheet", explode)
    job = run(client)
    assert job["ok"] is False and job["error"] == "The plan failed: the sheet broke"


# ---- recommended airports ----------------------------------------------------------------------------------


def test_recommended_airports_are_fetched_for_the_chart_box(make):
    load = FakeLoad()
    client = make(load)
    result = run(client, source="recommended", target=30, start_fresh=True)["result"]
    assert load.boxes == [HOUSTON]
    assert result["recommended"] is True
    assert len(result["sheet"]["pixels"]) == 30
    assert result["notes"] == [] and result["stale"] is False


def test_recommended_fills_whole_strings_by_default(make):
    client = make()
    result = run(client, source="recommended", start_fresh=True)["result"]
    assert len(result["sheet"]["pixels"]) == 50
    assert result["sheet"]["shopping"]["strings"] == 1


def test_the_strings_default_to_what_the_kept_airports_fill(make):
    airports = fake_airports(200)
    client = make(FakeLoad(airports))
    codes = [a["code"] for a in airports]
    fifty = run(client, source="recommended", start_fresh=True, must_keep=codes[:50])["result"]
    assert len(fifty["sheet"]["pixels"]) == 50 and fifty["notes"] == []  # one string: nothing more is asked for
    fifty_one = run(client, source="recommended", start_fresh=True, must_keep=codes[:51])["result"]
    assert len(fifty_one["sheet"]["pixels"]) == 100  # 51 airports need a second string, and it is filled
    assert fifty_one["sheet"]["shopping"]["strings"] == 2


def test_an_explicit_number_of_strings_is_filled(make):
    client = make(FakeLoad(fake_airports(200)))
    job = run(client, source="recommended", start_fresh=True, target="strings", strings=3)
    assert job["params"]["strings"] == 3
    assert len(job["result"]["sheet"]["pixels"]) == 150
    assert job["result"]["sheet"]["shopping"]["strings"] == 3 and job["result"]["notes"] == []
    short = run(client, source="recommended", start_fresh=True, strings=2, string_len=20)["result"]
    assert len(short["sheet"]["pixels"]) == 40  # strings of the length asked for
    # the number of strings is only for that target
    other = run(client, source="recommended", start_fresh=True, target=10, strings=3)
    assert other["params"]["strings"] is None and len(other["result"]["sheet"]["pixels"]) == 10


def test_the_kept_airports_raise_a_too_small_number_of_strings(make):
    airports = fake_airports(200)
    client = make(FakeLoad(airports))
    codes = [a["code"] for a in airports]
    result = run(client, source="recommended", start_fresh=True, must_keep=codes[:51], strings=1)["result"]
    assert len(result["sheet"]["pixels"]) == 100
    assert any("51 airports you keep need 2 strings of 50, so the plan uses 2, not 1" in n for n in result["notes"])
    assert set(codes[:51]) <= {p["code"] for p in result["sheet"]["pixels"]}


def test_strings_over_the_chart_s_pixels_say_so(make, monkeypatch):
    client = make(FakeLoad(fake_airports(200)))
    monkeypatch.setattr(planner_web, "MAX_LEDS", 80)
    result = run(client, source="recommended", start_fresh=True, strings=3)["result"]  # 150 asked, 80 the most
    assert len(result["sheet"]["pixels"]) == 80
    assert any("at most 80 pixels" in n for n in result["notes"])


def test_fewer_airports_than_the_strings_ask_for_say_how_many_fit(make):
    client = make(FakeLoad(fake_airports(30)))
    result = run(client, source="recommended", start_fresh=True, strings=1)["result"]  # 50 asked, 30 exist
    assert len(result["sheet"]["pixels"]) == 30
    assert any("Only 30 airports fit at this spacing, not 50" in n for n in result["notes"])
    assert any("larger board" in n and "smaller minimum spacing" in n for n in result["notes"])


def test_only_the_ticked_airports_are_kept_when_recommending(make):
    client = make()
    # the page ticks the current airports unless Start fresh, and sends the ticked ones as must_keep
    kept = run(client, source="recommended", target=60, must_keep=client.codes)["result"]
    assert set(client.codes) <= {p["code"] for p in kept["sheet"]["pixels"]}
    # unticking one takes it out of the plan, whether or not Start fresh is on
    three = client.codes[:3]
    some = run(client, source="recommended", target=60, must_keep=three)["result"]
    assert set(three) <= {p["code"] for p in some["sheet"]["pixels"]}
    assert not set(client.codes[3:]) & {p["code"] for p in some["sheet"]["pixels"]}
    fresh = run(client, source="recommended", target=60, start_fresh=True)["result"]
    assert not set(client.codes) & {p["code"] for p in fresh["sheet"]["pixels"]}


def test_must_keep_is_honoured(make):
    airports = fake_airports(120)
    client = make(FakeLoad(airports))
    last = airports[-1]["code"]  # the lowest rank: never picked for its rank in a short list
    without = run(client, source="recommended", target=10, start_fresh=True)["result"]
    assert last not in {p["code"] for p in without["sheet"]["pixels"]}
    kept = run(client, source="recommended", target=10, start_fresh=True, must_keep=[last])["result"]
    assert last in {p["code"] for p in kept["sheet"]["pixels"]}
    assert len(kept["sheet"]["pixels"]) == 10
    # a pasted list too: must keep reaches the pins
    assert run(client, source="paste", codes=client.codes[:5], must_keep=[client.codes[0]])["ok"]


def test_as_many_as_fit(make):
    client = make()
    few = run(client, source="recommended", target=5, start_fresh=True)["result"]
    most = run(client, source="recommended", target="max", start_fresh=True)["result"]
    assert len(few["sheet"]["pixels"]) == 5
    assert len(most["sheet"]["pixels"]) > 5


def test_the_plan_never_goes_over_the_pixels_the_chart_can_take(make, monkeypatch):
    client = make()
    monkeypatch.setattr(planner_web, "MAX_LEDS", 25)
    most = run(client, source="recommended", target="max", start_fresh=True)["result"]
    assert len(most["sheet"]["pixels"]) == 25
    assert any("at most 25 pixels" in n for n in most["notes"])
    strings = run(client, source="recommended", start_fresh=True, string_len=30)["result"]  # a whole 30, over the cap
    assert len(strings["sheet"]["pixels"]) == 25
    monkeypatch.setattr(planner_web, "MAX_LEDS", 30)  # the virtual airports take pixels' worth of the limit too
    client.services.config.data.led.virtual_count = 5
    more = run(client, source="recommended", target=28, start_fresh=True)["result"]
    assert len(more["sheet"]["pixels"]) == 25 and any("at most 25 pixels" in n for n in more["notes"])
    monkeypatch.setattr(planner_web, "MAX_LEDS", 25)
    client.services.config.data.led.virtual_count = 0
    few = run(client, source="recommended", target=10, start_fresh=True)["result"]
    assert not any("at most" in n for n in few["notes"])


def test_an_invalid_code_is_echoed_back_cut_to_forty_characters(make):
    client = make()
    status, body = post(client, source="paste", codes=["ABCD" * 5000])
    error = json.loads(body)["error"]
    assert status == 400 and len(error) < 200 and "…" in error
    status, body = post(client, source="paste", codes=[{"x": "y" * 5000}])
    assert status == 400 and len(json.loads(body)["error"]) < 200


def test_more_must_keep_airports_than_the_chart_takes_are_a_400_before_anything_runs(make):
    client = make()
    client.services.config.data.led.virtual_count = 10  # the Chart takes 1000 - 10 pixels
    codes = [f"K{n:03d}" for n in range(1000)]
    status, body = post(client, source="recommended", must_keep=codes, target="max")
    answer = json.loads(body)
    assert status == 400 and answer["reason"] == "invalid"
    assert "1000 airports" in answer["error"] and "990 pixels" in answer["error"]
    assert client.json("/config/planner/progress")["idle"] is True  # no job was started
    status, _ = post(client, source="recommended", must_keep=codes[:990], target="max")
    assert status == 202  # exactly what the Chart can take is allowed
    wait(client)


def test_a_plan_still_running_after_its_time_limit_is_stopped(make, monkeypatch):
    client = make()
    monkeypatch.setattr(planner_web, "PLAN_SECONDS", 0)  # out of time at the first step
    job = run(client)
    assert job["ok"] is False and job["cancelled"] is False and job["result"] is None
    assert "stopped after" in job["error"]


def test_the_time_limit_reaches_the_layout_calls(make, monkeypatch):
    client = make()
    seen = []

    def plan(pins, settings, cancel=None):
        seen.append(cancel)
        monkeypatch.setattr(planner_web, "PLAN_SECONDS", 0)  # not read again: the limit object was made at the start
        assert cancel() is False  # inside its time and not cancelled: it carries on
        raise layout.Cancelled()  # the layout stops itself the way a cancel makes it

    monkeypatch.setattr(planner_web.layout, "plan", plan)
    job = run(client)
    assert callable(seen[0]) and job["cancelled"] is False and "stopped after" in job["error"]


def test_a_list_over_the_chart_s_pixels_is_refused(make, monkeypatch):
    client = make()
    monkeypatch.setattr(planner_web, "MAX_LEDS", len(client.codes) - 1)
    job = run(client)
    assert job["ok"] is False and "more than the Chart can take" in job["error"]


def test_a_stale_cache_is_used_and_said_so(make):
    client = make(FakeLoad(stale=True, error="aviationweather.gov did not answer; using the cache from 2026-11-12"))
    job = run(client, source="recommended", target=10, start_fresh=True)
    assert job["ok"] is True
    assert job["result"]["stale"] is True
    assert any("cached" in n for n in job["result"]["notes"])


def test_a_failed_fetch_with_nothing_cached_shows_the_error(make):
    client = make(FakeLoad(airports=[], error="aviationweather.gov did not answer"))
    job = run(client, source="recommended", target=10, start_fresh=True)
    assert job["ok"] is False
    assert job["error"] == "The airports could not be fetched: aviationweather.gov did not answer"


def test_a_short_answer_is_used_with_a_note(make):
    client = make(
        FakeLoad(fake_airports(20), error="3 requests to aviationweather.gov failed, so the list may be short")
    )
    job = run(client, source="recommended", target=10, start_fresh=True)
    assert job["ok"] is True and "may be short" in job["result"]["notes"][0]


# ---- one job at a time, progress, cancel and resume --------------------------------------------------------


class SlowLoad:
    """A fetch that runs until cancelled, using the clock the job gives it: as the real one waits between requests."""

    def __init__(self):
        self.started = threading.Event()
        self.clock = None

    def __call__(self, box, clock=None, **kwargs):
        self.clock = clock
        self.started.set()
        while clock.time() != math.inf:
            clock.wait(threading.Event(), 0.01)
        return live_airports.Result([], False, None, "gave up")


def test_progress_before_any_job(make):
    job = make().json("/config/planner/progress")
    assert job["idle"] is True and job["done"] is True and job["result"] is None


def test_a_second_plan_while_one_runs_is_refused(make):
    load = SlowLoad()
    client = make(load)
    assert post(client, source="recommended", start_fresh=True)[0] == 202
    assert load.started.wait(5)
    status, body = post(client)
    assert status == 409
    answer = json.loads(body)
    assert answer["reason"] == "running" and "already running" in answer["error"]
    assert answer["id"] == 1 and answer["done"] is False  # and the running job's progress comes with it
    # a reloaded page asks for the progress and gets the job with the form's values
    job = client.json("/config/planner/progress")
    assert job["done"] is False and job["params"]["source"] == "recommended"
    assert job["label"].startswith("Fetching airports")
    assert job["fraction"] is None  # no way to know how long a fetch takes: the bar waits
    assert job["result"] is None
    client("/config/planner/cancel", method="POST")
    wait(client)
    assert post(client)[0] == 202  # free again
    wait(client)


def test_cancel_stops_the_airport_fetch(make):
    load = SlowLoad()
    client = make(load)
    post(client, source="recommended", start_fresh=True)
    assert load.started.wait(5)
    cancelled = client.json("/config/planner/cancel", method="POST")
    assert cancelled["label"] == "Cancelling"
    job = wait(client)
    assert job["cancelled"] is True and job["ok"] is False and job["message"] == "Cancelled" and job["result"] is None


def test_cancel_works_while_the_plan_itself_runs(make, monkeypatch):
    client = make()
    inside, asked = threading.Event(), []

    def slow_plan(pins, settings, cancel=None):
        asked.append(cancel)
        inside.set()
        end = time.time() + 10
        while time.time() < end:
            if cancel():
                raise layout.Cancelled()
            time.sleep(0.005)
        raise AssertionError("the plan was never asked to stop")

    monkeypatch.setattr(planner_web.layout, "plan", slow_plan)
    assert post(client)[0] == 202
    assert inside.wait(5)
    assert client.json("/config/planner/cancel", method="POST")["label"] == "Cancelling"
    job = wait(client)
    assert job["cancelled"] is True and job["ok"] is False and job["result"] is None and job["message"] == "Cancelled"
    assert callable(asked[0])


def test_cancel_works_while_a_recommendation_runs(make, monkeypatch):
    client = make()
    inside = threading.Event()

    def slow_recommend(pins, settings, target=None, coverage=0.0, cancel=None):
        inside.set()
        while not cancel():
            time.sleep(0.005)
        raise layout.Cancelled()

    monkeypatch.setattr(planner_web.layout, "recommend", slow_recommend)
    post(client, source="recommended", target=10, start_fresh=True)
    assert inside.wait(5)
    client("/config/planner/cancel", method="POST")
    assert wait(client)["cancelled"] is True


def test_a_cancel_after_the_last_step_does_not_end_as_a_success(make, monkeypatch):
    client = make()
    real = planner_web.make_sheet

    def sheet_then_cancel(*args, **kwargs):
        client.planner._cancel.set()  # Cancel pressed while the build sheet was being made
        return real(*args, **kwargs)

    monkeypatch.setattr(planner_web, "make_sheet", sheet_then_cancel)
    job = run(client)
    assert job["cancelled"] is True and job["ok"] is False and job["result"] is None


def test_a_library_value_error_is_logged_and_shown_as_a_failed_plan(make, monkeypatch, caplog):
    client = make()

    def refuse(*args, **kwargs):
        raise ValueError("a pin has no usable position")

    monkeypatch.setattr(planner_web.layout, "plan", refuse)
    with caplog.at_level("ERROR"):
        job = run(client)
    assert job["ok"] is False and job["error"].startswith("The plan failed")
    assert "usable position" not in job["error"]  # a bug's text is for the log, not the user
    assert "a pin has no usable position" in caplog.text and "Traceback" in caplog.text


def test_cancel_with_nothing_running(make):
    client = make()
    assert client.json("/config/planner/cancel", method="POST")["idle"] is True
    run(client)
    assert client.json("/config/planner/cancel", method="POST")["ok"] is True  # a finished job stays as it was


def test_a_finished_job_is_still_there_for_a_reloaded_page(make):
    client = make()
    run(client)
    again = client.json("/config/planner/progress")
    assert again["done"] is True and again["ok"] is True and again["result"]["sheet"]["pixels"]
    assert again["params"]["width_in"] == 32.0


def test_the_job_clock_stops_on_cancel():
    cancel = threading.Event()
    clock = planner_web.JobClock(cancel)
    assert math.isfinite(clock.time())
    assert clock.wait(threading.Event(), 0.001) is False  # a wait that runs its time out
    cancel.set()
    assert clock.time() == math.inf  # the fetch's budget is spent: it stops at its next request
    assert clock.wait(threading.Event(), 60) is True  # and a wait ends at once


# ---- bad input ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "values, text",
    [
        ({"chart": "Atlantis"}, "No chart called"),
        ({"chart": ""}, "No chart called"),
        ({"source": "magic"}, "source must be"),
        ({"width_in": 0}, "width"),
        ({"width_in": "wide"}, "width must be a number"),
        ({"width_in": 5000}, "width"),
        ({"height_in": -3}, "height"),
        ({"pitch": 0}, "pitch"),
        ({"min_gap": -1}, "minimum spacing"),
        ({"string_len": 2.5}, "whole number"),
        ({"string_len": 0}, "string length"),
        ({"tolerance": -5}, "tolerance"),
        ({"coverage": 2}, "coverage"),
        ({"start_corner": "middle"}, "start_corner"),
        ({"brightness": 3}, "brightness"),
        ({"ma_white_5v": 0}, "5 V"),
        ({"source": "paste", "codes": "KHOU 12"}, "not an airport code"),
        ({"must_keep": ["no way"]}, "not an airport code"),
        ({"source": "recommended", "target": 0}, "number of airports"),
        ({"source": "recommended", "target": "lots"}, "number of airports"),
        ({"source": "recommended", "strings": 0}, "number of strings"),
        ({"source": "recommended", "strings": 2.5}, "number of strings"),
        ({"source": "recommended", "strings": "lots"}, "number of strings"),
        ({"source": "recommended", "strings": True}, "number of strings"),
        ({"source": "recommended", "strings": 100000}, "number of strings"),
        ({"pitch": 5}, "pitch"),  # limits that keep a plan from running for hours on a Pi
        ({"pitch": 19}, "pitch"),
        ({"pitch": 5000}, "pitch"),
        ({"string_len": 4}, "string length"),
        ({"string_len": 9}, "string length"),
        ({"max_move": 500}, "maximum move"),
        ({"max_move": 26}, "maximum move"),
        ({"min_gap": 500}, "minimum spacing"),
        ({"min_gap": 26}, "minimum spacing"),
        ({"pitch": 10**400}, "(mm) must be a number"),  # too big for a float: not an OverflowError and an HTML 500
        ({"width_in": -(10**400)}, "width must be a number"),
        ({"min_gap": 10**400}, "minimum spacing (mm) must be a number"),
        ({"string_len": 10**400}, "string length must be a number"),
        ({"source": "recommended", "strings": 10**400}, "number of strings must be a number"),
        ({"source": "recommended", "target": 10**400}, "airports to recommend must be a number"),
        ({"pitch": "9" * 400}, "(mm) must be a number"),
        ({"source": "paste", "codes": ["ABCD" * 30]}, "…"),  # an invalid code is echoed back cut short
        ({"start_fresh": "false"}, "start_fresh must be true or false"),  # the text "false" would be true
        ({"suggest_sizes": "no"}, "suggest_sizes must be true or false"),
        ({"suggest_sizes": 0}, "suggest_sizes must be true or false"),
        ({"source": "paste", "codes": [None]}, "list of airport codes"),
        ({"source": "paste", "codes": [True]}, "list of airport codes"),
        ({"source": "paste", "codes": [123]}, "list of airport codes"),
        ({"must_keep": [None]}, "list of airport codes"),
        ({"must_keep": {"KHOU": 1}}, "list of airport codes"),
        ({"width_in": float("nan")}, "width must be a number"),
        ({"width_in": float("inf")}, "width must be a number"),
    ],
)
def test_bad_input_is_a_400_with_a_reason(make, values, text):
    client = make()
    status, body = post(client, **values)
    assert status == 400, body
    answer = json.loads(body)
    assert answer["reason"] == "invalid" and text.lower() in answer["error"].lower()
    assert client.headers["Content-Type"] == "application/json"
    assert client.json("/config/planner/progress")["idle"] is True  # nothing started


def test_a_body_that_is_not_an_object_is_a_400(make):
    client = make()
    for body in ([1, 2], "text", 5):
        status, answer = client("/config/planner/plan", method="POST", body=body)
        assert status == 400 and json.loads(answer)["reason"] == "invalid"
    assert client("/config/planner/plan", method="POST")[0] == 400  # no body at all


def raw_post(client, data, path="/config/planner/plan"):
    """A POST with these bytes as they are (Client always encodes its body as JSON)."""
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
    status, headers = [], []
    result = client.app(environ, lambda s, h, exc_info=None: (status.append(s), headers.extend(h)))
    body = b"".join(result).decode()
    return int(status[0].split()[0]), dict(headers), body


def test_a_body_that_is_not_json_is_a_json_400(make):
    client = make()
    status, headers, body = raw_post(client, b"{not json")
    assert status == 400 and headers["Content-Type"] == "application/json"
    assert json.loads(body)["reason"] == "invalid" and "not valid JSON" in json.loads(body)["error"]
    status, headers, body = raw_post(client, b'{"chart": "Houston", "width_in": NaN}')  # a literal Python accepts
    assert status == 400 and "width must be a number" in json.loads(body)["error"]
    assert client.json("/config/planner/progress")["idle"] is True


def test_a_body_over_the_size_limit_is_a_json_413(make):
    client = make()
    status, headers, body = raw_post(client, b'{"codes": "' + b"KHOU " * 30000 + b'"}')
    assert status == 413 and headers["Content-Type"] == "application/json"
    assert json.loads(body) == {"error": "The request is too big", "reason": "invalid"}


def test_a_long_pasted_list_is_cut_off_before_the_slow_part(make, monkeypatch):
    client = make()
    monkeypatch.setattr(planner_web, "MAX_PASTED", 50)
    status, body = post(client, source="paste", codes=[f"K{k:03d}" for k in range(60)])
    assert status == 400 and "60 entries" in json.loads(body)["error"]


def test_duplicate_pasted_codes_count_once(make):
    client = make()
    code = client.codes[0]
    result = run(client, source="paste", codes=f"{code} {code.lower()} {code} {client.codes[1]}")["result"]
    assert sorted(p["code"] for p in result["sheet"]["pixels"]) == sorted([code, client.codes[1]])


def test_form_values_may_be_strings(make):
    """The browser's number inputs can be sent as they are typed."""
    client = make()
    job = run(client, width_in="30", pitch="75", string_len=50, tolerance="4")
    assert job["ok"] is True and job["result"]["sheet"]["board"]["width_in"] == 30


# ---- the airport download's progress -----------------------------------------------------------------------


class ReportingLoad(FakeLoad):
    """A load that reports through progress= and records what the job showed after each report."""

    def __init__(self, client_of, reports, **kwargs):
        super().__init__(**kwargs)
        self.client_of, self.reports, self.seen = client_of, reports, []

    def __call__(self, box, clock=None, progress=None, **kwargs):
        for report in self.reports:
            progress(*report)
            job = self.client_of().json("/config/planner/progress")
            self.seen.append((job["label"], job["fraction"]))
        return super().__call__(box, clock=clock)


def reporting(make, reports, **kwargs):
    holder = []
    load = ReportingLoad(lambda: holder[0], reports, **kwargs)
    client = make(load)
    holder.append(client)
    return client, load


def test_the_progress_callback_sets_the_label_and_the_fraction(make):
    client, load = reporting(make, [("stations", 87, 270), ("stations", 270, 270), ("details", 5, 25)])
    job = run(client, source="recommended", target=30, start_fresh=True)
    assert job["ok"], job
    (l1, f1), (l2, f2), (l3, f3) = load.seen
    assert l1 == "Downloading stations: tile 87 of 270" and f1 == pytest.approx(0.6 * 87 / 270)
    assert f2 == pytest.approx(0.6)
    assert l3 == "Downloading airport details: batch 5 of 25" and f3 == pytest.approx(0.62)
    assert job["fraction"] == 1.0 and "_downloaded" not in job


def test_the_bar_never_goes_backwards_when_the_total_grows(make):
    client, load = reporting(make, [("stations", 50, 100), ("stations", 55, 200), ("stations", 60, 200)])
    run(client, source="recommended", target=30, start_fresh=True)
    fractions = [f for _l, f in load.seen]
    assert fractions[1] == fractions[0] == pytest.approx(0.3)  # 55/200 would be lower: held
    assert fractions == sorted(fractions)
    assert load.seen[1][0] == "Downloading stations: tile 55 of 200"


def test_a_bad_progress_value_is_ignored_and_never_raises(make):
    bad = [("stations", "x", 10), ("stations", 1, 0), ("stations", True, 3), ("nope", 1, 2), ("stations", None, None)]
    client, load = reporting(make, bad + [("stations", 3, 10)])
    job = run(client, source="recommended", target=30, start_fresh=True)
    assert job["ok"], job
    assert [label for label, _f in load.seen[:-1]] == ["Fetching airports from aviationweather.gov"] * len(bad)
    assert load.seen[-1][0] == "Downloading stations: tile 3 of 10"


class GrowingJob(dict):
    """A job dict that gains a key in the middle of any loop over its items(), as the planner thread does."""

    def items(self):
        real = iter(super().items())

        def walk():
            grown = False
            for pair in real:
                yield pair
                if not grown:
                    grown = True
                    self["_late"] = True  # the size changes while the loop is part way through

        return walk()


def test_progress_survives_a_key_added_while_it_is_copied(make):
    # looping over job.items() in the HTTP thread raised "dictionary changed size during iteration": a 500, and the
    # page stopped polling while the job went on
    planner = make().planner
    planner.job = GrowingJob(planner_web.NO_JOB, done=False, label="Downloading stations: tile 1 of 9", _x=1)
    got = planner.progress()
    assert got["label"] == "Downloading stations: tile 1 of 9" and "_x" not in got


def test_progress_survives_another_thread_changing_the_job(make):
    planner = make().planner
    planner.job = dict(planner_web.NO_JOB, done=False, label="x")
    stop = threading.Event()

    def change():  # the keys that appear while a job runs (_downloaded, fetched_at, stale), and go
        while not stop.is_set():
            planner.job["_downloaded"] = True
            planner.job["fetched_at"] = "now"
            del planner.job["_downloaded"], planner.job["fetched_at"]

    thread = threading.Thread(target=change, daemon=True)
    switch = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)  # threads swap far more often, so the window the bug needs is hit
    thread.start()
    try:
        for _ in range(3000):
            assert planner.progress()["label"] == "x"
    finally:
        sys.setswitchinterval(switch)
        stop.set()
        thread.join(5)


def test_a_cache_hit_is_a_note_in_the_result_not_a_label(make):
    saved = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    shown = []

    class Cached(FakeLoad):
        def __call__(self, box, clock=None, **kwargs):
            return super().__call__(box, clock=clock)._replace(fetched_at=saved)

    client = make(Cached())
    orig = client.planner._step

    def spy(job, cancel, fraction, label):
        shown.append(label)
        orig(job, cancel, fraction, label)

    client.planner._step = spy
    job = run(client, source="recommended", target=30, start_fresh=True)
    assert job["ok"], job
    assert "The airports came from the copy saved 1 minute ago." in job["result"]["notes"]
    assert not any(label.startswith("Using the airports") for label in shown)  # no status label for it any more


def test_airports_just_downloaded_have_no_cache_note(make):
    job = run(make(), source="recommended", target=30, start_fresh=True)
    assert job["ok"] and not any("copy saved" in n for n in job["result"]["notes"])


def test_a_cancelled_download_keeps_its_cancelling_label(make):
    gate = threading.Event()
    holder = []

    class Slow(FakeLoad):
        def __call__(self, box, clock=None, progress=None, **kwargs):
            gate.wait(10)
            progress("stations", 5, 10)  # after Cancel: ignored
            holder.append(True)
            return super().__call__(box, clock=clock)

    client = make(Slow())
    status, _body = post(client, source="recommended", target=30, start_fresh=True)
    assert status == 202
    client("/config/planner/cancel", method="POST", body={})
    gate.set()
    job = wait(client)
    assert job["cancelled"] and holder
    assert not job["label"].startswith("Downloading")


def test_a_loader_without_progress_still_works(make):
    class Old:
        def __call__(self, box, clock=None):
            return FakeLoad()(box)

    client = make(Old())
    assert run(client, source="recommended", target=30, start_fresh=True)["ok"]
