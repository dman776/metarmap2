"""
Tests for live traffic (metarmap.traffic): the area asked about, reading adsb.fi's answer, and how often it's asked.
"""

import json
import math
from types import SimpleNamespace

import pytest
import requests

from metarmap import traffic
from metarmap.settings import MapPage
from metarmap.traffic import Traffic

HOUSTON = [(29.6454, -95.2789), (29.9844, -95.3414), (31.3069, -95.4038)]  # KHOU, KIAH, KDKR

# one aircraft as adsb.fi sends it (trimmed), and one on the ground
FLYING = {
    "hex": "a0822c",
    "flight": "UCA4878 ",
    "r": "N13161",
    "t": "E45X",
    "desc": "EMBRAER ERJ-145XR",
    "ownOp": "UNITED AIRLINES INC",
    "alt_baro": 2450,
    "alt_geom": 2625,
    "gs": 211.0,
    "track": 90.54,
    "baro_rate": -1152,
    "squawk": "4561",
    "emergency": "none",
    "category": "A2",
    "lat": 30.006683,
    "lon": -95.498765,
    "seen_pos": 0.5,
    "seen": 0.1,
}
PARKED = {
    "hex": "a1b2c3",
    "r": "N12345",
    "t": "C172",
    "alt_baro": "ground",
    "gs": 0,
    "lat": 29.65,
    "lon": -95.28,
    "seen_pos": 2,
}


class FakeResponse:
    def __init__(self, data=None, status=200):
        self.data = data if data is not None else {"ac": [FLYING, PARKED], "now": 0}
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self.data


class FakeAdsbFi:
    """
    Counts requests; answers with `responses` in turn (the last one again once they run out). clock: to note when
    each request was made (in `times`).
    """

    def __init__(self, *responses, clock=None):
        self.responses = list(responses) or [FakeResponse()]
        self.urls = []
        self.times = []
        self.clock = clock

    def __call__(self, url, **kwargs):
        self.urls.append(url)
        if self.clock:
            self.times.append(self.clock())
        answer = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(answer, Exception):
            raise answer
        return answer


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class Jobs(list):
    """Stands in for a background thread: keeps what would run in it, for a test to run when it says (run())."""

    def run(self):
        while self:
            self.pop(0)()


def make(get=None, seconds=5, ground=False, points=HOUSTON, clock=None):
    settings = MapPage(traffic_seconds=seconds, traffic_ground=ground)
    clock = clock or Clock()

    def sleep(seconds):
        clock.t += seconds

    jobs = Jobs()
    t = Traffic(lambda: settings, lambda: points, get=get or FakeAdsbFi(), clock=clock, sleep=sleep, spawn=jobs.append)
    t.jobs = jobs
    return t, settings, clock


# ---- the area -------------------------------------------------------------------------------------------------


def test_area_covers_every_airport_with_a_margin():
    (lat, lon), radius = traffic.area(HOUSTON)
    assert lat == pytest.approx((29.6454 + 31.3069) / 2) and lon == pytest.approx((-95.2789 + -95.4038) / 2)
    farthest = max(traffic.distance_nm((lat, lon), p) for p in HOUSTON)
    assert farthest + traffic.MARGIN_NM <= radius < farthest + traffic.MARGIN_NM + 1


def test_area_is_at_most_what_adsb_fi_allows():
    assert traffic.area([(25.0, -125.0), (49.0, -67.0)])[1] == traffic.MAX_RADIUS_NM


def test_no_area_without_airports():
    assert traffic.area([]) is None


def test_distance():
    assert traffic.distance_nm((0, 0), (1, 0)) == pytest.approx(60, rel=0.01)  # a degree of latitude


# ---- reading adsb.fi's answer ---------------------------------------------------------------------------------


def test_parse():
    flying, parked = traffic.parse({"ac": [FLYING, PARKED]}, fetched=1000.0)
    assert flying == {
        "hex": "a0822c",
        "flight": "UCA4878",
        "reg": "N13161",
        "type": "E45X",
        "desc": "EMBRAER ERJ-145XR",
        "operator": "UNITED AIRLINES INC",
        "lat": 30.006683,
        "lon": -95.498765,
        "ground": False,
        "alt": 2450,
        "gs": 211.0,
        "track": 90.54,
        "vrate": -1152,
        "squawk": "4561",
        "emergency": None,
        "category": "A2",
        "kind": "small",
        "at": 999.5,
    }
    assert parked["ground"] is True and parked["alt"] is None and parked["flight"] is None


@pytest.mark.parametrize("change", [{"lat": None}, {"lon": "x"}, {"hex": ""}, {"seen_pos": 61}])
def test_parse_skips_aircraft_without_a_usable_position(change):
    assert traffic.parse({"ac": [{**FLYING, **change}]}, fetched=1000.0) == []


def test_parse_falls_back_to_other_fields():
    (a,) = traffic.parse(
        {
            "ac": [
                {
                    **FLYING,
                    "alt_baro": None,
                    "track": None,
                    "true_heading": 45,
                    "baro_rate": None,
                    "geom_rate": 300,
                    "seen_pos": None,
                    "emergency": "general",
                }
            ]
        },
        fetched=1000.0,
    )
    assert (a["alt"], a["track"], a["vrate"], a["at"], a["emergency"]) == (2625, 45, 300, 999.9, "general")


@pytest.mark.parametrize(
    "category, type_code, kind",
    [
        ("A1", "C172", "light"),
        ("A2", "E145", "small"),
        ("A3", "B738", "large"),
        ("A4", "B752", "large"),
        ("A5", "B77W", "heavy"),
        ("A5", "A388", "super"),  # the category can't tell an A380 from a 777
        (None, "B748", "super"),
        ("A7", "B407", "helicopter"),
        ("A1", "R44", "helicopter"),  # many helicopters send A1
        (None, "EC35", "helicopter"),
        ("B1", "DG1T", "glider"),
        ("B2", None, "balloon"),
        ("B6", None, "drone"),
        ("C1", None, "vehicle"),
        (None, None, "unknown"),
        ("A0", "ZZZZ", "unknown"),  # no category information
    ],
)
def test_kind(category, type_code, kind):
    assert traffic.kind_of(category, type_code) == kind


def test_parse_gives_each_aircraft_its_kind():
    flying, parked = traffic.parse({"ac": [FLYING, PARKED]}, fetched=1000.0)
    assert (flying["kind"], parked["kind"]) == ("small", "unknown")


@pytest.mark.parametrize("data", [None, {}, {"ac": None}, {"msg": "No error", "ac": []}])
def test_parse_empty(data):
    assert traffic.parse(data, fetched=1000.0) == []


# ---- how often adsb.fi is asked -------------------------------------------------------------------------------


def test_snapshot():
    adsb = FakeAdsbFi()
    t, _, clock = make(get=adsb)
    state = t.snapshot()
    assert len(adsb.urls) == 1
    assert adsb.urls[0] == "https://opendata.adsb.fi/api/v3/lat/30.4761/lon/-95.3414/dist/75"
    assert [a["hex"] for a in state["aircraft"]] == ["a0822c"]  # not the one on the ground
    assert state["fetched"] == clock.t and state["error"] is None and state["interval"] == 5
    assert state["center"] == pytest.approx([30.47615, -95.34135]) and state["radius"] <= traffic.MAX_RADIUS_NM
    assert state["source"]["name"] == "adsb.fi"


def test_one_fetch_per_interval_however_many_pages_ask():
    adsb = FakeAdsbFi()
    t, _, clock = make(get=adsb, seconds=5)
    for _ in range(10):
        t.snapshot()
    assert len(adsb.urls) == 1
    clock.t += 4.9
    t.snapshot()
    assert len(adsb.urls) == 1
    clock.t += 0.1
    t.snapshot()
    assert len(adsb.urls) == 2


def test_interval_is_the_setting():
    t, _, _ = make(seconds=10)
    assert t.interval() == 10


def test_a_changed_interval_applies_at_once():
    adsb = FakeAdsbFi()
    t, settings, clock = make(get=adsb, seconds=30)
    t.snapshot()
    settings.traffic_seconds = 5
    clock.t += 5
    t.snapshot()
    assert len(adsb.urls) == 2


def test_ground_traffic_follows_the_setting_without_a_new_fetch():
    adsb = FakeAdsbFi()
    t, settings, _ = make(get=adsb)
    assert len(t.snapshot()["aircraft"]) == 1
    settings.traffic_ground = True
    assert len(t.snapshot()["aircraft"]) == 2
    assert len(adsb.urls) == 1


def test_failures_wait_longer_each_time_and_keep_the_last_aircraft():
    adsb = FakeAdsbFi(
        FakeResponse(),
        requests.exceptions.ConnectionError("down"),
        requests.exceptions.ConnectionError("down"),
        FakeResponse(),
    )
    t, _, clock = make(get=adsb, seconds=5)
    t.snapshot()
    clock.t += 5
    state = t.snapshot()
    assert "couldn't reach adsb.fi" in state["error"]
    assert len(state["aircraft"]) == 1 and state["fetched"] == clock.t - 5  # what it had before
    clock.t += 9.9
    t.snapshot()
    assert len(adsb.urls) == 2  # waits 10 s (twice the interval) after a failure
    clock.t += 0.1
    t.snapshot()
    assert len(adsb.urls) == 3
    clock.t += 19.9
    t.snapshot()
    assert len(adsb.urls) == 3  # then 20 s
    clock.t += 0.1
    assert t.snapshot()["error"] is None
    clock.t += 5
    t.snapshot()
    assert len(adsb.urls) == 5  # back to every 5 s once it works


def test_backoff_has_a_limit():
    t, _, clock = make(get=FakeAdsbFi(requests.exceptions.ConnectionError("down")))
    for _ in range(20):
        t.snapshot()
        clock.t += traffic.MAX_BACKOFF
    assert next(iter(t._places.values())).backoff == traffic.MAX_BACKOFF


def test_too_many_requests_waits_at_least_a_minute():
    adsb = FakeAdsbFi(FakeResponse(status=429), FakeResponse())
    t, _, clock = make(get=adsb, seconds=2)
    assert "too many requests" in t.snapshot()["error"]
    clock.t += traffic.RATE_LIMITED - 1
    t.snapshot()
    assert len(adsb.urls) == 1
    clock.t += 1
    assert t.snapshot()["error"] is None


@pytest.mark.parametrize(
    "answer", [FakeResponse(status=500), FakeResponse(data="not json"), requests.exceptions.Timeout("slow")]
)
def test_bad_answers_are_errors(answer):
    if isinstance(answer, FakeResponse) and answer.data == "not json":
        answer.json = lambda: (_ for _ in ()).throw(ValueError("not json"))
    t, _, _ = make(get=FakeAdsbFi(answer))
    state = t.snapshot()
    assert state["error"] and state["aircraft"] == []


def test_no_airport_positions_yet():
    adsb = FakeAdsbFi()
    t, _, _ = make(get=adsb, points=[])
    assert t.snapshot()["error"] == "no airport positions yet"
    assert adsb.urls == []


def test_a_page_arriving_during_a_fetch_gets_what_is_there():
    t, _, _ = make()
    t._fetching.acquire()  # another page's fetch is under way
    try:
        state = t.snapshot()
    finally:
        t._fetching.release()
    assert state["fetched"] is None and state["aircraft"] == []


def test_sends_its_own_user_agent():
    seen = SimpleNamespace(headers=None)

    def get(url, **kwargs):
        seen.headers = kwargs["headers"]
        return FakeResponse()

    make(get=get)[0].snapshot()
    assert seen.headers["User-Agent"].startswith("metarmap2/")


# ---- following the map's view -----------------------------------------------------------------------------------

NYC = (40.7128, -74.0060, 60)  # lat, lon, radius in NM of what a page shows


def test_cover_snaps_to_a_grid_and_a_few_radii():
    (lat, lon), radius = traffic.cover(40.7128, -74.0060, 60)
    assert (lat, lon) == (40.75, -74.0) and radius in traffic.RADII
    assert traffic.distance_nm((40.7128, -74.0060), (lat, lon)) + 60 <= radius


def test_nearby_views_get_the_same_circle():
    assert traffic.cover(40.71, -74.01, 60) == traffic.cover(40.74, -73.98, 58)


@pytest.mark.parametrize("lat", [0, 25, 47, 60, 70])
def test_a_view_up_to_the_limit_is_always_covered(lat):
    for lon in (-123.9, -95.13, -74.02, 0.07):
        for dlat in (0, 0.05, 0.1, 0.124):
            for nm in (100, 238, 245, traffic.MAX_RADIUS_NM):
                (clat, clon), radius = traffic.cover(lat + dlat, lon + dlat, nm)
                assert radius <= traffic.MAX_RADIUS_NM  # what adsb.fi gives
                assert traffic.distance_nm((lat + dlat, lon + dlat), (clat, clon)) + nm <= radius + 0.01


def test_the_widest_views_get_their_own_circle():
    assert traffic.cover(40.0, -100.0, 249.5) == ((40.0, -100.0), 250)


def test_a_view_wider_than_one_circle_has_no_single_circle():
    assert traffic.cover(40.0, -100.0, traffic.MAX_RADIUS_NM + 1) is None


def test_a_view_is_fetched_around_itself():
    adsb = FakeAdsbFi()
    t, _, _ = make(get=adsb)
    state = t.snapshot(NYC)
    assert adsb.urls == [f"https://opendata.adsb.fi/api/v3/lat/40.7500/lon/-74.0000/dist/{state['radius']}"]
    assert state["center"] == [40.75, -74.0] and not state["too_wide"] and len(state["aircraft"]) == 1


def test_pages_looking_at_the_same_place_share_a_fetch():
    adsb = FakeAdsbFi()
    t, _, _ = make(get=adsb)
    t.snapshot(NYC)
    t.snapshot((40.74, -73.98, 58))
    assert len(adsb.urls) == 1


def test_a_view_too_wide_gets_no_aircraft_and_no_fetch():
    adsb = FakeAdsbFi()
    t, _, _ = make(get=adsb)
    state = t.snapshot((45.0, -110.0, traffic.MAX_VIEW_NM + 1))
    assert state["too_wide"] and state["aircraft"] == [] and state["max_view"] == traffic.MAX_VIEW_NM == 500
    assert adsb.urls == [] and t.jobs == []


def test_adsb_fi_is_asked_at_most_once_a_second_wherever_pages_look():
    adsb = FakeAdsbFi()
    t, _, clock = make(get=adsb)
    t.snapshot(NYC)
    state = t.snapshot((29.98, -95.34, 60))  # another place, right after
    assert len(adsb.urls) == 1 and state["fetched"] is None  # it's loading: its page asks again
    clock.t += traffic.MIN_GAP
    t.snapshot(NYC)  # a place that has been fetched before is only held back by the gap, which has passed
    assert len(adsb.urls) == 1  # (it isn't due yet)
    clock.t += 5
    assert t.snapshot((29.98, -95.34, 60))["fetched"] == clock.t
    assert len(adsb.urls) == 2


def test_only_one_new_place_starts_per_interval():
    adsb = FakeAdsbFi()
    t, _, clock = make(get=adsb, seconds=5)
    for i in range(12):  # a script that keeps changing its view, twice a second
        t.snapshot((30.0 + i, -95.0, 40))
        t.jobs.run()  # the background fetch starts at once
        clock.t += 0.5
    assert len(adsb.urls) == 2  # at t=0 and t=5: not one every 1.1 s, not even in the background


def test_a_new_view_starts_once_the_last_one_to_start_has_been_left():
    adsb = FakeAdsbFi()
    t, _, clock = make(get=adsb, seconds=30)
    t.snapshot((30.0, -95.0, 40))
    clock.t += traffic.ABANDONED_SECONDS + 0.1  # nobody asked about it since: the page has moved on
    t.snapshot((31.0, -95.0, 40))
    assert len(adsb.urls) == 2  # well within the 30 s interval


def test_too_many_requests_stops_every_place():
    adsb = FakeAdsbFi(FakeResponse(status=429), FakeResponse())
    t, _, clock = make(get=adsb, seconds=2)
    t.snapshot(NYC)
    clock.t += 30
    t.snapshot((29.98, -95.34, 60))
    assert len(adsb.urls) == 1
    clock.t += traffic.RATE_LIMITED
    assert t.snapshot((29.98, -95.34, 60))["error"] is None


def test_places_nobody_asks_about_are_forgotten():
    t, _, clock = make()
    t.snapshot(NYC)
    clock.t += traffic.KEEP_SECONDS + 1
    t.snapshot((29.98, -95.34, 60))
    assert len(t._places) == 1


def test_only_so_many_places_are_kept():
    t, _, clock = make()
    for i in range(traffic.MAX_PLACES + 5):
        clock.t += 2
        t.snapshot((30.0 + i, -95.0, 40))
    assert len(t._places) == traffic.MAX_PLACES


def test_the_json_is_the_snapshot_serialized_once_per_fetch(monkeypatch):
    t, settings, clock = make()
    text = t.snapshot_json(NYC)
    assert json.loads(text) == t.snapshot(NYC)
    assert " " not in text.split('"aircraft"')[0]  # compact
    dumps = []
    real = json.dumps
    monkeypatch.setattr(traffic.json, "dumps", lambda *a, **k: dumps.append(1) or real(*a, **k))
    t.snapshot_json(NYC)
    t.snapshot_json(NYC)
    assert len(dumps) == 2  # the head each time, the aircraft not at all
    settings.traffic_ground = True
    assert len(json.loads(t.snapshot_json(NYC))["aircraft"]) == 2


def test_the_json_of_a_view_too_wide():
    state = json.loads(make()[0].snapshot_json((45.0, -110.0, 600)))
    assert state["too_wide"] and state["aircraft"] == []


def test_a_view_that_takes_in_every_airport_is_still_too_wide_past_the_limit():
    adsb = FakeAdsbFi()
    t, _, _ = make(get=adsb)
    state = t.snapshot((30.4761, -95.3414, 600))  # all of HOUSTON is in it, but it is wider than the limit
    assert state["too_wide"] and state["aircraft"] == [] and adsb.urls == []


def test_a_view_up_to_250_nm_is_shown():
    adsb = FakeAdsbFi()
    t, _, _ = make(get=adsb)
    state = t.snapshot((30.4761, -95.3414, 245))
    assert not state["too_wide"] and state["radius"] <= 250 and len(adsb.urls) == 1


def test_every_place_says_when_adsb_fi_told_one_to_wait():
    adsb = FakeAdsbFi(FakeResponse(status=429), FakeResponse())
    t, _, clock = make(get=adsb, seconds=2)
    t.snapshot(NYC)
    clock.t += 10
    other = t.snapshot((29.98, -95.34, 60))  # never fetched, and nobody is asking until the wait is over
    assert other["error"] == traffic.TOO_MANY and other["fetched"] is None and len(adsb.urls) == 1
    clock.t += traffic.RATE_LIMITED
    assert t.snapshot((29.98, -95.34, 60))["error"] is None


def test_one_place_failing_doesnt_slow_the_others():
    adsb = FakeAdsbFi(requests.exceptions.ConnectionError("down"), FakeResponse())
    t, _, clock = make(get=adsb, seconds=2)
    t.snapshot(NYC)
    clock.t += 6  # past the new-place wait
    assert t.snapshot((29.98, -95.34, 60))["error"] is None


# ---- a view wider than one circle -------------------------------------------------------------------------------


def leaflet_view(lat, lon, width, height, nm):
    """
    What the Map page sends for a Web Mercator view of width x height (any units) around lat, lon whose corners are
    about nm away: (lat, lon, nm, half-height, half-width), the center being the box's middle as Leaflet's getCenter()
    gives it, nm its farthest corner rounded up, as map.js works them out.
    """

    def build(scale):
        y = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
        north = math.degrees(2 * math.atan(math.exp(y + height / 2 * scale)) - math.pi / 2)
        south = math.degrees(2 * math.atan(math.exp(y - height / 2 * scale)) - math.pi / 2)
        dlon = math.degrees(width / 2 * scale)
        middle = ((north + south) / 2, lon)
        far = max(traffic.distance_nm(middle, (north, lon + dlon)), traffic.distance_nm(middle, (south, lon - dlon)))
        return middle[0], lon, math.ceil(far), (north - south) / 2, dlon

    lo, hi = 1e-6, 0.5
    for _ in range(50):
        if build((lo + hi) / 2)[2] > nm:
            hi = (lo + hi) / 2
        else:
            lo = (lo + hi) / 2
    return build(lo)


def uncovered(view, circles, steps=20):
    """The points on the view's box (its edges and a grid inside) that no circle holds."""
    lat, lon, _, dlat, dlon = view
    points = [
        (lat - dlat + 2 * dlat * i / steps, lon - dlon + 2 * dlon * j / steps)
        for i in range(steps + 1)
        for j in range(steps + 1)
    ]
    return [p for p in points if all(traffic.distance_nm(p, c) > r + 0.01 for c, r in circles)]


@pytest.mark.parametrize("lat", [-60, 0, 25, 40, 55, 70])
@pytest.mark.parametrize("width, height", [(1, 1), (16, 9), (9, 16), (21, 9), (9, 19.5), (3, 1), (1, 3)])
@pytest.mark.parametrize("nm", [260, 380, traffic.MAX_VIEW_NM])
def test_a_wide_view_is_covered_corner_to_corner_by_a_few_circles(lat, width, height, nm):
    view = leaflet_view(lat, -95.3, width, height, nm)
    assert 250 < view[2] <= traffic.MAX_VIEW_NM
    circles = traffic.covering(*view)
    assert 4 <= len(circles) <= 6
    assert all(radius <= traffic.MAX_RADIUS_NM for _, radius in circles)  # what adsb.fi gives
    assert uncovered(view, circles) == []
    lat, lon, _, dlat, dlon = view
    for corner in (
        (lat + dlat, lon + dlon),
        (lat + dlat, lon - dlon),
        (lat - dlat, lon + dlon),
        (lat - dlat, lon - dlon),
    ):
        assert any(traffic.distance_nm(corner, c) <= r for c, r in circles)


def test_a_wide_view_without_its_box_is_taken_as_a_square():
    for lat in (0, 30, 45, 60):
        circles = traffic.covering(lat, -95.0, traffic.MAX_VIEW_NM)
        dlat, dlon = traffic.square(lat, traffic.MAX_VIEW_NM)
        assert circles and uncovered((lat, -95.0, traffic.MAX_VIEW_NM, dlat, dlon), circles) == []


def test_a_wide_view_across_the_dateline():
    view = leaflet_view(52.0, 179.5, 16, 9, 450)
    circles = traffic.covering(*view)
    assert all(-180 <= c[1] <= 180 for c, _ in circles) and uncovered(view, circles) == []


def test_a_wide_view_at_mid_zoom_shares_snapped_circles():
    circles = traffic.covering(40.7128, -74.006, 300, 3.0, 4.0)
    assert len(circles) == 4 and all(r in traffic.RADII for _, r in circles)
    assert traffic.covering(40.72, -74.01, 300, 3.0, 4.0) == circles  # a little pan: the same circles


def test_covering_up_to_one_circle_is_that_circle():
    assert traffic.covering(40.7128, -74.006, 60) == (traffic.cover(40.7128, -74.006, 60),)
    assert traffic.covering(40.7128, -74.006, 250, 2.5, 3.0) == (traffic.cover(40.7128, -74.006, 250),)


def test_covering_refuses_a_view_too_wide_or_a_box_too_big():
    assert traffic.covering(40.0, -100.0, traffic.MAX_VIEW_NM + 1) is None
    assert traffic.covering(40.0, -100.0, 300, 20.0, 30.0) is None  # a box far bigger than its nm says


def aircraft(hex_code, lat=30.0, lon=-95.0, at=1000.0):
    return {"hex": hex_code, "lat": lat, "lon": lon, "at": at, "ground": False}


def test_merge_keeps_each_aircraft_once_at_its_newest():
    old, new = aircraft("a1", at=990.0, lat=30.0), aircraft("a1", at=995.0, lat=30.1)
    merged = traffic.merge([[old, aircraft("b2")], [new, aircraft("c3")]])
    assert sorted(a["hex"] for a in merged) == ["a1", "b2", "c3"]
    assert next(a for a in merged if a["hex"] == "a1") is new


def test_merge_keeps_the_ones_nearest_the_middle_past_its_limit():
    many = [aircraft(f"{i:06x}", lat=30.0 + i / 100) for i in range(10)]
    merged = traffic.merge([many[5:], many[:5]], center=(30.0, -95.0), limit=3)
    assert [a["hex"] for a in merged] == ["000000", "000001", "000002"]


WIDE = (39.0, -98.0, 480, 5.0, 8.0)  # a wide view over the middle of the US: four or more circles


def wide_traffic(get=None, seconds=5):
    clock = Clock()
    adsb = get or FakeAdsbFi(clock=clock)
    if get is not None:
        get.clock = clock
    t, settings, _ = make(get=adsb, seconds=seconds, clock=clock)
    return t, adsb, clock


def test_a_wide_view_fetches_one_circle_and_answers_at_once():
    t, adsb, clock = wide_traffic()
    circles = traffic.covering(*WIDE)
    state = t.snapshot(WIDE)
    assert len(adsb.urls) == 1 and clock.t == 1000.0  # the page isn't kept waiting for the others
    assert state["loading"] and state["fetched"] == 1000.0 and len(state["circles"]) == len(circles)
    assert [c["fetched"] for c in state["circles"]].count(None) == len(circles) - 1
    assert len(t.jobs) == 1  # the rest are fetched in the background


def test_a_wide_view_fetches_its_other_circles_in_the_background_at_most_once_a_second():
    t, adsb, clock = wide_traffic()
    circles = traffic.covering(*WIDE)
    t.snapshot(WIDE)
    t.jobs.run()
    assert len(adsb.urls) == len(circles)
    assert all(b - a >= traffic.MIN_GAP for a, b in zip(adsb.times, adsb.times[1:]))
    state = t.snapshot(WIDE)
    assert not state["loading"] and all(c["fetched"] for c in state["circles"])
    assert state["fetched"] == adsb.times[0]  # the oldest of them


def test_aircraft_seen_by_several_circles_are_shown_once():
    t, adsb, _ = wide_traffic()  # every circle answers with the same two aircraft
    t.snapshot(WIDE)
    t.jobs.run()
    state = t.snapshot(WIDE)
    assert [a["hex"] for a in state["aircraft"]] == ["a0822c"]  # and not the one on the ground


def test_a_wide_view_says_where_its_aircraft_are_from():
    t, _, _ = wide_traffic()
    state = t.snapshot(WIDE)
    assert state["center"] == [39.0, -98.0]
    for c in state["circles"]:
        assert traffic.distance_nm((39.0, -98.0), c["center"]) + c["radius"] <= state["radius"]
        assert c["radius"] <= traffic.MAX_RADIUS_NM
    assert state["max_view"] == 500 and not state["too_wide"]


def test_many_pages_and_wide_views_never_ask_more_than_once_a_second():
    t, adsb, clock = wide_traffic(seconds=2)
    views = [WIDE, (45.0, -110.0, 400, 4.5, 8.0), NYC, (29.98, -95.34, 60), (39.1, -97.9, 470, 5.0, 8.0)]
    for step in range(120):
        t.snapshot(views[step % len(views)])
        if step % 3 == 0:
            t.jobs.run()
        clock.t += 0.35
    assert len(adsb.urls) > 20
    assert all(b - a >= traffic.MIN_GAP - 1e-9 for a, b in zip(adsb.times, adsb.times[1:]))


def test_only_one_new_wide_view_starts_per_interval():
    t, adsb, clock = wide_traffic(seconds=5)
    other = (45.0, -110.0, 400, 4.5, 8.0)
    pages = [lambda at: WIDE, lambda at: other if at >= 0.1 else None]  # another page, somewhere new, right after
    simulate(t, clock, pages, seconds=4.9)
    assert set(adsb.urls) == set(map(url_of, traffic.covering(*WIDE)))  # the first view's circles only
    simulate(t, clock, pages, seconds=5)
    assert set(map(url_of, traffic.covering(*other))) & set(adsb.urls)  # then the other one starts


def test_too_many_requests_stops_the_background_fetch_and_every_circle():
    t, adsb, clock = wide_traffic(FakeAdsbFi(FakeResponse(), FakeResponse(status=429), FakeResponse()))
    t.snapshot(WIDE)
    t.jobs.run()
    assert len(adsb.urls) == 2  # stopped at the 429
    blocked = adsb.times[1] + traffic.RATE_LIMITED
    state = t.snapshot(WIDE)
    assert state["error"] == traffic.TOO_MANY and not state["loading"] and len(state["aircraft"]) == 1
    for _ in range(20):  # the page keeps asking every 5 s
        clock.t += 5
        t.snapshot(WIDE)
        t.jobs.run()
    later = adsb.times[2:]
    assert later and all(at >= blocked for at in later)  # nobody asks until the wait is over
    assert t.snapshot(WIDE)["error"] is None


def test_the_background_fetch_leaves_alone_what_pages_no_longer_ask_for():
    t, adsb, clock = wide_traffic(seconds=5)
    t.snapshot(WIDE)
    t.jobs.run()
    count = len(adsb.urls)
    clock.t += 30
    t.snapshot(NYC)  # the page moved on
    t.jobs.run()
    assert len(adsb.urls) == count + 1  # NYC only, not the wide view's old circles


def test_the_background_fetch_survives_an_error():
    t, adsb, clock = wide_traffic()
    t.snapshot(WIDE)
    t._sleep = lambda seconds: 1 / 0
    t.jobs.run()  # logged, not raised
    assert t._working is False
    t._sleep = lambda seconds: setattr(clock, "t", clock.t + seconds)
    t.snapshot(WIDE)
    t.jobs.run()  # and it starts again
    assert len(adsb.urls) == len(traffic.covering(*WIDE))


def test_an_answer_has_at_most_so_many_aircraft(monkeypatch):
    monkeypatch.setattr(traffic, "MAX_AIRCRAFT", 2)
    crowd = {"ac": [{**FLYING, "hex": f"{i:06x}", "lat": 30.0 + i / 10} for i in range(5)]}
    t, _, _ = make(get=FakeAdsbFi(FakeResponse(crowd)))
    assert len(t.snapshot()["aircraft"]) == 2


def test_the_json_of_a_wide_view_is_the_snapshot():
    t, _, _ = wide_traffic()
    t.snapshot(WIDE)
    t.jobs.run()
    assert json.loads(t.snapshot_json(WIDE)) == t.snapshot(WIDE)


def test_a_wide_view_has_each_circle_fetched_about_once_an_interval():
    t, adsb, clock = wide_traffic(seconds=5)
    circles = traffic.covering(*WIDE)
    end, poll = clock.t + 60, clock.t
    while clock.t < end:  # a page that asks once an interval
        clock.t = max(clock.t, poll)
        t.snapshot(WIDE)
        t.jobs.run()
        poll += 5
    for c, r in circles:
        times = [
            at for url, at in zip(adsb.urls, adsb.times) if url == traffic.API_URL.format(lat=c[0], lon=c[1], dist=r)
        ]
        assert len(times) >= 10 and all(b - a < 5 + 2 * traffic.MIN_GAP for a, b in zip(times, times[1:]))
    assert all(b - a >= traffic.MIN_GAP for a, b in zip(adsb.times, adsb.times[1:]))


def test_a_single_circle_view_starts_no_background_fetch():
    t, adsb, clock = wide_traffic(seconds=5)
    t.snapshot(NYC)
    clock.t += 2
    t.snapshot(NYC)  # a second page, within the interval
    t.snapshot()  # and the airports' circle
    clock.t += 1.2
    t.snapshot((29.98, -95.34, 60))
    assert t.jobs == [] and t._working is False


SIX = [(60.0, lon, 500) for lon in (-120.0, -60.0, 0.0)]  # three of the widest views, 6 circles each


def test_three_pages_with_the_widest_views_all_finish_loading():
    assert all(len(traffic.covering(*view)) == 6 for view in SIX)
    t, adsb, clock = wide_traffic(seconds=5)
    for _ in range(12):  # a minute, each page asking every 5 s
        for view in SIX:
            t.snapshot(view)
            t.jobs.run()
            assert len(t._places) <= traffic.MAX_PLACES
        clock.t += 5
    assert all(not t.snapshot(view)["loading"] for view in SIX)
    assert all(b - a >= traffic.MIN_GAP for a, b in zip(adsb.times, adsb.times[1:]))


def test_a_dropped_circle_of_a_started_view_is_fetched_again_without_waiting():
    t, adsb, clock = wide_traffic(seconds=5)
    t.snapshot(WIDE)
    t.jobs.run()
    dropped = traffic.covering(*WIDE)[-1]
    del t._places[dropped]  # as _forget() does when there are too many
    clock.t += 1.2  # well within the interval since the view started
    t.snapshot(WIDE)
    t.jobs.run()
    assert not t.snapshot(WIDE)["loading"]
    assert adsb.urls.count(traffic.API_URL.format(lat=dropped[0][0], lon=dropped[0][1], dist=dropped[1])) == 2


def test_dropped_places_and_their_aircraft_are_released(monkeypatch):
    import gc
    import weakref

    monkeypatch.setattr(traffic, "MAX_PLACES", 4)
    t, _, clock = wide_traffic(seconds=5)
    t.snapshot(WIDE)
    t.jobs.run()
    t.snapshot_json(WIDE)
    old = [weakref.ref(p) for p in t._places.values()]
    old_keys = set(t._places)
    clock.t += 30
    t.snapshot((45.0, -110.0, 400, 4.5, 8.0))  # another wide view: the first one's circles make room
    assert not old_keys & set(t._places)
    assert all(not old_keys & set(key[0]) for key in t._shown)
    gc.collect()
    assert all(ref() is None for ref in old)


def test_only_so_many_merged_answers_are_kept():
    t, _, clock = wide_traffic(seconds=5)
    for i in range(traffic.SHOWN_KEPT + 4):
        t.snapshot((30.0 + i, -95.0, 40))
        clock.t += 6
    assert len(t._shown) <= traffic.SHOWN_KEPT


def simulate(t, clock, pages, seconds, every=5, tick=0.05):
    """
    Pages asking /api/traffic for `seconds` as the Map page does: every `every` seconds, every 1.2 s while what it
    asked about is loading. Each page is a function of the time since the start that gives its view (None: closed).
    The background fetch runs alongside them as its thread would (its waits in real time, not jumping the clock past
    the pages). Returns each page's answers, [(time, view, state), ...].
    """
    start = clock.t
    asks = [start] * len(pages)
    answers = [[] for _ in pages]
    while clock.t < start + seconds:
        for i, page in enumerate(pages):
            view = page(clock.t - start)
            if view is not None and (clock.t >= asks[i] or (answers[i] and answers[i][-1][1] != view)):
                state = t.snapshot(view)
                answers[i].append((clock.t - start, view, state))
                loading = state["loading"] or (state["fetched"] is None and not state["error"])
                asks[i] = clock.t + (1.2 if loading and not state["too_wide"] else every)
                assert len(t._places) <= traffic.MAX_PLACES
        t.jobs.clear()  # the thread is this loop: it chooses again after each wait
        planned = t._plan() if t._working else None
        if planned and clock.t >= planned[1]:
            t._fetch_due(planned[0])
        clock.t += tick
    return answers


def run_pages(t, clock, views, seconds=120, every=5):
    """A page for each of views, looking at it all along (see simulate())."""
    return simulate(t, clock, [lambda _, v=view: v for view in views], seconds, every)


def url_of(circle):
    (lat, lon), radius = circle
    return traffic.API_URL.format(lat=lat, lon=lon, dist=radius)


@pytest.mark.parametrize(
    "views",
    [
        SIX + [(29.98, -95.34, 100), (40.71, -74.0, 100)],  # 20 circles
        SIX + [(60.0, 60.0, 500)],  # 24 circles
    ],
)
def test_more_circles_than_are_kept_make_the_newest_view_wait_not_churn(views):
    t, adsb, clock = wide_traffic(seconds=5)
    run_pages(t, clock, views)
    *shown, last = views
    assert all(not t.snapshot(view)["loading"] for view in shown)
    waiting = t.snapshot(last)
    assert waiting["loading"] and waiting["fetched"] is None
    assert not set(map(url_of, traffic.covering(*last))) & set(adsb.urls)  # nothing fetched for it
    for url in set(adsb.urls):  # every circle about once an interval, not again and again
        assert adsb.urls.count(url) <= 120 / 5 + 1
    # one page closes: the one waiting gets in
    first, *rest = views
    run_pages(t, clock, rest, seconds=60)
    assert not t.snapshot(last)["loading"]
    assert all(b - a >= traffic.MIN_GAP for a, b in zip(adsb.times, adsb.times[1:]))


def test_a_view_started_long_ago_counts_as_new_again():
    t, adsb, clock = wide_traffic(seconds=5)
    old = (30.0, -95.0, 40)
    t.snapshot(old)
    clock.t += traffic.KEEP_SECONDS + 30
    t.snapshot((32.0, -95.0, 40))  # another page: the old view's place is forgotten
    clock.t += 50
    t.snapshot(old)  # asked again: its start is long past, so it's a new view now
    assert len(adsb.urls) == 3
    clock.t += 1.2
    t.snapshot((35.0, -95.0, 40))  # another new view, right after: it waits its turn
    assert len(adsb.urls) == 3


def test_one_circle_is_cut_to_the_limit_around_its_own_center(monkeypatch):
    monkeypatch.setattr(traffic, "MAX_AIRCRAFT", 2)
    crowd = {"ac": [{**FLYING, "hex": f"{i:06x}", "lat": 40.75 + i / 10} for i in range(-3, 4)]}
    t, _, _ = make(get=FakeAdsbFi(FakeResponse(crowd)))
    a = t.snapshot((40.70, -74.0, 60))
    b = t.snapshot((40.80, -74.0, 60))  # the same circle, from another page
    assert a["center"] == b["center"] and a["aircraft"] == b["aircraft"]


def test_a_wide_view_is_cut_to_the_limit_around_its_own_center(monkeypatch):
    t, _, _ = wide_traffic()
    view = (40.7128, -74.006, 300, 3.0, 4.0)
    other = (40.8, -74.1, 300, 3.0, 4.0)  # the same circles
    assert traffic.covering(*view) == traffic.covering(*other)
    t.snapshot(view)
    t.snapshot(other)
    assert {key[2] for key in t._shown} == {(40.7128, -74.006), (40.8, -74.1)}


def test_one_circle_failing_in_a_wide_view_leaves_the_rest_shown():
    down = requests.exceptions.ConnectionError("down")
    t, adsb, clock = wide_traffic(FakeAdsbFi(down, FakeResponse()))  # the first circle fetched fails, the rest work
    t.snapshot(WIDE)
    t.jobs.run()
    state = t.snapshot(WIDE)
    assert [bool(c["error"]) for c in state["circles"]] == [True] + [False] * (len(state["circles"]) - 1)
    assert state["error"] is None and not state["loading"] and len(state["aircraft"]) == 1


def test_a_wide_view_says_so_when_every_circle_fails():
    t, _, _ = wide_traffic(FakeAdsbFi(requests.exceptions.ConnectionError("down")))
    t.snapshot(WIDE)
    t.jobs.run()
    state = t.snapshot(WIDE)
    assert "couldn't reach adsb.fi" in state["error"] and not state["loading"]


PANS = [(60.0, -120.0 + 3 * i, 500) for i in range(4)]  # one page panning a wide view, a step every 2 s


def test_panning_a_wide_view_gets_the_latest_view_its_aircraft_first():
    t, adsb, clock = wide_traffic(seconds=5)
    assert len({c for view in PANS for c in traffic.covering(*view)}) > traffic.MAX_PLACES  # they don't all fit
    (answers,) = simulate(t, clock, [lambda at: PANS[min(3, int(at // 2))]], seconds=20)
    last = [(at, state) for at, view, state in answers if view == PANS[3]]
    first_data = next(at for at, state in last if state["fetched"] is not None)
    assert first_data - 6 <= 3  # within a few seconds of the last pan
    assert not last[-1][1]["loading"] and all(c["fetched"] for c in last[-1][1]["circles"])
    for view in PANS[:3]:  # the views it moved on from aren't fetched in full
        assert sum(url_of(c) in adsb.urls for c in traffic.covering(*view)) < 6
    assert all(b - a >= traffic.MIN_GAP for a, b in zip(adsb.times, adsb.times[1:]))


def test_a_view_that_does_not_fit_is_not_fetched_however_long_it_waits():
    t, adsb, clock = wide_traffic(seconds=5)
    for i in range(traffic.MAX_PLACES):  # pages looking at that many places, asking all along
        t.snapshot((20.0 + i, -100.0, 40))
        clock.t += 6
    assert len(t._places) == traffic.MAX_PLACES
    for _ in range(3):
        clock.t += 6  # past MIN_GAP, the interval and the new-view wait
        for i in range(traffic.MAX_PLACES):
            t.snapshot((20.0 + i, -100.0, 40))
        state = t.snapshot((45.0, -60.0, 40))  # one more: no room
        t.jobs.run()  # (the others are fetched again, as they're due)
        assert state["loading"] and state["fetched"] is None
        assert url_of(traffic.covering(45.0, -60.0, 40)[0]) not in adsb.urls


def test_the_background_fetch_skips_a_circle_dropped_while_it_waited():
    t, adsb, clock = wide_traffic(seconds=5)
    t.snapshot(WIDE)
    place, start = t._plan()
    del t._places[place.key]  # dropped to make room meanwhile
    clock.t = max(clock.t, start) + 0.1
    t._fetch_due(place)
    assert url_of(place.key) not in adsb.urls
