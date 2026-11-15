"""
Tests for the FAA airport status (metarmap.delays): reading the feed's XML (today's real one, and the documented
ASWS-style Ground Delay Program, Ground Stop and Arrival/Departure delays the live feed hasn't shown yet), which
closures count, what's in effect, fetching, and mapping the Chart's ICAO codes to the FAA's ids (metar.faa_id).
"""

import re
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from metarmap import delays
from metarmap.delays import CLOSED, DELAY, FOREVER, GROUND_STOP, NORMAL, Delays, parse
from metarmap.metar import faa_id, with_delays
from metarmap.models import Report

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = (FIXTURES / "faa_status_2026-11-14.xml").read_text()


def epoch(text):
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp()


NOW = epoch("2026-11-14 18:16")


def feed(*delay_types, updated="Sat Nov 14 18:16:36 2026 GMT"):
    stamp = f"<Update_Time>{updated}</Update_Time>" if updated is not None else ""
    return (
        f"<AIRPORT_STATUS_INFORMATION>{stamp}<Dtd_File>http://www.fly.faa.gov/AirportStatus.dtd</Dtd_File>"
        + "".join(delay_types)
        + "</AIRPORT_STATUS_INFORMATION>"
    )


def closures(*airports):
    return (
        "<Delay_type><Name>Airport Closures</Name><Airport_Closure_List>"
        + "".join(airports)
        + "</Airport_Closure_List></Delay_type>"
    )


def closure(code, reason, start="", reopen=""):
    return (
        f"<Airport><ARPT>{code}</ARPT><Reason>{reason}</Reason>"
        f"<Start>{start}</Start><Reopen>{reopen}</Reopen></Airport>"
    )


# the FAA's documented format (fly.faa.gov's ASWS XML): not seen in the live feed yet
GROUND_DELAYS = (
    "<Delay_type><Name>Ground Delay Programs</Name><Ground_Delay_List>"
    "<Ground_Delay><ARPT>EWR</ARPT><Reason>low ceilings</Reason><Avg>2 hours and 18 minutes</Avg>"
    "<Max>3 hours and 41 minutes</Max></Ground_Delay>"
    "<Ground_Delay><ARPT>SFO</ARPT><Reason>wind</Reason><Avg>45 minutes</Avg><Max>1 hour and 2 minutes</Max>"
    "</Ground_Delay>"
    "</Ground_Delay_List></Delay_type>"
)
GROUND_STOPS = (
    "<Delay_type><Name>Ground Stops</Name><Ground_Stop_List>"
    "<Program><ARPT>LGA</ARPT><Reason>thunderstorms</Reason><End_Time>7:45 pm EST</End_Time></Program>"
    "</Ground_Stop_List></Delay_type>"
)
ARRIVAL_DEPARTURE = (
    "<Delay_type><Name>General Arrival/Departure Delay Info</Name><Arrival_Departure_Delay_List>"
    "<Delay><ARPT>ORD</ARPT><Reason>VOL:Volume</Reason>"
    '<Arrival_Departure Type="Arrival"><Min>16 minutes</Min><Max>30 minutes</Max><Trend>Increasing</Trend>'
    "</Arrival_Departure>"
    '<Arrival_Departure Type="Departure"><Min>31 minutes</Min><Max>45 minutes</Max><Trend>Steady</Trend>'
    "</Arrival_Departure></Delay>"
    "</Arrival_Departure_Delay_List></Delay_type>"
)
AIRSPACE_FLOW = (
    "<Delay_type><Name>Airspace Flow Programs</Name><Airspace_Flow_List><Airspace_Flow>"
    "<CTL_Element>FCAA05</CTL_Element><Reason>WEATHER</Reason><AFP_StartTime>1800</AFP_StartTime>"
    "</Airspace_Flow></Airspace_Flow_List></Delay_type>"
)


# ---- today's real feed ----------------------------------------------------------------------------------------


def test_todays_feed_has_only_partial_closures():
    """
    2026-11-14: SUA closed except to the air show's aircraft, and LAX, SAN and LAS closed to non-scheduled transient GA
    by long-running NOTAMs (to 2027): none is a full closure, so no airport counts.
    """
    unknown = set()
    airports, updated = parse(TODAY, unknown)
    assert airports == {}
    assert updated == epoch("2026-11-14 18:16") + 36
    assert unknown == set()


def test_todays_closures_count_without_their_partial_words():
    full = re.sub(r" TO NON SKED TRANSIENT GA ACFT| EXC( 24HR)? PPR| EXC AIRSHOW ACFT", "", TODAY)
    airports, _ = parse(full)
    assert set(airports) == {"SUA", "LAX", "SAN", "LAS"}
    (lax,) = airports["LAX"]
    assert lax == {
        "kind": CLOSED,
        "minutes": None,
        "from": epoch("2026-05-27 18:26"),
        "until": epoch("2027-05-28 16:00"),
        "reason": "!LAX 05/277 LAX AD AP CLSD CTC ATLANTIC AVIATION 310-258-9884 OR "
        "SIGNATURE AVIATION 310-410-9605 2605271826-2705281600",
    }
    assert delays.worst(airports["SUA"], NOW)["kind"] == CLOSED  # 16:00-22:30 today
    assert delays.worst(airports["SUA"], epoch("2026-11-14 23:00"))["kind"] == NORMAL  # reopened


# ---- closures -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reason",
    [
        "!SAN 10/004 SAN AD AP CLSD TO NON SKED TRANSIENT GA ACFT EXC PPR 619-298-7704 2610011633-2701010800",
        "!MIA 11/159 SUA AD AP CLSD EXC AIRSHOW ACFT 2611141600-2611142230",
        "!ABC 11/001 ABC AD AP CLSD PPR 555-1212 2611140000-2611200000",
    ],
)
def test_partial_closures_are_left_out(reason):
    assert parse(feed(closures(closure("ABC", reason)))) == ({}, epoch("2026-11-14 18:16") + 36)


@pytest.mark.parametrize("code", ["", "AB", "MIAMI", "A-B", "SUA AIRSHOW"])
def test_ids_that_arent_airport_ids_are_left_out(code):
    reason = "!ABC 11/001 ABC AD AP CLSD 2611140000-2611200000"
    assert parse(feed(closures(closure(code, reason))))[0] == {}


def test_a_closure_is_in_effect_between_its_notams_dates():
    """The NOTAM's YYMMDDhhmm range gives the year; Start and Reopen ("Nov 14 at 16:00 UTC.") have none."""
    reason = "!JFK 11/001 JFK AD AP CLSD 2611150600-2611151000"
    (entry,) = parse(feed(closures(closure("JFK", reason, "Nov 15 at 06:00 UTC.", "Nov 15 at 10:00 UTC."))))[0]["JFK"]
    assert (entry["from"], entry["until"]) == (epoch("2026-11-15 06:00"), epoch("2026-11-15 10:00"))
    assert delays.worst([entry], NOW)["kind"] == NORMAL  # not yet
    assert delays.worst([entry], epoch("2026-11-15 07:00"))["kind"] == CLOSED
    assert delays.worst([entry], epoch("2026-11-15 10:00"))["kind"] == NORMAL  # reopened


def test_a_notam_range_across_the_new_year():
    assert delays.notam_range("... CLSD 2612312200-2701010600") == (
        epoch("2026-12-31 22:00"),
        epoch("2027-01-01 06:00"),
    )


def test_a_notam_range_estimated_or_permanent():
    assert delays.notam_range("CLSD 2611140000-2611200000EST") == (epoch("2026-11-14 00:00"), epoch("2026-11-20 00:00"))
    assert delays.notam_range("CLSD 2611140000-PERM") == (epoch("2026-11-14 00:00"), FOREVER)
    assert delays.notam_range("CLSD") is None
    assert delays.notam_range("CLSD 2613140000-2611200000") is None  # month 13


def test_without_a_notam_range_start_and_reopen_get_the_feeds_year():
    entry = parse(feed(closures(closure("JFK", "AD AP CLSD", "Nov 14 at 16:00 UTC.", "Nov 14 at 22:30 UTC."))))[0]
    assert (entry["JFK"][0]["from"], entry["JFK"][0]["until"]) == (epoch("2026-11-14 16:00"), epoch("2026-11-14 22:30"))


def test_start_and_reopen_across_the_new_year():
    """Updated on Dec 31: a closure from Dec 31 to Jan 2 reopens in the next year, and one from Jan 2 to Jan 3 too."""
    updated = "Thu Dec 31 12:00:00 2026 GMT"
    xml = feed(
        closures(
            closure("JFK", "AD AP CLSD", "Dec 31 at 06:00 UTC.", "Jan 02 at 08:00 UTC."),
            closure("LGA", "AD AP CLSD", "Jan 02 at 06:00 UTC.", "Jan 03 at 08:00 UTC."),
        ),
        updated=updated,
    )
    airports, _ = parse(xml)
    assert (airports["JFK"][0]["from"], airports["JFK"][0]["until"]) == (
        epoch("2026-12-31 06:00"),
        epoch("2027-01-02 08:00"),
    )
    assert airports["LGA"][0]["from"] == epoch("2027-01-02 06:00")


def test_a_closure_without_any_dates_is_in_effect():
    """Listed in the feed with nothing to say when: closed now, as the feed says."""
    (entry,) = parse(feed(closures("<Airport><ARPT>JFK</ARPT><Reason>AD AP CLSD</Reason></Airport>")))[0]["JFK"]
    assert delays.worst([entry], NOW)["kind"] == CLOSED


def test_a_closure_without_an_update_time_or_reopen():
    (entry,) = parse(feed(closures(closure("JFK", "AD AP CLSD", "Nov 14 at 06:00 UTC.")), updated=None))[0]["JFK"]
    assert (entry["from"], entry["until"]) == (None, FOREVER)  # no year to place Start in: in effect


# ---- ground delays, ground stops, arrival and departure delays (UNVERIFIED: the documented format) ---------------


def test_ground_delay_programs_by_their_average():
    airports, _ = parse(feed(GROUND_DELAYS))
    assert airports["EWR"] == [
        {"kind": DELAY, "minutes": 138, "from": None, "until": FOREVER, "reason": "low ceilings"}
    ]
    assert airports["SFO"][0]["minutes"] == 45


def test_ground_stops():
    airports, _ = parse(feed(GROUND_STOPS))
    assert airports == {
        "LGA": [{"kind": GROUND_STOP, "minutes": None, "from": None, "until": FOREVER, "reason": "thunderstorms"}]
    }


def test_arrival_and_departure_delays_by_the_worst_middle_of_their_range():
    airports, _ = parse(feed(ARRIVAL_DEPARTURE))
    assert airports["ORD"][0]["kind"] == DELAY
    assert airports["ORD"][0]["minutes"] == 38  # departures: 31-45 minutes


def test_airspace_flow_programs_are_not_an_airports():
    unknown = set()
    assert parse(feed(AIRSPACE_FLOW), unknown)[0] == {} and unknown == set()


def test_unknown_delay_types_are_ignored_and_named():
    unknown = set()
    xml = feed("<Delay_type><Name>Deicing</Name><List><Item><ARPT>DEN</ARPT></Item></List></Delay_type>", GROUND_STOPS)
    assert set(parse(xml, unknown)[0]) == {"LGA"}
    assert unknown == {"Deicing"}


def test_renamed_wrappers_still_find_the_airports():
    """Any element with an ARPT is an airport's entry, whatever the list and entry are called."""
    xml = feed("<Delay_type><Name>Ground Stops</Name><Stops><Stop><ARPT>BOS</ARPT></Stop></Stops></Delay_type>")
    assert parse(xml)[0]["BOS"][0]["kind"] == GROUND_STOP


def test_a_delay_without_readable_minutes():
    xml = feed(
        "<Delay_type><Name>Ground Delay Programs</Name><Ground_Delay_List><Ground_Delay><ARPT>EWR</ARPT>"
        "<Avg>a while</Avg></Ground_Delay></Ground_Delay_List></Delay_type>"
    )
    assert parse(xml)[0]["EWR"][0]["minutes"] is None


@pytest.mark.parametrize(
    "words, minutes",
    [
        ("2 hours and 18 minutes", 138),
        ("1 hour and 3 minutes", 63),
        ("1 hour", 60),
        ("45 minutes", 45),
        ("16 minutes", 16),
        ("", None),
        ("soon", None),
    ],
)
def test_minutes(words, minutes):
    assert delays.minutes(words) == minutes


# ---- the worst one --------------------------------------------------------------------------------------------


def test_the_worst_status_wins():
    airports, _ = parse(
        feed(
            GROUND_DELAYS,
            GROUND_STOPS.replace("LGA", "EWR"),
            closures(closure("SFO", "AD AP CLSD 2611140000-2611200000")),
            ARRIVAL_DEPARTURE.replace("ORD", "SFO"),
        )
    )
    ewr = delays.worst(airports["EWR"], NOW)  # the ground stop is over its 138-minute GDP
    assert (ewr["kind"], ewr["reason"], ewr["until"]) == (GROUND_STOP, "thunderstorms", None)
    sfo = delays.worst(airports["SFO"], NOW)
    assert (sfo["kind"], sfo["reason"], sfo["until"]) == (
        CLOSED,
        "AD AP CLSD 2611140000-2611200000",
        epoch("2026-11-20 00:00"),
    )
    assert delays.worst([], NOW) == {"kind": NORMAL, "minutes": None}
    two = [{"kind": DELAY, "minutes": 20, "from": None, "until": FOREVER}, {**airports["EWR"][0]}]
    assert delays.worst(two, NOW)["minutes"] == 138  # the longer delay


# ---- bad feeds --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text", ["", "<AIRPORT_STATUS_INFORMATION><Delay_type>", "not xml", "<html><body>Bad gateway</body></html>"]
)
def test_what_isnt_the_feed_is_an_error(text):
    with pytest.raises(ValueError):
        parse(text)


def test_an_empty_feed_has_no_delays():
    assert parse("<AIRPORT_STATUS_INFORMATION/>") == ({}, None)
    assert parse(feed()) == ({}, epoch("2026-11-14 18:16") + 36)


def test_missing_tags_dont_break_it():
    xml = feed(
        "<Delay_type><Airport_Closure_List><Airport><ARPT>JFK</ARPT></Airport></Airport_Closure_List></Delay_type>",
        "<Delay_type><Name>Airport Closures</Name><Airport_Closure_List><Airport><ARPT>JFK</ARPT></Airport>"
        "</Airport_Closure_List></Delay_type>",
        "<Delay_type><Name>Ground Delay Programs</Name></Delay_type>",
    )
    unknown = set()
    airports, _ = parse(xml, unknown)
    assert airports["JFK"][0]["kind"] == CLOSED  # no Reason: no partial words, and no dates
    assert unknown == {""}  # the Delay_type without a Name


# ---- fetching ---------------------------------------------------------------------------------------------------


class Get:
    def __init__(self, text=TODAY, status=200):
        self.text, self.status, self.calls = text, status, []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if isinstance(self.text, Exception):
            raise self.text
        response = SimpleNamespace(text=self.text, status_code=self.status)

        def raise_for_status():
            if self.status >= 400:
                raise requests.exceptions.HTTPError(f"{self.status}")

        response.raise_for_status = raise_for_status
        return response


def test_fetch_and_status():
    get = Get(feed(GROUND_DELAYS, GROUND_STOPS))
    d = Delays(get=get, clock=lambda: NOW)
    assert d.status("EWR") is None  # before the first fetch
    assert d.fetch() is True
    url, kwargs = get.calls[0]
    assert url == delays.STATUS_URL and kwargs["headers"]["User-Agent"].startswith("metarmap2/")
    assert d.status("EWR") == {"kind": DELAY, "minutes": 138, "reason": "low ceilings", "until": None}
    assert d.status("lga") == {"kind": GROUND_STOP, "minutes": None, "reason": "thunderstorms", "until": None}
    assert d.status("IAH") == {"kind": NORMAL, "minutes": None}
    assert d.fetched == NOW and d.error is None


def test_a_fetch_that_changes_nothing_needs_no_redraw():
    d = Delays(get=Get(TODAY), clock=lambda: NOW)
    assert d.fetch() is True  # the first one always does
    assert d.fetch() is False


def test_a_closure_that_starts_between_fetches_is_a_change():
    now = [NOW]
    xml = feed(closures(closure("JFK", "AD AP CLSD 2611141900-2611142200")))
    d = Delays(get=Get(xml), clock=lambda: now[0])
    assert d.fetch() is True and d.status("JFK")["kind"] == NORMAL
    now[0] = epoch("2026-11-14 19:05")
    assert d.fetch() is True and d.status("JFK")["kind"] == CLOSED


@pytest.mark.parametrize(
    "get", [Get("<html>oops</html>"), Get(TODAY, status=503), Get(requests.exceptions.ConnectionError("offline"))]
)
def test_a_failed_fetch_keeps_the_last_status(get, caplog):
    d = Delays(get=Get(feed(GROUND_STOPS)), clock=lambda: NOW)
    d.fetch()
    d._get = get
    assert d.fetch() is False
    assert d.fetch() is False
    assert d.status("LGA")["kind"] == GROUND_STOP and d.error
    assert sum("FAA airport status" in r.message for r in caplog.records) == 1  # logged once


def test_an_unknown_delay_type_is_logged_once(caplog):
    xml = feed("<Delay_type><Name>Deicing</Name></Delay_type>")
    d = Delays(get=Get(xml), clock=lambda: NOW)
    d.fetch()
    d.fetch()
    assert sum("Deicing" in r.message for r in caplog.records) == 1


def test_fetch_soon_redraws_when_it_changed():
    import threading

    done = threading.Event()
    Delays(get=Get(feed(GROUND_STOPS)), clock=lambda: NOW).fetch_soon(then=done.set)
    assert done.wait(5)


# ---- the Chart's codes and the FAA's ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code, known, expected",
    [
        ("KSAN", {"faa": "SAN"}, "SAN"),
        ("PHNL", {"faa": "HNL"}, "HNL"),  # Hawaii: not P minus its first letter
        ("TJSJ", {"faa": "SJU"}, "SJU"),
        ("KSAN", None, "SAN"),  # not looked up yet, or unknown: the K comes off
        ("KSAN", {"faa": ""}, "SAN"),
        ("PHNL", None, None),  # can't be guessed
        ("CYYZ", {"faa": ""}, None),  # abroad
        ("52F", None, "52F"),
        ("", None, None),
    ],
)
def test_faa_id(code, known, expected):
    assert faa_id(code, known) == expected


def test_with_delays():
    d = Delays(get=Get(feed(GROUND_STOPS.replace("LGA", "HNL"), GROUND_DELAYS)), clock=lambda: NOW)
    d.fetch()
    data = {"PHNL": Report(), "KEWR": Report(), "KIAH": Report(), "CYYZ": Report(), "KXXX": None}
    known = {"PHNL": {"faa": "HNL"}, "CYYZ": {"faa": ""}}
    shown = with_delays(data, d, known)
    assert shown["PHNL"].faa_status["kind"] == GROUND_STOP
    assert shown["KEWR"].faa_status == {"kind": DELAY, "minutes": 138, "reason": "low ceilings", "until": None}
    assert shown["KIAH"].faa_status["kind"] == NORMAL
    assert shown["CYYZ"].faa_status == {"kind": NORMAL, "minutes": None}  # no FAA id: not in the FAA's status
    before = with_delays(data, Delays(get=Get(), clock=lambda: NOW), known)
    assert before["CYYZ"].faa_status is None and before["KEWR"].faa_status is None  # nothing fetched yet
    assert shown["KXXX"] is None  # no report stays None


# ---- saying it in a sentence ------------------------------------------------------------------------------------


def test_describe():
    until = epoch("2026-11-14 22:30")
    assert delays.describe({"kind": CLOSED, "minutes": None, "until": until}) == "Closed by the FAA until 14 Nov 22:30Z"
    assert delays.describe({"kind": CLOSED, "minutes": None, "until": FOREVER}) == "Closed by the FAA"
    assert delays.describe({"kind": GROUND_STOP, "minutes": None}) == "FAA ground stop"
    assert delays.describe({"kind": DELAY, "minutes": 45}) == "FAA delay of about 45 min"
    assert delays.describe({"kind": DELAY, "minutes": 138}) == "FAA delay of about 2 h 18 min"
    assert delays.describe({"kind": DELAY, "minutes": None}) == "FAA delay"
    assert delays.describe({"kind": NORMAL, "minutes": None}) == ""
    assert delays.describe(None) == ""
