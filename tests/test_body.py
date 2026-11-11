"""Tests for metarmap.body: what a METAR's body (before RMK) says that the JSON doesn't, read from the raw text."""

import json
import logging
import random
from collections import Counter
from datetime import datetime, timezone
from dataclasses import replace
from pathlib import Path

import pytest

from metarmap import body, decode, metar
from metarmap.body import Body, Cloud, RunwayRange, RunwayState, Trend, Visibility, Wind, parse
from metarmap.models import Report

# real reports from aviationweather.gov's JSON (metarType and cover to check against)
CORPUS = json.loads((Path(__file__).parent / "fixtures" / "metars_body.json").read_text())["reports"]

UUEE = "METAR UUEE 110500Z 18004MPS 9999 -RA SCT007 OVC024 01/M00 Q1014 R24L/290145 R24C/290145 NOSIG"
LSGG = "METAR LSGG 110450Z AUTO VRB01KT 0800 0500NE R04/P2000N R22/0750N PRFG VV002 12/12 Q1006 TEMPO 0400 FG VV001"
CYYT = "SPECI CYYT 110447Z 02007KT 1/2SM R16/2600V3500FT/U R10/2600V3500FT/U -DZ FG VV003 04/04 A2939 RMK FG8 SLP957"


def groups(text, time="110450Z"):
    """The body of a report at `time` with these groups after the wind and visibility."""
    return parse(f"METAR KTST {time} 24008KT 9999 {text} 12/10 Q1012")


def test_uuee():
    assert parse(UUEE) == Body(
        text=UUEE,
        report_type="METAR",
        runway_states=(
            RunwayState("R24L/290145", "24L", "2", "9", "01", "45"),
            RunwayState("R24C/290145", "24C", "2", "9", "01", "45"),
        ),
        clouds=(Cloud("SCT", 700), Cloud("OVC", 2400)),
        trends=(Trend("NOSIG"),),
    )


def test_lsgg():
    assert parse(LSGG) == Body(
        text=LSGG,
        report_type="METAR",
        modifiers=("AUTO",),
        lowest_visibility_m=500,
        lowest_visibility_toward="NE",
        runway_ranges=(RunwayRange("04", 2000, "P", trend="N"), RunwayRange("22", 750, trend="N")),
        trends=(Trend("TEMPO", visibility=Visibility(metres=400), weather=("FG",), clouds=(Cloud("VV", 100),)),),
    )


def test_cyyt():
    assert parse(CYYT) == Body(
        text=CYYT.split(" RMK ")[0],
        report_type="SPECI",
        runway_ranges=(
            RunwayRange("16", 2600, high=3500, feet=True, trend="U"),
            RunwayRange("10", 2600, high=3500, feet=True, trend="U"),
        ),
    )


@pytest.mark.parametrize("raw", ["", None, "   ", "RMK AO2", "="])
def test_nothing_to_read(raw):
    assert parse(raw) == Body()


def test_the_remarks_arent_read():
    found = parse("METAR KTST 110353Z 00000KT 10SM CLR 16/15 A3015 RMK AO2 TEMPO R24/0600N CAVOK")
    assert found.text == "METAR KTST 110353Z 00000KT 10SM CLR 16/15 A3015"
    assert (found.trends, found.runway_ranges, found.sky, found.unread) == ((), (), None, ())


def test_a_plain_us_report_has_nothing_new():
    raw = "METAR KIAH 110353Z 09004KT 10SM SCT043 BKN120 BKN220 16/14 A3011 RMK AO2 SLP197"
    assert parse(raw) == Body(
        text=raw.split(" RMK ")[0],
        report_type="METAR",
        clouds=(Cloud("SCT", 4300), Cloud("BKN", 12000), Cloud("BKN", 22000)),
    )


# ---- report type and modifiers --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, report_type, modifiers",
    [
        ("METAR KTST 110353Z 00000KT 10SM CLR 16/15 A3015", "METAR", ()),
        ("METAR KTST 110353Z AUTO 00000KT 10SM CLR 16/15 A3015", "METAR", ("AUTO",)),
        ("SPECI KTST 110410Z 00000KT 10SM CLR 16/15 A3015", "SPECI", ()),
        ("SPECI KTST 110410Z AUTO 00000KT 10SM CLR 16/15 A3015", "SPECI", ("AUTO",)),
        ("METAR KICT 110453Z COR 00000KT 6SM BCFG FEW010 10/10 A3004", "METAR", ("COR",)),
        ("METAR EGCC 110450Z COR AUTO 04008KT 9999 NCD 06/04 Q1006", "METAR", ("COR", "AUTO")),
        ("METAR KTST 110353Z AUTO COR 00000KT 10SM CLR 16/15 A3015", "METAR", ("AUTO", "COR")),
        ("METAR COR LFPG 091800Z 07008KT 6000 -RA SCT005 07/06 Q1013", "METAR", ("COR",)),  # WMO's place for it
        ("SPECI CYOW 101927Z CCA 29015G25KT 8SM -RA BKN040 08/06 A2966", "SPECI", ("CCA",)),
        ("METAR CYXX 110400Z CCB 01008KT 10SM FEW004 10/09 A2994", "METAR", ("CCB",)),
        ("METAR MMCZ 110359Z RTD 00000KT 7SM SCT015 24/24 A3003", "METAR", ("RTD",)),
        ("KTST 110353Z AUTO 00000KT 10SM CLR 16/15 A3015", None, ("AUTO",)),  # a mock typed without METAR
    ],
)
def test_report_type_and_modifiers(raw, report_type, modifiers):
    found = parse(raw)
    assert (found.report_type, found.modifiers, found.unread) == (report_type, modifiers, ())


def test_the_station_is_not_a_weather_or_a_modifier():
    # a station code that reads like a group is still the station
    assert parse("METAR AUTO 110353Z 00000KT 10SM CLR 16/15 A3015").modifiers == ()
    assert parse("METAR SHRA 110353Z 00000KT 10SM CLR 16/15 A3015").unread == ()


# ---- the wind's variable direction ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "wind, varies",
    [
        ("24008KT 210V270", (210, 270)),
        ("36010KT 350V050", (350, 50)),  # across north
        ("VRB05KT 090V180", (90, 180)),  # with VRB, as reported
        ("24012G25KT 200V280", (200, 280)),
        ("05004MPS 020V090", (20, 90)),
        ("00000KT 000V360", (0, 360)),
    ],
)
def test_wind_varies(wind, varies):
    found = parse(f"METAR KTST 110450Z {wind} 9999 FEW040 12/10 Q1012")
    assert (found.wind_varies, found.unread) == (varies, ())


@pytest.mark.parametrize(
    "text",
    [
        "24008KT 370V050",  # over 360
        "24008KT 350V999",
        "24008KT 9999 350V050",  # not after the wind
        "350V050 24008KT",
    ],
)
def test_a_wind_variation_that_isnt_one(text):
    found = parse(f"METAR KTST 110450Z {text} FEW040 12/10 Q1012")
    assert found.wind_varies is None and found.unread == tuple(t for t in text.split() if "V" in t and "KT" not in t)


# ---- visibility ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, metres, toward",
    [
        ("0800 0500NE", 500, "NE"),
        ("4000 0400W", 400, "W"),
        ("9999 6000N", 6000, "N"),
        ("0450 0150//", 150, None),  # automated: direction not known
        ("0750 0700", 700, None),
        ("1100 0900", 900, None),
    ],
)
def test_the_lowest_visibility(text, metres, toward):
    found = parse(f"METAR KTST 110450Z 24008KT {text} FG VV001 06/06 Q1003")
    assert (found.lowest_visibility_m, found.lowest_visibility_toward, found.unread) == (metres, toward, ())


def test_a_lowest_visibility_not_after_the_visibility_isnt_read():
    found = parse("METAR KTST 110450Z 24008KT 0400NW 0800 FG 06/06 Q1003")
    assert found.lowest_visibility_m is None and found.unread == ("0400NW",)


def test_no_directional_variation():
    found = parse("METAR LSZL 110450Z AUTO 00000KT 9999NDV BKN051 08/07 Q1011")
    assert found.no_directional_variation and found.lowest_visibility_m is None and found.unread == ()
    assert not parse("METAR KTST 110450Z 00000KT 9999 BKN051 08/07 Q1011").no_directional_variation


@pytest.mark.parametrize("vis", ["10SM", "1/2SM", "1 1/2SM", "M1/4SM", "P6SM", "15SM", "////", "////SM", "CAVOK"])
def test_visibility_forms_are_recognized(vis):
    assert parse(f"METAR KTST 110450Z 24008KT {vis} 12/10 A3001").unread == ()


# ---- runway visual range --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "group, found",
    [
        ("R28/2400FT", RunwayRange("28", 2400, feet=True)),
        ("R28L/M0600FT", RunwayRange("28L", 600, "M", feet=True)),
        ("R06/P6000FT", RunwayRange("06", 6000, "P", feet=True)),
        ("R13R/1200VP6000FT", RunwayRange("13R", 1200, high=6000, high_bound="P", feet=True)),
        ("R13C/M0600V1200FT", RunwayRange("13C", 600, "M", 1200, feet=True)),
        ("R16/2600V3500FT/U", RunwayRange("16", 2600, high=3500, feet=True, trend="U")),
        ("R10/3000FT/N", RunwayRange("10", 3000, feet=True, trend="N")),
        ("R06L/4500FT/D", RunwayRange("06L", 4500, feet=True, trend="D")),
        # metres, outside North America: a trend right after the value
        ("R24/0600N", RunwayRange("24", 600, trend="N")),
        ("R24/0550V0800U", RunwayRange("24", 550, high=800, trend="U")),
        ("R24/0900V1600D", RunwayRange("24", 900, high=1600, trend="D")),
        ("R18R/P2000N", RunwayRange("18R", 2000, "P", trend="N")),
        ("R02/P2000", RunwayRange("02", 2000, "P")),
        ("R27/M0050D", RunwayRange("27", 50, "M", trend="D")),
        ("R24/////", RunwayRange("24")),  # not available
    ],
)
def test_runway_visual_range(group, found):
    assert groups(group).runway_ranges == (found,)
    assert groups(group).unread == ()


@pytest.mark.parametrize(
    "group",
    [
        "R37/0600N",  # no runway 37
        "R00/0600N",
        "R06/35000FT",  # five digits: a typo seen in PAKU's
        "R24/0600X",
        "R24/060N",
        "R24/0600V",
        "R24/",
        "R",
    ],
)
def test_a_runway_visual_range_that_isnt_one(group):
    found = groups(group)
    assert found.runway_ranges == () and found.unread == (group,)


# ---- runway state (WMO) ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "group, found",
    [
        ("R24L/290145", RunwayState("R24L/290145", "24L", "2", "9", "01", "45")),
        ("R25/190055", RunwayState("R25/190055", "25", "1", "9", "00", "55")),
        ("R21/39//23", RunwayState("R21/39//23", "21", "3", "9", "//", "23")),
        ("R88/290055", RunwayState("R88/290055", "88", "2", "9", "00", "55")),
        ("R24///////", RunwayState("R24///////", "24", "/", "/", "//", "//")),  # R24/ and six /: nothing reported
        ("R88/CLRD70", RunwayState("R88/CLRD70", "88", braking="70", cleared=True)),
        ("R24C/CLRD//", RunwayState("R24C/CLRD//", "24C", braking="//", cleared=True)),
        ("R99/421594", RunwayState("R99/421594", "99", "4", "2", "15", "94")),
        ("R/SNOCLO", RunwayState("R/SNOCLO", None, closed=True)),
        ("SNOCLO", RunwayState("SNOCLO", None, closed=True)),
    ],
)
def test_runway_state(group, found):
    assert groups(group).runway_states == (found,)
    assert groups(group).unread == ()


@pytest.mark.parametrize("group", ["R24/29014", "R24/2901455", "R24/CLRD7", "R24/X90145", "R24L/SNOCLO"])
def test_a_runway_state_that_isnt_one(group):
    found = groups(group)
    assert found.runway_states == () and found.unread == (group,)


# ---- sky, clouds, recent weather, wind shear -------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, sky",
    [("CAVOK", "CAVOK"), ("NSC", "NSC"), ("NCD", "NCD"), ("CLR", None), ("SKC", None), ("FEW040", None)],
)
def test_sky(text, sky):
    found = parse(f"METAR KTST 110450Z 24008KT {'' if text == 'CAVOK' else '9999 '}{text} 12/10 Q1012")
    assert (found.sky, found.unread) == (sky, ())


def test_cloud_types():
    found = groups("FEW002 SCT022CB BKN014TCU OVC017/// FEW///CB ///CB ////// /////////")
    assert found.clouds == (
        Cloud("FEW", 200),
        Cloud("SCT", 2200, "CB"),
        Cloud("BKN", 1400, "TCU"),
        Cloud("OVC", 1700),  # ///: type not known (automated)
        Cloud("FEW", None, "CB"),  # height not known
        Cloud("", None, "CB"),  # cover and height not known; ////// and ///////// say nothing
    )
    assert found.unread == ()
    assert groups("//////TCU BKN///TCU").clouds == (Cloud("", None, "TCU"), Cloud("BKN", None, "TCU"))


@pytest.mark.parametrize(
    "text, recent",
    [
        ("RERA", ("RA",)),
        ("RESHRA", ("SHRA",)),
        ("RETS", ("TS",)),
        ("RERA REDZ", ("RA", "DZ")),
        ("REFZRA", ("FZRA",)),
        ("RE//", ()),  # not observed (automated)
    ],
)
def test_recent_weather(text, recent):
    found = groups(text)
    assert (found.recent_weather, found.unread) == (recent, ())


@pytest.mark.parametrize("text", ["RE-RA", "RE+SHRA", "REVCSH", "REXX", "RE"])
def test_a_recent_weather_that_isnt_one(text):
    # recent weather has no intensity and isn't in the vicinity
    found = groups(text)
    assert found.recent_weather == () and found.unread == (text,)


@pytest.mark.parametrize(
    "text, runways",
    [
        ("WS R20", ("20",)),
        ("WS RWY25", ("25",)),
        ("WS R24L", ("24L",)),
        ("WS ALL RWY", ("ALL",)),
        ("WS R20 WS R02", ("20", "02")),
    ],
)
def test_wind_shear(text, runways):
    found = groups(text)
    assert (found.wind_shear, found.unread) == (runways, ())


@pytest.mark.parametrize("text, unread", [("WS", ("WS",)), ("WS R40", ("WS", "R40")), ("WS ALL", ("WS", "ALL"))])
def test_a_wind_shear_that_isnt_one(text, unread):
    found = groups(text)
    assert found.wind_shear == () and found.unread == unread


# ---- the trend -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, trends",
    [
        ("NOSIG", (Trend("NOSIG"),)),
        (
            "TEMPO 4000 RA BKN014",
            (Trend("TEMPO", visibility=Visibility(metres=4000), weather=("RA",), clouds=(Cloud("BKN", 1400),)),),
        ),
        (
            "BECMG FM1050 6000 BKN006",
            (Trend("BECMG", times=(("FM", "1050"),), visibility=Visibility(metres=6000), clouds=(Cloud("BKN", 600),)),),
        ),
        (
            "TEMPO FM0430 TL0500 4000 TSRA",
            (
                Trend(
                    "TEMPO",
                    times=(("FM", "0430"), ("TL", "0500")),
                    visibility=Visibility(metres=4000),
                    weather=("TSRA",),
                ),
            ),
        ),
        (
            "BECMG AT1000 9999 NSW",
            (
                Trend(
                    "BECMG",
                    times=(("AT", "1000"),),
                    visibility=Visibility(9999, more=True),
                    no_significant_weather=True,
                ),
            ),
        ),
        (
            "TEMPO 14018G30KT 3000 SHRA FEW015CB BKN020",
            (
                Trend(
                    "TEMPO",
                    wind=Wind(140, 18, 30),
                    visibility=Visibility(metres=3000),
                    weather=("SHRA",),
                    clouds=(Cloud("FEW", 1500, "CB"), Cloud("BKN", 2000)),
                ),
            ),
        ),
        ("BECMG VRB03MPS CAVOK", (Trend("BECMG", wind=Wind(None, 3, unit="MPS"), cavok=True),)),
        (
            "TEMPO 8000 RA NSC",
            (Trend("TEMPO", visibility=Visibility(metres=8000), weather=("RA",), no_significant_cloud=True),),
        ),
        (
            "TEMPO 0400 FG VV///",
            (Trend("TEMPO", visibility=Visibility(metres=400), weather=("FG",), clouds=(Cloud("VV"),)),),
        ),
        ("TEMPO 2SM BR", (Trend("TEMPO", visibility=Visibility(miles=2.0), weather=("BR",)),)),
        ("TEMPO 1 1/2SM -SN", (Trend("TEMPO", visibility=Visibility(miles=1.5), weather=("-SN",)),)),
        ("BECMG P6SM", (Trend("BECMG", visibility=Visibility(miles=6.0, more=True)),)),
        # what it can't read is kept, as reported (LFPG's typo of 4000)
        ("TEMPO 40000 -RA BKN005", (Trend("TEMPO", weather=("-RA",), clouds=(Cloud("BKN", 500),), other=("40000",)),)),
        (
            "BECMG 0600 FG TEMPO 0200",
            (
                Trend("BECMG", visibility=Visibility(metres=600), weather=("FG",)),
                Trend("TEMPO", visibility=Visibility(metres=200)),
            ),
        ),
        ("TEMPO FM2460 TL0500 1/0SM", (Trend("TEMPO", times=(("TL", "0500"),), other=("FM2460", "1/0SM")),)),
        ("TEMPO TL2400 BR", (Trend("TEMPO", times=(("TL", "2400"),), weather=("BR",)),)),  # the end of the day
        ("TEMPO FM1000 FM1100", (Trend("TEMPO", times=(("FM", "1000"),), other=("FM1100",)),)),  # only one of each
        ("TEMPO 37010KT", (Trend("TEMPO", other=("37010KT",)),)),
        # military color states are left out of a trend, as out of the body; other codes are kept
        ("TEMPO SHRA BLU", (Trend("TEMPO", weather=("SHRA",)),)),
        ("BECMG 3000 YLO1 W12/S2", (Trend("BECMG", visibility=Visibility(metres=3000), other=("W12/S2",)),)),
        ("TEMPO BLACKBLU WHT GRN YLO2 AMB RED BLU+ BLACK", (Trend("TEMPO"),)),
        ("TEMPO BLUE", (Trend("TEMPO", other=("BLUE",)),)),  # not a color state
    ],
)
def test_trend(text, trends):
    found = parse(f"METAR KTST 110450Z 24008KT 9999 FEW040 12/10 Q1012 {text}")
    assert found.trends == trends
    assert found.unread == ()


def test_the_trend_isnt_read_as_the_observation():
    found = parse("METAR EGLL 101920Z AUTO 06007KT 7000 -RA BKN018 OVC027 09/08 Q1005 TEMPO 4000 RA BKN014")
    assert found.clouds == (Cloud("BKN", 1800), Cloud("OVC", 2700))  # not the trend's BKN014
    assert found.lowest_visibility_m is None


# ---- whatever it's given ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "METAR",
        "SPECI",
        "METAR KTST",
        "METAR KTST 110450Z",
        "METAR KTST 110450Z 1",  # a whole mile with no fraction after it
        "METAR KTST 110450Z 24008KT 1/0SM",
        "METAR KTST 110450Z 24008KT 0/0SM 1 1/0SM",
        "METAR KTST 110450Z 24008KT 350V",
        "METAR KTST 110450Z 24008KT V050",
        "METAR KTST 110450Z 24008KT 9999 R24/1200V",
        "METAR KTST 110450Z 24008KT 9999 WS",
        "METAR KTST 110450Z 24008KT 9999 WS ALL",
        "METAR KTST 110450Z 24008KT 9999 TEMPO",
        "METAR KTST 110450Z 24008KT 9999 TEMPO 1",
        "METAR KTST 110450Z 24008KT 9999 TEMPO FM",
        "METAR KTST 110450Z 24008KT 9999 BECMG 99999KT",
        "METAR KTST 110450Z 99999G999KT 9999 R99/999999 R88/////// 12/10 Q9999",
        "COR COR COR",
        "TEMPO TEMPO NOSIG",
        "R24/0600N",
        "X" * 5000,
        "AUTO " * 3000,
    ],
)
def test_truncated_and_strange_reports(raw, caplog):
    with caplog.at_level(logging.WARNING, logger="metarmap.body"):
        parse(raw)
        decode.decode(Report(raw=raw))
    assert caplog.records == []  # read, not caught by the guard


UNICODE_DIGITS = ["²", "³", "¹", "١", "٣", "۴", "５", "߀", "①"]  # superscripts, Arabic-Indic, full width, N'Ko...


@pytest.mark.parametrize("digit", UNICODE_DIGITS)
def test_digits_are_ascii_only(digit, caplog):
    """str.isdigit() is true for ² (and \\d matches ١): neither is a number here, so none raises or is read."""
    tokens = [
        f"{digit} 1/2SM",
        f"R24/{digit}600N",
        f"R2{digit}/0600N",
        f"R24L/29{digit}145",
        f"R24/CLRD{digit}0",
        f"FEW0{digit}0CB",
        f"VV00{digit}",
        f"0{digit}00NE",
        f"24{digit}08KT",
        f"350V0{digit}0",
        f"RE{digit}",
        f"WS R2{digit}",
        f"TEMPO {digit} 1/2SM FEW0{digit}0 VV0{digit}0 FM0{digit}00 {digit}000",
    ]
    with caplog.at_level(logging.WARNING, logger="metarmap.body"):
        for text in tokens:
            raw = f"METAR KTST 110450Z 24008KT 9999 {text} 12/10 Q1012"
            found = parse(raw)
            assert found.runway_ranges == found.runway_states == found.clouds == found.wind_shear == ()
            assert found.wind_varies is found.lowest_visibility_m is None
            for group in found.trends:
                assert group.visibility == Visibility(miles=0.5)  # 1/2SM: the digit before it isn't a whole mile
                assert group.clouds == () and group.times == () and digit in group.other
            decode.decode(Report(raw=raw))
            metar.parse_raw(raw, datetime(2026, 11, 11, tzinfo=timezone.utc))
    assert caplog.records == []  # read, not caught by the guard


def test_a_parse_failure_reads_nothing(monkeypatch, caplog):
    def broken(tokens, text):
        raise ZeroDivisionError("a bug")

    monkeypatch.setattr(body, "_parse", broken)
    monkeypatch.setattr(body, "_LOGGED", set())
    with caplog.at_level(logging.WARNING, logger="metarmap.body"):
        assert parse(LSGG) == Body(text=LSGG)
        assert parse(LSGG) == Body(text=LSGG)
    assert len(caplog.records) == 1  # once per body
    assert "ZeroDivisionError" in caplog.text and LSGG in caplog.text
    # the Decoded tab shows what it did before
    report = metar.parse_report({"rawOb": LSGG, "wdir": "VRB", "wspd": 1, "visib": 0.5, "temp": 12, "dewp": 12})
    assert [line["label"] for line in decode.decode(report)] == ["Wind", "Visibility", "Temperature", "Dewpoint"]


def test_a_body_is_immutable():
    with pytest.raises(AttributeError):
        parse(UUEE).sky = "CAVOK"


# ---- on the Report -----------------------------------------------------------------------------------------------


def test_a_report_reads_its_body_once():
    report = Report(raw=UUEE)
    assert report.body is report.body and report.body.runway_states
    assert report == Report(raw=UUEE)  # not a field: equality and replace() see only the fields
    assert replace(report, raw=LSGG).body.modifiers == ("AUTO",)
    assert Report().body == Body()


def test_fetched_and_mock_reports_read_the_same_body():
    from datetime import datetime, timezone

    fetched = metar.parse_report({"rawOb": LSGG + " "})
    mock = metar.parse_raw(LSGG, datetime(2026, 11, 11, 5, 0, tzinfo=timezone.utc))
    assert fetched.body == mock.body == parse(LSGG)


def test_body_and_remarks_split_at_rmk():
    report = Report(raw=CYYT)
    assert report.body.text + " RMK " + report.remarks.text == CYYT


# ---- the corpus: real reports ----------------------------------------------------------------------------------


@pytest.mark.parametrize("case", CORPUS, ids=lambda c: c["icaoId"])
def test_real_reports_agree_with_the_json(case):
    """The report type is the JSON's metarType; CAVOK is its cover CAVOK; NCD and NSC are its cover CLR."""
    found = parse(case["rawOb"])
    assert found.report_type == case["metarType"]
    assert (found.sky == "CAVOK") == (case.get("cover") == "CAVOK")
    if found.sky in ("NCD", "NSC"):
        assert case.get("cover") == "CLR" and not case.get("clouds")


def test_the_corpus_has_every_group():
    found = [parse(case["rawOb"]) for case in CORPUS]
    assert any("AUTO" in b.modifiers for b in found) and any("COR" in b.modifiers for b in found)
    assert any(m.startswith("CC") for b in found for m in b.modifiers)
    assert any(b.report_type == "SPECI" for b in found) and any(b.wind_varies for b in found)
    assert any(r.feet and r.high for b in found for r in b.runway_ranges)
    assert any(r.trend and not r.feet for b in found for r in b.runway_ranges)
    assert any(r.low is None for b in found for r in b.runway_ranges)
    assert any(s.cleared for b in found for s in b.runway_states) and any(b.runway_states for b in found)
    assert {b.sky for b in found} >= {"CAVOK", "NSC", "NCD"}
    assert any(b.lowest_visibility_m for b in found) and any(b.no_directional_variation for b in found)
    assert any(b.recent_weather for b in found) and any(b.wind_shear for b in found)
    assert {t.kind for b in found for t in b.trends} == {"NOSIG", "BECMG", "TEMPO"}


def test_most_of_the_body_is_read():
    tokens = unread = 0
    unknown = Counter()
    for case in CORPUS:
        found = parse(case["rawOb"])
        tokens += len(found.text.split())
        unread += len(found.unread)
        unknown.update(found.unread)
        assert all(t in found.text.split() for t in found.unread)  # nothing made up
    share = (tokens - unread) / tokens
    print(f"\n{len(CORPUS)} reports, {tokens} body groups, {share:.1%} read; not read: {unknown.most_common(12)}")
    assert len(CORPUS) >= 200 and share > 0.99


# ---- fuzz: mutated real groups never raise -------------------------------------------------------------------------

NASTY = [
    "",
    "RMK",
    "R24/",
    "R/",
    "R//",
    "1/0SM",
    "0/0SM",
    "1",
    "V",
    "350V",
    "V350",
    "999V999",
    "WS",
    "ALL",
    "RWY",
    "RE",
    "RE-",
    "FM",
    "FM9999",
    "TL2460",
    "TEMPO",
    "BECMG",
    "NOSIG",
    "CLRD",
    "R88/CLRD",
    "R99/",
    "R24/////////",
    "//////",
    "M",
    "P",
    "=",
    "CAVOK",
    "NDV",
    "9999NDV",
    "0400NNE",
    "99999MPS",
    "VRBKT",
    "G",
    "CC",
    "CCZ",
]


def test_fuzz():
    """
    30,000 bodies of real groups, shuffled, with characters changed: none raises out of parse() (the guard isn't
    needed) or out of decode(). Seeded, so the same every run.
    """
    pool = [t for case in CORPUS for t in parse(case["rawOb"]).text.split()[2:]] + NASTY
    rng = random.Random(9)
    caught = []
    log = logging.getLogger("metarmap.body")
    handler = logging.Handler()
    handler.emit = caught.append
    log.addHandler(handler)
    try:
        for _ in range(30000):
            text = " ".join(rng.choice(pool) for _ in range(rng.randint(0, 14)))
            text = "".join(c if rng.random() > 0.05 else rng.choice("0123456789/ VMPRLCNSEWUDFTKG") for c in text)
            raw = rng.choice(("METAR KTST 110450Z ", "SPECI ", "", "METAR COR ")) + text
            decode.decode(Report(raw=raw, wind_speed=5, visibility_sm=1.0))
    finally:
        log.removeHandler(handler)
    assert caught == []
