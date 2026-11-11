"""Tests for metarmap.decode: a METAR in plain English for the Map page's Decoded tab."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from metarmap import decode
from metarmap.metar import parse_raw, parse_report, parse_visibility
from metarmap.body import RunwayRange
from metarmap.models import Report, SkyLayer

OBS = datetime(2026, 10, 24, 17, 53, tzinfo=timezone.utc)


def lines(metar):
    return [(line["label"], line["text"]) for line in decode.decode(metar)]


def test_a_whole_report():
    metar = Report(
        obs_time=OBS,
        wind_dir="100",
        wind_speed=13,
        wind_gust_speed=19,
        visibility_sm=10.0,
        visibility_more=True,
        weather="-RA BR",
        temp_c=28,
        dewpoint_c=17,
        altimeter_inhg=30.2,
        lightning=False,
        sky_conditions=[
            SkyLayer("SCT", 4300),
            SkyLayer("BKN", 8000),
            SkyLayer("OVC", 12000),
        ],
    )
    assert lines(metar) == [
        ("Observed", "24 Oct 17:53Z"),
        ("Wind", "100° at 13 kt, gusts 19 kt"),
        ("Visibility", "10+ miles"),
        ("Weather", "Light rain, mist"),
        ("Clouds", "Scattered 4,300 ft"),
        ("", "Broken 8,000 ft (ceiling)"),  # only the lowest broken or overcast layer is the ceiling
        ("", "Overcast 12,000 ft"),
        ("Temperature", "28°C / 82°F"),
        ("Dewpoint", "17°C / 63°F (spread 11°C)"),
        ("Altimeter", "30.20 inHg"),
    ]


def test_not_reporting():
    assert decode.decode(None) == []


def test_only_what_the_report_has():
    assert lines(Report(raw="METAR KXXX", temp_c=-2, lightning=True)) == [
        ("Temperature", "-2°C / 28°F"),
        ("Lightning", "Lightning observed"),
    ]


@pytest.mark.parametrize(
    "metar, text",
    [
        (Report(wind_speed=0, wind_dir="0"), "Calm"),
        (Report(wind_speed=4, wind_dir="VRB"), "Variable at 4 kt"),
        (Report(wind_speed=4, wind_dir=""), "Variable at 4 kt"),
        (Report(wind_speed=9, wind_dir="50"), "050° at 9 kt"),
        (Report(wind_speed=25, wind_dir="270", wind_gust_speed=35), "270° at 25 kt, gusts 35 kt"),
    ],
)
def test_wind(metar, text):
    assert decode.wind(metar) == text


@pytest.mark.parametrize(
    "miles, more, text",
    [
        (10.0, True, "10+ miles"),
        (6.0, False, "6 miles"),
        (1.5, False, "1 1/2 miles"),
        (1.0, False, "1 mile"),
        (0.75, False, "3/4 mile"),
        (0.25, False, "1/4 mile"),
        (0.0, False, "0 miles"),
        (None, False, None),
    ],
)
def test_visibility(miles, more, text):
    assert decode.visibility(miles, more) == text


@pytest.mark.parametrize(
    "wx, text",
    [
        ("RA", "Rain"),
        ("-RA", "Light rain"),
        ("+SN", "Heavy snow"),
        ("-RASN", "Light rain and snow"),
        ("-SHRA", "Light rain showers"),
        ("SHRA", "Rain showers"),
        ("VCSH", "Showers in the vicinity"),
        ("TS", "Thunderstorm"),
        ("TSRA", "Thunderstorm with rain"),
        ("+TSRAGR", "Thunderstorm with heavy rain and hail"),
        ("VCTS", "Thunderstorm in the vicinity"),
        ("-FZRA", "Light freezing rain"),
        ("FZFG", "Freezing fog"),
        ("BLSN", "Blowing snow"),
        ("DRSN", "Low drifting snow"),
        ("MIFG", "Shallow fog"),
        ("BCFG", "Patches of fog"),
        ("PRFG", "Partial fog"),
        ("BR HZ", "Mist, haze"),
        ("FU", "Smoke"),
        ("VA", "Volcanic ash"),
        ("UP", "Unknown precipitation"),
        ("SQ", "Squalls"),
        ("FC", "Funnel cloud"),
        ("+FC", "Tornado or waterspout"),
        ("VCFG", "Fog in the vicinity"),
        ("-DZ BR", "Light drizzle, mist"),
        ("NSW", "NSW"),  # not a code we know: shown as it is
        ("RAXX", "RAXX"),
        ("", None),
        (None, None),
    ],
)
def test_weather(wx, text):
    assert decode.weather(wx) == text


def test_clouds():
    assert decode.clouds([SkyLayer("CLR", 0)]) == ["Clear"]
    assert decode.clouds([SkyLayer("FEW", 1200), SkyLayer("OVC", 2500)]) == [
        "Few 1,200 ft",
        "Overcast 2,500 ft (ceiling)",
    ]
    assert decode.clouds([SkyLayer("OVX", 0)], vert_vis_ft=300) == [
        "Sky obscured, vertical visibility 300 ft (ceiling)"
    ]
    assert decode.clouds([]) == [] and decode.clouds(None) == []


# ---- what the decoder reads from metar.py -----------------------------------------------------------------


@pytest.mark.parametrize(
    "value, miles",
    [("10+", 10.0), ("6.0", 6.0), ("0.25", 0.25), ("1/2", 0.5), ("1 1/2", 1.5), ("", None), (None, None)],
)
def test_parse_visibility(value, miles):
    assert parse_visibility(value) == miles


def test_parsed_reports_have_what_decode_needs():
    parsed = parse_report(
        {
            "rawOb": "METAR KTST 241753Z 00000KT 1/2SM FG VV003",
            "wdir": 0,
            "wspd": 0,
            "visib": 0.5,
            "wxString": "FG",
            "vertVis": 3,
            "cover": "OVX",
            "clouds": [{"cover": "OVX", "base": 300}],
            "obsTime": 1792871580,
        }
    )
    assert (parsed.vis, parsed.visibility_sm, parsed.visibility_more) == (0, 0.5, False)
    assert parsed.vert_vis_ft == 300
    assert lines(parsed)[2:5] == [
        ("Visibility", "1/2 mile"),
        ("Weather", "Fog"),
        ("Clouds", "Sky obscured, vertical visibility 300 ft (ceiling)"),
    ]


# ---- the popup's Summary tab ----------------------------------------------------------------------------------


def test_summary_of_a_whole_report():
    metar = Report(
        flight_category="MVFR",
        weather="-RA BR",
        lightning=True,
        wind_dir="170",
        wind_speed=12,
        wind_gust_speed=20,
        temp_c=1,
        dewpoint_c=0,
        altimeter_inhg=29.85,
        elevation_m=14,
        sky_conditions=[SkyLayer("FEW", 800), SkyLayer("BKN", 2500)],
    )
    assert decode.summary(metar) == [
        "Marginal VFR: ceiling 1,000-3,000 ft or visibility 3-5 miles",
        "Light rain, mist",
        "Lightning reported",
        "Wind from the south (170°) at 12 knots, gusting to 20",
        "Ceiling 2,500 ft (broken)",
        "Density altitude -1,500 ft (field elevation 46 ft)",
        "Temperature and dewpoint are 1°C apart: fog or low clouds can form",
        "Temperature 1°C with clouds or precipitation: icing is possible",
    ]


def test_summary_not_reporting():
    assert decode.summary(None) == []


def test_summary_only_what_the_report_has():
    # a hot, dry, clear day: no fog or icing, and a high density altitude
    assert decode.summary(
        Report(
            flight_category="VFR",
            wind_speed=0,
            temp_c=30,
            dewpoint_c=10,
            altimeter_inhg=30.01,
            elevation_m=300,
            sky_conditions=[SkyLayer("CLR", 0)],
        )
    ) == [
        "VFR: ceiling above 3,000 ft and visibility over 5 miles",
        "Calm wind",  # reported as 0: calm, not missing
        "Clear skies",
        "Density altitude 2,900 ft (field elevation 984 ft)",
    ]
    assert decode.summary(Report(temp_c=-5, dewpoint_c=-12)) == []  # cold but dry: no icing; no wind reported


@pytest.mark.parametrize(
    "metar, text",
    [
        (Report(wind_speed=4, wind_dir="VRB"), "Variable wind at 4 knots"),
        (Report(wind_speed=9, wind_dir="360"), "Wind from the north (360°) at 9 knots"),
        (Report(wind_speed=9, wind_dir="337"), "Wind from the northwest (337°) at 9 knots"),
        (Report(wind_speed=9, wind_dir="338"), "Wind from the north (338°) at 9 knots"),
        (Report(wind_speed=9, wind_dir="290"), "Wind from the west (290°) at 9 knots"),
        (Report(wind_speed=9, wind_dir="45"), "Wind from the northeast (045°) at 9 knots"),
    ],
)
def test_wind_sentence(metar, text):
    assert decode.wind_sentence(metar) == text


@pytest.mark.parametrize(
    "layers, vv, text",
    [
        (
            [SkyLayer("SCT", 4300), SkyLayer("OVC", 9000)],
            None,
            "Ceiling 9,000 ft (overcast)",
        ),
        ([SkyLayer("FEW", 1200)], None, "No ceiling; few clouds at 1,200 ft"),
        ([SkyLayer("OVX", 0)], 300, "Sky obscured: vertical visibility 300 ft"),
        ([SkyLayer("SKC", 0)], None, "Clear skies"),
        ([], None, None),
    ],
)
def test_sky_sentence(layers, vv, text):
    assert decode.sky_sentence(layers, vv) == text


def test_parsed_reports_have_what_the_summary_needs():
    """Every field the summary reads comes out of metar.parse_report."""
    report = parse_report(
        {
            "rawOb": "KHOU 241753Z 17012G20KT 10SM BKN025 01/00 A2985",
            "fltCat": "MVFR",
            "wdir": 170,
            "wspd": 12,
            "wgst": 20,
            "temp": 1,
            "dewp": 0,
            "elev": 14,
            "clouds": [{"cover": "BKN", "base": 2500}],
            "obsTime": 1792000000,
        }
    )
    assert "Density altitude -1,500 ft (field elevation 46 ft)" in decode.summary(report)
    assert "Ceiling 2,500 ft (broken)" in decode.summary(report)


@pytest.mark.parametrize(
    "layers, vv, feet",
    [
        ([SkyLayer("SCT", 800), SkyLayer("BKN", 2500)], None, 2500),
        ([SkyLayer("OVX", 0)], 300, 300),
        ([SkyLayer("FEW", 800)], None, None),
        ([SkyLayer("CLR", 0)], None, None),
        ([], None, None),
    ],
)
def test_ceiling_ft(layers, vv, feet):
    assert decode.ceiling_ft(layers, vv) == feet


# ---- the remarks (metarmap.remarks) ------------------------------------------------------------------------------

KHOU = (
    "METAR KHOU 110353Z 00000KT 8SM -TSRA SCT022CB BKN070 OVC090 16/15 A3015 RMK AO2 SLP214 OCNL LTGICCG E AND SW "
    "TS E AND SW MOV NE P0001 T01610150 $"
)
KIAH = "METAR KIAH 110353Z 09004KT 10SM SCT043 BKN120 BKN220 16/14 A3011 RMK AO2 RAB09E27 PRESFR SLP197 P0000 T01560144"
NOV_11 = datetime(2026, 11, 11, 4, 0, tzinfo=timezone.utc)


def remark_lines(text, time="110353Z"):
    return decode.remarks(Report(raw=f"METAR KTST {time} 00000KT 10SM CLR 16/15 A3015 RMK {text}").remarks)


def test_khou_with_its_remarks():
    assert lines(parse_raw(KHOU, NOV_11))[10:] == [
        # the body's lines come first, as before; the lightning group is read, so it isn't in Other remarks
        ("Lightning", "Occasional in-cloud and cloud-to-ground, east and southwest"),
        ("Station type", "Automated, with a precipitation discriminator"),
        ("Sea-level pressure", "1021.4 hPa"),
        ("Precise temperature", "16.1°C / 61.0°F"),
        ("Precise dewpoint", "15.0°C / 59.0°F"),
        ("Precipitation (since the last hourly report)", "0.01 in"),
        ("Maintenance", "The station needs maintenance"),
        ("Other remarks", "TS E AND SW MOV NE"),
    ]


# synthetic remarks (not real reports; real ones are in test_remarks.py's test_real_lightning_reports)
@pytest.mark.parametrize(
    "text, decoded, summary",
    [
        ("LTG DSNT N", ["Distant north"], ["Lightning distant north"]),  # shown, though the pixel doesn't flicker
        ("OCNL LTGCGIC DSNT N", ["Occasional cloud-to-ground and in-cloud, distant north"], None),
        ("FRQ LTGCG OHD", ["Frequent cloud-to-ground, overhead"], ["Frequent lightning overhead"]),
        ("LTG VC E AND SW", ["In the vicinity, east and southwest"], ["Lightning in the vicinity, east and southwest"]),
        ("CONS LTG", ["Continuous"], ["Continuous lightning"]),
        ("LTGCC", ["Cloud-to-cloud"], ["Lightning reported"]),  # the popup leaves out the kind
        ("LTG", ["Lightning observed"], ["Lightning reported"]),
        ("LTG DSNT ALQDS", ["Distant in all quadrants"], ["Lightning distant in all quadrants"]),
        ("LTG VC ALQDS", ["In the vicinity in all quadrants"], None),
        ("LTG DSNT NW THRU SE", ["Distant northwest through southeast"], None),
        ("OCNL LTGIC OHD-NE AND DSNT SW", ["Occasional in-cloud, overhead and northeast, distant southwest"], None),
        (
            "LTG DSNT E AND W OCNL LTGICCCCG SE-SW",
            [
                "Distant east and west",
                "Occasional in-cloud, cloud-to-cloud and cloud-to-ground, southeast through southwest",
            ],
            ["Lightning distant east and west", "Occasional lightning, southeast through southwest"],
        ),
    ],
)
def test_lightning_lines(text, decoded, summary):
    report = parse_raw(f"METAR KTST 110353Z 00000KT 10SM CLR 16/15 A3015 RMK AO2 {text}", NOV_11)
    found = [(label, t) for label, t in lines(report) if label == "Lightning" or t in decoded]
    assert found == [("Lightning" if n == 0 else "", t) for n, t in enumerate(decoded)]
    assert all(label != "Other remarks" for label, _ in lines(report))  # read, so not shown again
    if summary is not None:
        assert [t for t in decode.summary(report) if "ightning" in t or t in summary] == summary


def test_one_lightning_line():
    """The Lightning line is the only one about lightning: the group isn't in Other remarks too."""
    found = lines(parse_raw(KHOU, NOV_11))
    assert [label for label, _ in found].count("Lightning") == 1
    assert not any("LTG" in text for _, text in found)


def test_no_lightning_no_line():
    assert not any(label == "Lightning" for label, _ in lines(parse_raw(KIAH, NOV_11)))
    assert not any("ightning" in t for t in decode.summary(parse_raw(KIAH, NOV_11)))


def test_kiah_with_its_remarks():
    assert lines(parse_raw(KIAH, NOV_11))[9:] == [
        ("Station type", "Automated, with a precipitation discriminator"),
        ("Sea-level pressure", "1019.7 hPa"),
        ("Precise temperature", "15.6°C / 60.1°F"),
        ("Precise dewpoint", "14.4°C / 57.9°F"),
        ("Pressure tendency", "Falling rapidly"),
        ("Precipitation (since the last hourly report)", "Trace"),
        ("Precipitation began/ended", "Rain began 03:09Z, ended 03:27Z"),
    ]


def test_a_fetched_report_decodes_its_remarks_as_a_mock_does():
    fetched = parse_report({"rawOb": KIAH, "obsTime": 1792900380, "wdir": 90, "wspd": 4})
    assert lines(fetched)[-7:] == lines(parse_raw(KIAH, NOV_11))[-7:]


def test_a_report_without_remarks_decodes_as_before():
    raw = "METAR KTST 110353Z 09004KT 10SM CLR 16/14 A3011"
    assert lines(parse_raw(raw, NOV_11)) == [
        ("Observed", "11 Nov 03:53Z"),
        ("Wind", "090° at 4 kt"),
        ("Visibility", "10 miles"),
        ("Clouds", "Clear"),
        ("Temperature", "16°C / 61°F"),
        ("Dewpoint", "14°C / 57°F (spread 2°C)"),
        ("Altimeter", "30.11 inHg"),
    ]


def test_every_remark_line():
    text = (
        "AO1A SLPNO T11001122 10117 21043 400281039 53016 PRESRR PK WND 05038/21 WSHFT 2138 FROPA TWR VIS 1 1/2 "
        "SFC VIS 1/4 VIS 1/4V2 CIG 003V008 P0048 60036 70000 I1000 4/001 931005 933012 UPB27E41SNE19 TSE05B24E39 "
        "PWINO VISNO RWY06 TSNO NOSPECI ROOF WIND 12028G40KT $"
    )
    assert remark_lines(text, "102253Z") == [
        ("Station type", "Automated, without a precipitation discriminator, augmented by an observer"),
        ("Sea-level pressure", "Not available"),
        ("Precise temperature", "-10.0°C / 14.0°F"),
        ("Precise dewpoint", "-12.2°C / 10.0°F"),
        ("Temperature (last 6 hours)", "High 11.7°C / 53.1°F, low -4.3°C / 24.3°F"),
        ("Temperature (last 24 hours)", "High 2.8°C / 37.0°F, low -3.9°C / 25.0°F"),
        ("Pressure tendency", "Up 1.6 hPa in 3 hours (falling or steady, then rising)"),
        ("", "Rising rapidly"),
        ("Peak wind", "050° at 38 kt (22:21Z)"),
        ("Wind shift", "At 21:38Z, frontal passage"),
        ("Tower visibility", "1 1/2 miles"),
        ("Surface visibility", "1/4 mile"),
        ("Variable visibility", "1/4 to 2 miles"),
        ("Variable ceiling", "300 to 800 ft"),
        ("Precipitation (since the last hourly report)", "0.48 in"),
        ("Precipitation (last 3 or 6 hours)", "0.36 in"),  # a 2253Z report is neither the 3- nor the 6-hourly one
        ("Precipitation (last 24 hours)", "Trace"),
        ("Ice accretion (since the last hourly report)", "Trace"),
        ("Snow depth", "1 in"),
        ("Snowfall (last 6 hours)", "0.5 in"),
        ("Snow water equivalent", "1.2 in"),
        ("Precipitation began/ended", "Unknown precipitation began 22:27Z, ended 22:41Z"),
        ("", "Snow ended 22:19Z"),
        ("Thunderstorm began/ended", "Thunderstorm ended 22:05Z, began 22:24Z, ended 22:39Z"),
        ("Sensors out of service", "Precipitation identifier, visibility sensor at RWY06, lightning detector"),
        ("Special reports", "Not sent by this station"),
        ("Maintenance", "The station needs maintenance"),
        ("Other remarks", "ROOF WIND 12028G40KT"),
    ]


@pytest.mark.parametrize(
    "text, time, line",
    [
        ("AO2", "110353Z", ("Station type", "Automated, with a precipitation discriminator")),
        ("54000", "110353Z", ("Pressure tendency", "Unchanged in 3 hours (steady)")),
        ("58069", "110353Z", ("Pressure tendency", "Down 6.9 hPa in 3 hours (steady or rising, then falling)")),
        ("P////", "110353Z", ("Precipitation (since the last hourly report)", "Couldn't be measured")),
        ("60010", "111153Z", ("Precipitation (last 6 hours)", "0.10 in")),
        ("20094", "110353Z", ("Temperature (last 6 hours)", "Low 9.4°C / 48.9°F")),
        ("FZRAB07", "110353Z", ("Precipitation began/ended", "Freezing rain began 03:07Z")),
        ("SHSNE10", "110353Z", ("Precipitation began/ended", "Snow showers ended 03:10Z")),
        # a zero is a trace in every amount group (decode.inches() has the sources)
        ("4/000", "111153Z", ("Snow depth", "Trace")),
        ("931000", "111153Z", ("Snowfall (last 6 hours)", "Trace")),
        ("933000", "111153Z", ("Snow water equivalent", "Trace")),
        ("I1000", "110353Z", ("Ice accretion (since the last hourly report)", "Trace")),
        ("I3001", "110353Z", ("Ice accretion (last 3 hours)", "0.01 in")),
        ("70000", "111153Z", ("Precipitation (last 24 hours)", "Trace")),
    ],
)
def test_remark_line(text, time, line):
    assert remark_lines(text, time) == [line]


@pytest.mark.parametrize("text", ["VIS 1/0V2", "TWR VIS 1/0", "SFC VIS 0/0"])
def test_a_zero_denominator_is_other_remarks(text):
    report = Report(raw=f"METAR KTST 110353Z 00000KT 10SM CLR 16/15 A3015 RMK {text}")
    assert decode.remarks(report.remarks) == [("Other remarks", text)]
    assert decode.decode(report)[-1] == {"label": "Other remarks", "text": text}


def test_remark_times_without_the_hour():
    # no report time to place a minute in its hour
    found = decode.remarks(Report(raw="KTST RMK PK WND 33041/45 RAB09").remarks)
    assert found == [
        ("Peak wind", "330° at 41 kt (:45 past the hour)"),
        ("Precipitation began/ended", "Rain began :09 past the hour"),
    ]


# ---- the body: what the JSON doesn't have (metarmap.body) ----------------------------------------------------------

BODY = {
    case["rawOb"]: case
    for case in json.loads((Path(__file__).parent / "fixtures" / "metars_body.json").read_text())["reports"]
}


def fetched(start):
    """The fixture's report starting with `start`, as metar.parse_report reads it from the JSON."""
    return parse_report(next(case for raw, case in BODY.items() if raw.startswith(start)))


def test_a_us_automated_report_with_runway_visual_range():
    assert lines(fetched("METAR PASC 110453Z"))[:9] == [
        ("Observed", "11 Nov 04:53Z"),  # AUTO: no Report type line (Station type says it)
        ("Wind", "060° at 26 kt"),
        ("Visibility", "1 mile"),
        ("Runway visual range", "Runway 06: more than 6,000 ft"),
        ("Weather", "Mist, unknown precipitation"),
        ("Clouds", "Overcast 700 ft (ceiling)"),
        ("Temperature", "-8°C / 18°F"),
        ("Dewpoint", "-9°C / 16°F (spread 1°C)"),
        ("Altimeter", "29.52 inHg"),
    ]


def test_a_varying_runway_visual_range():
    assert lines(fetched("METAR KHIO 110453Z"))[:9] == [
        ("Observed", "11 Nov 04:53Z"),
        ("Wind", "Calm"),  # a manual METAR with no modifier: no Report type line
        ("Visibility", "1/4 mile"),
        ("Runway visual range", "Runway 13 right: varying 1,200 to more than 6,000 ft"),
        ("Weather", "Fog"),
        ("Clouds", "Sky obscured, vertical visibility 100 ft (ceiling)"),
        ("Temperature", "12°C / 54°F"),
        ("Dewpoint", "12°C / 54°F (spread 0°C)"),
        ("Altimeter", "30.04 inHg"),
    ]


def test_an_international_cavok_report_with_runway_state_and_trend():
    assert lines(fetched("METAR UTAM 110400Z")) == [
        ("Observed", "11 Nov 04:00Z"),
        ("Wind", "050° at 6 kt"),
        ("Visibility", "6+ miles"),
        ("CAVOK", decode.CAVOK),  # in place of the Clouds line, which said Clear
        ("Temperature", "4°C / 39°F"),
        ("Dewpoint", "2°C / 36°F (spread 2°C)"),
        ("Altimeter", "30.50 inHg"),
        ("Runway state", "All runways: cleared, friction coefficient 0.70"),
        ("Trend", "No significant change expected in the next 2 hours"),
    ]
    assert decode.CAVOK == (
        "Ceiling and visibility OK: visibility 10 km or more, no cloud below 5,000 ft, no cumulonimbus or towering "
        "cumulus, no significant weather"
    )


def test_every_body_line_in_order():
    raw = (
        "SPECI LTST 110450Z COR AUTO 24008KT 200V280 0800 0500NE R04/P2000N R22L/0550V0800U FG BKN002 FEW015CB "
        "05/04 Q1003 RERA WS R22L R24L/290145 TEMPO FM0500 0400 FG VV001"
    )
    report = parse_report(
        {
            "rawOb": raw,
            "obsTime": 1794372600,
            "wdir": 240,
            "wspd": 8,
            "visib": 0.5,
            "wxString": "FG",
            "clouds": [{"cover": "BKN", "base": 200}, {"cover": "FEW", "base": 1500}],
            "temp": 5,
            "dewp": 4,
            "altim": 1003,
        }
    )
    assert lines(report) == [
        ("Observed", "11 Nov 04:50Z"),
        ("Report type", "Special report (unscheduled), corrected"),  # not AUTO
        ("Wind", "240° at 8 kt"),
        ("Wind variability", "Varying between 200° and 280°"),
        ("Visibility", "1/2 mile"),
        ("Lowest visibility", "500 m to the northeast"),
        ("Runway visual range", "Runway 04: more than 2,000 m, no change"),
        ("", "Runway 22 left: varying 550 to 800 m, improving"),
        ("Weather", "Fog"),
        ("Clouds", "Broken 200 ft (ceiling)"),
        ("", "Few 1,500 ft, cumulonimbus"),
        ("Temperature", "5°C / 41°F"),
        ("Dewpoint", "4°C / 39°F (spread 1°C)"),
        ("Altimeter", "29.62 inHg"),
        ("Recent weather", "Rain (since the last routine report, not now)"),
        ("Wind shear", "Runway 22 left"),
        (
            "Runway state",
            "Runway 24 left: wet or water patches, covering 51-100%, 1 mm deep, friction coefficient 0.45",
        ),
        ("Trend", "Temporarily from 05:00Z: visibility 400 m, fog, sky obscured (vertical visibility 100 ft)"),
    ]


FIXTURES = Path(__file__).parent / "fixtures"
# master's lines (decode.py before phase 2) for the fixture reports with none of the body groups phase 2 reads
BEFORE = json.loads((FIXTURES / "decode_before_body.json").read_text())
REMARKS = json.loads((FIXTURES / "metars_remarks.json").read_text())["reports"]


def has_body_groups(raw):
    """Whether the body has a group phase 2 shows: AUTO and RTD alone don't (no Report type line)."""
    found = Report(raw=raw).body
    return bool(
        found.report_type == "SPECI"
        or any(code == "COR" or code.startswith("CC") for code in found.modifiers)
        or found.wind_varies
        or found.lowest_visibility_m is not None
        or found.no_directional_variation
        or found.runway_ranges
        or found.sky
        or any(cloud.kind for cloud in found.clouds)
        or found.recent_weather
        or found.wind_shear
        or found.runway_states
        or found.trends
    )


def test_the_reports_without_body_groups_are_the_golden_ones():
    assert sorted(BEFORE["mock"]) == sorted(case["rawOb"] for case in REMARKS if not has_body_groups(case["rawOb"]))
    us = [raw for raw in BODY if raw.split()[1][:1] in "KP" and not has_body_groups(raw)]
    assert sorted(BEFORE["fetched"]) == sorted(us)
    assert len(BEFORE["mock"]) >= 100 and sum(" AUTO " in raw for raw in BEFORE["mock"]) >= 40


@pytest.mark.parametrize("raw", sorted(BEFORE["mock"]))
def test_a_mock_without_body_groups_decodes_as_before(raw):
    assert lines(parse_raw(raw, NOV_11)) == [tuple(line) for line in BEFORE["mock"][raw]]


@pytest.mark.parametrize("raw", sorted(BEFORE["fetched"]))
def test_a_fetched_report_without_body_groups_decodes_as_before(raw):
    assert lines(parse_report(BODY[raw])) == [tuple(line) for line in BEFORE["fetched"][raw]]


@pytest.mark.parametrize(
    "start, text",
    [
        ("METAR PASC 110453Z", None),  # AUTO only: Station type says it
        ("METAR KICT 110453Z", "Routine report, corrected"),
        ("METAR EGCC 110450Z", "Routine report, corrected"),  # COR AUTO: the AUTO isn't shown
        ("SPECI CYOW 101927Z", "Special report (unscheduled), corrected (first correction)"),
        ("SPECI KHUF 110456Z", "Special report (unscheduled)"),
        ("METAR MMCZ 110359Z", None),  # RTD only: neither special nor corrected
        ("METAR KHIO 110453Z", None),  # routine, no modifier: the usual report has no line
    ],
)
def test_report_type(start, text):
    assert decode.report_type(fetched(start).body) == text


@pytest.mark.parametrize(
    "raw, text",
    [
        ("METAR KTST 110353Z CCB 00000KT 10SM CLR 16/15 A3015", "Routine report, corrected (second correction)"),
        ("KTST 110353Z AUTO 00000KT 10SM CLR 16/15 A3015", None),  # no METAR or SPECI
        ("KTST 110353Z COR 00000KT 10SM CLR 16/15 A3015", "Corrected"),
        ("METAR KTST 110353Z CCZ 00000KT 10SM CLR 16/15 A3015", "Routine report, corrected"),
        ("SPECI KTST 110353Z AUTO 00000KT 10SM CLR 16/15 A3015", "Special report (unscheduled)"),
        ("SPECI KTST 110353Z COR AUTO 00000KT 10SM CLR 16/15 A3015", "Special report (unscheduled), corrected"),
        ("METAR KTST 110353Z RTD 00000KT 10SM CLR 16/15 A3015", None),
        (
            "METAR KTST 110353Z CCA RTD 00000KT 10SM CLR 16/15 A3015",
            "Routine report, corrected (first correction), delayed",
        ),
        ("METAR KTST 110353Z 00000KT 10SM CLR 16/15 A3015", None),
    ],
)
def test_report_type_of_a_typed_report(raw, text):
    assert decode.report_type(Report(raw=raw).body) == text


@pytest.mark.parametrize(
    "group, text",
    [
        ("R28/2400FT", "Runway 28: 2,400 ft"),
        ("R28L/M0600FT", "Runway 28 left: less than 600 ft"),
        ("R06/P6000FT", "Runway 06: more than 6,000 ft"),
        ("R13C/M0600V1200FT", "Runway 13 center: varying less than 600 to 1,200 ft"),
        ("R16/2600V3500FT/U", "Runway 16: varying 2,600 to 3,500 ft, improving"),
        ("R06L/4500FT/D", "Runway 06 left: 4,500 ft, worsening"),
        ("R24/0600N", "Runway 24: 600 m, no change"),
        ("R24/0550V0800U", "Runway 24: varying 550 to 800 m, improving"),
        ("R18R/P2000N", "Runway 18 right: more than 2,000 m, no change"),
        ("R27/M0050D", "Runway 27: less than 50 m, worsening"),
    ],
)
def test_runway_visual_range(group, text):
    body = Report(raw=f"METAR KTST 110450Z 24008KT 0800 {group} FG VV001 06/06 Q1003").body
    assert decode.body_visibility(body) == [("Runway visual range", text)]


def test_a_runway_visual_range_not_reported_isnt_shown():
    body = Report(raw="METAR KTST 110450Z 24008KT 0800 R24///// FG VV001 06/06 Q1003").body
    assert body.runway_ranges == (RunwayRange("24"),) and decode.body_visibility(body) == []  # no line at all
    body = Report(raw="METAR KTST 110450Z 24008KT 0800 R24///// R06/0600N R18///// FG VV001 06/06 Q1003").body
    assert decode.body_visibility(body) == [("Runway visual range", "Runway 06: 600 m, no change")]
    # LFPO's reports: three runways reported and two all slashes
    assert [line for line in lines(fetched("METAR LFPO 110500Z")) if line[0] in ("Runway visual range", "")] == [
        ("Runway visual range", "Runway 02: more than 2,000 m"),
        ("", "Runway 25: more than 2,000 m"),
        ("", "Runway 07: more than 2,000 m"),
    ]


@pytest.mark.parametrize(
    "group, text",
    [
        ("R24L/290145", "Runway 24 left: wet or water patches, covering 51-100%, 1 mm deep, friction coefficient 0.45"),
        (
            "R21/39//23",
            "Runway 21: rime or frost (normally less than 1 mm deep), covering 51-100%, friction coefficient 0.23",
        ),
        (
            "R88/290055",
            "All runways: wet or water patches, covering 51-100%, less than 1 mm deep, friction coefficient 0.55",
        ),
        ("R06/451293", "Runway 06: dry snow, covering 26-50%, 12 mm deep, braking action medium"),
        (
            "R06/899891",
            "Runway 06: compacted or rolled snow, covering 51-100%, 40 cm or more deep, braking action poor",
        ),
        ("R06/719295", "Runway 06: ice, covering less than 10%, 10 cm deep, braking action good"),
        (
            "R06/6299//",
            "Runway 06: slush, covering 11-25%, runway not operational (snow, slush, ice, drifts or clearance), "
            "depth not reported",
        ),
        ("R06/0///99", "Runway 06: clear and dry, braking figures unreliable"),
        ("R06///////", "Runway 06: deposit not reported"),
        ("R88/CLRD70", "All runways: cleared, friction coefficient 0.70"),
        ("R24C/CLRD//", "Runway 24 center: cleared"),
        ("R/SNOCLO", "Airport closed by snow"),
        # a code that isn't in the tables, or a runway that isn't one: shown as reported, not guessed
        ("R06/239145", "R06/239145"),  # extent 3
        ("R06/879891", "R06/879891"),  # extent 7
        ("R06/299145", "R06/299145"),  # depth 91
        ("R06/290196", "R06/290196"),  # braking 96
        ("R06/290100", "R06/290100"),  # friction 00
        ("R24/CLRD96", "R24/CLRD96"),
        ("R99/290145", "R99/290145"),  # repeats the last report's: which runway isn't said
        ("R74/290145", "R74/290145"),  # the old code for 24R (50 added): not read
    ],
)
def test_runway_state(group, text):
    body = Report(raw=f"METAR UTST 110450Z 24004MPS 9999 OVC020 01/M01 Q1014 {group}").body
    assert decode.body_after_altimeter(body) == [("Runway state", text)]


@pytest.mark.parametrize(
    "trend, text",
    [
        ("NOSIG", "No significant change expected in the next 2 hours"),
        ("TEMPO 4000 RA BKN014", "Temporarily: visibility 4,000 m, rain, broken 1,400 ft"),
        ("BECMG FM1050 6000 BKN006", "Becoming from 10:50Z: visibility 6,000 m, broken 600 ft"),
        (
            "TEMPO FM0430 TL0500 4000 TSRA",
            "Temporarily from 04:30Z until 05:00Z: visibility 4,000 m, thunderstorm with rain",
        ),
        ("BECMG AT1000 9999 NSW", "Becoming at 10:00Z: visibility 10 km or more, no significant weather"),
        (
            "TEMPO 14018G30KT 3000 SHRA FEW015CB BKN020",
            "Temporarily: wind 140° at 18 kt gusting 30 kt, visibility 3,000 m, rain showers, "
            "few 1,500 ft cumulonimbus, broken 2,000 ft",
        ),
        ("BECMG 29012KT", "Becoming: wind 290° at 12 kt"),
        ("BECMG VRB03MPS CAVOK", "Becoming: wind variable at 3 m/s, ceiling and visibility OK"),
        ("BECMG 00000KT", "Becoming: wind calm"),
        ("TEMPO 8000 RA NSC", "Temporarily: visibility 8,000 m, rain, no significant cloud"),
        ("TEMPO 0400 FG VV///", "Temporarily: visibility 400 m, fog, sky obscured"),
        ("TEMPO 2SM BR", "Temporarily: visibility 2 miles, mist"),
        ("BECMG P6SM", "Becoming: visibility 6+ miles"),
        ("TEMPO 40000 -RA BKN005", "Temporarily: light rain, broken 500 ft, 40000"),  # what it can't read, as reported
        ("TEMPO SHRA BLU", "Temporarily: rain showers"),  # a military color state is left out
        ("BECMG YLO1 W12/S2", "Becoming: W12/S2"),  # another code it can't read is shown
    ],
)
def test_trend(trend, text):
    body = Report(raw=f"METAR LTST 110450Z 24008KT 9999 FEW040 12/10 Q1012 {trend}").body
    assert decode.body_after_altimeter(body) == [("Trend", text)]


def test_two_trends_and_two_wind_shears_go_on_over_more_lines():
    body = Report(
        raw="METAR LTST 110450Z 24008KT 9999 FEW040 12/10 Q1012 WS R20 WS ALL RWY BECMG 0600 FG TEMPO 0200"
    ).body
    assert decode.body_after_altimeter(body) == [
        ("Wind shear", "Runway 20"),
        ("", "All runways"),
        ("Trend", "Becoming: visibility 600 m, fog"),
        ("", "Temporarily: visibility 200 m"),
    ]


@pytest.mark.parametrize(
    "start, line",
    [
        ("METAR EGCC 110450Z", ("Clouds", "No clouds detected (automated)")),  # the JSON says CLR
        (
            "METAR EDDH 100550Z",
            ("Clouds", "No significant cloud: none below 5,000 ft, no cumulonimbus or towering cumulus"),
        ),
    ],
)
def test_no_cloud_detected_and_no_significant_cloud(start, line):
    assert line in lines(fetched(start))
    assert ("Clouds", "Clear") not in lines(fetched(start))


def test_a_mock_reads_ncd_nsc_and_cavok_as_a_fetched_report_does():
    for raw in (
        "METAR EGCC 110450Z COR AUTO 04008KT 9999 NCD 06/04 Q1006 NOSIG",
        "METAR SAEZ 110400Z 16003KT CAVOK 19/15 Q1017",
    ):
        mock = [line for line in lines(parse_raw(raw, NOV_11)) if line[0] in ("Clouds", "CAVOK")]
        real = [
            line
            for line in lines(parse_report({"rawOb": raw, "cover": "CAVOK" if "CAVOK" in raw else "CLR"}))
            if line[0] in ("Clouds", "CAVOK")
        ]
        assert mock == real and len(mock) == 1


def test_the_clouds_have_their_cb_and_tcu():
    report = parse_raw(KHOU, NOV_11)
    assert lines(report)[4:7] == [
        ("Clouds", "Scattered 2,200 ft, cumulonimbus"),
        ("", "Broken 7,000 ft (ceiling)"),
        ("", "Overcast 9,000 ft"),
    ]
    tcu = parse_raw("METAR KTST 110353Z 00000KT 10SM BKN030TCU 16/15 A3015", NOV_11)
    assert ("Clouds", "Broken 3,000 ft, towering cumulus (ceiling)") in lines(tcu)


def test_a_cloud_type_is_never_put_on_the_wrong_layer():
    # the JSON leaves out FEW///TCU (no height): the layers it has still line up
    report = fetched("METAR EDDS 110350Z")
    assert decode.cloud_kinds(report.sky_conditions, report.body.clouds) == [None]
    # layers that don't match the body's (the JSON has at most 4): no types at all
    groups = Report(raw="METAR KTST 110353Z 00000KT 10SM SCT020CB BKN030 16/15 A3015").body.clouds
    assert decode.cloud_kinds([SkyLayer("SCT", 2500), SkyLayer("BKN", 3000)], groups) == ()
    assert decode.cloud_kinds([SkyLayer("SCT", 2000)], groups) == ()
    assert decode.cloud_kinds([SkyLayer("SCT", 2000), SkyLayer("BKN", 3000)], groups) == ["CB", None]


def test_no_directional_variation_and_the_lowest_visibility():
    body = Report(raw="METAR LSZL 110450Z AUTO 00000KT 9999NDV BKN051 08/07 Q1011").body
    assert decode.body_visibility(body) == [("", "Directional variation not available")]  # goes on from Visibility
    assert decode.body_visibility(body, shown=False) == [("Visibility", "Directional variation not available")]
    body = Report(raw="METAR ELLX 110220Z AUTO 11004KT 080V150 0450 0150// R24/0650N FG VV001 06/06 Q1003").body
    assert decode.body_visibility(body) == [
        ("Lowest visibility", "150 m"),  # direction not known
        ("Runway visual range", "Runway 24: 650 m, no change"),
    ]


@pytest.mark.parametrize(
    "directions, text",
    [((350, 50), "Varying between 350° and 050°"), ((90, 180), "Varying between 090° and 180°"), (None, None)],
)
def test_wind_variability(directions, text):
    assert decode.wind_varies(directions) == text


def test_recent_weather():
    body = Report(raw="METAR EHEH 110455Z AUTO 05005KT 3000 -RA BKN003 05/04 Q1003 RERA RESHSN RETS").body
    assert decode.body_after_altimeter(body) == [
        ("Recent weather", "Rain, snow showers, thunderstorm (since the last routine report, not now)")
    ]


def test_a_mock_doesnt_read_the_trend_as_the_weather():
    raw = "METAR EGLL 101920Z AUTO 06007KT 7000 -RA BKN018 OVC027 09/08 Q1005 TEMPO 4000 RA BKN014"
    mock = parse_raw(raw, NOV_11)
    assert mock.weather == "-RA"  # as the JSON's wxString: not the TEMPO's RA
    assert [(layer.cover, layer.base_ft) for layer in mock.sky_conditions] == [("BKN", 1800), ("OVC", 2700)]
    assert parse_raw("METAR LSZL 110450Z AUTO 00000KT 9999NDV BKN051 08/07 Q1011", NOV_11).visibility_more


@pytest.mark.parametrize(
    "raw",
    [raw for raw in BODY if raw.split()[1] in ("UUEE", "LSGG", "EGLL", "CYYT", "PASC", "KHIO", "EGCC", "LFPO", "OMDB")],
)
def test_fetched_and_mock_reports_agree(raw):
    """
    metar.parse_report (the JSON) and parse_raw (a mock typed from the same text) give the same wind, temperatures,
    altimeter, weather and cloud layers, and the same lines from the body. Known differences: the JSON rounds the
    visibility, says CLR for NCD and NSC, and keeps 4 cloud layers.
    """
    case = BODY[raw]
    real, mock = parse_report(case), parse_raw(raw, NOV_11)
    for field in ("wind_dir", "wind_speed", "wind_gust_speed", "temp_c", "dewpoint_c", "altimeter_inhg"):
        assert getattr(real, field) == getattr(mock, field), field
    assert sorted(real.weather.split()) == sorted(mock.weather.split())
    covers = [(layer.cover, layer.base_ft) for layer in real.sky_conditions if layer.cover in decode.COVER]
    assert covers == [(layer.cover, layer.base_ft) for layer in mock.sky_conditions if layer.cover in decode.COVER]
    new = (
        "Report type",
        "Wind variability",
        "Lowest visibility",
        "Runway visual range",
        "Recent weather",
        "Wind shear",
        "Runway state",
        "Trend",
        "CAVOK",
    )
    real_lines, mock_lines = lines(real), lines(mock)
    for label in new:
        assert [line for line in real_lines if line[0] == label] == [line for line in mock_lines if line[0] == label]


UNKNOWN_HEIGHT = [raw for raw in BODY if "///CB" in raw or "///TCU" in raw]


@pytest.mark.parametrize("raw", UNKNOWN_HEIGHT)
def test_a_cb_or_tcu_of_unknown_height_is_shown(raw):
    """The JSON leaves out FEW///CB: its line goes on after the Clouds, once, from the fetched report and a mock."""
    group = next(t for t in raw.split() if t.endswith(("///CB", "///TCU")))
    cover, kind = decode.COVER[group[:3]], decode.CLOUD_KINDS[group[6:]]
    real = lines(parse_report(BODY[raw]))
    sky = real[real.index(next(line for line in real if line[0] == "Clouds")) :]
    sky = sky[: next(n for n, line in enumerate(sky) if line[0] not in ("Clouds", ""))]
    assert sky[-1] == ("", f"{cover} {kind}, height not known")
    assert [text for _, text in real].count(f"{cover} {kind}, height not known") == 1
    assert len(sky) == len(BODY[raw]["clouds"]) + 1  # the JSON's layers, then this one
    mock = lines(parse_raw(raw, NOV_11))
    assert mock[mock.index(sky[0]) : mock.index(sky[0]) + len(sky)] == sky  # a mock typed from it: the same lines


def test_the_corpus_has_eight_cbs_or_tcus_of_unknown_height():
    assert len(UNKNOWN_HEIGHT) == 8


@pytest.mark.parametrize(
    "layers, text, found",
    [
        # the JSON has no layers: the first is labeled Clouds
        ([], "//////CB", [("Clouds", "Cumulonimbus, cover and height not known")]),
        ([], "///TCU", [("Clouds", "Towering cumulus, cover and height not known")]),
        ([], "SCT///CB", [("Clouds", "Scattered cumulonimbus, height not known")]),
        (
            [SkyLayer("BKN", 500)],
            "BKN005 FEW///CB //////TCU",
            [
                ("Clouds", "Broken 500 ft (ceiling)"),
                ("", "Few cumulonimbus, height not known"),
                ("", "Towering cumulus, cover and height not known"),
            ],
        ),
        # a layer the JSON has with no height (base null: 0) is that one: shown once, with its type
        (
            [SkyLayer("BKN", 500), SkyLayer("FEW", 0)],
            "BKN005 FEW///CB",
            [("Clouds", "Broken 500 ft (ceiling)"), ("", "Few, cumulonimbus")],
        ),
        # a height not known without a type says nothing new: not shown
        ([SkyLayer("BKN", 500)], "BKN005 FEW///", [("Clouds", "Broken 500 ft (ceiling)")]),
        ([SkyLayer("BKN", 500)], "BKN005 FEW/////////", [("Clouds", "Broken 500 ft (ceiling)")]),
        # NCD, as the JSON's CLR: what it means, then the cloud the sensor did see
        (
            [SkyLayer("CLR")],
            "NCD //////CB",
            [("Clouds", "No clouds detected (automated)"), ("", "Cumulonimbus, cover and height not known")],
        ),
    ],
)
def test_the_lines_of_clouds_of_unknown_height(layers, text, found):
    report = Report(raw=f"METAR EDTS 110450Z AUTO 24008KT 9999 {text} 12/10 Q1012", sky_conditions=tuple(layers))
    assert decode.sky(report, report.body) == found


def test_cavok_has_no_cloud_lines():
    report = Report(
        raw="METAR EDTS 110450Z AUTO 24008KT CAVOK //////CB 12/10 Q1012", sky_conditions=(SkyLayer("CAVOK"),)
    )
    assert decode.sky(report, report.body) == [("CAVOK", decode.CAVOK)]
