"""Tests for metarmap.remarks: a METAR's remarks (after RMK), read from the raw text."""

import json
import logging
import random
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from metarmap import decode, metar, remarks
from metarmap.models import Report
from metarmap.remarks import (
    Amount,
    Lightning,
    PeakWind,
    Place,
    PressureTendency,
    Remarks,
    WeatherEvent,
    WindShift,
    parse,
)

# real reports from aviationweather.gov's JSON, with the JSON's own remark fields (slp, precip...) to check against
CORPUS = json.loads((Path(__file__).parent / "fixtures" / "metars_remarks.json").read_text())["reports"]
# real reports with lightning remarks of more forms (manual stations: OHD, AND DSNT, CONS...), in the same shape
LIGHTNING = json.loads((Path(__file__).parent / "fixtures" / "metars_lightning.json").read_text())["reports"]

KHOU = (
    "METAR KHOU 110353Z 00000KT 8SM -TSRA SCT022CB BKN070 OVC090 16/15 A3015 RMK AO2 SLP214 OCNL LTGICCG E AND SW "
    "TS E AND SW MOV NE P0001 T01610150 $"
)
KIAH = "METAR KIAH 110353Z 09004KT 10SM SCT043 BKN120 BKN220 16/14 A3011 RMK AO2 RAB09E27 PRESFR SLP197 P0000 T01560144"


def rmk(text, time="110353Z"):
    """The remarks of a report at `time` with these remarks."""
    return parse(f"METAR KTST {time} 00000KT 10SM CLR 16/15 A3015 RMK {text}")


def test_khou():
    assert parse(KHOU) == Remarks(
        text="AO2 SLP214 OCNL LTGICCG E AND SW TS E AND SW MOV NE P0001 T01610150 $",
        station_type="AO2",
        sea_level_pressure_hpa=1021.4,
        temp_c=16.1,
        dewpoint_c=15.0,
        precipitation=(Amount(1, 0.01),),
        maintenance=True,
        lightning=(Lightning("OCNL", ("IC", "CG"), (Place(None, (("E",), ("SW",))),)),),
        other=("TS E AND SW MOV NE",),  # the thunderstorm's place: not read yet, kept
    )


def test_kiah():
    assert parse(KIAH) == Remarks(
        text="AO2 RAB09E27 PRESFR SLP197 P0000 T01560144",
        station_type="AO2",
        sea_level_pressure_hpa=1019.7,
        temp_c=15.6,
        dewpoint_c=14.4,
        precipitation=(Amount(1, 0.0),),  # P0000: a trace
        pressure_change="falling rapidly",
        events=(WeatherEvent("RA", True, 3, 9), WeatherEvent("RA", False, 3, 27)),
    )


@pytest.mark.parametrize("raw", ["", None, "METAR KTST 110353Z 00000KT 10SM CLR 16/15 A3015", "KTST RMKX AO2"])
def test_no_remarks(raw):
    assert parse(raw) == Remarks()


def test_empty_remarks():
    assert rmk("") == Remarks()


@pytest.mark.parametrize(
    "text, station",
    [("AO1", "AO1"), ("AO2", "AO2"), ("AO2A", "AO2A"), ("AO1A", "AO1A"), ("A02", "AO2")],  # A02: a typo seen in KSEA's
)
def test_station_type(text, station):
    assert rmk(text).station_type == station


@pytest.mark.parametrize(
    "text, hpa",
    [
        ("SLP214", 1021.4),
        ("SLP000", 1000.0),
        ("SLP499", 1049.9),
        ("SLP500", 950.0),  # 500 and up: below 1000 hPa
        ("SLP927", 992.7),
        ("SLP727", 972.7),
    ],
)
def test_sea_level_pressure(text, hpa):
    assert rmk(text).sea_level_pressure_hpa == hpa


def test_sea_level_pressure_not_available():
    found = rmk("SLPNO")
    assert found.sea_level_pressure_missing and found.sea_level_pressure_hpa is None and found.other == ()


@pytest.mark.parametrize(
    "text, temp, dewpoint",
    [("T01610150", 16.1, 15.0), ("T11001122", -10.0, -12.2), ("T00061011", 0.6, -1.1), ("T0161", 16.1, None)],
)
def test_exact_temperature(text, temp, dewpoint):
    found = rmk(text)
    assert (found.temp_c, found.dewpoint_c) == (temp, dewpoint)


@pytest.mark.parametrize(
    "text, time, amounts",
    [
        ("P0001", "110353Z", (Amount(1, 0.01),)),
        ("P0048", "110353Z", (Amount(1, 0.48),)),
        ("P0000", "110353Z", (Amount(1, 0.0),)),  # a trace
        ("P////", "110353Z", (Amount(1, None),)),  # couldn't be measured
        ("60036", "102053Z", (Amount(3, 0.36),)),  # the 21Z report: 3 hours
        ("60010", "101156Z", (Amount(6, 0.10),)),  # the 12Z report: 6 hours
        ("60002", "102351Z", (Amount(6, 0.02),)),  # 2351Z is the 00Z report
        ("60001", "110410Z", (Amount(None, 0.01),)),  # a special at 0410Z: 3 or 6 hours can't be told
        ("6////", "101153Z", (Amount(6, None),)),
        ("70031", "101156Z", (Amount(24, 0.31),)),
        ("P0000 60002 70002", "101153Z", (Amount(1, 0.0), Amount(6, 0.02), Amount(24, 0.02))),
    ],
)
def test_precipitation(text, time, amounts):
    assert rmk(text, time).precipitation == amounts


def test_six_hour_precipitation_without_a_report_time():
    assert parse("KTST RMK 60012").precipitation == (Amount(None, 0.12),)


def test_ice_accretion():
    assert rmk("I1000 I3002 I6010").ice_accretion == (Amount(1, 0.0), Amount(3, 0.02), Amount(6, 0.10))


def test_six_and_twenty_four_hour_temperatures():
    found = rmk("10117 20094")
    assert (found.max_temp_6h_c, found.min_temp_6h_c) == (11.7, 9.4)
    found = rmk("11022 21043")
    assert (found.max_temp_6h_c, found.min_temp_6h_c) == (-2.2, -4.3)
    found = rmk("400281039")
    assert (found.max_temp_24h_c, found.min_temp_24h_c) == (2.8, -3.9)
    found = rmk("410251050")
    assert (found.max_temp_24h_c, found.min_temp_24h_c) == (-2.5, -5.0)


@pytest.mark.parametrize(
    "text, tendency",
    [
        ("53016", PressureTendency(3, 1.6)),
        ("51028", PressureTendency(1, 2.8)),
        ("50001", PressureTendency(0, 0.1)),
        ("54000", PressureTendency(4, 0.0)),
        ("55000", PressureTendency(5, 0.0)),
        ("58069", PressureTendency(8, -6.9)),
        ("56002", PressureTendency(6, -0.2)),
    ],
)
def test_pressure_tendency(text, tendency):
    assert rmk(text).pressure_tendency == tendency


def test_pressure_rising_or_falling_rapidly():
    assert rmk("PRESRR").pressure_change == "rising rapidly"
    assert rmk("PRESFR").pressure_change == "falling rapidly"


@pytest.mark.parametrize(
    "text, time, wind",
    [
        ("PK WND 27030/0303", "110351Z", PeakWind(270, 30, 3, 3)),
        ("PK WND 05038/0321", "110353Z", PeakWind(50, 38, 3, 21)),
        ("PK WND 280105/2155", "110353Z", PeakWind(280, 105, 21, 55)),  # three-digit speed
        ("PK WND 33041/45", "110353Z", PeakWind(330, 41, 3, 45)),  # minutes only: this hour
        ("PK WND 33041/58", "110353Z", PeakWind(330, 41, 2, 58)),  # later than the report: the hour before
        ("PK WND 33041/58", "110053Z", PeakWind(330, 41, 23, 58)),
    ],
)
def test_peak_wind(text, time, wind):
    assert rmk(text, time).peak_wind == wind


def test_peak_wind_minutes_without_a_report_time():
    assert parse("KTST RMK PK WND 33041/45").peak_wind == PeakWind(330, 41, None, 45)


def test_wind_shift():
    assert rmk("WSHFT 2138", "102251Z").wind_shift == WindShift(21, 38)
    assert rmk("WSHFT 30 FROPA").wind_shift == WindShift(3, 30, frontal_passage=True)


def test_tower_and_surface_visibility():
    found = rmk("TWR VIS 1 1/2 SFC VIS 3")
    assert (found.tower_visibility_sm, found.surface_visibility_sm, found.other) == (1.5, 3.0, ())
    assert rmk("SFC VIS 1/4").surface_visibility_sm == 0.25


def test_variable_visibility_and_ceiling():
    assert rmk("VIS 1/4V2").variable_visibility_sm == (0.25, 2.0)
    assert rmk("VIS 2 1/2V4").variable_visibility_sm == (2.5, 4.0)
    assert rmk("VIS 1V1 1/2").variable_visibility_sm == (1.0, 1.5)
    assert rmk("CIG 003V008").variable_ceiling_ft == (300, 800)
    # visibility in one direction isn't read yet
    assert rmk("VIS N-E 1 1/4").other == ("VIS N-E 1 1/4",)


@pytest.mark.parametrize(
    "text, time, events",
    [
        ("RAB09E27", "110353Z", [("RA", True, 3, 9), ("RA", False, 3, 27)]),
        ("RAE00B44", "110353Z", [("RA", False, 3, 0), ("RA", True, 3, 44)]),
        ("RAB0311E0339", "110355Z", [("RA", True, 3, 11), ("RA", False, 3, 39)]),
        ("RAE0359", "110410Z", [("RA", False, 3, 59)]),
        ("RAB55", "110353Z", [("RA", True, 2, 55)]),  # after :53 in the 0353Z report: 02:55
        ("FZRAB07", "110353Z", [("FZRA", True, 3, 7)]),
        ("SHSNB20", "102351Z", [("SHSN", True, 23, 20)]),
        (
            "UPB29E36B52SNE29",
            "101453Z",
            [("UP", True, 14, 29), ("UP", False, 14, 36), ("UP", True, 14, 52), ("SN", False, 14, 29)],
        ),
        ("TSE05B24E39", "110351Z", [("TS", False, 3, 5), ("TS", True, 3, 24), ("TS", False, 3, 39)]),
        ("SGB20E40SHSNB40", "101750Z", [("SG", True, 17, 20), ("SG", False, 17, 40), ("SHSN", True, 17, 40)]),
    ],
)
def test_began_and_ended(text, time, events):
    found = rmk(text, time)
    assert found.events == tuple(WeatherEvent(*e) for e in events) and found.other == ()


def test_began_and_ended_without_a_report_time():
    assert parse("KTST RMK RAB09").events == (WeatherEvent("RA", True, None, 9),)


@pytest.mark.parametrize("text", ["MIB10", "BCE05", "FZB10", "SHB10", "PRB10E20", "DRE05", "BLB1015", "SHB10E20RAB30"])
def test_a_descriptor_alone_is_not_a_weather_that_begins(text):
    # FMH-1 12.7.1 k: w'w' is a precipitation (SHRA, FZRA); only TS stands alone (l)
    found = rmk(text)
    assert found.events == () and found.other == (text,)


def test_a_thunderstorm_alone_and_with_rain():
    assert rmk("TSB0159E30", "110251Z").events == (WeatherEvent("TS", True, 1, 59), WeatherEvent("TS", False, 2, 30))
    assert rmk("TSRAB10").events == (WeatherEvent("TSRA", True, 3, 10),)


@pytest.mark.parametrize(
    "text", ["RAB99", "RAB60", "RAB2400", "RAB0960", "RAB09E2460", "PK WND 27030/2410", "PK WND 27030/61", "WSHFT 2460"]
)
def test_a_time_out_of_range_is_not_read(text):
    found = rmk(text)
    assert (found.events, found.peak_wind, found.wind_shift, found.other) == ((), None, None, (text,))


def test_the_last_minute_of_the_day_is_read():
    assert rmk("RAB2359 PK WND 27030/2359 WSHFT 0000", "110010Z") == Remarks(
        text="RAB2359 PK WND 27030/2359 WSHFT 0000",
        events=(WeatherEvent("RA", True, 23, 59),),
        peak_wind=PeakWind(270, 30, 23, 59),
        wind_shift=WindShift(0, 0),
    )


@pytest.mark.parametrize("time", ["112460Z", "110360Z", "119999Z"])
def test_a_bad_report_time_is_not_used(time):
    # a minute alone then has no hour, rather than 24:59Z
    assert rmk("RAB59 PK WND 27030/59", time).events == (WeatherEvent("RA", True, None, 59),)
    assert rmk("RAB59 PK WND 27030/59", time).peak_wind == PeakWind(270, 30, None, 59)


@pytest.mark.parametrize("text", ["VIS 1/0V2", "TWR VIS 1/0", "SFC VIS 0/0", "VIS 1V2/0", "SFC VIS 1 1/0"])
def test_a_zero_denominator_is_not_read(text):
    found = rmk(text)
    assert found.other == (text,)
    assert (found.tower_visibility_sm, found.surface_visibility_sm, found.variable_visibility_sm) == (None,) * 3


def test_a_parse_failure_keeps_the_remarks_as_other(monkeypatch, caplog):
    def broken(text, pos):
        raise ZeroDivisionError("a bug")

    monkeypatch.setattr(remarks, "_group_at", broken)
    monkeypatch.setattr(remarks, "_LOGGED", set())
    raw = "METAR KTST 110353Z 00000KT 10SM CLR 16/15 A3015 RMK AO2 SLP214 $"
    with caplog.at_level(logging.WARNING, logger="metarmap.remarks"):
        assert parse(raw) == Remarks(text="AO2 SLP214 $", other=("AO2 SLP214 $",))
        assert parse(raw) == Remarks(text="AO2 SLP214 $", other=("AO2 SLP214 $",))
    assert len(caplog.records) == 1  # once per remarks text
    assert "ZeroDivisionError" in caplog.text and raw in caplog.text
    # the Decoded tab still shows: the remarks as one Other remarks line
    assert decode.remarks(Report(raw=raw).remarks) == [("Other remarks", "AO2 SLP214 $")]


def test_sensors_out_of_service():
    found = rmk("PWINO PNO FZRANO TSNO RVRNO VISNO RWY06 CHINO RWY24L CHINO")
    assert found.sensors_out == ("PWINO", "PNO", "FZRANO", "TSNO", "RVRNO", "VISNO RWY06", "CHINO RWY24L", "CHINO")
    assert found.other == ()


def test_no_specials_and_maintenance():
    found = rmk("NOSPECI $")
    assert found.no_speci and found.maintenance and found.other == ()


def test_snow():
    found = rmk("4/001 931005 933012")
    assert (found.snow_depth_in, found.snowfall_6h_in, found.snow_water_in) == (1, 0.5, 1.2)


def test_what_it_doesnt_read_is_kept_in_order():
    found = rmk("AO2 RAE12B34 TS DSNT S SLP198 HARBOR WIND 11015KT P0000 VIRGA $")
    assert found.other == ("TS DSNT S", "HARBOR WIND 11015KT", "VIRGA")
    assert found.events and found.sea_level_pressure_hpa == 1019.8 and found.maintenance


def test_a_group_inside_free_text_is_still_read():
    # FIRST and LAST aren't read; the 5-digit group after them is
    assert rmk("FIRST 53016 LAST").other == ("FIRST", "LAST")


def test_remarks_are_immutable():
    with pytest.raises(AttributeError):
        parse(KHOU).station_type = "AO1"


# ---- lightning (FMH-1 12.7.1 j) ------------------------------------------------------------------------------

DSNT_N = Place("DSNT", (("N",),))


@pytest.mark.parametrize(
    "text, lightning",
    [
        ("LTG", Lightning()),  # nothing else: at the station
        ("OCNL LTGICCG E AND SW", Lightning("OCNL", ("IC", "CG"), (Place(None, (("E",), ("SW",))),))),
        ("LTG DSNT N", Lightning(places=(DSNT_N,))),
        ("FRQ LTGCG OHD", Lightning("FRQ", ("CG",), (Place("OHD"),))),
        ("LTG DSNT ALQDS", Lightning(places=(Place("DSNT", all_quadrants=True),))),
        ("FRQ LTG VC", Lightning("FRQ", places=(Place("VC"),))),
        ("LTG VC E AND SW", Lightning(places=(Place("VC", (("E",), ("SW",))),))),
        ("CONS LTGICCGCA OHD", Lightning("CONS", ("IC", "CG", "CA"), (Place("OHD"),))),
        ("OCNL LTGICCCCG S", Lightning("OCNL", ("IC", "CC", "CG"), (Place(None, (("S",),)),))),
        ("LTGICIC", Lightning(types=("IC",))),  # a type twice: once
        ("OCNL LTG DSNT W", Lightning("OCNL", places=(Place("DSNT", (("W",),)),))),
        # ranges, clockwise: with - or THRU, of two points or more
        ("LTG DSNT NE-SE", Lightning(places=(Place("DSNT", (("NE", "SE"),)),))),
        ("OCNL LTGICCG SE-S-SW", Lightning("OCNL", ("IC", "CG"), (Place(None, (("SE", "S", "SW"),)),))),
        ("LTG DSNT NW THRU SE", Lightning(places=(Place("DSNT", (("NW", "SE"),)),))),
        ("LTG DSNT N AND NE-E AND SW", Lightning(places=(Place("DSNT", (("N",), ("NE", "E"), ("SW",))),))),
        # as manual stations write them: a list without AND, and more than one place
        ("OCNL LTGCG DSNT S SW W", Lightning("OCNL", ("CG",), (Place("DSNT", (("S",), ("SW",), ("W",))),))),
        (
            "FRQ LTGICCG OHD-S-SW AND DSNT W",
            Lightning("FRQ", ("IC", "CG"), (Place("OHD", (("S", "SW"),)), Place("DSNT", (("W",),)))),
        ),
        (
            "OCNL LTGICCG S-SW DSNT W",
            Lightning("OCNL", ("IC", "CG"), (Place(None, (("S", "SW"),)), Place("DSNT", (("W",),)))),
        ),
        ("OCNL LTGCG W AND DSNT SW", Lightning("OCNL", ("CG",), (Place(None, (("W",),)), Place("DSNT", (("SW",),))))),
        (
            "OCNL LTGICCG NE AND DSNT S SW",
            Lightning("OCNL", ("IC", "CG"), (Place(None, (("NE",),)), Place("DSNT", (("S",), ("SW",))))),
        ),
        ("OCNL LTGICCG OHD-N-E", Lightning("OCNL", ("IC", "CG"), (Place("OHD", (("N", "E"),)),))),
    ],
)
def test_lightning(text, lightning):
    found = rmk(f"AO2 {text} SLP214")
    assert found.lightning == (lightning,)
    assert found.other == () and found.station_type == "AO2" and found.sea_level_pressure_hpa == 1021.4


def test_lightning_alone_and_more_than_one_group():
    assert rmk("LTG").lightning == (Lightning(),) and rmk("LTG").other == ()
    found = rmk("AO2 LTG DSNT ALQDS PRESRR OCNL LTGICCCCG E-S-SW TS E-S-SW MOV NE")
    assert found.lightning == (
        Lightning(places=(Place("DSNT", all_quadrants=True),)),
        Lightning("OCNL", ("IC", "CC", "CG"), (Place(None, (("E", "S", "SW"),)),)),
    )
    assert found.other == ("TS E-S-SW MOV NE",)


@pytest.mark.parametrize(
    "text, lightning, other",
    [
        ("LTGX", (), ("LTGX",)),  # not a type
        ("LTGI DSNT N", (), ("LTGI DSNT N",)),
        ("XLTG DSNT N", (), ("XLTG DSNT N",)),
        ("OCNL", (), ("OCNL",)),  # a frequency alone
        ("OCNL LTGX", (), ("OCNL LTGX",)),
        ("LTG/DSNT", (), ("LTG/DSNT",)),
        ("LTG VCTS", (), ("LTG VCTS",)),  # VC only as a word of its own: a place that can't be read
        ("LTG DSNT N AND", (Lightning(places=(DSNT_N,)),), ("AND",)),  # AND with nothing after it
        ("LTG DSNT NE-", (Lightning(places=(Place("DSNT"),)),), ("NE-",)),  # a range with no end
        ("LTG DSNT NNE", (Lightning(places=(Place("DSNT"),)),), ("NNE",)),  # 8 points only
        ("LTG DSNT THRU", (Lightning(places=(Place("DSNT"),)),), ("THRU",)),
        ("LTG FAR N", (Lightning(),), ("FAR N",)),
        ("LTG ALQDS AND N", (Lightning(places=(Place(all_quadrants=True),)),), ("AND N",)),
        ("LTG DSNT ALQDS N", (Lightning(places=(Place("DSNT", all_quadrants=True),)),), ("N",)),
    ],
)
def test_what_isnt_a_lightning_group_is_kept(text, lightning, other):
    found = rmk(text)
    assert (found.lightning, found.other) == (lightning, other)


@pytest.mark.parametrize(
    "raw, at_station",
    [
        ("KTST 110353Z RMK LTG DSNT W", False),  # distant only
        ("KTST 110353Z RMK OCNL LTG DSNT W AND DSNT N", False),
        ("KTST 110353Z RMK LTG", True),  # no distance: at the station
        ("KTST 110353Z RMK OCNL LTGICCG E AND SW", True),
        ("KTST 110353Z RMK FRQ LTGCG OHD", True),
        ("KTST 110353Z RMK LTG VC", True),
        ("KTST 110353Z RMK OCNL LTGCG W AND DSNT SW", True),  # one place near is enough
        ("KTST 110353Z RMK LTG DSNT ALQDS OCNL LTGIC E", True),  # and one group
        ("KTST 110353Z RMK LTG DSNT5 W", False),  # a distance that can't be read isn't lightning at the station
        ("KTST 110353Z RMK LTG VCY", False),
        ("KTST 110353Z LTG DSNT5 W", False),  # without RMK
        ("KTST 110353Z RMK AO2 SLP214", False),
        ("", False),
        (None, False),
    ],
)
def test_lightning_at_station(raw, at_station):
    assert remarks.lightning_at_station(remarks.lightning_groups(raw)) is at_station


def test_lightning_outside_the_remarks_is_read():
    """A mock typed without RMK, or remarks that couldn't be read: the groups are found anywhere in the report."""
    assert remarks.lightning_groups("KTST 110353Z 10SM TS LTG DSNT N") == (Lightning(places=(DSNT_N,)),)
    assert remarks.lightning_groups("KTST 110353Z 10SM RMK AO2 LTGX") == ()
    # a station's code, or a word that starts with LTG, isn't lightning
    assert remarks.lightning_groups("LTGP 110350Z 9999 FEW030 20/10 Q1015") == ()
    found = parse(KHOU)
    assert remarks.lightning_groups(KHOU, found) is found.lightning  # what's read already isn't read again


def test_lightning_in_remarks_that_cant_be_read(monkeypatch, caplog):
    monkeypatch.setattr(remarks, "_parse", lambda body, text: 1 / 0)
    raw = "METAR KTST 110353Z 00000KT 10SM CLR 16/15 A3015 RMK AO2 FRQ LTGCG OHD"
    with caplog.at_level(logging.WARNING, logger="metarmap.remarks"):
        assert parse(raw).lightning == ()
        assert remarks.lightning_groups(raw) == (Lightning("FRQ", ("CG",), (Place("OHD"),)),)
    assert metar.parse_raw(raw, datetime(2026, 11, 11, 4, 0, tzinfo=timezone.utc)).lightning is True


def test_lightning_outside_the_remarks_that_cant_be_read(monkeypatch, caplog):
    """A bug reading a lightning group found outside the remarks: none, logged once, and nothing raises."""
    monkeypatch.setattr(remarks, "_lightning", lambda g: 1 / 0)
    raw = "KTST 110353Z 10SM TS LTG OHD"
    with caplog.at_level(logging.WARNING, logger="metarmap.remarks"):
        assert remarks.lightning_groups(raw) == ()
        assert remarks.lightning_groups(raw) == ()
    assert len(caplog.records) == 1 and "ZeroDivisionError" in caplog.text
    assert metar.parse_raw(raw, datetime(2026, 11, 11, 4, 0, tzinfo=timezone.utc)).lightning is False


# real reports (metars_lightning.json and metars_remarks.json): the flag, and the Decoded tab's Lightning lines
REAL = {
    "METAR KCRP 081551Z": (
        True,
        ["Frequent in-cloud and cloud-to-ground, overhead and south through southwest, distant west"],
    ),
    "SPECI KCRP 081521Z": (True, ["Occasional in-cloud and cloud-to-ground, south through southwest, distant west"]),
    "METAR KCRP 101551Z": (True, ["Occasional cloud-to-ground, west, distant southwest"]),
    "METAR KCRP 101251Z": (False, ["Occasional in-cloud and cloud-to-ground, distant north, northeast and east"]),
    "METAR KCRP 100851Z": (True, ["Continuous in-cloud and cloud-to-ground, south through southwest"]),
    "METAR KCRP 100951Z": (True, ["Occasional in-cloud and cloud-to-ground, overhead and north through east"]),
    "METAR KAUS 080253Z": (False, ["Occasional, distant west"]),
    "METAR KHOU 110553Z": (
        True,
        ["Distant in all quadrants", "Occasional in-cloud, cloud-to-cloud and cloud-to-ground, east through southwest"],
    ),
    "SPECI KCRP 081600Z": (
        True,
        ["Occasional in-cloud and cloud-to-ground, overhead and northeast, distant southwest"],
    ),
    "METAR KHOU 102253Z": (True, ["Occasional in-cloud, southwest and west"]),
    "SPECI KAUS 080626Z": (True, ["Occasional in-cloud, cloud-to-cloud and cloud-to-ground, south"]),
    "SPECI KVCT 101413Z": (False, ["Distant in all quadrants"]),
    "METAR KC75 111755Z": (False, ["Distant northwest through southeast"]),
    "SPECI KCRP 081617Z": (True, ["Occasional in-cloud and cloud-to-ground, northeast, distant south and southwest"]),
    "METAR KHOU 110653Z": (
        True,
        [
            "Distant east and west",
            "Occasional in-cloud, cloud-to-cloud and cloud-to-ground, southeast through southwest",
        ],
    ),
    "METAR KCRP 081251Z": (False, ["Occasional cloud-to-ground, distant southwest and west"]),
    "METAR KHOU 110353Z": (True, ["Occasional in-cloud and cloud-to-ground, east and southwest"]),
    "METAR K11R 110355Z": (False, ["Distant southeast and south"]),
    "SPECI KLBX 110402Z": (False, ["Distant northwest through east"]),
    "SPECI KSGR 110359Z": (False, ["Distant in all quadrants"]),
}


def test_real_lightning_reports():
    by_start = {" ".join(case["rawOb"].split()[:3]): case for case in LIGHTNING + CORPUS}
    assert len(LIGHTNING) >= 15
    for start, (flag, texts) in REAL.items():
        report = metar.parse_report(by_start[start])
        assert report.lightning is flag, start
        lines = decode.lightning_lines(report)
        assert [text for _, text in lines] == texts, start
        assert [label for label, _ in lines] == ["Lightning"] + [""] * (len(texts) - 1)
        mock = metar.parse_raw(report.raw, datetime(2026, 11, 11, 18, tzinfo=timezone.utc))
        assert mock.lightning is report.lightning and mock.lightning_groups == report.lightning_groups
    # every real report: no lightning group left unread, and the flag is what its groups say
    for case in LIGHTNING + CORPUS:
        report = metar.parse_report(case)
        assert report.lightning is any(group.at_station for group in report.lightning_groups), case["rawOb"]


# ---- fuzz: mutated lightning groups never raise ---------------------------------------------------------------

POOL = "OCNL FRQ CONS LTG LTGIC LTGCG LTGICCG LTGICCCCG OHD VC DSNT ALQDS AND THRU N NE E SE S SW W NW - TS MOV".split()


def test_fuzz():
    """
    20,000 remarks of lightning words and real groups, shuffled, with characters changed: none raises out of parse()
    (the guard isn't needed), lightning_groups(), decode() or the spoken weather, and no LTG word is lost. Seeded.
    """
    from metarmap import spoken

    pool = POOL + [t for case in LIGHTNING for t in parse(case["rawOb"]).text.split()]
    rng = random.Random(11)
    caught = []
    log = logging.getLogger("metarmap.remarks")
    handler = logging.Handler()
    handler.emit = caught.append
    log.addHandler(handler)
    try:
        for _ in range(20000):
            text = " ".join(rng.choice(pool) for _ in range(rng.randint(0, 12)))
            text = "".join(c if rng.random() > 0.04 else rng.choice("NESW- LTGICDHOVAQ") for c in text)
            raw = "METAR KTST 110353Z 00000KT 10SM CLR 16/15 A3015 " + rng.choice(("RMK ", "")) + text
            report = Report(raw=raw, wind_speed=5, visibility_sm=1.0)
            found = report.remarks
            assert all(run in found.text for run in found.other)
            assert report.lightning_groups == remarks.lightning_groups(raw)
            decode.decode(report)
            decode.summary(report)
            spoken.spoken(report, "Test", "KTST")
    finally:
        log.removeHandler(handler)
    assert caught == []


# ---- on the Report -------------------------------------------------------------------------------------------


def test_a_report_reads_its_remarks_once():
    report = Report(raw=KHOU)
    assert report.remarks is report.remarks and report.remarks.sea_level_pressure_hpa == 1021.4
    assert report == Report(raw=KHOU)  # not a field: equality and replace() see only the fields
    changed = replace(report, raw=KIAH)
    assert changed.remarks.sea_level_pressure_hpa == 1019.7


def test_fetched_and_mock_reports_read_the_same_remarks():
    fetched = metar.parse_report({"rawOb": KIAH + " ", "obsTime": 1792900380})
    mock = metar.parse_raw(KIAH, datetime(2026, 11, 11, 4, 0, tzinfo=timezone.utc))
    assert fetched.remarks == mock.remarks == parse(KIAH)


def test_a_report_without_remarks():
    assert Report().remarks == Remarks()
    assert Report(raw="KTST 110353Z 00000KT 10SM CLR 16/15 A3015").remarks == Remarks()


# ---- the corpus: real reports ---------------------------------------------------------------------------------


@pytest.mark.parametrize("case", CORPUS + LIGHTNING, ids=lambda c: c["icaoId"])
def test_real_reports_agree_with_the_json(case):
    """
    Where aviationweather.gov's JSON has a remark field, it agrees. It says 0.005 for a trace. Its maxT/minT read
    PAKT's HARBOR WIND 11025KT as a 1 group, so those are left out for reports with a local wind.
    """
    found = parse(case["rawOb"])
    amounts = {a.hours: (0.005 if a.inches == 0 else a.inches) for a in found.precipitation}
    local_wind = "HARBOR WIND" in found.text or "ROOF WIND" in found.text

    def same(got, key):
        if key in case:
            assert got == pytest.approx(case[key]), key

    same(found.sea_level_pressure_hpa, "slp")
    same(amounts.get(1), "precip")
    same(amounts.get(3), "pcp3hr")
    same(amounts.get(6), "pcp6hr")
    same(amounts.get(24), "pcp24hr")
    if not local_wind:
        same(found.max_temp_6h_c, "maxT")
        same(found.min_temp_6h_c, "minT")
    same(found.max_temp_24h_c, "maxT24")
    same(found.min_temp_24h_c, "minT24")
    same(found.snow_depth_in, "snow")
    if found.pressure_tendency and found.pressure_tendency.change_hpa:  # the JSON leaves out a change of 0
        same(found.pressure_tendency.change_hpa, "presTend")
    if found.temp_c is not None:
        same(found.temp_c, "temp")
        same(found.dewpoint_c, "dewp")


def test_the_json_fields_are_all_found():
    """Every slp and precip the JSON has comes out of the raw text too (none is missed)."""
    for case in CORPUS:
        found = parse(case["rawOb"])
        hours = {a.hours for a in found.precipitation}
        assert ("slp" in case) <= (found.sea_level_pressure_hpa is not None), case["rawOb"]
        assert ("precip" in case) <= (1 in hours), case["rawOb"]


def test_most_of_the_remarks_are_read():
    tokens = unread = 0
    unknown = Counter()
    for case in CORPUS:
        found = parse(case["rawOb"])
        tokens += len(found.text.split())
        for run in found.other:
            unread += len(run.split())
            unknown.update(run.split())
        # nothing is lost: what's read and what isn't add up to the whole remarks
        assert all(run in found.text for run in found.other)
        # every lightning group is read: none is left in what isn't
        assert not any("LTG" in run for run in found.other), found.text
        assert ("LTG" in found.text) == bool(found.lightning)
    share = (tokens - unread) / tokens
    print(f"\n{len(CORPUS)} reports, {tokens} remark groups, {share:.1%} read; not read: {unknown.most_common(12)}")
    assert len(CORPUS) >= 150 and share > 0.80
