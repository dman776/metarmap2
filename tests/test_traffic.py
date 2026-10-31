"""
Tests for live traffic (metarmap.traffic): the area asked about, reading adsb.fi's answer, and how often it's asked.
"""
from types import SimpleNamespace

import pytest
import requests

from metarmap import traffic
from metarmap.settings import MapPage
from metarmap.traffic import Traffic

HOUSTON = [(29.6454, -95.2789), (29.9844, -95.3414), (31.3069, -95.4038)]  # KHOU, KIAH, KDKR

# one aircraft as adsb.fi sends it (trimmed), and one on the ground
FLYING = {"hex": "a0822c", "flight": "UCA4878 ", "r": "N13161", "t": "E45X", "desc": "EMBRAER ERJ-145XR",
          "ownOp": "UNITED AIRLINES INC", "alt_baro": 2450, "alt_geom": 2625, "gs": 211.0, "track": 90.54,
          "baro_rate": -1152, "squawk": "4561", "emergency": "none", "category": "A2", "lat": 30.006683,
          "lon": -95.498765, "seen_pos": 0.5, "seen": 0.1}
PARKED = {"hex": "a1b2c3", "r": "N12345", "t": "C172", "alt_baro": "ground", "gs": 0, "lat": 29.65, "lon": -95.28,
          "seen_pos": 2}


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
    """Counts requests; answers with `responses` in turn (the last one again once they run out)."""

    def __init__(self, *responses):
        self.responses = list(responses) or [FakeResponse()]
        self.urls = []

    def __call__(self, url, **kwargs):
        self.urls.append(url)
        answer = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(answer, Exception):
            raise answer
        return answer


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def make(get=None, seconds=5, ground=False, points=HOUSTON, clock=None):
    settings = MapPage(traffic_seconds=seconds, traffic_ground=ground)
    clock = clock or Clock()
    t = Traffic(lambda: settings, lambda: points, get=get or FakeAdsbFi(), clock=clock)
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
    assert flying == {"hex": "a0822c", "flight": "UCA4878", "reg": "N13161", "type": "E45X",
                      "desc": "EMBRAER ERJ-145XR", "operator": "UNITED AIRLINES INC", "lat": 30.006683,
                      "lon": -95.498765, "ground": False, "alt": 2450, "gs": 211.0, "track": 90.54, "vrate": -1152,
                      "squawk": "4561", "emergency": None, "category": "A2", "at": 999.5}
    assert parked["ground"] is True and parked["alt"] is None and parked["flight"] is None


@pytest.mark.parametrize("change", [{"lat": None}, {"lon": "x"}, {"hex": ""}, {"seen_pos": 61}])
def test_parse_skips_aircraft_without_a_usable_position(change):
    assert traffic.parse({"ac": [{**FLYING, **change}]}, fetched=1000.0) == []


def test_parse_falls_back_to_other_fields():
    (a,) = traffic.parse({"ac": [{**FLYING, "alt_baro": None, "track": None, "true_heading": 45, "baro_rate": None,
                                  "geom_rate": 300, "seen_pos": None, "emergency": "general"}]}, fetched=1000.0)
    assert (a["alt"], a["track"], a["vrate"], a["at"], a["emergency"]) == (2625, 45, 300, 999.9, "general")


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


@pytest.mark.parametrize("seconds, used", [(0.5, 2), (1, 2), ("fast", 2), (10, 10), (3600, 60)])
def test_interval_is_kept_within_the_limits(seconds, used):
    t, _, _ = make(seconds=seconds)
    assert t.interval() == used


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
    adsb = FakeAdsbFi(FakeResponse(), requests.exceptions.ConnectionError("down"),
                      requests.exceptions.ConnectionError("down"), FakeResponse())
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
    assert t._backoff == traffic.MAX_BACKOFF


def test_too_many_requests_waits_at_least_a_minute():
    adsb = FakeAdsbFi(FakeResponse(status=429), FakeResponse())
    t, _, clock = make(get=adsb, seconds=2)
    assert "too many requests" in t.snapshot()["error"]
    clock.t += traffic.RATE_LIMITED - 1
    t.snapshot()
    assert len(adsb.urls) == 1
    clock.t += 1
    assert t.snapshot()["error"] is None


@pytest.mark.parametrize("answer", [FakeResponse(status=500), FakeResponse(data="not json"),
                                    requests.exceptions.Timeout("slow")])
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
    assert seen.headers["User-Agent"].startswith("metarmap/")
