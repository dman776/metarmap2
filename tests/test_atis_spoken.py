"""Tests for metarmap.atis_spoken: the FAA's D-ATIS text as words a voice reads right."""

import json
from pathlib import Path

import pytest

from metarmap import atis_spoken

CORPUS = json.loads((Path(__file__).parent / "fixtures" / "atis_all.json").read_text())  # atis.info, 2026-11-07
IDS = [e["airport"] for e in CORPUS]


def entry(code, kind="combined"):
    return next(e for e in CORPUS if e["airport"] == code and e["type"] == kind)


def test_a_whole_atis():
    text = atis_spoken.spoken_atis([entry("KIAH")], "George Bush Intcntl/Houston Arpt", "KIAH", IDS)
    assert text.startswith(
        "George Bush Intercontinental Houston Airport information Tango, one seven five tree Zulu. "
        "Wind one one zero at six. Visibility one zero. Sky condition few clouds at eight thousand, "
        "ceiling twenty five thousand broken. Temperature two five, dew point one tree. Altimeter tree zero one one. "
        "Arrivals expect ILS or R-NAV Yankee runway eight right, ILS or R-NAV Yankee runway eight left, "
        "ILS or R-NAV Yankee runway niner. Simultaneous approaches in use. "
        "Departing runway one five left, runway one five right, runway niner."
    )
    assert "Land and hold short operations runway eight right." in text  # LAHSO RY8R
    assert "Taxiway Echo Alpha closed." in text
    assert "on frequency one two six point two two five." in text
    assert text.endswith("Advise you have information Tango.")
    assert "(" not in text and "THREE" not in text  # the altimeter's own words, said once from A3011


def test_arrival_then_departure():
    """One button per airport: an airport with two ATIS reads the arrival one, then the departure one."""
    text = atis_spoken.spoken_atis([entry("KATL", "dep"), entry("KATL", "arr")], "Atlanta", "KATL")
    assert text.startswith("Atlanta arrival information Juliett, one seven five two Zulu.")
    assert text.index("Atlanta departure information Whiskey") > text.index("Advise you have information Juliett")


def test_no_atis():
    assert atis_spoken.spoken_atis([], "Hobby", "KHOU") == "Hobby. No ATIS is available."


@pytest.mark.parametrize(
    "atis, said",
    [
        (
            "ALB ATIS INFO I 1755Z SPECIAL. 27005KT 3SM -DZ BR FEW009 OVC013 08/07 A2981.",
            "information India, one seven five five Zulu, special. Wind two seven zero at five. Visibility tree. "
            "Weather light drizzle and mist. Sky condition few clouds at niner hundred, "
            "ceiling one thousand tree hundred overcast.",
        ),
        (
            "BOS ATIS INFO D 1754Z. 03006KT 1 1/2SM R04R/6000VP6000FT BR OVC005 14/13 A2967 RMK RAB1655E15B31.",
            "Visibility one and one half. Weather mist. Sky condition ceiling five hundred overcast.",
        ),
        (
            "DEN ARR INFO N 1753Z. VRB04KT 10SM FEW220 16/M03 A3022.",
            "Wind variable at four. Visibility one zero. Sky condition few clouds at twenty two thousand. "
            "Temperature one six, dew point minus tree.",
        ),
        (
            "ADW ATIS INFO D 1755Z. 33013G20KT 10SM CLR 15/01 A2991 RMK PRES ALT PS289.",
            "Wind tree tree zero at one tree, gusting two zero. Visibility one zero. Sky clear.",
        ),
    ],
)
def test_the_weather_as_the_awos_says_it(atis, said):
    assert said in atis_spoken.expand(atis, "Here")


@pytest.mark.parametrize(
    "words, said",
    [
        ("DEPG RWYS 26L, 27R", "Departing runways two six left, two seven right."),
        ("ILS RWY 01 APCH IN USE", "ILS runway one approach in use."),
        (
            "SIMULTANEOUS APCHS IN USE VIS 26R, VIS 27L",
            "Simultaneous approaches in use visual two six right, visual two seven left.",
        ),
        ("DEPARTING RWY8, RWY17L", "Departing runway eight, runway one seven left."),
        ("TWY R10 CLSD", "Taxiway Romeo one zero closed."),
        ("TXY Z BTN D AND E", "Taxiway Zulu between Delta and Echo."),
        ("TWY B, H 2, K 1 CLSD", "Taxiway Bravo, Hotel two, Kilo one closed."),
        ("RNAV Z AVAILABLE UPON REQUEST", "R-NAV Zulu available upon request."),
        ("RAMP CONTROL OPEN 126.225", "Ramp control open one two six point two two five."),
        (
            "CRANE 0.5NM SOUTH AOB 100 FT AGL",
            "Crane zero point five nautical miles south at or below one hundred feet above ground level.",
        ),
        ("CRANE AT 80 FT", "Crane at eight zero feet."),
        (
            "CRANE 1.5NM SSE APCH END RWY 05",
            "Crane one point five nautical miles south southeast approach end runway five.",
        ),
        (
            "RWY 4R CONDITION CODE, 5 5 5 OBSERVED AT 0918Z",
            "Runway four right condition code, five five five observed at zero niner one eight Zulu.",
        ),
        ("ALB TACAN/AZIMUTH OTS", "ALB tacan azimuth out of service."),
        (
            "ATTN ALL ACFT HAZD WX INFO AVBL FM FLT SVC",
            "Attention all aircraft hazardous weather information available from flight service.",
        ),
        ("ALL ACFT USE CTN, BUT LESS THAN 35 KT", "All aircraft use caution, but less than tree five knots."),
        ("CAUTION FOR VNY EAST TRAFFIC", "Caution for VNY east traffic."),
        ("ADVS YOU HAVE INFO Q", "Advise you have information Quebec."),
    ],
)
def test_the_rest_word_by_word(words, said):
    assert atis_spoken.sentence(words.split(), atis_spoken.identifiers(["KALB"])) == said


def test_identifiers():
    assert atis_spoken.identifiers(["KIAH", "PHNL", "TJSJ", ""]) == {"KIAH", "IAH", "PHNL", "HNL", "TJSJ"}


def test_stray_punctuation():
    assert atis_spoken.tidy("RWY 3 . TWY A CLSD BTN TWY, M AND THE RAMP , . X. . . Y ...ADVS") == (
        "RWY 3. TWY A CLSD BTN TWY, M AND THE RAMP. X. Y. ADVS"
    )


@pytest.mark.parametrize("e", CORPUS, ids=[f"{e['airport']}-{e['type']}" for e in CORPUS])
def test_every_real_atis(e):
    """Every ATIS atis.info had: words only (no digits, no contraction this knows left as written), and its letter."""
    text = atis_spoken.spoken_atis([e], "Here", e["airport"], IDS)
    assert text.startswith("Here ") and text.endswith(".")
    assert not any(c.isdigit() for c in text.replace("X-ray", ""))
    assert not set(text.split()) & {k for k in atis_spoken.CONTRACTIONS if len(k) > 2}
    assert f"information {atis_spoken.PHONETIC[e['code']]}" in text


def test_what_it_doesnt_know_is_identifiers_and_fixes():
    """The capitals left as they are (spelled by the voice): airports and fixes, not contractions to add."""
    left = set().union(*(atis_spoken.unknown(e["datis"]) for e in CORPUS))
    assert left == {
        "BNR", "CHS", "CKH", "CLT", "CMH", "DCM", "HNL", "HPN", "JFK", "KRSW", "MNSTR", "MSP", "MTV", "PDX", "PHX",
        "PSP", "PVD", "RSW", "SC", "SDL", "SLC", "TRM", "TRSSH", "VNY", "YVR",
    }  # fmt: skip
