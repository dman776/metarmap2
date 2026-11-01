"""
Tests for G-AIRMETs (metarmap.airmet), the hazards added to each METAR, and the AIRMET visualizer.
"""
import pytest
import requests

from metarmap import airmet
from metarmap.airmet import Airmets
from metarmap.lib import colors as colors_lib
from metarmap.metar import with_airmets
from metarmap.models import Look
from metarmap.settings import Settings
from metarmap.visualizers import airmet as vis
from metarmap.visualizers import style


def square(lat, lon, size=1.0):
    """A G-AIRMET polygon around (lat, lon), as aviationweather.gov sends it (strings)."""
    return [{"lat": str(lat - size), "lon": str(lon - size)}, {"lat": str(lat - size), "lon": str(lon + size)},
            {"lat": str(lat + size), "lon": str(lon + size)}, {"lat": str(lat + size), "lon": str(lon - size)}]


def gairmet(hazard, lat=30.0, lon=-95.0, base=None, top=None, geometry="AREA", expires=2000, **more):
    product = {"IFR": "SIERRA", "MT_OBSC": "SIERRA", "ICE": "ZULU", "FZLVL": "ZULU"}.get(hazard, "TANGO")
    return {"tag": "1C", "forecastHour": 3, "validTime": "2026-11-02T00:00:00.000Z", "hazard": hazard,
            "geometryType": geometry, "base": base, "top": top, "fzlbase": None, "fzltop": None, "due_to": None,
            "severity": None, "product": product, "expireTime": expires, "coords": square(lat, lon), **more}


HOUSTON = (29.98, -95.34)  # KIAH


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


def make(*responses, now=1000.0):
    answers = list(responses)
    urls = []

    def get(url, **kwargs):
        urls.append((url, kwargs["headers"]["User-Agent"]))
        answer = answers.pop(0) if len(answers) > 1 else answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer
    clock = type("Clock", (), {"t": now, "__call__": lambda self: self.t})()
    return Airmets(get=get, clock=clock), urls, clock


# ---- reading aviationweather.gov's answer ---------------------------------------------------------------------

def test_parse_keeps_hazard_areas_below_18000_ft():
    areas = airmet.parse([
        gairmet("IFR", due_to="CIG BLW 010 VIS BLW 3SM PCPN BR"),
        gairmet("TURB-LO", base="SFC", top="140", severity="MOD"),
        gairmet("TURB-HI", base="180", top="390"),  # high-level: doesn't affect the airport
        gairmet("ICE", base="FZL", top="200", fzlbase="070"),
        gairmet("ICE", base="FZL", top="300", fzlbase="190"),  # freezing level too high
        gairmet("FZLVL", geometry="LINE", level="040"),  # a freezing level line, not a hazard
        gairmet("M_FZLVL", base="SFC", top="040"),
        gairmet("SFC_WND"),
    ])
    assert [(a["hazard"], a["base"], a["top"]) for a in areas] == [
        ("IFR", 0, None), ("TURB-LO", 0, 14000), ("ICE", 7000, 20000), ("SFC_WND", 0, None)]
    ifr = areas[0]
    assert ifr["product"] == "SIERRA" and ifr["due_to"] == "CIG BLW 010 VIS BLW 3SM PCPN BR"
    assert ifr["coords"][0] == (29.0, -96.0) and ifr["valid"] == "2026-11-02T00:00:00.000Z"
    assert ifr["name"].startswith("IFR")


@pytest.mark.parametrize("data", [None, {}, [None], [{"hazard": "IFR", "geometryType": "AREA", "coords": "x"}],
                                  [{**gairmet("IFR"), "coords": [{"lat": "30", "lon": "-95"}]}]])
def test_parse_skips_what_it_cant_use(data):
    assert airmet.parse(data) == []


@pytest.mark.parametrize("point, expected", [((30.0, -95.0), True), ((30.9, -94.1), True), ((31.1, -95.0), False),
                                             ((30.0, -96.5), False)])
def test_inside(point, expected):
    polygon = [(float(c["lat"]), float(c["lon"])) for c in square(30.0, -95.0)]
    assert airmet.inside(*point, polygon) is expected


def test_inside_a_concave_area():
    # an L: the notch at the top right isn't inside
    ell = [(0, 0), (0, 4), (2, 4), (2, 2), (4, 2), (4, 0)]
    assert airmet.inside(1, 3, ell) and airmet.inside(3, 1, ell)
    assert not airmet.inside(3, 3, ell)


# ---- fetching, and the hazards over a place -------------------------------------------------------------------

def test_hazards_at():
    airmets, urls, _ = make(FakeResponse([gairmet("TURB-LO", *HOUSTON, base="SFC", top="100"), gairmet("ICE", *HOUSTON),
                                          gairmet("IFR", *HOUSTON), gairmet("IFR", *HOUSTON),
                                          gairmet("MT_OBSC", 40.0, -105.0)]))
    assert airmets.hazards_at(*HOUSTON) is None  # nothing fetched yet
    assert airmets.fetch() is True
    assert urls == [("https://aviationweather.gov/api/data/gairmet?format=json", airmet.USER_AGENT)]
    assert airmets.hazards_at(*HOUSTON) == ["ICE", "IFR", "TURB-LO"]  # most important first, each once
    assert airmets.hazards_at(40.0, -105.0) == ["MT_OBSC"]
    assert airmets.hazards_at(35.0, -80.0) == []


def test_expired_areas_are_left_out():
    airmets, _, clock = make(FakeResponse([gairmet("IFR", *HOUSTON, expires=2000)]))
    airmets.fetch()
    assert airmets.hazards_at(*HOUSTON) == ["IFR"]
    clock.t = 2000
    assert airmets.hazards_at(*HOUSTON) == [] and airmets.state()["areas"] == []


def test_nothing_in_effect():
    airmets, _, _ = make(FakeResponse(status=204))
    assert airmets.fetch() is True
    assert airmets.hazards_at(*HOUSTON) == []


@pytest.mark.parametrize("failure", [requests.exceptions.ConnectionError("down"), FakeResponse(status=502),
                                     FakeResponse(ValueError("not json"))])
def test_a_failed_fetch_keeps_the_last_areas(failure):
    airmets, _, _ = make(FakeResponse([gairmet("IFR", *HOUSTON)]), failure)
    airmets.fetch()
    assert airmets.fetch() is False
    assert "couldn't reach aviationweather.gov" in airmets.error
    assert airmets.hazards_at(*HOUSTON) == ["IFR"]
    assert airmets.state()["error"] == airmets.error


def test_a_failed_first_fetch_leaves_none():
    airmets, _, _ = make(requests.exceptions.Timeout("slow"))
    assert airmets.fetch() is False
    assert airmets.hazards_at(*HOUSTON) is None
    assert airmets.state() == {"fetched": None, "error": airmets.error, "areas": []}


# ---- each METAR gets its hazards ------------------------------------------------------------------------------

def test_with_airmets():
    airmets, _, _ = make(FakeResponse([gairmet("IFR", *HOUSTON)]))
    airmets.fetch()
    data = {"KIAH": {"raw": "...", "latitude": 29.98, "longitude": -95.34},
            "KDFW": {"raw": "...", "latitude": "32.9", "longitude": "-97.04"},
            "KXXX": {"raw": "..."}}
    result = with_airmets(data, airmets)
    assert result["KIAH"]["airmets"] == ["IFR"] and result["KDFW"]["airmets"] == []
    assert result["KXXX"]["airmets"] is None  # no position
    assert "airmets" not in data["KIAH"]  # the fetched reports are left as they were


def test_an_airport_without_a_report_stays_empty():
    """Every visualizer shows {} as "METAR not available"; a hazard list would make it look like a report."""
    airmets, _, _ = make(FakeResponse([gairmet("IFR", *HOUSTON)]))
    airmets.fetch()
    assert with_airmets({"KDKR": {}}, airmets) == {"KDKR": {}}


# ---- the visualizer -------------------------------------------------------------------------------------------

@pytest.fixture
def settings():
    return Settings()


def color(name):
    return colors_lib.get_colors()[name]


@pytest.mark.parametrize("hazards, expected", [
    ([], Look.solid(color(colors_lib.GRAY))),
    (["IFR"], Look.solid(color(colors_lib.ORANGE))),
    (["ICE"], Look.solid(color(colors_lib.CYAN))),
    (["TURB-LO", "TURB-HI"], Look.solid(color(colors_lib.YELLOW))),  # one color for both turbulences
    (["ICE", "IFR"], Look.blink(color(colors_lib.CYAN), period=vis.MIXED_PERIOD, background=color(colors_lib.ORANGE))),
    (["ICE", "IFR", "SFC_WND"], Look.blink(color(colors_lib.CYAN), period=vis.MIXED_PERIOD,
                                           background=color(colors_lib.ORANGE))),
])
def test_look(settings, hazards, expected):
    assert vis.look({"raw": "...", "airmets": hazards}, settings) == expected


def test_look_without_data(settings):
    assert vis.look({}, settings) == style.no_report()
    assert vis.look({"raw": "...", "airmets": None}, settings) == style.missing()
    assert vis.look({"raw": "..."}, settings) == style.missing()


def test_legend(settings):
    labels = [item["label"] for item in vis.legend(settings)]
    assert labels[:6] == ["IFR: ceiling below 1,000 ft or visibility below 3 mi", "Mountain obscuration",
                          "Turbulence (moderate)", "Low-level wind shear",
                          "Strong surface wind: sustained 30 kt or more", "Icing (moderate)"]
    assert "No G-AIRMET below 18,000 ft" in labels and labels[-1] == "METAR not available"


def test_every_hazard_has_a_color():
    assert set(vis.COLORS) == set(airmet.HAZARDS)
    assert vis.css("IFR").startswith("#")
