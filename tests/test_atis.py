"""Tests for metarmap.atis: the digital ATIS from atis.info, fetched only when asked, faked here."""

from types import SimpleNamespace

import pytest
import requests

from metarmap import atis
from metarmap.atis import Atis, AtisError

KIAH = {
    "airport": "KIAH",
    "type": "combined",
    "code": "S",
    "datis": "IAH ATIS INFO S 1653Z. 11007KT 10SM A3013. ...ADVS YOU HAVE INFO S.",
    "time": "1653",
    "updatedAt": "2026-11-07T17:44:58Z",
}
KATL = [
    {"airport": "KATL", "type": "dep", "code": "W", "datis": "ATL DEP INFO W 1752Z.", "time": "1752"},
    {"airport": "KATL", "type": "arr", "code": "J", "datis": "ATL ARR INFO J 1752Z.", "time": "1752"},
]


class FakeGet:
    """Stands in for requests.get: answers with `data` (or raises `error`) and counts the requests."""

    def __init__(self, data=None, status=200, error=None):
        self.data, self.status, self.error = [KIAH, *KATL] if data is None else data, status, error
        self.calls = []

    def __call__(self, url, timeout=None, headers=None):
        self.calls.append((url, headers))
        if self.error:
            raise self.error

        def raise_for_status():
            if self.status >= 400:
                raise requests.HTTPError(f"{self.status}")

        return SimpleNamespace(status_code=self.status, json=lambda: self.data, raise_for_status=raise_for_status)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make(get=None, on=True):
    clock, get = Clock(), get or FakeGet()
    state = SimpleNamespace(on=on)
    return Atis(lambda: state.on, get=get, clock=clock, background=False), get, clock, state


def test_parse_keeps_atis_entries_only():
    found = atis.parse([KIAH, *KATL, {"airport": "KXXX"}, {"airport": "", "datis": "x"}, "junk", None])
    assert set(found) == {"KIAH", "KATL"}
    assert [e["type"] for e in found["KATL"]] == ["dep", "arr"]
    assert found["KIAH"][0] == {
        "type": "combined",
        "code": "S",
        "time": "1653",
        "updatedAt": "2026-11-07T17:44:58Z",
        "datis": KIAH["datis"],
    }
    assert atis.parse({"error": "No results found"}) == {}


def test_entries_fetch_once_a_minute_for_every_airport():
    found, get, clock, _ = make()
    assert found.entries("kiah")[0]["code"] == "S"
    assert [e["code"] for e in found.entries("KATL")] == ["W", "J"]
    assert len(get.calls) == 1  # one request serves every airport
    url, headers = get.calls[0]
    assert url == atis.API_URL and "metarmap2" in headers["User-Agent"]
    clock.now += atis.FRESH_SECONDS - 1
    found.entries("KIAH")
    assert len(get.calls) == 1
    clock.now += 1
    found.entries("KIAH")
    assert len(get.calls) == 2


def test_an_airport_without_an_atis_is_a_404():
    found, _, _, _ = make()
    with pytest.raises(AtisError) as e:
        found.entries("KDWH")
    assert e.value.status == 404 and "KDWH has no digital ATIS" in str(e.value)


def test_off_asks_nothing():
    found, get, _, state = make(on=False)
    with pytest.raises(AtisError) as e:
        found.entries("KIAH")
    assert e.value.status == 503 and "speech.atis" in str(e.value)
    assert found.available() == set() and get.calls == []
    state.on = True
    assert found.available() == {"KIAH", "KATL"}


def test_available_is_refreshed_every_half_hour():
    found, get, clock, _ = make()
    assert found.available() == {"KIAH", "KATL"}
    clock.now += atis.AVAILABLE_SECONDS - 1
    found.available()
    assert len(get.calls) == 1
    clock.now += 1
    get.data = [KIAH]
    assert found.available() == {"KIAH"}


def test_a_failure_keeps_what_was_there_and_waits():
    get = FakeGet()
    found, _, clock, _ = make(get)
    found.entries("KIAH")
    get.error = requests.ConnectionError("down")
    clock.now += atis.FRESH_SECONDS
    assert found.entries("KIAH")[0]["code"] == "S"  # the last one atis.info gave
    assert len(get.calls) == 2
    clock.now += 1
    found.entries("KIAH")
    assert len(get.calls) == 2  # waiting after the failure
    clock.now += atis.FRESH_SECONDS
    get.error = None
    found.entries("KIAH")
    assert len(get.calls) == 3


class BadJson(FakeGet):
    def __call__(self, url, timeout=None, headers=None):
        answer = super().__call__(url, timeout, headers)

        def broken():
            raise ValueError("Expecting value")

        answer.json = broken
        return answer


@pytest.mark.parametrize("get", [FakeGet(error=requests.ConnectionError("down")), FakeGet(status=500), BadJson()])
def test_nothing_yet_says_why(get):
    found, _, _, _ = make(get)
    with pytest.raises(AtisError) as e:
        found.entries("KIAH")
    assert e.value.status == 502 and "atis.info" in str(e.value)


def test_the_backoff_grows_and_stops_growing():
    get = FakeGet(error=requests.ConnectionError("down"))
    found, _, clock, _ = make(get)
    waits = []
    for _ in range(8):
        before = len(get.calls)
        while len(get.calls) == before:
            clock.now += 1
            found.refresh(atis.FRESH_SECONDS)
        waits.append(found._backoff)
    assert waits[0] == atis.FRESH_SECONDS and waits[1] == 2 * atis.FRESH_SECONDS
    assert waits[-1] == atis.MAX_BACKOFF
