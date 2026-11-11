"""Tests for metarmap.decode: a METAR in plain English for the Map page's Decoded tab."""

from datetime import datetime, timezone

import pytest

from metarmap import decode
from metarmap.metar import parse_raw, parse_report, parse_visibility
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
        ("Lightning", "Lightning observed"),  # the body's lines come first, as before
        ("Station type", "Automated, with a precipitation discriminator"),
        ("Sea-level pressure", "1021.4 hPa"),
        ("Precise temperature", "16.1°C / 61.0°F"),
        ("Precise dewpoint", "15.0°C / 59.0°F"),
        ("Precipitation (since the last hourly report)", "0.01 in"),
        ("Maintenance", "The station needs maintenance"),
        ("Other remarks", "OCNL LTGICCG E AND SW TS E AND SW MOV NE"),
    ]


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
