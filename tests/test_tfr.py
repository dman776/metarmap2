"""
Tests for TFRs (metarmap.tfr): reading the FAA's detail XML, what's in effect or upcoming, which airports are in or
near one, fetching, and the TFR visualizer.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import requests

from metarmap import tfr
from metarmap.lib import colors as colors_lib
from metarmap.metar import with_tfrs
from metarmap.models import Look, Report
from metarmap.settings import Settings
from metarmap.tfr import FOREVER, Tfrs
from metarmap.visualizers import style
from metarmap.visualizers import tfr as vis

HOUSTON = (29.98, -95.34)  # KIAH


def epoch(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()


NOW = epoch("2026-11-02T12:00:00")


def square_points(lat, lon, size):
    """Avx points around (lat, lon), as the FAA writes them (42.98154645N, 090.68611111W)."""

    def point(la, lo):
        return (
            f"<Avx><codeDatum>WGE</codeDatum><codeType>GRC</codeType><geoLat>{abs(la):.8f}{'N' if la >= 0 else 'S'}"
            f"</geoLat><geoLong>{abs(lo):012.8f}{'E' if lo >= 0 else 'W'}</geoLong></Avx>"
        )

    return "".join(
        point(la, lo)
        for la, lo in [
            (lat - size, lon - size),
            (lat - size, lon + size),
            (lat + size, lon + size),
            (lat + size, lon - size),
        ]
    )


def area_xml(
    name="Area A",
    lat=HOUSTON[0],
    lon=HOUSTON[1],
    size=0.05,
    floor="0",
    floor_code="HEI",
    ceiling="17999",
    ceiling_code="ALT",
    start="2026-11-02T10:00:00",
    end="2026-11-02T20:00:00",
    uom="FT",
    points=None,
):
    outline = points if points is not None else square_points(lat, lon, size)
    effective = f"<dateEffective>{start}</dateEffective>" if start else ""
    expire = f"<dateExpire>{end}</dateExpire>" if end else ""
    return f"""<TFRAreaGroup>
        <aseTFRArea>
          <txtName>{name}</txtName>
          <codeDistVerUpper>{ceiling_code}</codeDistVerUpper><valDistVerUpper>{ceiling}</valDistVerUpper>
          <uomDistVerUpper>{uom}</uomDistVerUpper>
          <codeDistVerLower>{floor_code}</codeDistVerLower><valDistVerLower>{floor}</valDistVerLower>
          <uomDistVerLower>{uom}</uomDistVerLower>
          <ScheduleGroup><isTimeSeparate>FALSE</isTimeSeparate>{effective}{expire}</ScheduleGroup>
        </aseTFRArea>
        <abdMergedArea><txtRmk>1</txtRmk>{outline}</abdMergedArea>
      </TFRAreaGroup>"""


def detail_xml(*areas):
    return f"<XNOTAM-Update><Group><Add><Not><TfrNot>{''.join(areas)}</TfrNot></Not></Add></Group></XNOTAM-Update>"


# ---- reading the detail XML -----------------------------------------------------------------------------------


def test_parse_detail():
    (area,) = tfr.parse_detail(detail_xml(area_xml(floor="0", floor_code="HEI", ceiling="17999", ceiling_code="ALT")))
    assert area["name"] == "Area A"
    assert (area["floor"], area["floor_ref"], area["ceiling"], area["ceiling_ref"]) == (0, "AGL", 17999, "MSL")
    assert (area["from"], area["until"]) == (epoch("2026-11-02T10:00:00"), epoch("2026-11-02T20:00:00"))
    assert area["coords"][0] == pytest.approx((HOUSTON[0] - 0.05, HOUSTON[1] - 0.05))
    assert len(area["coords"]) == 4


def test_parse_detail_several_areas_and_flight_levels():
    areas = tfr.parse_detail(
        detail_xml(
            area_xml("Area A"),
            area_xml("Area B", floor="180", floor_code="ALT", uom="FL", ceiling="600", start=None, end=None),
        )
    )
    assert [a["name"] for a in areas] == ["Area A", "Area B"]
    b = areas[1]
    assert (b["floor"], b["floor_ref"], b["ceiling"]) == (18000, "MSL", 60000)
    assert (b["from"], b["until"]) == (None, FOREVER)  # no start: in effect; no end: until further notice


def test_parse_detail_skips_areas_without_an_outline():
    line = (
        "<Avx><geoLat>29.00000000N</geoLat><geoLong>095.00000000W</geoLong></Avx>"
        "<Avx><geoLat>30.00000000N</geoLat><geoLong>095.00000000W</geoLong></Avx>"
    )  # two points: not an area
    assert tfr.parse_detail(detail_xml(area_xml(points=""), area_xml(points=line))) == []


def test_parse_detail_rejects_what_isnt_xml():
    with pytest.raises(ValueError):
        tfr.parse_detail("<html><body>Not found")


@pytest.mark.parametrize(
    "text, value",
    [
        ("42.98154645N", 42.98154645),
        ("090.68611111W", -90.68611111),
        ("12.5S", -12.5),
        ("100.0E", 100.0),
        ("", None),
        (None, None),
        ("abcN", None),
    ],
)
def test_degrees(text, value):
    assert tfr.degrees(text) == value


# ---- distance -------------------------------------------------------------------------------------------------


def test_distance_nm():
    box = [(29.0, -96.0), (29.0, -95.0), (30.0, -95.0), (30.0, -96.0)]
    assert tfr.distance_nm(29.5, -95.5, box) == 0  # inside
    assert tfr.distance_nm(30.5, -95.5, box) == pytest.approx(30, rel=0.01)  # half a degree of latitude north
    assert tfr.distance_nm(29.5, -94.5, box) == pytest.approx(30 * 0.87, rel=0.02)  # half a degree of longitude east


# ---- fetching -------------------------------------------------------------------------------------------------


class FakeFaa:
    """Answers the list and details; counts what was asked."""

    def __init__(self, listed, details, fail=()):
        self.listed, self.details, self.fail = listed, details, set(fail)
        self.urls = []

    def __call__(self, url, **kwargs):
        self.urls.append(url)
        if url in self.fail:
            raise requests.exceptions.ConnectionError("down")
        if url == tfr.LIST_URL:
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: self.listed)
        notam = url.rsplit("detail_", 1)[1][:-4].replace("_", "/")
        return SimpleNamespace(raise_for_status=lambda: None, text=self.details[notam])


def item(notam, kind="SECURITY", description="HOUSTON, TX"):
    return {
        "notam_id": notam,
        "type": kind,
        "facility": "ZHU",
        "state": "TX",
        "description": description,
        "creation_date": "11/01/2026",
    }


def make(listed, details, nearby=10, fail=()):
    faa = FakeFaa(listed, details, fail)
    clock = SimpleNamespace(t=NOW)
    found = Tfrs(nearby=lambda: nearby, get=faa, clock=lambda: clock.t, sleep=lambda s: None)
    return found, faa, clock


def test_fetch_gets_each_detail_once():
    found, faa, _ = make(
        [item("6/1"), item("6/2", "VIP")], {"6/1": detail_xml(area_xml()), "6/2": detail_xml(area_xml())}
    )
    assert found.at(*HOUSTON) is None  # nothing fetched yet
    assert found.fetch() is True
    assert faa.urls == [
        tfr.LIST_URL,
        "https://tfr.faa.gov/download/detail_6_1.xml",
        "https://tfr.faa.gov/download/detail_6_2.xml",
    ]
    found.fetch()
    assert faa.urls[3:] == [tfr.LIST_URL]  # the details are known
    assert found.at(*HOUSTON) == [
        {"type": "VIP", "upcoming": False, "inside": True},
        {"type": "SECURITY", "upcoming": False, "inside": True},
    ]


def test_a_tfr_that_leaves_the_list_is_forgotten():
    found, faa, _ = make([item("6/1")], {"6/1": detail_xml(area_xml())})
    found.fetch()
    faa.listed = []
    found.fetch()
    assert found.at(*HOUSTON) == [] and found._details == {}


def test_types_it_doesnt_know_are_left_out():
    found, faa, _ = make([item("6/1", "SOMETHING NEW")], {"6/1": detail_xml(area_xml())})
    found.fetch()
    assert found.at(*HOUSTON) == [] and faa.urls == [tfr.LIST_URL]


def test_a_detail_that_fails_is_tried_again_next_time():
    url = "https://tfr.faa.gov/download/detail_6_1.xml"
    found, faa, _ = make([item("6/1")], {"6/1": detail_xml(area_xml())}, fail={url})
    assert found.fetch() is True
    assert found.at(*HOUSTON) == []
    faa.fail = set()
    found.fetch()
    assert found.at(*HOUSTON) == [{"type": "SECURITY", "upcoming": False, "inside": True}]


def test_after_three_failed_details_the_rest_wait():
    listed = [item(f"6/{n}") for n in range(1, 6)]
    found, faa, _ = make(listed, {}, fail={f"https://tfr.faa.gov/download/detail_6_{n}.xml" for n in range(1, 6)})
    found.fetch()
    assert len(faa.urls) == 1 + 3


def test_a_failed_list_keeps_the_last_tfrs():
    found, faa, _ = make([item("6/1")], {"6/1": detail_xml(area_xml())})
    found.fetch()
    faa.fail = {tfr.LIST_URL}
    assert found.fetch() is False
    assert "couldn't get the TFR list" in found.error
    assert found.at(*HOUSTON) == [{"type": "SECURITY", "upcoming": False, "inside": True}]


def test_fetch_soon_runs_in_the_background_then_calls_back():
    found, _, _ = make([item("6/1")], {"6/1": detail_xml(area_xml())})
    done = []
    import threading

    finished = threading.Event()
    found.fetch_soon(then=lambda: (done.append(True), finished.set()))
    assert finished.wait(5) and done == [True]


# ---- what's in effect, and where ------------------------------------------------------------------------------


def test_in_effect_upcoming_or_neither():
    found, _, clock = make(
        [item("6/1")], {"6/1": detail_xml(area_xml(start="2026-11-03T08:00:00", end="2026-11-03T20:00:00"))}
    )
    found.fetch()
    assert found.at(*HOUSTON) == [{"type": "SECURITY", "upcoming": True, "inside": True}]  # starts in 20 h
    clock.t = epoch("2026-11-01T12:00:00")
    assert found.at(*HOUSTON) == []  # more than 24 h away
    clock.t = epoch("2026-11-03T09:00:00")
    assert found.at(*HOUSTON) == [{"type": "SECURITY", "upcoming": False, "inside": True}]
    clock.t = epoch("2026-11-03T20:00:00")
    assert found.at(*HOUSTON) == []  # over


def test_high_floors_are_left_out():
    found, _, _ = make([item("6/1")], {"6/1": detail_xml(area_xml(floor="18000", floor_code="ALT"))})
    found.fetch()
    assert found.at(*HOUSTON) == []


def test_nearby():
    # a TFR about 12 NM north of the airport
    details = {"6/1": detail_xml(area_xml(lat=HOUSTON[0] + 0.25, size=0.04))}
    for nearby, expected in [(0, []), (10, []), (15, [{"type": "SECURITY", "upcoming": False, "inside": False}])]:
        found, _, _ = make([item("6/1")], details, nearby=nearby)
        found.fetch()
        assert found.at(*HOUSTON) == expected, nearby


def test_order_in_effect_then_inside_then_type():
    details = {
        "6/1": detail_xml(area_xml(start="2026-11-02T20:00:00", end="2026-11-02T23:00:00")),  # VIP, upcoming
        "6/2": detail_xml(area_xml(lat=HOUSTON[0] + 0.2, size=0.04)),  # VIP, nearby
        "6/3": detail_xml(area_xml()),
    }  # air show, inside
    found, _, _ = make([item("6/1", "VIP"), item("6/2", "VIP"), item("6/3", "AIR SHOWS/SPORTS")], details, nearby=15)
    found.fetch()
    assert found.at(*HOUSTON) == [
        {"type": "AIR SHOWS/SPORTS", "upcoming": False, "inside": True},
        {"type": "VIP", "upcoming": False, "inside": False},
        {"type": "VIP", "upcoming": True, "inside": True},
    ]


def test_state():
    found, _, _ = make([item("6/1", "VIP", "Dubuque, IA")], {"6/1": detail_xml(area_xml(end=None))})
    assert found.state()["areas"] == []
    found.fetch()
    state = found.state()
    (area,) = state["areas"]
    assert area["notam"] == "6/1" and area["description"] == "Dubuque, IA" and area["until"] is None
    assert area["url"] == "https://tfr.faa.gov/tfr3/?page=detail_6_1"
    assert state["fetched"] == NOW and state["error"] is None and state["nearby_nm"] == 10


# ---- each METAR gets its TFRs ---------------------------------------------------------------------------------


def test_with_tfrs():
    found, _, _ = make([item("6/1")], {"6/1": detail_xml(area_xml())})
    found.fetch()
    data = {
        "KIAH": Report(raw="...", latitude=HOUSTON[0], longitude=HOUSTON[1]),
        "KDFW": Report(raw="...", latitude=32.9, longitude=-97.04),
        "KXXX": Report(raw="..."),
        "KDKR": None,
    }
    result = with_tfrs(data, found)
    assert result["KIAH"].tfrs == [{"type": "SECURITY", "upcoming": False, "inside": True}]
    assert result["KDFW"].tfrs == [] and result["KXXX"].tfrs is None
    assert result["KDKR"] is None  # no report: stays None


# ---- the visualizer -------------------------------------------------------------------------------------------


@pytest.fixture
def settings():
    return Settings()


def color(name):
    return colors_lib.get_colors()[name]


@pytest.mark.parametrize(
    "tfrs, expected",
    [
        ([], Look.solid(color(colors_lib.GRAY))),
        ([{"type": "VIP", "upcoming": False, "inside": True}], Look.solid(color(colors_lib.RED))),
        ([{"type": "HAZARDS", "upcoming": False, "inside": False}], Look.solid(style.dim(color(colors_lib.ORANGE)))),
        (
            [{"type": "SECURITY", "upcoming": True, "inside": True}],
            Look.pulse(color(colors_lib.MAGENTA), period=style.LIGHT_PERIOD, low=style.LIGHT_LOW),
        ),
        (
            [
                {"type": "UAS PUBLIC GATHERING", "upcoming": False, "inside": True},
                {"type": "VIP", "upcoming": True, "inside": True},
            ],
            Look.solid(color(colors_lib.CYAN)),
        ),  # the first one
    ],
)
def test_look(settings, tfrs, expected):
    assert vis.look(Report(raw="...", tfrs=tfrs), settings) == expected


def test_look_without_data(settings):
    assert vis.look(None, settings) == style.no_report()
    assert vis.look(Report(raw="...", tfrs=None), settings) == style.missing()


def test_legend(settings):
    labels = [i["label"] for i in vis.legend(settings)]
    assert labels[0].startswith("VIP") and "Within 10 NM of a TFR" in labels and "No TFR within 10 NM" in labels
    settings.tfr.nearby_nm = 0
    labels = [i["label"] for i in vis.legend(settings)]
    assert not any(label.startswith("Within") for label in labels) and "No TFR" in labels


def test_every_type_has_a_color():
    assert set(vis.COLORS) == set(tfr.TYPES)
    assert vis.css("VIP") == colors_lib.to_css(color(colors_lib.RED))
