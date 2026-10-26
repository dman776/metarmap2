"""Tests for METAR fetching and parsing (metar.py)."""
import json
from datetime import datetime, timedelta, timezone

import pytest
import requests

from metarmap import metar
from metarmap.clock import FakeClock

# the fixture and GOOD reports are from 2026-10-24 14:53Z-17:53Z
CLOCK = FakeClock(datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc))

HOUSTON = ("KHOU", "KIAH", "KGLS", "KCLL", "KLBX", "KBPT", "KDKR", "")  # "": an LED with no airport


def at(iso):
    """A report time as the JSON API gives it: Unix seconds."""
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def report(station, **fields):
    """One report, as in the JSON API's list."""
    return {"icaoId": station, **fields}


def response(*reports):
    return json.dumps(list(reports)).encode()


GOOD = dict(rawOb="KTST 241453Z 14009KT 10SM CLR 28/22 A2995", obsTime=at("2026-10-24T14:53:00Z"),
            temp=28, dewp=22, wdir=140, wspd=9, visib="10+", altim=1014.2, fltCat="VFR", cover="CLR", clouds=[])


@pytest.fixture
def houston(make_config, fixture_bytes):
    m = metar.METAR(make_config(*HOUSTON), clock=CLOCK)
    m._process(fixture_bytes("metars_houston.json"))
    return m


# ---- parsing a real aviationweather.gov response ------------------------------------------------------------

def test_real_response_fields(houston):
    khou = houston.data["KHOU"]
    assert khou["flightCategory"] == "VFR"
    assert khou["windDir"] == "100"
    assert (khou["windSpeed"], khou["windGustSpeed"], khou["windGust"]) == (13, 19, True)
    assert khou["vis"] == 10  # "10+" in the report
    assert (khou["tempC"], khou["dewpointC"]) == (28, 16)
    assert khou["altimHg"] == pytest.approx(30.20, abs=0.01)
    assert khou["obsTime"] == datetime(2026, 10, 24, 17, 53, tzinfo=timezone.utc)
    assert khou["raw"].startswith("METAR KHOU 241753Z")
    assert khou["lightning"] is False


def test_uses_latest_report_per_station(houston, fixture_bytes):
    reports = json.loads(fixture_bytes("metars_houston.json"))
    khou_times = [r["obsTime"] for r in reports if r["icaoId"] == "KHOU"]
    assert len(khou_times) > 1  # the API returns several hours of reports
    assert houston.data["KHOU"]["obsTime"] == datetime.fromtimestamp(max(khou_times), timezone.utc)


def test_newest_report_wins_whatever_the_order(make_config):
    older = report("KTST", **{**GOOD, "obsTime": at("2026-10-24T13:53:00Z"), "rawOb": "older"})
    newer = report("KTST", **{**GOOD, "obsTime": at("2026-10-24T15:53:00Z"), "rawOb": "newer"})
    middle = report("KTST", **{**GOOD, "obsTime": at("2026-10-24T14:53:00Z"), "rawOb": "middle"})
    for order in [(older, newer, middle), (newer, middle, older), (middle, older, newer)]:
        m = metar.METAR(make_config("KTST"), clock=CLOCK)
        m._process(response(*order))
        assert m.data["KTST"]["raw"] == "newer"


def test_requests_only_the_latest_reports():
    # hours=N returned many reports per station and was cut off at 400
    assert "hours=" not in metar.API_URL


def test_variable_wind_direction(houston):
    assert houston.data["KBPT"]["windDir"] == "VRB"


def test_missing_stations_get_empty_data(houston):
    assert houston.data["KDKR"] == {}
    assert "" not in houston.data
    assert houston.missing_stations() == ["KDKR"]
    assert "KDKR" not in houston.stations()


def test_every_airport_has_an_entry(houston):
    assert list(houston.data) == [code for code in HOUSTON if code]


def test_an_airport_on_two_leds_is_fetched_once(make_config):
    assert metar.airport_codes(make_config("KHOU", "", "KIAH", "KHOU").airports) == ["KHOU", "KIAH"]


# ---- unusual responses -----------------------------------------------------------------------------------------

def test_single_report_response(make_config):
    m = metar.METAR(make_config("KTST", "KOTH"), clock=CLOCK)
    m._process(response(report("KTST", **GOOD)))
    assert m.data["KTST"]["windSpeed"] == 9
    assert m.data["KOTH"] == {}


@pytest.mark.parametrize("content", [b"[]", b"", b"  \n"])  # no reports; the API can answer with no body
def test_empty_responses(make_config, content):
    m = metar.METAR(make_config("KTST"), clock=CLOCK)
    m._process(content)
    assert m.data == {"KTST": {}}
    assert m.missing_stations() == ["KTST"]


def test_malformed_report_only_affects_its_airport(make_config):
    m = metar.METAR(make_config("KONE", "KBAD", "KTWO"), clock=CLOCK)
    bad = report("KBAD", rawOb="KBAD junk", obsTime="garbage", temp="M05")
    m._process(response(report("KONE", **GOOD), bad, report("KTWO", **GOOD)))
    assert m.data["KBAD"] == {}
    assert "KBAD" in m.missing_stations()
    assert m.data["KONE"]["tempC"] == 28
    assert m.data["KTWO"]["tempC"] == 28  # parsed even though it came after the bad one


def test_sparse_report_uses_defaults(make_config):
    m = metar.METAR(make_config("KTST"), clock=CLOCK)
    m._process(response(report("KTST", rawOb="KTST 241453Z AUTO")))
    d = m.data["KTST"]
    assert d["flightCategory"] is None
    assert (d["windSpeed"], d["vis"], d["altimHg"]) == (0, 0, 0)
    assert (d["tempC"], d["dewpointC"], d["obsTime"]) == (None, None, None)


def test_lightning_flag(make_config):
    m = metar.METAR(make_config("KTST"), clock=CLOCK)
    m._process(response(report("KTST", **{**GOOD, "rawOb": "KTST 241453Z 14009KT 10SM TS LTG DSNT"})))
    assert m.data["KTST"]["lightning"] is True


def test_data_is_replaced_not_mutated(make_config):
    """Readers (the OLED loop, the web server) must never see a half-filled dict."""
    m = metar.METAR(make_config("KTST"), clock=CLOCK)
    old = {"KTST": {"raw": "old"}}
    m.data = old
    m._process(response(report("KTST", **GOOD)))
    assert m.data is not old
    assert old == {"KTST": {"raw": "old"}}


# ---- fetch() ---------------------------------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, content=b"", status=200):
        self.content = content
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status}")

    def json(self):
        return json.loads(self.content)


def test_fetch_success(monkeypatch, make_config, fixture_bytes):
    urls = []

    def fake_get(url, **kwargs):
        urls.append(url)
        return FakeResponse(fixture_bytes("metars_houston.json"))
    monkeypatch.setattr(metar.requests, "get", fake_get)

    m = metar.METAR(make_config(*HOUSTON), clock=CLOCK)
    assert m.last_fetch_ok is None
    assert m.fetch() is True and m.last_fetch_ok is True
    assert m.data["KIAH"]["windSpeed"] == 10
    assert m.lastFetchTime is not None
    assert not m.is_fetching()
    assert urls[0].endswith("ids=KHOU,KIAH,KGLS,KCLL,KLBX,KBPT,KDKR")


@pytest.mark.parametrize("fake_get", [
    lambda url, **kw: (_ for _ in ()).throw(requests.exceptions.ConnectionError("no network")),
    lambda url, **kw: FakeResponse(status=503),
    lambda url, **kw: FakeResponse(b"<html>not the JSON you wanted"),
])
def test_fetch_errors_are_contained(monkeypatch, make_config, fake_get):
    monkeypatch.setattr(metar.requests, "get", fake_get)
    m = metar.METAR(make_config("KTST"), clock=CLOCK)
    m.data = {"KTST": {"raw": "previous"}}
    assert m.fetch() is False  # must not raise: it runs on the scheduler in the main loop
    assert m.last_fetch_ok is False
    assert m.data == {"KTST": {"raw": "previous"}}
    assert not m.is_fetching()


def test_fetch_calls_callback_even_on_error(monkeypatch, make_config):
    monkeypatch.setattr(metar.requests, "get", lambda url, **kw: FakeResponse(status=500))
    called = []
    metar.METAR(make_config("KTST"), clock=CLOCK).fetch(callback=lambda: called.append(True))
    assert called == [True]


@pytest.mark.parametrize("hours_old, reporting", [(1, True), (4.9, True), (5.1, False), (24 * 8, False)])
def test_old_reports_count_as_not_reporting(make_config, hours_old, reporting):
    observed = datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc) - timedelta(hours=hours_old)
    m = metar.METAR(make_config("KTST"), clock=CLOCK)
    m._process(response(report("KTST", **{**GOOD, "obsTime": int(observed.timestamp())})))
    assert bool(m.data["KTST"]) is reporting
    assert ("KTST" in m.missing_stations()) is not reporting


# ---- where airports without a report are ----------------------------------------------------------------------

STATIONS = [{"icaoId": "KDKR", "lat": 31.307, "lon": -95.404}, {"icaoId": "KEFD", "lat": 29.606, "lon": -95.16}]


def stations_api(monkeypatch, fixture_bytes, stations=STATIONS, fail=False):
    """Fakes aviationweather.gov (Houston METARs and the station lookup). Returns the codes each lookup asked for."""
    asked = []

    def fake_get(url, **kwargs):
        if url.startswith(metar.STATION_URL):
            asked.append(url[len(metar.STATION_URL):].split(","))
            return FakeResponse(b"", status=502) if fail else FakeResponse(json.dumps(stations).encode())
        return FakeResponse(fixture_bytes("metars_houston.json"))
    monkeypatch.setattr(metar.requests, "get", fake_get)
    return asked


def test_airports_without_a_report_are_looked_up(monkeypatch, make_config, fixture_bytes):
    asked = stations_api(monkeypatch, fixture_bytes)
    m = metar.METAR(make_config("KHOU", "KDKR", "KEFD", "KXXX", ""), clock=CLOCK)
    m.fetch()
    assert asked == [["KDKR", "KEFD", "KXXX"]]  # KHOU's METAR has its position
    assert m.position("KDKR") == (31.307, -95.404)
    assert m.position("KHOU") == (29.6458, -95.2821)  # from its METAR
    assert m.position("KXXX") is None  # the lookup doesn't know it

    m.fetch()
    assert len(asked) == 1  # each code is looked up once, including ones it doesn't know


def test_a_failed_lookup_is_tried_again(monkeypatch, make_config, fixture_bytes):
    stations_api(monkeypatch, fixture_bytes, fail=True)
    m = metar.METAR(make_config("KDKR"), clock=CLOCK)
    assert m.fetch() is True  # the METARs still count as fetched
    assert m.position("KDKR") is None and m.locate_failed is True
    asked = stations_api(monkeypatch, fixture_bytes)
    assert m.locate() is True  # the app's retry calls this on its own, without fetching the METARs again
    assert asked == [["KDKR"]] and m.position("KDKR") == (31.307, -95.404)
    assert m.locate_failed is False


def test_a_failed_metar_fetch_skips_the_lookup(monkeypatch, make_config):
    asked = []
    monkeypatch.setattr(metar.requests, "get", lambda url, **kw: asked.append(url) or FakeResponse(status=502))
    metar.METAR(make_config("KDKR"), clock=CLOCK).fetch()
    assert len(asked) == 1


# ---- the parsing on its own (no METAR object, no network) ------------------------------------------------------

def test_process_is_a_plain_function(fixture_bytes):
    data, reporting, missing = metar.process(fixture_bytes("metars_houston.json"), ["KHOU", "KDKR", "KIAH"],
                                             CLOCK.now())
    assert list(data) == ["KHOU", "KDKR", "KIAH"]
    assert reporting == ["KHOU", "KIAH"] and missing == ["KDKR"]
    assert data["KIAH"]["windSpeed"] == 10 and data["KDKR"] == {}


def test_reports_too_old_count_as_missing(fixture_bytes):
    later = CLOCK.now() + metar.MAX_REPORT_AGE + timedelta(minutes=1)
    data, reporting, missing = metar.process(fixture_bytes("metars_houston.json"), ["KHOU"], later)
    assert (data, reporting, missing) == ({"KHOU": {}}, [], ["KHOU"])


# ---- reading the JSON API's fields ------------------------------------------------------------------------------

def parse(**fields):
    return metar.parse_report({**GOOD, **fields})


def test_altimeter_comes_from_the_report_text():
    """The JSON gives hPa rounded to 0.1; the report's A2995 is exact."""
    assert parse()["altimHg"] == 29.95
    assert parse(rawOb="KTST 241453Z 14009KT 10SM RMK A3001", altim=1014.2)["altimHg"] == 29.95  # not in remarks


def test_altimeter_from_hectopascals_without_an_a_group():
    assert parse(rawOb="EGLL 241450Z 24010KT 9999 FEW030 14/08 Q1013", altim=1013.0)["altimHg"] == 29.91
    assert parse(rawOb="KTST 241453Z AUTO", altim=None)["altimHg"] == 0


def test_vertical_visibility_is_in_hundreds_of_feet():
    d = parse(vertVis=2, cover="OVX", clouds=[{"cover": "OVX", "base": 200}])
    assert d["vertVisFt"] == 200
    assert d["skyConditions"] == [{"cover": "OVX", "cloudBaseFt": 200}]


def test_a_clear_sky_has_no_layers_only_a_cover():
    assert parse(cover="CLR", clouds=[])["skyConditions"] == [{"cover": "CLR", "cloudBaseFt": 0}]


def test_wind_direction_is_text_like_before():
    assert parse(wdir=80)["windDir"] == "80"
    assert parse(wdir="VRB")["windDir"] == "VRB"
    assert parse(wdir=None)["windDir"] == ""


def test_trailing_space_and_name():
    d = parse(rawOb="METAR KTST 241453Z 14009KT 10SM A2995 $ ", name="Test Field, TX, US")
    assert d["raw"].endswith("$") and d["name"] == "Test Field, TX, US"
