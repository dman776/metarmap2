"""
Tests for TFRs (metarmap.tfr): reading the FAA's detail XML, what's in effect or upcoming, which airports are in or
near one, fetching, and the TFR visualizer.
"""

import math
import random
import threading
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import requests

from metarmap import tfr
from metarmap.lib import colors as colors_lib
from metarmap.metar import with_tfrs
from metarmap.models import Look, Report
from metarmap.settings import Settings
from metarmap.tfr import FOREVER, Tfrs, distance_nm
from metarmap.visualizers import style, visualizer
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


# ---- at() works each distance out once, and skips the far areas -----------------------------------------------


def brute_force_at(found, lat, lon):
    """at() as it was before the bounding boxes and the memory: every area's distance, every time."""
    areas = found.areas()
    if areas is None:
        return None
    reach = found.nearby_nm()
    seen = {}
    for area in areas:
        distance = distance_nm(lat, lon, area["coords"])
        if distance > reach:
            continue
        key = (area["type"], area["upcoming"])
        seen[key] = seen.get(key, False) or distance == 0
    order = list(tfr.TYPES)
    return sorted(
        ({"type": t, "upcoming": upcoming, "inside": seen[(t, upcoming)]} for t, upcoming in seen),
        key=lambda f: (f["upcoming"], not f["inside"], order.index(f["type"])),
    )


def outline(coords):
    """Avx points for [(lat, lon), ...]."""
    return "".join(
        f"<Avx><geoLat>{abs(la):.8f}{'N' if la >= 0 else 'S'}</geoLat>"
        f"<geoLong>{abs(lo):012.8f}{'E' if lo >= 0 else 'W'}</geoLong></Avx>"
        for la, lo in coords
    )


SHAPES = {
    "square": [(29.9, -95.4), (29.9, -95.2), (30.1, -95.2), (30.1, -95.4)],
    "concave": [
        (32.5, -97.5),
        (32.5, -96.5),
        (33.5, -96.5),
        (33.5, -96.9),
        (32.8, -96.9),
        (32.8, -97.1),
        (33.5, -97.1),
        (33.5, -97.5),
    ],  # a U, open to the north
    "sliver": [(31.0, -94.0), (31.001, -93.0), (31.0, -92.0)],
    "star": [
        (
            35.0 + 0.4 * (1 if k % 2 == 0 else 0.3) * math.sin(k * math.pi / 6),
            -90.0 + 0.4 * (1 if k % 2 == 0 else 0.3) * math.cos(k * math.pi / 6),
        )
        for k in range(12)
    ],
    "date line": [(51.5, 179.6), (51.5, -179.6), (52.0, -179.6), (52.0, 179.6)],  # an Aleutian area, as given
    "far north": [(71.2, -156.9), (71.2, -156.5), (71.4, -156.5), (71.4, -156.9)],  # Utqiagvik
}


def shapes_tfrs(nearby=10, shapes=SHAPES, clock=None):
    """Tfrs with one TFR per shape, types in turn, the third in each three upcoming."""
    kinds = list(tfr.TYPES)
    listed, details = [], {}
    for n, coords in enumerate(shapes.values()):
        notam = f"6/{n}"
        listed.append(item(notam, kinds[n % len(kinds)]))
        start = "2026-11-02T20:00:00" if n % 3 == 2 else "2026-11-02T10:00:00"
        details[notam] = detail_xml(area_xml(name=notam, points=outline(coords), start=start, end=None))
    setting = SimpleNamespace(nearby=nearby)
    clock = clock or SimpleNamespace(t=NOW)
    found = Tfrs(nearby=lambda: setting.nearby, get=FakeFaa(listed, details), clock=lambda: clock.t, sleep=lambda s: 0)
    found.fetch()
    return found, setting, clock


def around(coords, step=0.1, margin=0.6):
    """A grid of places around each corner of the polygon: over it, along its edges and past the nearby distance."""
    count = round(margin / step)
    return sorted(
        {
            (round(lat + i * step, 6), round(lon + j * step, 6))
            for lat, lon in coords
            for i in range(-count, count + 1)
            for j in range(-count, count + 1)
        }
    )


@pytest.fixture
def counted(monkeypatch):
    """Counts at()'s calls to distance_nm."""
    calls = []

    def counting(lat, lon, polygon):
        calls.append((lat, lon))
        return distance_nm(lat, lon, polygon)

    monkeypatch.setattr(tfr, "distance_nm", counting)
    return calls


@pytest.mark.parametrize("nearby", [0, 10, 25, 1000])
def test_at_is_what_working_out_every_area_every_time_gives(nearby):
    found, _, _ = shapes_tfrs(nearby)
    expected = {p: brute_force_at(found, *p) for coords in SHAPES.values() for p in around(coords)}
    assert {p: found.at(*p) for p in expected} == expected
    assert {p: found.at(*p) for p in expected} == expected  # again, from memory


def test_at_matches_on_many_random_polygons_and_places():
    rng = random.Random(7)
    shapes = {}
    for n in range(60):
        lat, lon, radius, sides = rng.uniform(25, 48), rng.uniform(-124, -68), rng.uniform(0.02, 1), rng.randint(5, 30)
        shapes[n] = [
            (
                lat + radius * rng.uniform(0.3, 1) * math.sin(2 * math.pi * k / sides),
                lon + radius * rng.uniform(0.3, 1) * math.cos(2 * math.pi * k / sides),
            )
            for k in range(sides)
        ]
    found, setting, _ = shapes_tfrs(15, shapes)
    places = [(rng.uniform(25, 48), rng.uniform(-124, -68)) for _ in range(100)]
    places += [(la + rng.uniform(-0.5, 0.5), lo + rng.uniform(-0.5, 0.5)) for c in shapes.values() for la, lo in c[:2]]
    for nearby in (15, 3, 40):
        setting.nearby = nearby
        expected = {p: brute_force_at(found, *p) for p in places}
        assert {p: found.at(*p) for p in places} == expected, nearby
        assert {p: found.at(*p) for p in places} == expected, nearby  # again, from memory


def test_the_bounding_box_is_never_farther_than_the_polygon():
    rng = random.Random(3)
    for coords in list(SHAPES.values()):
        bounds = tfr.box(coords)
        for _ in range(500):
            lat, lon = rng.uniform(-80, 80), rng.uniform(-180, 180)
            if rng.random() < 0.8:  # mostly close by
                lat, lon = coords[0][0] + rng.uniform(-2, 2), coords[0][1] + rng.uniform(-2, 2)
            scale = abs(math.cos(math.radians(lat)))
            assert tfr.nearest_nm(lat, lon, scale, bounds) <= distance_nm(lat, lon, coords) + 1e-9


@pytest.mark.parametrize("nearby", [0.5, 5, 10, 12.345])
def test_an_area_right_at_the_nearby_distance_still_counts(nearby):
    found, _, _ = shapes_tfrs(nearby, {"square": SHAPES["square"]})
    (area,) = found.areas()
    south, north, west, east = tfr.box(area["coords"])
    scale = math.cos(math.radians(north))
    places = []
    for nudge in (-1e-9, 0, 1e-9):  # just inside, at and just past the nearby distance
        degrees = nearby / 60 + nudge
        places += [
            (north + degrees, (west + east) / 2),  # north of the middle
            (south - degrees, (west + east) / 2),
            ((south + north) / 2, east + degrees / scale),  # east, roughly
            (north + degrees / math.sqrt(2), east + degrees / math.sqrt(2) / scale),  # off the corner
        ]
    within = 0
    for lat, lon in places:
        expected = brute_force_at(found, lat, lon)
        assert found.at(lat, lon) == expected, (lat, lon)
        within += bool(expected)
    assert within  # some are kept, so the boundary is really tested


def test_asking_again_works_nothing_out_again(counted):
    found, _, _ = shapes_tfrs(10)
    places = around(SHAPES["square"], step=0.2, margin=1)
    first = [found.at(*p) for p in places]
    assert counted  # some were near enough to work out
    worked_out = len(counted)
    assert worked_out < len(places) * len(found.areas())  # the far ones were skipped by their boxes
    assert [found.at(*p) for p in places] == first and len(counted) == worked_out


def test_a_new_list_or_nearby_distance_starts_afresh(counted):
    found, setting, _ = shapes_tfrs(10)
    near = (SHAPES["square"][2][0] + 0.15, -95.3)  # 9 NM north of the square
    assert found.at(*near) == [{"type": "VIP", "upcoming": False, "inside": False}]
    setting.nearby = 5
    assert found.at(*near) == []  # the square's box rules it out: remembered as beyond 5 NM
    calls = len(counted)
    setting.nearby = 10
    assert found.at(*near) == [{"type": "VIP", "upcoming": False, "inside": False}] and len(counted) > calls
    calls = len(counted)
    found.fetch()  # a new list (the same TFRs, but anything could have changed)
    assert found.at(*near) == [{"type": "VIP", "upcoming": False, "inside": False}] and len(counted) > calls
    found._get.listed = []
    found.fetch()
    assert found.at(*near) == []


def test_the_clock_moving_on_needs_no_new_distances(counted):
    found, _, clock = shapes_tfrs(10)
    sliver = SHAPES["sliver"][0]  # the third shape: upcoming at NOW, in effect from 20:00
    assert found.at(*sliver) == [{"type": "SECURITY", "upcoming": True, "inside": True}]
    calls = len(counted)
    clock.t = epoch("2026-11-02T21:00:00")
    assert found.at(*sliver) == [{"type": "SECURITY", "upcoming": False, "inside": True}]
    clock.t = epoch("2026-11-01T09:00:00")  # the square (from 10:00 on the 2nd) is more than a day away
    assert found.at(29.98, -95.34) == [] == brute_force_at(found, 29.98, -95.34)
    clock.t = NOW
    assert found.at(29.98, -95.34) == [{"type": "VIP", "upcoming": False, "inside": True}]
    assert len(counted) == calls + 1  # only the square, the first time it was in view at that place


def test_only_so_many_places_are_remembered(counted, monkeypatch):
    monkeypatch.setattr(tfr, "MAX_PLACES", 5)
    found, _, _ = shapes_tfrs(1000)  # every area is near enough to be worked out
    places = [(30.0 + n / 10, -95.3) for n in range(20)]
    for place in places:
        found.at(*place)
    calls = len(counted)
    found.at(*places[-1])
    assert len(counted) == calls  # remembered
    found.at(*places[0])
    assert len(counted) > calls  # forgotten, worked out again


@pytest.mark.parametrize("lat, lon", [(float("nan"), -95.3), (30.0, float("inf")), (float("nan"), float("nan"))])
def test_places_that_arent_numbers_go_the_long_way(counted, lat, lon):
    found, _, _ = shapes_tfrs(10)
    for _ in range(3):
        assert found.at(lat, lon) == brute_force_at(found, lat, lon)
    assert len(counted) == 3 * len(found.areas())  # every area, every time: nothing remembered


def test_odd_input_fails_as_it_did():
    found, _, _ = shapes_tfrs(10)
    with pytest.raises(ValueError):  # math.cos(inf)
        found.at(float("-inf"), -95.3)
    with pytest.raises(ValueError):
        brute_force_at(found, float("-inf"), -95.3)
    with pytest.raises(TypeError):
        found.at("30", -95.3)
    with pytest.raises(TypeError):
        brute_force_at(found, "30", -95.3)
    empty, _, _ = shapes_tfrs(10, {})
    assert empty.at("30", -95.3) == [] and empty.at([30], -95.3) == []  # no areas: nothing to work out


@pytest.mark.parametrize("lat, lon", [(10**400, -95.3), (30.0, -(10**400))])
def test_an_int_too_big_for_a_float_fails_as_it_did(lat, lon):
    found, _, _ = shapes_tfrs(10)
    with pytest.raises(OverflowError) as new:
        found.at(lat, lon)
    with pytest.raises(OverflowError) as old:
        brute_force_at(found, lat, lon)
    assert str(new.value) == str(old.value)
    empty, _, _ = shapes_tfrs(10, {})
    assert empty.at(lat, lon) == [] == brute_force_at(empty, lat, lon)  # no areas: nothing to work out


def test_several_threads_at_once(monkeypatch):
    monkeypatch.setattr(tfr, "MAX_PLACES", 50)  # some forgetting while they run, too
    found, _, _ = shapes_tfrs(25)
    places = [p for coords in SHAPES.values() for p in around(coords, step=0.2)]
    expected = {p: brute_force_at(found, *p) for p in places}
    start, problems = threading.Barrier(8), []

    def ask(seed):
        order = places[:]
        random.Random(seed).shuffle(order)
        start.wait()
        for _ in range(3):
            for p in order:
                result = found.at(*p)
                if result != expected[p]:
                    problems.append((p, result))

    threads = [threading.Thread(target=ask, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert not any(t.is_alive() for t in threads) and problems == []


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
    assert vis.look(Report(raw="...", tfrs=None), settings) == style.missing()  # no position: a problem


def test_an_airport_waits_for_the_first_tfr_list_breathing_dimly(settings):
    assert vis.look(Report(raw="...", latitude=29.98, longitude=-95.34, tfrs=None), settings) == style.waiting()
    assert vis.look(Report(raw="...", latitude=29.98, longitude=-95.34, tfrs=[]), settings) != style.waiting()


def test_the_legend_tells_waiting_from_an_unknown_position(settings):
    items = {item["key"]: item for item in vis.legend(settings)}
    assert items[style.WAITING]["effect"] == "pulse" and items[style.WAITING]["label"] == "Waiting for the TFR list"
    assert items[style.MISSING]["effect"] == "blink" and "position" in items[style.MISSING]["label"]


def test_legend(settings):
    labels = [i["label"] for i in vis.legend(settings)]
    assert labels[0].startswith("VIP") and "Within 10 NM of a TFR" in labels and "No TFR within 10 NM" in labels
    settings.tfr.nearby_nm = 0
    labels = [i["label"] for i in vis.legend(settings)]
    assert not any(label.startswith("Within") for label in labels) and "No TFR" in labels


def test_every_type_has_a_color():
    assert set(vis.COLORS) == set(tfr.TYPES)
    assert vis.css("VIP") == colors_lib.to_css(color(colors_lib.RED))


def test_the_breath_survives_missing_data_blink_off(settings):
    settings.visualizer.missing_data_blink = False
    report = Report(raw="...", latitude=29.98, longitude=-95.34, tfrs=None)
    assert visualizer.look(vis.VISUALIZER, report, settings) == style.waiting()
