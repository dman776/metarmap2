"""
Tests for G-AIRMETs and SIGMETs (metarmap.advisories), the hazards added to each METAR, and the Advisories
visualizer.
"""

import pytest
import requests

from metarmap import advisories
from metarmap.advisories import Advisories
from metarmap.lib import colors as colors_lib
from metarmap.metar import with_advisories
from metarmap.models import Look, Report
from metarmap.settings import Settings
from metarmap.visualizers import advisories as vis
from metarmap.visualizers import style, visualizer

HOUSTON = (29.98, -95.34)  # KIAH
NOW = 1000.0


def square(lat, lon, size=1.0, text=True):
    """A polygon around (lat, lon), as aviationweather.gov sends it: strings for G-AIRMETs, numbers for SIGMETs."""
    kind = str if text else float
    return [
        {"lat": kind(lat - size), "lon": kind(lon - size)},
        {"lat": kind(lat - size), "lon": kind(lon + size)},
        {"lat": kind(lat + size), "lon": kind(lon + size)},
        {"lat": kind(lat + size), "lon": kind(lon - size)},
    ]


def gairmet(hazard, lat=30.0, lon=-95.0, base=None, top=None, geometry="AREA", expires=2000, **more):
    product = {"IFR": "SIERRA", "MT_OBSC": "SIERRA", "ICE": "ZULU", "FZLVL": "ZULU"}.get(hazard, "TANGO")
    return {
        "tag": "1C",
        "forecastHour": 3,
        "validTime": "2026-11-02T00:00:00.000Z",
        "hazard": hazard,
        "geometryType": geometry,
        "base": base,
        "top": top,
        "fzlbase": None,
        "fzltop": None,
        "due_to": None,
        "severity": None,
        "product": product,
        "expireTime": expires,
        "coords": square(lat, lon),
        **more,
    }


def sigmet(hazard, lat=30.0, lon=-95.0, base=None, top=45000, start=500, end=2000, **more):
    return {
        "icaoId": "KKCI",
        "firId": "KZHU",
        "seriesId": "61C",
        "hazard": hazard,
        "qualifier": "EMBD",
        "sigmetType": "OBS",
        "geom": "AREA",
        "base": base,
        "top": top,
        "dir": "E",
        "spd": "20",
        "chng": None,
        "validTimeFrom": start,
        "validTimeTo": end,
        "rawSigmet": "CONVECTIVE SIGMET 61C\nVALID UNTIL 0055Z",
        "coords": square(lat, lon, text=False),
        **more,
    }


class FakeResponse:
    def __init__(self, data=None, status=200):
        self.data = data
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if isinstance(self.data, Exception):
            raise self.data
        return self.data


class Clock:
    def __init__(self, t=NOW):
        self.t = t

    def __call__(self):
        return self.t


def make(airmets=None, sigmets=None):
    """
    Advisories answering from lists of answers per feed (each a FakeResponse or an exception, the last one repeated);
    a list of G-AIRMET/SIGMET dicts is one 200 answer.
    """
    answers = {advisories.AIRMET_URL: as_answers(airmets), advisories.SIGMET_URL: as_answers(sigmets)}
    asked = []

    def get(url, **kwargs):
        asked.append((url, kwargs["headers"]["User-Agent"]))
        queue = answers[url]
        answer = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(answer, Exception):
            raise answer
        return answer

    clock = Clock()
    return Advisories(get=get, clock=clock), asked, clock


def as_answers(given):
    if given is None:
        return [FakeResponse(status=204)]
    if isinstance(given, list) and all(isinstance(g, dict) for g in given):
        return [FakeResponse(given)]
    return list(given) if isinstance(given, (list, tuple)) else [given]


# ---- reading aviationweather.gov's answers --------------------------------------------------------------------


def test_parse_airmets_keeps_hazard_areas_below_18000_ft():
    areas = advisories.parse_airmets(
        [
            gairmet("IFR", due_to="CIG BLW 010 VIS BLW 3SM PCPN BR"),
            gairmet("TURB-LO", base="SFC", top="140", severity="MOD"),
            gairmet("TURB-HI", base="180", top="390"),  # high-level: doesn't affect the airport
            gairmet("ICE", base="FZL", top="200", fzlbase="070"),
            gairmet("ICE", base="FZL", top="300", fzlbase="190"),  # freezing level too high
            gairmet("FZLVL", geometry="LINE", level="040"),  # a freezing level line, not a hazard
            gairmet("M_FZLVL", base="SFC", top="040"),
            gairmet("SFC_WND"),
        ]
    )
    assert [(a["hazard"], a["base"], a["top"]) for a in areas] == [
        ("IFR", 0, None),
        ("TURB-LO", 0, 14000),
        ("ICE", 7000, 20000),
        ("SFC_WND", 0, None),
    ]
    ifr = areas[0]
    assert ifr["kind"] == "AIRMET" and ifr["product"] == "SIERRA" and ifr["name"] == "IFR"
    assert ifr["due_to"] == "CIG BLW 010 VIS BLW 3SM PCPN BR"
    assert ifr["coords"][0] == (29.0, -96.0) and ifr["valid"] == "2026-11-02T00:00:00.000Z"


def test_parse_sigmets_keeps_areas_below_18000_ft():
    areas = advisories.parse_sigmets(
        [
            sigmet("CONV"),
            sigmet("TURB", base=30000, top=41000),  # jet-level turbulence
            sigmet("ICE", base=8000, top=16000, qualifier="SEV", sigmetType="FCST", dir=None, spd=None),
            sigmet("XX"),  # not a hazard it knows
        ]
    )
    assert [(a["hazard"], a["base"], a["top"]) for a in areas] == [("CONV", 0, 45000), ("ICE", 8000, 16000)]
    conv, ice = areas
    assert conv == {
        "kind": "SIGMET",
        "hazard": "CONV",
        "name": "Convective SIGMET",
        "series": "61C",
        "qualifier": "EMBD",
        "observed": True,
        "base": 0,
        "top": 45000,
        "moving": "Toward E at 20 kt",
        "from": 500,
        "expires": 2000,
        "text": "CONVECTIVE SIGMET 61C\nVALID UNTIL 0055Z",
        "coords": [(29.0, -96.0), (29.0, -94.0), (31.0, -94.0), (31.0, -96.0)],
    }
    assert ice["observed"] is False and ice["moving"] is None and ice["qualifier"] == "SEV"


@pytest.mark.parametrize(
    "direction, speed, text",
    [
        (320, 5, "Toward 320° at 5 kt"),
        ("45", "0", "Toward 045°"),
        ("E", "20", "Toward E at 20 kt"),
        (None, "10", None),
        ("", None, None),
    ],
)
def test_movement(direction, speed, text):
    assert advisories.movement(direction, speed) == text


@pytest.mark.parametrize(
    "data",
    [
        None,
        {},
        [None],
        [{"hazard": "IFR", "geometryType": "AREA", "coords": "x"}],
        [{**gairmet("IFR"), "coords": [{"lat": "30", "lon": "-95"}]}],
        [{**gairmet("IFR"), "coords": [*square(30.0, -95.0)[:3], {"lat": "nan", "lon": "-95"}]}],
        [{**gairmet("IFR"), "coords": [*square(30.0, -95.0)[:3], {"lat": "30", "lon": "-inf"}]}],
    ],
)
def test_parse_skips_what_it_cant_use(data):
    assert advisories.parse_airmets(data) == []
    assert advisories.parse_sigmets(data) == []


@pytest.mark.parametrize(
    "point, expected", [((30.0, -95.0), True), ((30.9, -94.1), True), ((31.1, -95.0), False), ((30.0, -96.5), False)]
)
def test_inside(point, expected):
    polygon = [(float(c["lat"]), float(c["lon"])) for c in square(30.0, -95.0)]
    assert advisories.inside(*point, polygon) is expected


def test_inside_a_concave_area():
    # an L: the notch at the top right isn't inside
    ell = [(0, 0), (0, 4), (2, 4), (2, 2), (4, 2), (4, 0)]
    assert advisories.inside(1, 3, ell) and advisories.inside(3, 1, ell)
    assert not advisories.inside(3, 3, ell)


# ---- fetching, and the hazards over a place -------------------------------------------------------------------


def test_hazards_at():
    found, asked, _ = make(
        airmets=[
            gairmet("TURB-LO", *HOUSTON, base="SFC", top="100"),
            gairmet("ICE", *HOUSTON),
            gairmet("IFR", *HOUSTON),
            gairmet("IFR", *HOUSTON),
            gairmet("MT_OBSC", 40.0, -105.0),
        ],
        sigmets=[sigmet("TURB", *HOUSTON, base=0, top=12000), sigmet("CONV", *HOUSTON)],
    )
    assert found.hazards_at(*HOUSTON) == {"airmets": None, "sigmets": None}  # nothing fetched yet
    assert found.fetch() is True
    assert asked == [(advisories.AIRMET_URL, advisories.USER_AGENT), (advisories.SIGMET_URL, advisories.USER_AGENT)]
    # most important first, each once
    assert found.hazards_at(*HOUSTON) == {"airmets": ["ICE", "IFR", "TURB-LO"], "sigmets": ["CONV", "TURB"]}
    assert found.hazards_at(40.0, -105.0) == {"airmets": ["MT_OBSC"], "sigmets": []}
    assert found.hazards_at(35.0, -80.0) == {"airmets": [], "sigmets": []}


def corners(*points):
    """A polygon as aviationweather.gov sends a SIGMET's: [{"lat", "lon"}, ...]."""
    return [{"lat": lat, "lon": lon} for lat, lon in points]


def test_a_place_outside_an_areas_box_is_not_ray_cast(monkeypatch):
    found, _, _ = make(airmets=[gairmet("IFR", *HOUSTON)], sigmets=[sigmet("CONV", *HOUSTON)])
    found.fetch()
    cast = []
    real = advisories.inside
    monkeypatch.setattr(advisories, "inside", lambda lat, lon, polygon: cast.append(polygon) or real(lat, lon, polygon))
    assert found.hazards_at(35.0, -80.0) == {"airmets": [], "sigmets": []}  # far from every area
    assert cast == []
    assert found.hazards_at(*HOUSTON) == {"airmets": ["IFR"], "sigmets": ["CONV"]}  # in both boxes, so both are cast
    assert len(cast) == 2


# a triangle and an L, each with an empty corner of its box, and one across 180° (taken as given, not wrapped)
TRIANGLE = ((30.0, -100.0), (30.0, -96.0), (34.0, -100.0))
ELL = ((40.0, -90.0), (40.0, -86.0), (42.0, -86.0), (42.0, -88.0), (44.0, -88.0), (44.0, -90.0))
ACROSS_180 = ((50.0, 175.0), (50.0, -175.0), (55.0, -175.0), (55.0, 175.0))


def brute_force_at(found, lat, lon):
    """hazards_at() the long way: every area in effect ray cast, as before the boxes."""
    hazards = {}
    for kind, order in (("airmet", advisories.AIRMETS), ("sigmet", advisories.SIGMETS)):
        inside = {a["hazard"] for a in found.areas(kind) if advisories.inside(lat, lon, a["coords"])}
        hazards[kind + "s"] = [h for h in order if h in inside]
    return hazards


def test_the_boxes_change_no_answer():
    found, _, _ = make(
        airmets=[gairmet("IFR", coords=corners(*TRIANGLE)), gairmet("ICE", coords=corners(*ELL))],
        sigmets=[sigmet("CONV", coords=corners(*TRIANGLE)), sigmet("VA", coords=corners(*ACROSS_180))],
    )
    found.fetch()
    places = [
        (33.0, -97.0),  # in the triangle's box, past its long side
        (31.0, -99.0),  # in the triangle
        (43.0, -87.0),  # in the L's box, in its notch
        (41.0, -89.0),  # in the L
        (32.0, -100.0),  # on the triangle's west edge, its box's west side
        (34.0, -100.0),  # its north corner
        (30.0, -98.0),  # its south edge
        (44.0, -89.0),  # on the L's north edge
        (52.0, 179.0),  # inside the area across 180°, which as given spans -175..175: not in it
        (52.0, 0.0),  # in that span's middle: in it, as before the boxes
        (52.0, -180.0),
    ]
    places += [(lat / 4, lon / 4) for lat in range(110, 230) for lon in range(-410, -340, 3)]  # a grid over them
    for lat, lon in places:
        assert found.hazards_at(lat, lon) == brute_force_at(found, lat, lon), (lat, lon)
    assert found.hazards_at(31.0, -99.0) == {"airmets": ["IFR"], "sigmets": ["CONV"]}
    assert found.hazards_at(33.0, -97.0) == {"airmets": [], "sigmets": []}
    assert found.hazards_at(43.0, -87.0) == {"airmets": [], "sigmets": []}
    assert found.hazards_at(41.0, -89.0) == {"airmets": ["ICE"], "sigmets": []}
    assert found.hazards_at(52.0, 0.0) == {"airmets": [], "sigmets": ["VA"]}


@pytest.mark.parametrize("lat, lon", [(float("nan"), -95.34), (29.98, float("inf")), (29.98, float("-inf"))])
def test_a_place_that_isnt_a_number_is_in_nothing(lat, lon):
    found, _, _ = make(airmets=[gairmet("IFR", *HOUSTON)], sigmets=[sigmet("CONV", *HOUSTON)])
    found.fetch()
    assert found.hazards_at(lat, lon) == {"airmets": [], "sigmets": []} == brute_force_at(found, lat, lon)


def test_box():
    assert advisories.box(list(ELL)) == (40.0, 44.0, -90.0, -86.0)
    assert advisories.box([]) is None


def test_hazards_are_the_areas_in_effect_when_asked():
    found, _, clock = make(airmets=[gairmet("IFR", *HOUSTON, expires=2000)])
    assert found.hazards().at(*HOUSTON) == {"airmets": None, "sigmets": None}
    found.fetch()
    hazards = found.hazards()
    clock.t = 2000  # the G-AIRMET expires, but these are the ones in effect when they were asked for
    assert hazards.at(*HOUSTON) == {"airmets": ["IFR"], "sigmets": []}
    assert found.hazards().at(*HOUSTON) == {"airmets": [], "sigmets": []}


def test_only_advisories_in_effect_count():
    found, _, clock = make(
        airmets=[gairmet("IFR", *HOUSTON, expires=2000)], sigmets=[sigmet("CONV", *HOUSTON, start=1500, end=3000)]
    )
    found.fetch()
    assert found.hazards_at(*HOUSTON) == {"airmets": ["IFR"], "sigmets": []}  # the SIGMET isn't valid yet
    clock.t = 2000
    assert found.hazards_at(*HOUSTON) == {"airmets": [], "sigmets": ["CONV"]}  # the G-AIRMET expired
    clock.t = 3000
    assert found.state()["areas"] == []


def test_nothing_in_effect():
    found, _, _ = make()  # both answer 204
    assert found.fetch() is True
    assert found.hazards_at(*HOUSTON) == {"airmets": [], "sigmets": []}


@pytest.mark.parametrize(
    "failure",
    [requests.exceptions.ConnectionError("down"), FakeResponse(status=502), FakeResponse(ValueError("not json"))],
)
def test_a_failed_fetch_keeps_the_last_areas(failure):
    found, _, _ = make(
        airmets=[FakeResponse([gairmet("IFR", *HOUSTON)]), failure],
        sigmets=[FakeResponse([sigmet("CONV", *HOUSTON)]), failure],
    )
    found.fetch()
    assert found.fetch() is False
    state = found.state()
    assert "couldn't reach aviationweather.gov" in state["airmet"]["error"]
    assert "couldn't reach aviationweather.gov" in state["sigmet"]["error"]
    assert found.hazards_at(*HOUSTON) == {"airmets": ["IFR"], "sigmets": ["CONV"]}


def test_one_feed_can_fail_alone():
    found, _, _ = make(airmets=[requests.exceptions.Timeout("slow")], sigmets=[sigmet("CONV", *HOUSTON)])
    assert found.fetch() is True  # the SIGMETs came
    assert found.hazards_at(*HOUSTON) == {"airmets": None, "sigmets": ["CONV"]}
    state = found.state()
    assert state["airmet"]["fetched"] is None and state["sigmet"] == {"fetched": NOW, "error": None}
    assert [a["kind"] for a in state["areas"]] == ["SIGMET"]


def test_both_failing():
    found, _, _ = make(airmets=[requests.exceptions.Timeout("slow")], sigmets=[requests.exceptions.Timeout("slow")])
    assert found.fetch() is False
    assert found.hazards_at(*HOUSTON) == {"airmets": None, "sigmets": None}
    assert found.state()["areas"] == []


# ---- each METAR gets its hazards ------------------------------------------------------------------------------


def test_with_advisories():
    found, _, _ = make(airmets=[gairmet("IFR", *HOUSTON)], sigmets=[sigmet("CONV", *HOUSTON)])
    found.fetch()
    data = {
        "KIAH": Report(raw="...", latitude=29.98, longitude=-95.34),
        "KDFW": Report(raw="...", latitude=32.9, longitude=-97.04),
        "KXXX": Report(raw="..."),
    }
    result = with_advisories(data, found)
    assert (result["KIAH"].airmets, result["KIAH"].sigmets) == (["IFR"], ["CONV"])
    assert (result["KDFW"].airmets, result["KDFW"].sigmets) == ([], [])
    assert (result["KXXX"].airmets, result["KXXX"].sigmets) == (None, None)  # no position
    assert data["KIAH"].airmets is None  # the fetched reports are left as they were


def test_with_advisories_works_out_the_areas_in_effect_once(monkeypatch):
    found, _, _ = make(airmets=[gairmet("IFR", *HOUSTON)], sigmets=[sigmet("CONV", *HOUSTON)])
    found.fetch()
    checked = []
    real = advisories.in_effect
    monkeypatch.setattr(advisories, "in_effect", lambda area, now: checked.append(area) or real(area, now))
    data = {code: Report(raw="...", latitude=29.98 + n / 100, longitude=-95.34) for n, code in enumerate("ABCDE")}
    result = with_advisories(data, found)
    assert all((r.airmets, r.sigmets) == (["IFR"], ["CONV"]) for r in result.values())
    assert len(checked) == 2  # each area once, not once for each of the 5 airports


def test_an_airport_without_a_report_stays_none():
    """Every visualizer shows None as "METAR not available"; hazard lists would make it look like a report."""
    found, _, _ = make(airmets=[gairmet("IFR", *HOUSTON)])
    found.fetch()
    assert with_advisories({"KDKR": None}, found) == {"KDKR": None}


# ---- the visualizer -------------------------------------------------------------------------------------------


@pytest.fixture
def settings():
    return Settings()


def color(name):
    return colors_lib.get_colors()[name]


def severe(name):
    return Look.blink(color(name), period=vis.SIGMET_PERIOD, background=style.dim(color(name)))


@pytest.mark.parametrize(
    "airmets, sigmets, expected",
    [
        ([], [], Look.solid(color(colors_lib.DIM_WHITE))),
        (["IFR"], [], Look.solid(color(colors_lib.ORANGE))),
        (["ICE"], None, Look.solid(color(colors_lib.CYAN))),  # the SIGMETs didn't come: the AIRMETs still show
        (["TURB-LO", "TURB-HI"], [], Look.solid(color(colors_lib.YELLOW))),  # one color for both turbulences
        (
            ["ICE", "IFR"],
            [],
            Look.blink(color(colors_lib.CYAN), period=vis.MIXED_PERIOD, background=color(colors_lib.ORANGE)),
        ),
        (
            ["ICE", "IFR", "SFC_WND"],
            [],
            Look.blink(color(colors_lib.CYAN), period=vis.MIXED_PERIOD, background=color(colors_lib.ORANGE)),
        ),
        # a SIGMET takes over, the most serious one
        (["IFR"], ["CONV"], severe(colors_lib.RED)),
        ([], ["ICE", "TURB"], severe(colors_lib.CYAN)),
        ([], ["MTW"], severe(colors_lib.YELLOW)),
        ([], ["VA"], severe(colors_lib.ORANGE)),
        (None, ["TS"], severe(colors_lib.RED)),  # the G-AIRMETs didn't come, but a SIGMET is enough
    ],
)
def test_look(settings, airmets, sigmets, expected):
    assert vis.look(Report(raw="...", airmets=airmets, sigmets=sigmets), settings) == expected


def test_look_without_data(settings):
    assert vis.look(None, settings) == style.no_report()
    # no position: nowhere to look the airport up, a problem
    assert vis.look(Report(raw="...", airmets=None, sigmets=None), settings) == style.missing()
    assert vis.look(Report(raw="...", airmets=None, sigmets=[]), settings) == style.missing()
    assert vis.look(Report(raw="..."), settings) == style.missing()


def test_an_airport_waits_for_the_first_g_airmets_breathing_dimly(settings):
    """With a position but no G-AIRMET list yet it's waiting, not the red of a problem."""
    waiting = vis.look(Report(raw="...", latitude=29.98, longitude=-95.34), settings)
    assert waiting == style.waiting() and waiting != style.missing()
    assert waiting.legend == (style.WAITING,)
    assert vis.look(Report(raw="...", latitude="29.98", longitude="-95.34"), settings) == style.waiting()
    # a SIGMET is enough, and no position stays red whatever the feeds did
    assert vis.look(Report(raw="...", latitude=1.0, longitude=2.0, sigmets=["TS"]), settings) != style.waiting()
    assert vis.look(Report(raw="...", latitude="north", longitude="west"), settings) == style.missing()


def test_legend(settings):
    items = vis.legend(settings)
    labels = [item["label"] for item in items]
    assert labels[:10] == [
        "SIGMET: thunderstorms (convective) or tropical cyclone",
        "SIGMET: severe icing",
        "SIGMET: severe turbulence or mountain wave",
        "SIGMET: volcanic ash, dust or sand storm",
        "Sierra: IFR, ceiling below 1,000 ft or visibility below 3 mi",
        "Sierra: mountain obscuration",
        "Tango: turbulence (moderate)",
        "Tango: low-level wind shear",
        "Tango: strong surface wind, sustained 30 kt or more",
        "Zulu: icing (moderate)",
    ]
    assert items[0]["effect"] == "alternate" and items[0]["detail"] == "Red, fast blink, bright and dim"
    assert "No advisory below 18,000 ft" in labels and labels[-1] == "METAR not available"


def test_every_hazard_has_a_color():
    assert set(vis.COLORS) == set(advisories.AIRMETS)
    assert set(vis.SIGMET_COLORS) == set(advisories.SIGMETS)
    assert vis.css("IFR").startswith("#") and vis.css("CONV", "SIGMET") == colors_lib.to_css(color(colors_lib.RED))


def test_the_legend_tells_waiting_from_an_unknown_position(settings):
    items = {item["key"]: item for item in vis.legend(settings)}
    waiting, missing = items[style.WAITING], items[style.MISSING]
    assert waiting["effect"] == "pulse" and waiting["period"] == style.WAITING_PERIOD
    assert waiting["low"] == style.WAITING_LOW and waiting["label"] == "Waiting for the G-AIRMETs and SIGMETs"
    assert missing["effect"] == "blink" and "position" in missing["label"]


def test_a_feed_that_never_loaded_is_waiting_and_failed_when_its_try_failed():
    found, _, _ = make(
        airmets=[requests.exceptions.Timeout("slow")], sigmets=[FakeResponse([sigmet("CONV", *HOUSTON)])]
    )
    assert found.waiting() is True and found.failed() is False  # nothing tried yet
    found.fetch()  # the SIGMETs came; the G-AIRMETs didn't
    assert found.waiting() is True and found.failed() is True


def test_once_both_feeds_loaded_a_later_failure_is_not_waiting():
    found, _, _ = make(
        airmets=[FakeResponse([gairmet("IFR", *HOUSTON)]), requests.exceptions.Timeout("slow")],
        sigmets=[FakeResponse([]), requests.exceptions.Timeout("slow")],
    )
    found.fetch()
    found.fetch()  # fails: the old areas stay
    assert found.waiting() is False and found.failed() is False


def test_a_fetch_under_way_is_not_overlapped_by_the_next_try():
    found, asked, _ = make(airmets=[gairmet("IFR", *HOUSTON)], sigmets=[])
    found._fetching.acquire()  # a slow one is still waiting on aviationweather.gov
    try:
        assert found.fetch() is False
    finally:
        found._fetching.release()
    assert asked == []  # it didn't even ask
    assert found.fetch() is True  # and once it's over, the next try goes ahead


def test_sigmets_alone_are_enough_and_without_either_an_airport_waits(settings):
    place = {"latitude": 29.98, "longitude": -95.34}
    assert vis.look(Report(raw="...", sigmets=["CONV"], **place), settings) == severe(colors_lib.RED)
    assert vis.look(Report(raw="...", **place), settings) == style.waiting()  # G-AIRMETs not loaded, no SIGMET


def test_the_breath_survives_missing_data_blink_off(settings):
    settings.visualizer.missing_data_blink = False
    report = Report(raw="...", latitude=29.98, longitude=-95.34)
    assert visualizer.look(vis.VISUALIZER, report, settings) == style.waiting()
    assert visualizer.look(vis.VISUALIZER, Report(raw="..."), settings).effect == "off"  # no position: off, not red
