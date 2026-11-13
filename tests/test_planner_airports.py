"""Tests for the Chart Planner's live airport data (planner/airports.py): tiles, filtering, batches, rank and cache."""

import json
import random
import threading
import time
from datetime import timedelta

import pytest
import requests

from metarmap.clock import FakeClock
from metarmap.planner import airports


class FakeResponse:
    def __init__(self, body, status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = headers or {}

    @property
    def status_code(self):
        return self.status

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status}")

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


class FakeApi:
    """aviationweather.gov: `stations` is the METAR list for a bbox (a function), `known` the airport details."""

    def __init__(
        self, stations=None, known=None, fail=(), retry_after=None, clock=None, latency=0.0, seed=0, barrier=None
    ):
        self.stations = stations or (lambda bbox: [])
        self.known = known or {}
        self.fail = list(fail)  # statuses to answer the next requests with, then everything works
        self.retry_after = retry_after  # the Retry-After header of a 429
        self.clock = clock  # when given, the clock time of each request is noted in `starts`
        self.latency = latency  # up to this many real seconds before it answers, at random
        self.barrier = barrier  # when given, a failing request waits on it before it is answered (all in flight)
        self.random = random.Random(seed)
        self.metar_boxes = []
        self.bbox_texts = []  # the bbox parameter exactly as sent
        self.airport_ids = []
        self.starts = []
        self.lock = threading.Lock()  # the workers call get() from several threads

    def get(self, url, params=None, **kwargs):
        with self.lock:
            if self.clock:
                self.starts.append(self.clock.time())
            status = self.fail.pop(0) if self.fail else None
            pause = self.random.random() * self.latency
        if pause:
            time.sleep(pause)
        if status and self.barrier:
            self.barrier.wait(10)
        if status == "network":
            raise requests.exceptions.ConnectionError("no network")
        if status:
            headers = {"Retry-After": self.retry_after} if status == 429 and self.retry_after else {}
            return FakeResponse([], status, headers)
        if url == airports.METAR_URL:
            bbox = tuple(float(x) for x in params["bbox"].split(","))
            with self.lock:
                self.metar_boxes.append(bbox)
                self.bbox_texts.append(params["bbox"])
            return FakeResponse(self.stations(bbox))
        ids = params["ids"].split(",")
        with self.lock:
            self.airport_ids.append(ids)
        return FakeResponse([self.known[i] for i in ids if i in self.known])


def report(code, lat=30.0, lon=-95.0, name="Test Field, TX, US"):
    return {"icaoId": code, "lat": lat, "lon": lon, "name": name}


def detail(code, tower="", passengers="0", rwyNum="1", runways=()):
    return {
        "icaoId": code,
        "tower": tower,
        "passengers": passengers,
        "rwyNum": rwyNum,
        "runways": [{"id": f"{i}", "dimension": d} for i, d in enumerate(runways)],
    }


class SafeClock(FakeClock):
    """A FakeClock the worker threads can share: advancing it is one step under a lock."""

    def __init__(self):
        super().__init__()
        self.lock = threading.Lock()

    def advance(self, seconds):
        with self.lock:
            super().advance(seconds)

    def time(self):
        with self.lock:
            return super().time()


class CancelClock(SafeClock):
    """What the planner's JobClock does: once `cancel` is set, time is infinite and waits end at once."""

    def __init__(self, cancel):
        super().__init__()
        self.cancel = cancel

    def time(self):
        return float("inf") if self.cancel.is_set() else super().time()

    def wait(self, event, seconds):
        return event.is_set() or self.cancel.is_set() or super().wait(event, seconds)


@pytest.fixture(autouse=True)
def one_worker(monkeypatch):
    """The older tests count requests in the order they go out: one worker, like the first version. The tests of the
    workers themselves pass workers=3."""
    monkeypatch.setattr(airports, "WORKERS", 1)


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def api(monkeypatch):
    def install(**kwargs):
        fake = FakeApi(**kwargs)
        monkeypatch.setattr(airports.requests, "get", fake.get)
        return fake

    return install


# ---- candidates --------------------------------------------------------------------------------------------


def test_a_small_box_is_one_request_with_its_own_bounds(api, clock):
    fake = api(stations=lambda bbox: [report("KHOU")])
    got = airports.candidates(-96, 29, -95, 30, clock=clock)
    assert fake.metar_boxes == [(29.0, -96.0, 30.0, -95.0)]
    assert [s.code for s in got.items] == ["KHOU"] and got.failed == 0


def test_the_bbox_sent_has_no_float_noise(api, clock):
    # the API answers 400 to 34.019999999999996 (31.52 + 2.5 in floats); it takes at most four decimals
    fake = api()
    airports.candidates(-95.7306, 31.52, -94.7655, 34.02, clock=clock)
    assert fake.bbox_texts and all(
        len(part.partition(".")[2]) <= 4 for text in fake.bbox_texts for part in text.split(",")
    )
    assert "31.52,-95.7306,34.02,-94.7655" in fake.bbox_texts


@pytest.mark.parametrize(
    "value, text",
    [
        (34.019999999999996, "34.02"),
        (30.0, "30"),
        (-96.0, "-96"),
        (-95.73064, "-95.7306"),
        (-0.00001, "0"),
        (0.5, "0.5"),
    ],
)
def test_a_coordinate_is_short_and_exact(value, text):
    assert airports._coordinate(value) == text


def test_a_big_box_is_fetched_in_tiles_that_cover_it(api, clock):
    fake = api()
    airports.candidates(-100, 25, -90, 35, clock=clock)  # 10 x 10 degrees: 4 x 4 tiles of 2.5
    assert len(fake.metar_boxes) == 16
    assert min(b[0] for b in fake.metar_boxes) == 25 and max(b[2] for b in fake.metar_boxes) == 35
    assert min(b[1] for b in fake.metar_boxes) == -100 and max(b[3] for b in fake.metar_boxes) == -90
    assert all(b[2] - b[0] <= airports.TILE_DEGREES and b[3] - b[1] <= airports.TILE_DEGREES for b in fake.metar_boxes)


def test_the_last_tile_stops_at_the_box_edge(api, clock):
    fake = api()
    airports.candidates(-96, 29, -92, 30, clock=clock)  # 4 degrees wide: tiles of 2.5 and 1.5
    assert sorted(fake.metar_boxes) == [(29.0, -96.0, 30.0, -93.5), (29.0, -93.5, 30.0, -92.0)]


def test_an_airport_on_a_tile_edge_is_listed_once(api, clock):
    api(stations=lambda bbox: [report("KHOU")])  # every tile answers with it
    got = airports.candidates(-100, 25, -90, 35, clock=clock)
    assert [s.code for s in got.items] == ["KHOU"]


def test_only_airports_are_kept(api, clock):
    reports = [
        report("KHOU"),
        report("K11R"),  # an FAA id with digits is an airport
        report("PHNL"),
        report("TJSJ"),
        report("42019"),  # a buoy
        report("EGLL"),  # not in the US
        report("KABC", lat=None),  # no position
        {"lat": 30, "lon": -95},  # no id
    ]
    api(stations=lambda bbox: reports)
    got = airports.candidates(-96, 29, -95, 30, clock=clock)
    assert [s.code for s in got.items] == ["K11R", "KHOU", "PHNL", "TJSJ"]


def test_a_station_is_named_without_its_state_and_country(api, clock):
    api(stations=lambda bbox: [report("KARG", lat=36.1, lon=-90.9, name="Walnut Ridge Rgnl, AR, US")])
    station = airports.candidates(-91, 36, -90, 37, clock=clock).items[0]
    assert station == airports.Station("KARG", "Walnut Ridge Rgnl", 36.1, -90.9)


def test_a_dense_tile_is_fetched_again_as_four_smaller_ones(api, clock):
    def stations(bbox):
        if bbox[2] - bbox[0] > 2:  # the 2.5 degree tile is full
            return [report(f"K{i:03d}") for i in range(airports.SPLIT_AT)]
        return [report(f"K{int(bbox[1] * 10) % 100:02d}{int(bbox[0]) % 10}")]

    fake = api(stations=stations)
    airports.candidates(-96, 29, -93.5, 31.5, clock=clock)
    sizes = sorted({round(b[2] - b[0], 2) for b in fake.metar_boxes})
    assert sizes == [1.25, 2.5] and len(fake.metar_boxes) == 5


def test_a_tile_is_never_split_below_the_smallest(api, clock):
    fake = api(stations=lambda bbox: [report(f"K{i:03d}") for i in range(airports.SPLIT_AT)])
    airports.candidates(-96, 29, -93.5, 31.5, clock=clock)
    assert len(fake.metar_boxes) == 5  # the tile, then its four 1.25 degree ones, which stay as they are


def test_a_request_is_tried_again_after_a_504(api, clock):
    fake = api(stations=lambda bbox: [report("KHOU")], fail=[504])
    got = airports.candidates(-96, 29, -95, 30, clock=clock)
    assert [s.code for s in got.items] == ["KHOU"] and got.failed == 0
    assert len(fake.metar_boxes) == 1


def test_a_tile_that_never_answers_is_counted_not_raised(api, clock):
    api(fail=[504, "network"])
    got = airports.candidates(-96, 29, -95, 30, clock=clock)
    assert got.items == [] and got.failed == 1


def test_an_answer_that_is_not_json_is_a_failed_request(monkeypatch, clock):
    monkeypatch.setattr(airports.requests, "get", lambda url, **kw: FakeResponse(ValueError("not JSON")))
    assert airports.candidates(-96, 29, -95, 30, clock=clock).failed == 1


# ---- details -----------------------------------------------------------------------------------------------


def test_details_reads_the_tower_passengers_and_the_longest_runway(api, clock):
    api(known={"KHOU": detail("KHOU", "T", "13110", "3", ["7602x150", "5148x100", "7602x150"])})
    got = airports.details(["KHOU"], clock=clock)
    assert got.items == {"KHOU": {"tower": True, "passengers": 13110, "rwyNum": 3, "rwyLength": 7602}}


def test_details_copes_with_missing_and_odd_fields(api, clock):
    odd = {"icaoId": "K1A1", "tower": None, "passengers": "", "runways": [{"dimension": "x"}, "junk", {"id": "1"}]}
    api(known={"K1A1": odd})
    got = airports.details(["K1A1"], clock=clock)
    assert got.items["K1A1"] == {"tower": False, "passengers": 0, "rwyNum": 2, "rwyLength": 0}


def test_codes_are_asked_in_batches_once_each(api, clock):
    fake = api()
    codes = [f"K{i:03d}" for i in range(250)] + ["K000"]  # one repeated
    airports.details(codes, clock=clock)
    assert [len(ids) for ids in fake.airport_ids] == [100, 100, 50]
    assert sum(fake.airport_ids, []) == codes[:250]


def test_a_code_the_api_does_not_know_is_left_out(api, clock):
    api(known={"KHOU": detail("KHOU", "T")})
    assert list(airports.details(["KHOU", "KXXX"], clock=clock).items) == ["KHOU"]


def test_a_failed_batch_is_counted(api, clock):
    api(known={"K000": detail("K000")}, fail=[500, 500])  # the first batch fails both tries
    got = airports.details([f"K{i:03d}" for i in range(150)], clock=clock)
    assert got.failed == 1 and "K000" not in got.items


# ---- rank --------------------------------------------------------------------------------------------------

KIAH = {"tower": True, "passengers": 40970, "rwyNum": 5, "rwyLength": 12001}
KHOU = {"tower": True, "passengers": 13110, "rwyNum": 3, "rwyLength": 7602}
SMALL_TOWERED = {"tower": True, "passengers": 0, "rwyNum": 1, "rwyLength": 5000}
SMALL_FIELD = {"tower": False, "passengers": 0, "rwyNum": 1, "rwyLength": 3000}


def test_a_bigger_airport_ranks_higher():
    assert airports.rank(KIAH) > airports.rank(KHOU) > airports.rank(SMALL_TOWERED) > airports.rank(SMALL_FIELD)


def test_a_tower_beats_passengers_and_runways():
    busy_untowered = {"tower": False, "passengers": 90000, "rwyNum": 6, "rwyLength": 16000}
    assert airports.rank(SMALL_TOWERED) > airports.rank(busy_untowered)


@pytest.mark.parametrize(
    "detail,tier",
    [
        ({"tower": True, "passengers": 5000}, 4),
        ({"tower": True, "passengers": 4999}, 3),
        ({"tower": True, "passengers": 300}, 3),
        ({"tower": True, "passengers": 299, "rwyNum": 3}, 3),
        ({"tower": True, "passengers": 299, "rwyNum": 2}, 2),
        ({"tower": False, "passengers": 50}, 1),
        ({"tower": False, "rwyNum": 2}, 1),
        ({"tower": False, "rwyNum": 1}, 0),
        ({}, 0),
    ],
)
def test_the_tier_is_the_hundreds(detail, tier):
    assert int(airports.rank(detail) // 100) == tier


def test_rank_is_never_pushed_into_the_next_tier():
    biggest = {"tower": False, "passengers": 10**9, "rwyNum": 20, "rwyLength": 30000}  # an untowered tier 1
    assert airports.rank(biggest) < 200
    assert airports.rank({"tower": True, "passengers": 10**9, "rwyNum": 20, "rwyLength": 30000}) < 500


def test_rank_copes_with_nonsense():
    assert airports.rank({"passengers": -5, "rwyNum": -1, "rwyLength": -1}) == 0
    assert airports.rank({"passengers": None, "tower": None}) == 0


# ---- load and its cache ------------------------------------------------------------------------------------

BOX = (-96, 29, -95, 30)


def path_text(path):
    with open(path) as f:
        return f.read()


def houston(api):
    return api(
        stations=lambda bbox: [report("KHOU", 29.6, -95.3), report("KIAH", 30.0, -95.3), report("K11R", 30.9, -96.0)],
        known={
            "KHOU": detail("KHOU", "T", "13110", "3", ["7602x150"]),
            "KIAH": detail("KIAH", "T", "40970", "5", ["12001x150"]),
            "K11R": detail("K11R"),
        },
    )


def test_load_gives_the_airports_best_first(api, clock, tmp_path):
    houston(api)
    result = airports.load(BOX, cache_path=str(tmp_path / "a.json"), clock=clock)
    assert [a["code"] for a in result.airports] == ["KIAH", "KHOU", "K11R"]
    assert result.stale is False and result.error is None and result.fetched_at == clock.now().isoformat()
    khou = result.airports[1]
    assert set(khou) == {"code", "name", "lat", "lon", "tower", "passengers", "rwyNum", "rwyLength", "rank"}
    assert khou["rank"] == pytest.approx(airports.rank(KHOU))


def test_load_keeps_the_answer_for_a_day(api, clock, tmp_path):
    fake = houston(api)
    path = str(tmp_path / "planner-cache" / "a.json")  # the folder is made
    first = airports.load(BOX, cache_path=path, clock=clock)
    asked = len(fake.metar_boxes)
    clock.advance(23 * 3600)
    again = airports.load(BOX, cache_path=path, clock=clock)
    assert len(fake.metar_boxes) == asked  # nothing fetched
    assert again.airports == first.airports and again.fetched_at == first.fetched_at and again.stale is False
    assert json.loads(path_text(path))["-96,29,-95,30"]["fetched_at"] == first.fetched_at


def test_load_fetches_again_after_the_cache_is_a_day_old(api, clock, tmp_path):
    fake = houston(api)
    path = str(tmp_path / "a.json")
    airports.load(BOX, cache_path=path, clock=clock)
    asked = len(fake.metar_boxes)
    clock.advance(25 * 3600)
    airports.load(BOX, cache_path=path, clock=clock)
    assert len(fake.metar_boxes) == 2 * asked


def test_each_box_has_its_own_cache_entry(api, clock, tmp_path):
    fake = houston(api)
    path = str(tmp_path / "a.json")
    airports.load(BOX, cache_path=path, clock=clock)
    airports.load((-100, 25, -99, 26), cache_path=path, clock=clock)
    assert len(fake.metar_boxes) == 2 and len(json.loads(path_text(path))) == 2


def test_max_age_is_a_parameter(api, clock, tmp_path):
    fake = houston(api)
    path = str(tmp_path / "a.json")
    airports.load(BOX, cache_path=path, clock=clock)
    clock.advance(3600)
    airports.load(BOX, cache_path=path, clock=clock, max_age=timedelta(minutes=30))
    assert len(fake.metar_boxes) == 2


def test_an_old_cache_is_used_when_the_network_fails(api, clock, tmp_path):
    fake = houston(api)
    path = str(tmp_path / "a.json")
    first = airports.load(BOX, cache_path=path, clock=clock)
    clock.advance(3 * 86400)
    fake.fail = [504, 504]
    result = airports.load(BOX, cache_path=path, clock=clock)
    assert result.stale is True and result.airports == first.airports
    assert result.fetched_at == first.fetched_at and "did not answer" in result.error


def test_without_a_cache_a_failure_gives_no_airports_and_a_reason(api, clock, tmp_path):
    api(fail=[504, 504])
    result = airports.load(BOX, cache_path=str(tmp_path / "a.json"), clock=clock)
    assert result.airports == [] and result.stale is False and result.fetched_at is None
    assert "did not answer" in result.error


def test_a_cache_file_that_is_not_json_is_ignored(api, clock, tmp_path):
    houston(api)
    path = tmp_path / "a.json"
    path.write_text("{not json")
    result = airports.load(BOX, cache_path=str(path), clock=clock)
    assert len(result.airports) == 3 and json.loads(path.read_text())  # and rewritten


def test_a_partial_fetch_is_returned_with_an_error_and_not_cached(api, monkeypatch, clock, tmp_path):
    fake = houston(api)
    path = tmp_path / "a.json"

    def metar_only(url, params=None, **kwargs):  # the METAR list answers, the airport details do not
        if url == airports.AIRPORT_URL:
            return FakeResponse([], 500)
        return fake.get(url, params=params, **kwargs)

    monkeypatch.setattr(airports.requests, "get", metar_only)
    result = airports.load(BOX, cache_path=str(path), clock=clock)
    assert len(result.airports) == 3 and "failed" in result.error and result.stale is False
    assert not path.exists()  # a short list isn't kept over a good one
    assert all(a["tower"] is False and a["passengers"] == 0 for a in result.airports)


def test_an_area_with_no_airports_says_so(api, clock, tmp_path):
    api()
    result = airports.load(BOX, cache_path=str(tmp_path / "a.json"), clock=clock)
    assert result.airports == [] and "no airport" in result.error and result.stale is False


def test_an_unwritable_cache_does_not_stop_load(api, clock, tmp_path):
    houston(api)
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where the folder should be")
    result = airports.load(BOX, cache_path=str(blocker / "a.json"), clock=clock)
    assert len(result.airports) == 3 and result.error is None


# ---- the API's 204, a budget, a malformed cache, the cache write -------------------------------------------


def test_a_204_is_an_empty_answer_not_a_failed_request(monkeypatch, clock):
    # the API answers a valid request with nothing to report (a box over the sea, an unknown code) with 204 and no body
    monkeypatch.setattr(airports.requests, "get", lambda url, **kw: FakeResponse(ValueError("no body"), 204))
    assert airports.candidates(-96, 29, -95, 30, clock=clock) == airports.Fetched([], 0)
    assert airports.details(["KXXX"], clock=clock) == airports.Fetched({}, 0)


def test_requests_are_paced_under_the_rate_limit(api, clock):
    api()
    start = clock.time()
    airports.candidates(-100, 25, -90, 35, clock=clock)  # 16 requests
    assert clock.time() - start >= 15 * airports.REQUEST_SPACING  # the API allows 100 a minute
    assert airports.REQUEST_SPACING >= 60 / 100


def test_a_fetch_gives_up_when_its_time_is_up(api, clock, tmp_path):
    fake = api(stations=lambda bbox: [report("KHOU")])
    result = airports.load((-100, 25, -90, 35), cache_path=str(tmp_path / "a.json"), clock=clock, deadline=3)
    assert len(fake.metar_boxes) < 16  # it stopped asking
    assert "gave up after 3 seconds" in result.error
    assert [a["code"] for a in result.airports] == ["KHOU"]  # what it had is still returned
    assert not (tmp_path / "a.json").exists()


def test_a_fetch_gives_up_after_failures_in_a_row(api, clock, tmp_path):
    fake = api(fail=["network"] * 40)
    result = airports.load((-100, 25, -90, 35), cache_path=str(tmp_path / "a.json"), clock=clock)
    assert 40 - len(fake.fail) == airports.FAILURES_IN_A_ROW * airports.ATTEMPTS  # 5 requests, 2 tries each
    assert result.airports == [] and f"{airports.FAILURES_IN_A_ROW} failed requests in a row" in result.error


def test_a_success_ends_a_run_of_failures(api, clock):
    fake = api(stations=lambda bbox: [report("KHOU")], fail=["network"] * 8)  # 4 requests fail, then it works
    got = airports.candidates(-100, 25, -90, 35, clock=clock)
    assert len(fake.metar_boxes) == 12 and got.failed == 4  # the streak never reached 5


def test_a_partial_fetch_does_not_replace_a_whole_old_cache(api, monkeypatch, clock, tmp_path):
    fake = houston(api)
    path = str(tmp_path / "a.json")
    first = airports.load(BOX, cache_path=path, clock=clock)
    clock.advance(3 * 86400)

    def metar_only(url, params=None, **kwargs):
        if url == airports.AIRPORT_URL:
            return FakeResponse([], 500)
        return fake.get(url, params=params, **kwargs)

    monkeypatch.setattr(airports.requests, "get", metar_only)
    result = airports.load(BOX, cache_path=path, clock=clock)
    assert result.stale is True and result.airports == first.airports and result.fetched_at == first.fetched_at
    assert "failed" in result.error and "using the cache from" in result.error
    assert json.loads(path_text(path))["-96,29,-95,30"]["fetched_at"] == first.fetched_at  # not overwritten


def test_longitudes_past_180_are_asked_for_as_two_boxes_the_api_takes():
    assert airports._longitudes(-96, -95) == [(-96, -95)]
    assert airports._longitudes(168.1678, 187.6496) == [(168.1678, 180.0), (-180.0, 187.6496 - 360)]
    assert airports._longitudes(181, 190) == [(-179, -170)]  # all of it past 180
    assert airports._longitudes(-190, -170) == [(170, 180.0), (-180.0, -170)]


def test_a_box_across_the_antimeridian_never_asks_for_a_longitude_the_api_rejects(api, clock):
    # the Western Aleutian Islands chart: 168.17 to 187.65 east, which is 168.17 to 180 and -180 to -172.35
    fake = api(stations=lambda b: [report("PADK", 51.88, -176.65)] if b[1] <= -176.65 <= b[3] else [])
    got = airports.candidates(168.1678, 50.7546, 187.6496, 53.2873, clock=clock)
    assert [s.code for s in got.items] == ["PADK"] and got.failed == 0
    assert fake.metar_boxes and all(-180 <= b[1] < b[3] <= 180 for b in fake.metar_boxes)
    west = [b for b in fake.metar_boxes if b[1] > 0]  # the part up to 180
    east = [b for b in fake.metar_boxes if b[1] < 0]  # the part from -180
    assert min(b[1] for b in west) == pytest.approx(168.1678) and max(b[3] for b in west) == 180
    assert min(b[1] for b in east) == -180 and max(b[3] for b in east) == pytest.approx(187.6496 - 360)


def test_load_gets_the_airports_on_both_sides_of_the_antimeridian(api, clock, tmp_path):
    api(
        stations=lambda b: (
            [report("PASY", 52.72, 174.11)] * (b[1] <= 174.11 <= b[3])
            + [report("PADK", 51.88, -176.65)] * (b[1] <= -176.65 <= b[3])
        ),
        known={
            "PASY": detail("PASY", "", "0", "1", ["10000x150"]),
            "PADK": detail("PADK", "T", "5", "2", ["7800x150"]),
        },
    )
    result = airports.load((168.1678, 50.7546, 187.6496, 53.2873), cache_path=str(tmp_path / "a.json"), clock=clock)
    assert sorted(a["code"] for a in result.airports) == ["PADK", "PASY"] and result.error is None


KEY = "-96,29,-95,30"
WHEN = "2026-10-24T12:00:00+00:00"
MALFORMED = [
    [],
    {KEY: []},
    {KEY: "text"},
    {KEY: None},
    {KEY: {"fetched_at": WHEN}},
    {KEY: {"airports": []}},
    {KEY: {"fetched_at": 5, "airports": []}},
    {KEY: {"fetched_at": "yesterday", "airports": []}},
    {KEY: {"fetched_at": "2026-10-24T12:00:00", "airports": []}},  # no time zone
    {KEY: {"fetched_at": WHEN, "airports": "none"}},
    {KEY: {"fetched_at": WHEN, "airports": [1, 2]}},
    {KEY: {"fetched_at": WHEN, "airports": [{"x": 1}]}},  # dicts, but not airports
    {KEY: {"fetched_at": WHEN, "airports": [{"code": "KHOU", "lat": 29.6}]}},  # no lon
    {KEY: {"fetched_at": WHEN, "airports": [{"code": "KHOU", "lat": "29.6", "lon": -95.3}]}},  # a lat that is text
    {KEY: {"fetched_at": WHEN, "airports": [{"code": "", "lat": 29.6, "lon": -95.3}]}},
    {KEY: {"fetched_at": WHEN, "airports": [{"code": "KHOU", "lat": float("nan"), "lon": -95.3}]}},
    {KEY: {"fetched_at": "2999-01-01T00:00:00+00:00", "airports": [{"code": "KHOU", "lat": 29.6, "lon": -95.3}]}},
]


@pytest.mark.parametrize("content", MALFORMED)
def test_a_malformed_cache_entry_is_no_entry(api, clock, tmp_path, content):
    houston(api)
    path = tmp_path / "a.json"
    path.write_text(json.dumps(content))
    result = airports.load(BOX, cache_path=str(path), clock=clock)
    assert len(result.airports) == 3 and result.error is None
    assert len(json.loads(path.read_text())[KEY]["airports"]) == 3  # and it was replaced


@pytest.mark.parametrize("content", MALFORMED)
def test_a_malformed_cache_entry_is_no_help_offline(api, clock, tmp_path, content):
    api(fail=["network"] * 40)
    path = tmp_path / "a.json"
    path.write_text(json.dumps(content))
    result = airports.load(BOX, cache_path=str(path), clock=clock)
    assert result.airports == [] and result.stale is False and "did not answer" in result.error


def test_a_cache_a_minute_ahead_of_the_clock_is_still_fresh_but_an_hour_ahead_is_not(api, clock, tmp_path):
    fake = houston(api)
    path = tmp_path / "a.json"
    cached = [{"code": "KHOU", "lat": 29.6, "lon": -95.3}]
    for ahead, fetched_again in ((timedelta(minutes=1), False), (timedelta(hours=1), True)):
        path.write_text(json.dumps({KEY: {"fetched_at": (clock.now() + ahead).isoformat(), "airports": cached}}))
        before = len(fake.metar_boxes)
        airports.load(BOX, cache_path=str(path), clock=clock)
        assert (len(fake.metar_boxes) > before) is fetched_again


@pytest.mark.parametrize(
    "box",
    [
        None,
        5,
        "abc",
        "1234",
        {1, 2, 3, 4},
        (1, 2, 3),
        (1, 2, 3, "x"),
        ("1", "2", "3", "4"),
        (True, 29, -95, 30),
        (float("nan"), 29, -95, 30),
        (1, 2, 3, float("inf")),
    ],
)
def test_a_box_that_is_not_four_numbers_is_an_error_not_a_raise(clock, tmp_path, box):
    result = airports.load(box, cache_path=str(tmp_path / "a.json"), clock=clock)
    assert result.airports == [] and "four numbers" in result.error


def test_saving_one_box_keeps_the_entry_another_request_saved_meanwhile(api, clock, tmp_path, monkeypatch):
    houston(api)
    path = str(tmp_path / "a.json")
    other = {"fetched_at": WHEN, "airports": [{"code": "KDFW"}]}
    real = airports.candidates

    def candidates_while_another_request_saves(*box, **kwargs):
        airports._store(path, "-100,25,-99,26", other)  # a request on another thread finishes first
        return real(*box, **kwargs)

    monkeypatch.setattr(airports, "candidates", candidates_while_another_request_saves)
    airports.load(BOX, cache_path=path, clock=clock)
    saved = json.loads(path_text(path))
    assert saved["-100,25,-99,26"] == other and len(saved[KEY]["airports"]) == 3


def test_threads_saving_at_once_lose_nothing_and_leave_no_temporary_files(tmp_path):
    path = str(tmp_path / "planner-cache" / "a.json")
    entry = {"fetched_at": WHEN, "airports": []}
    threads = [threading.Thread(target=airports._store, args=(path, f"box{i}", entry)) for i in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(json.loads(path_text(path))) == sorted(f"box{i}" for i in range(12))
    assert [p.name for p in (tmp_path / "planner-cache").iterdir()] == ["a.json"]


def test_a_failed_save_leaves_no_temporary_file(tmp_path, monkeypatch):
    def refuse(source, destination):
        raise OSError("disk full")

    monkeypatch.setattr(airports.os, "replace", refuse)
    airports._store(str(tmp_path / "a.json"), "k", {"fetched_at": WHEN, "airports": []})  # does not raise
    assert list(tmp_path.iterdir()) == []


def test_the_cache_file_is_readable_by_others(api, clock, tmp_path):
    houston(api)
    path = tmp_path / "a.json"
    airports.load(BOX, cache_path=str(path), clock=clock)
    assert path.stat().st_mode & 0o044  # mkstemp makes a private file; the cache is not a secret


@pytest.mark.parametrize(
    "lat,lon",
    [("nan", 0), ("inf", 0), (0, "-inf"), (91, 0), (0, 181), ("x", 0)],
)
def test_a_station_with_no_real_position_is_left_out(api, clock, lat, lon):
    api(stations=lambda bbox: [report("KBAD", lat=lat, lon=lon), report("KHOU")])
    assert [s.code for s in airports.candidates(-96, 29, -95, 30, clock=clock).items] == ["KHOU"]


def test_details_copes_with_odd_value_types(api, clock):
    odd = {"icaoId": "K1A1", "tower": "T", "passengers": "inf", "rwyNum": "nan", "runways": 5}
    odd2 = {"icaoId": "K2A2", "tower": "T", "passengers": [1], "rwyNum": {}, "runways": "none"}
    odd3 = {"icaoId": "K3A3", "passengers": 1e400, "runways": [{"dimension": "9" * 6000}]}
    api(known={"K1A1": odd, "K2A2": odd2, "K3A3": odd3})
    got = airports.details(["K1A1", "K2A2", "K3A3"], clock=clock).items
    assert got["K1A1"] == {"tower": True, "passengers": 0, "rwyNum": 0, "rwyLength": 0}
    assert got["K2A2"] == {"tower": True, "passengers": 0, "rwyNum": 0, "rwyLength": 0}
    assert got["K3A3"]["passengers"] == 0 and got["K3A3"]["rwyLength"] >= 0


def test_rank_copes_with_values_that_are_not_numbers():
    assert airports.rank({"tower": True, "passengers": "lots", "rwyNum": [], "rwyLength": float("nan")}) == 200
    assert airports.rank({"passengers": float("inf")}) == 0


# ---- the workers: several requests at once, one gate, the same answer ------------------------------------------

BIG_BOX = (-100.0, 30.0, -90.0, 40.0)  # 4 x 4 tiles of 2.5 degrees
NATIONAL_BOX = (-125.0, 24.0, -66.5, 50.0)  # the US Wall Planning chart: 24 x 11 tiles
US_BOX = (-125.0, 24.0, -66.5, 50.0)  # the wall chart: 24 x 11 tiles


def fetch_threads():
    return [t for t in threading.enumerate() if t.name.startswith("airports-fetch")]


def tile_code(bbox):
    """A station id of its own for each tile of BIG_BOX and its quarters: K, a row letter, a column letter, X."""
    south, west = bbox[0], bbox[1]
    return "K" + "ABCDEFGH"[int((south - 30) / 1.25)] + "ABCDEFGH"[int((west + 100) / 1.25)] + "X"


def tile_stations(bbox):
    """One station of its own for every tile, and KDUP in all of them with the tile's name, so which tile's answer
    is kept would show if it depended on which finished first; the tile at 32.5 N, 97.5 W is dense (30 stations)."""
    south, west, north, east = bbox
    own = report(tile_code(bbox), lat=south, lon=west, name=f"own {south:g} {west:g}")
    dup = report("KDUP", lat=south, lon=west, name=f"tile {south:g} {west:g}")
    if (south, west, north - south) == (32.5, -97.5, 2.5):
        return [report(f"KD{i:02d}", lat=south + 0.01 * i, lon=west) for i in range(airports.SPLIT_AT)]
    return [own, dup]


def test_workers_give_the_same_answer_as_one_worker_whatever_finishes_first(api, clock):
    api(stations=tile_stations)
    alone = airports.candidates(*BIG_BOX, clock=clock, workers=1)
    assert alone.failed == 0 and len(alone.items) > 16
    assert [s.name for s in alone.items if s.code == "KDUP"] == ["tile 30 -100"]  # the first tile in tile order
    for seed in range(6):
        api(stations=tile_stations, latency=0.003, seed=seed)  # a different order of answers each time
        got = airports.candidates(*BIG_BOX, clock=SafeClock(), workers=3)
        assert got == alone, seed
    assert fetch_threads() == []


class RecordingBudget(airports._Budget):
    """A budget that notes every turn it hands out."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.turns = []

    def _reserve(self, not_before=None):
        turn = super()._reserve(not_before)
        with self._lock:
            self.turns.append(turn)
        return turn


def test_the_requests_go_out_a_gate_apart_however_many_workers(api, monkeypatch):
    # asserted on the turns the gate hands out, not on when the threads happen to wake: under load a thread wakes
    # late, and two late ones then go out close together
    monkeypatch.setattr(airports, "REQUEST_SPACING", 0.03)  # a short gap, on the real clock
    fake = api(clock=airports.Clock(), latency=0.002)
    budget = RecordingBudget(fake.clock)
    airports.candidates(*BIG_BOX, clock=fake.clock, budget=budget, workers=3)
    turns = sorted(budget.turns)
    assert len(turns) == 16 == len(fake.starts)
    assert all(b - a >= 0.03 - 1e-6 for a, b in zip(turns, turns[1:]))  # epoch seconds are exact to about 2e-7
    assert fetch_threads() == []


def test_a_slow_request_does_not_stall_the_other_workers(api, clock):
    first = tuple(float(x) for x in airports._bbox_text(*airports._grid(30, -100, 40, -90)[-1], 40, -90).split(","))
    others = []  # the tiles answered while the first one is held
    release = threading.Event()

    def stations(bbox):
        if bbox == first:
            assert release.wait(10), "the other workers never got on"
            return []
        others.append(bbox)
        if len(others) == 15:
            release.set()
        return []

    api(stations=stations)
    got = airports.candidates(*BIG_BOX, clock=SafeClock(), workers=3)
    assert release.is_set() and len(others) == 15 and got.failed == 0
    assert fetch_threads() == []


def test_a_request_that_raises_counts_as_failed_and_the_rest_go_on(api, clock):
    def stations(bbox):
        if bbox[:2] == (32.5, -97.5):
            raise RuntimeError("a bug in a handler")
        return [report(tile_code(bbox))]

    api(stations=stations)
    got = airports.candidates(*BIG_BOX, clock=SafeClock(), workers=3)
    assert got.failed == 1 and len(got.items) == 15


def test_progress_counts_the_tiles_and_what_a_split_adds(api, clock):
    for workers in (1, 3):
        api(stations=tile_stations)
        calls = []
        got = airports.candidates(
            *BIG_BOX, clock=SafeClock(), workers=workers, progress=lambda done, total: calls.append((done, total))
        )
        assert calls[0] == (0, 16)  # the tiles are known before the first one is fetched
        assert [done for done, _ in calls] == list(range(len(calls)))  # one call per request, in order
        totals = [total for _, total in calls]
        assert totals == sorted(totals) and totals[-1] == 16 + 4  # the dense tile became four
        assert calls[-1] == (20, 20) and got.failed == 0


def test_a_progress_callback_that_raises_does_not_stop_the_fetch(api, clock):
    api(stations=tile_stations)

    def broken(done, total):
        raise RuntimeError("the page broke")

    got = airports.candidates(*BIG_BOX, clock=SafeClock(), workers=3, progress=broken)
    assert got.failed == 0 and len(got.items) > 16


def test_the_deadline_ends_every_worker_and_the_tiles_left_count_as_failed(api):
    clock = SafeClock()
    fake = api()
    budget = airports._Budget(clock, deadline=5)
    got = airports.candidates(*US_BOX, clock=clock, budget=budget, workers=3)
    assert budget.reason == "gave up after 5 seconds"
    assert 0 < len(fake.metar_boxes) < 264
    assert len(fake.metar_boxes) + got.failed == 264  # every tile either went out or counts as failed
    assert fetch_threads() == []


def test_cancel_ends_every_worker_at_once(api):
    cancel = threading.Event()
    clock = CancelClock(cancel)
    seen = []

    def stations(bbox):
        seen.append(bbox)
        if len(seen) == 3:
            cancel.set()  # the page's Cancel button
        return []

    api(stations=stations)
    calls = []
    got = airports.candidates(*US_BOX, clock=clock, workers=3, progress=lambda done, total: calls.append((done, total)))
    assert len(seen) < 20 and got.failed >= 264 - 20
    assert calls[-1] == (264, 264)  # nothing is left unaccounted for
    assert fetch_threads() == []


def test_one_worker_goes_through_the_tiles_in_the_first_versions_order(api, clock):
    fake = api()
    airports.candidates(*BIG_BOX, clock=clock, workers=1)
    wanted = [(s, w, s + 2.5, w + 2.5) for s, w in reversed(airports._grid(30, -100, 40, -90))]
    assert fake.metar_boxes == wanted  # the last tile of the grid first


@pytest.mark.parametrize(
    "asked, used", [(None, 3), (1, 1), (0, 1), (-4, 1), (3, 3), (50, airports.MAX_WORKERS), ("x", 3)]
)
def test_the_number_of_workers_is_kept_in_range(monkeypatch, asked, used):
    monkeypatch.setattr(airports, "WORKERS", 3)
    assert airports._workers(asked) == used


# ---- 429: the API says slow down --------------------------------------------------------------------------


def one_tile_after_a_429(api, retry_after):
    clock = SafeClock()
    fake = api(fail=[429], retry_after=retry_after, clock=clock, stations=lambda bbox: [report("KHOU")])
    budget = airports._Budget(clock)
    got = airports.candidates(-96, 29, -95, 30, clock=clock, budget=budget, workers=3)
    return fake, budget, got


def test_a_429_holds_the_next_request_back_for_the_retry_after_and_slows_the_gate(api):
    fake, budget, got = one_tile_after_a_429(api, "7")
    assert [s.code for s in got.items] == ["KHOU"] and got.failed == 0  # the second try got through
    assert fake.starts[1] - fake.starts[0] == pytest.approx(7)
    assert budget.spacing == pytest.approx(airports.REQUEST_SPACING * 1.5)


def test_a_retry_after_is_capped(api):
    fake, _, got = one_tile_after_a_429(api, "999")
    assert fake.starts[1] - fake.starts[0] == pytest.approx(airports.MAX_RETRY_AFTER) and got.failed == 0


def test_a_429_without_a_usable_retry_after_still_waits_a_little(api):
    for header in (None, "Wed, 21 Oct 2026 07:28:00 GMT", "nan", "-5"):
        fake, _, got = one_tile_after_a_429(api, header)
        assert fake.starts[1] - fake.starts[0] >= airports.RETRY_SECONDS and got.failed == 0, header


def test_the_gate_slows_down_with_each_burst_of_429s_but_not_past_its_limit(clock):
    budget = airports._Budget(clock)
    for _ in range(20):
        budget.rate_limited(1)
        clock.advance(2)  # past the hold: the next 429 is a new burst
    assert budget.spacing == airports.MAX_SPACING


def test_429s_of_the_same_burst_slow_the_gate_once(clock):
    budget = airports._Budget(clock)
    sent = clock.time()  # three requests that went out together
    clock.advance(1)
    for _ in range(3):
        budget.rate_limited(7, sent)
    assert budget.spacing == pytest.approx(airports.REQUEST_SPACING * 1.5)
    clock.advance(10)  # the hold is over; a request sent after it that is answered 429 starts a new burst
    budget.rate_limited(7, clock.time())
    assert budget.spacing == pytest.approx(airports.REQUEST_SPACING * 1.5**2)
    for _ in range(20):
        clock.advance(10)
        budget.rate_limited(7, clock.time())
    assert budget.spacing == airports.MAX_SPACING


def test_three_workers_answered_429_at_once_slow_the_gate_once(api):
    clock = SafeClock()
    fake = api(
        fail=[429] * 3,
        retry_after="7",
        clock=clock,
        barrier=threading.Barrier(3),  # all three requests are in flight before any is answered
        stations=lambda bbox: [report("KHOU")],
    )
    budget = airports._Budget(clock)
    got = airports.candidates(*BIG_BOX, clock=clock, budget=budget, workers=3)
    assert got.failed == 0 and len(fake.starts) == 16 + 3
    assert budget.spacing == pytest.approx(airports.REQUEST_SPACING * 1.5)


def test_a_turn_reserved_before_a_429_waits_for_the_hold():
    class Rate429DuringWait(FakeClock):
        """Another worker's 429 arrives while the second request waits for its turn."""

        def __init__(self):
            super().__init__()
            self.budget, self.fired = None, False

        def wait(self, event, seconds):
            if not self.fired:
                self.fired = True
                self.budget.rate_limited(7)
            return super().wait(event, seconds)

    clock = Rate429DuringWait()
    budget = clock.budget = airports._Budget(clock)
    first = clock.time()
    assert budget.start()  # goes out at once; the next turn is REQUEST_SPACING later
    assert budget.start()  # reserved that turn, then the 429 came in while it waited
    assert clock.time() >= first + 7  # it did not go out inside the hold


def test_a_national_fetch_at_the_capped_spacing_says_it_ran_out_of_time(api, monkeypatch, tmp_path):
    # about 280 requests 5 s apart is 1400 s, past the 900 s limit: the answer is short, says why, and is not saved
    monkeypatch.setattr(airports, "REQUEST_SPACING", airports.MAX_SPACING)
    api(stations=lambda bbox: [report("KHOU")], known={"KHOU": detail("KHOU", tower="T", passengers="13110")})
    cache = tmp_path / "airports.json"
    result = airports.load(NATIONAL_BOX, clock=SafeClock(), cache_path=cache, workers=1)
    assert result.error and f"gave up after {airports.DEADLINE:g} seconds" in result.error
    assert "may be short" in result.error and [a["code"] for a in result.airports] == ["KHOU"]
    assert not cache.exists()


@pytest.mark.parametrize(
    "headers, seconds",
    [({"Retry-After": "7"}, 7), ({"Retry-After": " 12.5 "}, 12.5), ({"Retry-After": "0"}, airports.RETRY_SECONDS)]
    + [
        ({"Retry-After": "9999"}, airports.MAX_RETRY_AFTER),
        ({}, airports.RETRY_SECONDS),
        (None, airports.RETRY_SECONDS),
    ],
)
def test_the_retry_after_is_read_from_the_header(headers, seconds):
    assert airports._retry_after(FakeResponse([], 429, headers)) == seconds


# ---- details and load with workers --------------------------------------------------------------------------


def test_details_in_batches_at_once_match_one_at_a_time_and_report_each_batch(api, clock):
    codes = [f"K{i:03d}" for i in range(250)]  # three batches of at most 100
    known = {c: detail(c, tower="T" if i % 2 else "", passengers=str(i)) for i, c in enumerate(codes)}
    api(known=known)
    alone = airports.details(codes, clock=clock, workers=1)
    api(known=known, latency=0.003, seed=3)
    calls = []
    got = airports.details(
        codes, clock=SafeClock(), workers=3, progress=lambda done, total: calls.append((done, total))
    )
    assert got == alone and got.failed == 0 and len(got.items) == 250
    assert calls == [(0, 3), (1, 3), (2, 3), (3, 3)]
    assert fetch_threads() == []


def test_load_reports_the_stations_and_then_the_details(api, clock, tmp_path):
    api(stations=tile_stations, known={})
    calls = []
    result = airports.load(
        BIG_BOX,
        cache_path=str(tmp_path / "a.json"),
        clock=SafeClock(),
        workers=3,
        progress=lambda phase, done, total: calls.append((phase, done, total)),
    )
    assert result.airports and result.error is None
    phases = [phase for phase, _, _ in calls]
    assert phases == sorted(phases, key=["stations", "details"].index)  # all the stations, then all the details
    assert calls[0] == ("stations", 0, 16) and ("details", 0, 1) in calls
    last = {phase: (done, total) for phase, done, total in calls}
    assert last["stations"][0] == last["stations"][1] and last["details"][0] == last["details"][1]


def test_load_does_not_report_a_cache_it_uses_as_it_is(api, clock, tmp_path):
    api(stations=tile_stations)
    path = str(tmp_path / "a.json")
    airports.load(BIG_BOX, cache_path=path, clock=clock, workers=3)
    calls = []
    airports.load(BIG_BOX, cache_path=path, clock=clock, progress=lambda *args: calls.append(args))
    assert calls == []
