"""Tests for metarmap.spoken: a METAR as text to be read aloud."""

import functools
import json
import random
from datetime import datetime, timezone
from pathlib import Path

import pytest

from metarmap import spoken
from metarmap.models import Report, SkyLayer

OBS = datetime(2026, 11, 7, 0, 53, tzinfo=timezone.utc)


def report(**fields):
    """A calm, clear VFR report; fields change what's in it."""
    defaults = dict(
        obs_time=OBS,
        wind_dir="130",
        wind_speed=8,
        visibility_sm=10.0,
        visibility_more=True,
        temp_c=21,
        dewpoint_c=16,
        altimeter_inhg=30.05,
        sky_conditions=(SkyLayer("CLR"),),
        flight_category="VFR",
    )
    return Report(**{**defaults, **fields})


def test_a_whole_report():
    metar = report(
        wind_speed=13,
        wind_gust_speed=19,
        weather="-RA BR",
        lightning=True,
        sky_conditions=(SkyLayer("FEW", 4900), SkyLayer("BKN", 8000), SkyLayer("OVC", 12000)),
        flight_category="MVFR",
    )
    assert spoken.spoken(metar, "Houston/Hobby Arpt, TX, US", "KHOU") == (
        "Houston Hobby Airport. Weather at zero zero five tree Zulu. "
        "Wind one tree zero at one tree, gusting one niner. Visibility one zero. "
        "Weather light rain and mist. Lightning observed. "
        "Sky condition few clouds at four thousand niner hundred, ceiling eight thousand broken, "
        "overcast at twelve thousand. "
        "Temperature two one, dew point one six. Altimeter tree zero zero five. Marginal VFR."
    )


def test_a_plain_report():
    assert spoken.spoken(report(), "Hooks", "KDWH") == (
        "Hooks. Weather at zero zero five tree Zulu. Wind one tree zero at eight. Visibility one zero. Sky clear. "
        "Temperature two one, dew point one six. Altimeter tree zero zero five. VFR."
    )


def test_no_report():
    assert spoken.spoken(None, "Crockett", "KDKR") == "Crockett. No weather report is available."
    assert spoken.spoken(None, "", "KDKR") == "K D K R. No weather report is available."


def test_missing_values_are_said_to_be_missing():
    metar = Report(obs_time=OBS)
    text = spoken.spoken(metar, "Hooks", "KDWH")
    assert text == (
        "Hooks. Weather at zero zero five tree Zulu. Wind not reported. Visibility not reported. "
        "Sky condition not reported. Temperature not reported, dew point not reported. Altimeter not reported."
    )  # and no category to say


def test_no_time():
    assert "Weather at" not in spoken.spoken(report(obs_time=None), "Hooks")


@pytest.mark.parametrize(
    "fields, text",
    [
        (dict(wind_speed=0, wind_dir="0"), "Wind calm."),
        (dict(wind_speed=None), "Wind not reported."),
        (dict(wind_dir="VRB", wind_speed=4), "Wind variable at four."),
        (dict(wind_dir="VRB", wind_speed=12, wind_gust_speed=20), "Wind variable at one two, gusting two zero."),
        (dict(wind_dir="90", wind_speed=5), "Wind zero niner zero at five."),
        (dict(wind_dir="360", wind_speed=22, wind_gust_speed=31), "Wind tree six zero at two two, gusting tree one."),
    ],
)
def test_wind(fields, text):
    assert spoken.wind(report(**fields)) == text


@pytest.mark.parametrize(
    "miles, more, text",
    [
        (10, True, "Visibility one zero."),
        (6, True, "Visibility more than six."),
        (7, False, "Visibility seven."),
        (1.5, False, "Visibility one and one half."),
        (0.25, False, "Visibility one quarter."),
        (0.75, False, "Visibility tree quarters."),
        (2.5, False, "Visibility two and one half."),
        (0.0625, False, "Visibility one sixteenth."),
        (0.375, False, "Visibility tree eighths."),
        (0, False, "Visibility zero."),
        (None, False, "Visibility not reported."),
    ],
)
def test_visibility(miles, more, text):
    assert spoken.visibility(miles, more) == text


def test_weather():
    assert spoken.weather("") is None
    assert spoken.weather("NSW") is None
    assert spoken.weather("TSRA") == "Weather thunderstorm with rain."
    assert spoken.weather("-RA BR") == "Weather light rain and mist."
    assert spoken.weather("+SN FG BR") == "Weather heavy snow, fog and mist."
    assert spoken.weather("VCSH") == "Weather showers in the vicinity."
    assert spoken.weather("XX") is None  # a code that isn't weather is left out


@pytest.mark.parametrize(
    "layers, vert, text",
    [
        ((), None, "Sky condition not reported."),
        ((SkyLayer("CLR"),), None, "Sky clear."),
        ((SkyLayer("SKC"),), None, "Sky clear."),
        ((SkyLayer("FEW", 5000),), None, "Sky condition few clouds at five thousand."),
        ((SkyLayer("SCT", 3800),), None, "Sky condition scattered at tree thousand eight hundred."),
        ((SkyLayer("OVC", 800),), None, "Sky condition ceiling eight hundred overcast."),
        (
            (SkyLayer("SCT", 4300), SkyLayer("BKN", 8000), SkyLayer("OVC", 12000)),
            None,
            "Sky condition scattered at four thousand tree hundred, ceiling eight thousand broken, "
            "overcast at twelve thousand.",
        ),
        ((SkyLayer("BKN", 25000),), None, "Sky condition ceiling twenty five thousand broken."),
        ((SkyLayer("OVX"),), 300, "Sky obscured, vertical visibility tree hundred."),
        ((SkyLayer("OVX"),), None, "Sky obscured."),
        ((SkyLayer("BKN"),), None, "Sky condition broken."),  # no base reported
    ],
)
def test_sky(layers, vert, text):
    assert spoken.sky(report(sky_conditions=layers, vert_vis_ft=vert)) == text


@pytest.mark.parametrize(
    "temp, dew, text",
    [
        (21, 16, "Temperature two one, dew point one six."),
        (-3, -8, "Temperature minus tree, dew point minus eight."),
        (0, -1, "Temperature zero, dew point minus one."),
        (5, None, "Temperature five, dew point not reported."),
        (None, 4, "Temperature not reported, dew point four."),
    ],
)
def test_temperature(temp, dew, text):
    assert spoken.temperature(report(temp_c=temp, dewpoint_c=dew)) == text


def test_altimeter():
    assert spoken.altimeter(30.05) == "Altimeter tree zero zero five."
    assert spoken.altimeter(29.92) == "Altimeter two niner niner two."
    assert spoken.altimeter(None) == "Altimeter not reported."


@pytest.mark.parametrize("category, text", [("IFR", "IFR."), ("LIFR", "Low IFR."), ("MVFR", "Marginal VFR.")])
def test_flight_category(category, text):
    assert spoken.spoken(report(flight_category=category), "Hooks").endswith(" " + text)


def test_no_flight_category_is_left_out():
    assert spoken.spoken(report(flight_category=None), "Hooks").endswith("Altimeter tree zero zero five.")


@pytest.mark.parametrize(
    "name, code, text",
    [
        ("Houston/Hobby Arpt, TX, US", "KHOU", "Houston Hobby Airport"),
        ("Victoria Rgnl", "KVCT", "Victoria Regional"),
        ("Port Lavaca/Calhoun Cnty", "KPKV", "Port Lavaca Calhoun County"),
        ("Fort Polk AAF", "KPOE", "Fort Polk Army Airfield"),
        ("Beaumont SE Texas Rgnl", "KBPT", "Beaumont Southeast Texas Regional"),
        ("Opelousas St Landry", "KOPL", "Opelousas Saint Landry"),
        ("Chenault Intl", "KCWF", "Chenault International"),
        ("Hobby", "KHOU", "Hobby"),
        ("", "KDWH", "K D W H"),
        ("", "", "This airport"),
    ],
)
def test_airport_name(name, code, text):
    assert spoken.airport_name(name, code) == text


def test_the_stations_name_is_used_when_the_map_has_none():
    assert spoken.spoken(report(name="Houston/Hobby Arpt, TX, US"), "", "KHOU").startswith("Houston Hobby Airport.")


def tuning(text, say, airport=""):
    from metarmap.settings import Tuning

    return Tuning(text=text, say=say, airport=airport)


def test_tunings_are_said_as_written_the_name_too():
    tunings = [tuning("Hooks Memorial", "Hooks"), tuning("david wayne", "Dave")]  # a phrase, any case
    said = spoken.spoken(report(name="David Wayne Hooks Memorial"), "", "KDWH", tunings)
    assert said.startswith("Dave Hooks. Weather at")
    assert spoken.spoken(None, "Hooks Memorial", "KDWH", tunings) == "Hooks. No weather report is available."


def test_tune_in_one_pass_whole_words_longest_first():
    tunings = [tuning("Hobby Airport", "the hobby field"), tuning("Hobby", "Hobbie"), tuning("field", "x")]
    assert spoken.tune("Houston Hobby Airport. Hobby. Hobbyist.", tunings) == (
        "Houston the hobby field. Hobbie. Hobbyist."  # what a tuning says isn't tuned again; Hobbyist isn't Hobby
    )
    assert spoken.tune("Hobby", []) == "Hobby"


def test_numbers():
    assert [spoken.number(n) for n in (0, 7, 10, 19, 20, 49, 99)] == [
        "zero",
        "seven",
        "ten",
        "nineteen",
        "twenty",
        "forty niner",
        "ninety niner",
    ]
    assert spoken.digits(130) == "one tree zero"
    assert spoken.digits("0053") == "zero zero five tree"
    assert spoken.digits(-8) == "eight"
    assert spoken.altitude(4900) == "four thousand niner hundred"
    assert spoken.altitude(800) == "eight hundred"
    assert spoken.altitude(12000) == "twelve thousand"
    assert spoken.altitude(4950) == "five thousand"  # to the nearest hundred (banker's rounding: 4950 -> 5000)
    assert spoken.altitude(0) == "zero"


# ---- lightning: how often, how far and which way, not its kind ------------------------------------------------

LTG_NOW = datetime(2026, 11, 11, 4, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "remarks, said",
    [
        # real: KHOU 110353Z (tests/fixtures/metars_remarks.json)
        (
            "AO2 SLP214 OCNL LTGICCG E AND SW TS E AND SW MOV NE P0001 T01610150 $",
            "Occasional lightning, east and southwest.",
        ),
        # the rest synthetic
        ("AO2 OCNL LTGCGIC DSNT N", "Occasional lightning distant north."),
        ("AO2 LTG DSNT N", "Lightning distant north."),  # said, though the pixel doesn't flicker
        ("AO2 FRQ LTGCG OHD", "Frequent lightning overhead."),
        ("AO2 LTG VC E AND SW", "Lightning in the vicinity, east and southwest."),
        ("AO2 LTG DSNT ALQDS", "Lightning distant in all quadrants."),
        ("AO2 LTG DSNT NW-E", "Lightning distant northwest through east."),
        (
            "AO2 FRQ LTGICCG OHD-S-SW AND DSNT W",
            "Frequent lightning overhead and south through southwest, distant west.",
        ),
        ("AO2 LTGICCG", "Lightning observed."),  # nothing more than its kind
        ("AO2 LTG", "Lightning observed."),
        ("AO2 LTG DSNT ALQDS OCNL LTG OHD", "Lightning distant in all quadrants. Occasional lightning overhead."),
        ("AO2 SLP214", None),
    ],
)
def test_lightning(remarks, said):
    from metarmap.metar import parse_raw

    report = parse_raw(f"METAR KHOU 110353Z 00000KT 8SM -TSRA SCT022CB 16/15 A3015 RMK {remarks}", LTG_NOW)
    assert spoken.lightning(report) == said
    text = spoken.spoken(report, "Hobby", "KHOU")
    if said:  # after the weather, before the sky
        assert f"Weather thunderstorm with light rain. {said} Sky condition" in text
    assert not any(code in text for code in ("LTG", "DSNT", "OHD", "ALQDS", "-"))  # words only


def test_lightning_flag_alone():
    """A Report made with the flag and no raw says what it used to."""
    assert spoken.lightning(report(lightning=True)) == "Lightning observed."
    assert spoken.lightning(report()) is None


# ---- what the body and the remarks add: runway visual range, peak wind, wind shift, began/ended -----------------

FIXTURES = Path(__file__).parent / "fixtures"
CORPORA = {
    name: json.loads((FIXTURES / name).read_text())["reports"]
    for name in ("metars_body.json", "metars_remarks.json", "metars_lightning.json")
}


def real(name, station_time):
    """The report of a fixture, as fetched (metar.parse_report): station_time is e.g. "PASC 110053Z"."""
    from metarmap import metar

    found = [r for r in CORPORA[name] if f" {station_time} " in r["rawOb"]]
    assert len(found) == 1, station_time
    return metar.parse_report(found[0])


def raw_report(raw):
    """A Report of a raw METAR (metar.parse_raw), read as of the report's own day."""
    from metarmap.metar import parse_raw

    return parse_raw(raw, datetime(2026, 11, 11, 4, 0, tzinfo=timezone.utc))


@pytest.mark.parametrize(
    "n, said",
    [
        (0, "zero"),
        (550, "five hundred fifty"),
        (600, "six hundred"),
        (1400, "one thousand four hundred"),
        (2400, "two thousand four hundred"),
        (6000, "six thousand"),
        (1250, "one thousand two hundred fifty"),
        (35000, "thirty five thousand"),
        (9999, "niner thousand niner hundred ninety niner"),
    ],
)
def test_count(n, said):
    assert spoken.count(n) == said


def test_clock():
    assert spoken.clock(14, 50) == "one four five zero Zulu"
    assert spoken.clock(3, 9) == "zero tree zero niner Zulu"
    assert spoken.clock(None, 50) == "five zero past the hour"
    assert spoken.clock(None, 9) == "zero niner past the hour"


@pytest.mark.parametrize(
    "groups, said",
    [
        # real: KCRP 081551Z, PASC 110053Z, CYYT 110447Z, EBBR 100020Z (tests/fixtures/metars_lightning.json and
        # metars_body.json)
        ("1SM R13/2600V4000FT", "Runway one tree R V R variable from two thousand six hundred to four thousand feet."),
        (
            "1SM R06/5500VP6000FT",
            "Runway six R V R variable from five thousand five hundred to more than six thousand feet.",
        ),
        ("1SM R06/P6000FT", "Runway six R V R more than six thousand feet."),
        (
            "1/2SM R16/2600V3500FT/U R10/2600V3500FT/U",
            "Runway one six R V R variable from two thousand six hundred to tree thousand five hundred feet, "
            "improving. Runway one zero R V R variable from two thousand six hundred to tree thousand five hundred "
            "feet, improving.",
        ),
        (
            "0500 0300 R25L/0750U R25R/0750D R01/P2000N",
            "Runway two five left R V R seven hundred fifty meters, improving. "
            "Runway two five right R V R seven hundred fifty meters, worsening. "
            "Runway one R V R more than two thousand meters, no change.",
        ),
        # the rest synthetic
        ("1/4SM R28/2400FT", "Runway two eight R V R two thousand four hundred feet."),
        ("1/4SM R36C/M0600FT", "Runway tree six center R V R less than six hundred feet."),
        (
            "1/4SM R09R/M0600VP6000FT",
            "Runway niner right R V R variable from less than six hundred to more than six thousand feet.",
        ),
        ("1/4SM R24/////", None),  # not reported: not said, as the Decoded tab doesn't show it
        ("1/4SM R24///// R06/1200FT", "Runway six R V R one thousand two hundred feet."),
        ("10SM", None),
    ],
)
def test_runway_visual_range(groups, said):
    report = raw_report(f"METAR KTST 110353Z 00000KT {groups} FG OVC002 16/15 A3015")
    assert spoken.runway_visual_range(report) == said
    text = spoken.spoken(report, "Test", "KTST")
    if said:  # right after the visibility, before the weather
        assert f". {said} Weather fog." in text
    else:
        assert "R V R" not in text


@pytest.mark.parametrize(
    "remarks, said",
    [
        # the remarks of real KCRP 081551Z (tests/fixtures/metars_lightning.json), PASC 110453Z (metars_body.json),
        # in a 0353Z report
        ("AO2 PK WND 06026/1452 TSB07 SLP195", "Peak wind zero six zero at two six, at one four five two Zulu."),
        ("AO2 PK WND 06034/0414 SLP999", "Peak wind zero six zero at tree four, at zero four one four Zulu."),
        # the rest synthetic
        ("AO2 PK WND 29035/1450", "Peak wind two niner zero at tree five, at one four five zero Zulu."),
        ("AO2 PK WND 29035/58", "Peak wind two niner zero at tree five, at zero two five eight Zulu."),  # hour before
        ("AO2 PK WND 29035/05", "Peak wind two niner zero at tree five, at zero tree zero five Zulu."),  # this hour
        ("AO2 PK WND 360105/0302", "Peak wind tree six zero at one zero five, at zero tree zero two Zulu."),
        ("AO2 SLP214", None),
    ],
)
def test_peak_wind(remarks, said):
    report = raw_report(f"METAR KTST 110353Z 29012KT 10SM CLR 16/15 A3015 RMK {remarks}")
    assert spoken.peak_wind(report) == said


@pytest.mark.parametrize(
    "remarks, said",
    [
        # real: KCRP 081551Z (tests/fixtures/metars_lightning.json), KVCT 102251Z (metars_remarks.json)
        ("AO2 SLP195 WSHFT 1519 FRQ LTGICCG OHD", "Wind shift at one five one niner Zulu."),
        ("AO2 WSHFT 2138 LTG DSNT NW-E", "Wind shift at two one tree eight Zulu."),
        # the rest synthetic
        ("AO2 WSHFT 0520 FROPA", "Wind shift at zero five two zero Zulu, frontal passage."),
        ("AO2 WSHFT 30 FROPA", "Wind shift at zero tree tree zero Zulu, frontal passage."),
        ("AO2 SLP214", None),
    ],
)
def test_wind_shift(remarks, said):
    report = raw_report(f"METAR KTST 110353Z 29012KT 10SM CLR 16/15 A3015 RMK {remarks}")
    assert spoken.wind_shift(report) == said


def test_minutes_only_with_no_report_time_are_past_the_hour():
    """Synthetic: a report with no time in its raw (as a mock can be), so the remarks' minutes have no hour."""
    report = Report(raw="METAR KTST 29012KT 10SM CLR RMK AO2 PK WND 29035/50 WSHFT 20 FROPA RAB09E27", wind_speed=12)
    assert spoken.peak_wind(report) == "Peak wind two niner zero at tree five, at five zero past the hour."
    assert spoken.wind_shift(report) == "Wind shift at two zero past the hour, frontal passage."
    assert spoken.began_ended(report) == "Rain began zero niner past the hour, ended two seven past the hour."


@pytest.mark.parametrize(
    "remarks, said",
    [
        # the remarks of real K3T5 110355Z, KCLL 110353Z, KCAR 110254Z (tests/fixtures/metars_remarks.json), in a
        # 0353Z report
        ("AO2 RAB0311E0339 P0003", "Rain began zero tree one one Zulu, ended zero tree tree niner Zulu."),
        ("AO2 RAE03B32 SLP197", "Rain ended zero tree zero tree Zulu, began zero tree tree two Zulu."),  # as reported
        (
            "AO2 UPB29E36B52SNE29 SLP051",
            "Unknown precipitation began zero tree two niner Zulu, ended zero tree tree six Zulu, "
            "began zero tree five two Zulu. Snow ended zero tree two niner Zulu.",
        ),
        # the rest synthetic
        ("AO2 RAB09E27", "Rain began zero tree zero niner Zulu, ended zero tree two seven Zulu."),
        (
            "AO2 FZRAB0250 SHSNB15",
            "Freezing rain began zero two five zero Zulu. Snow showers began zero tree one five Zulu.",
        ),
        ("AO2 TSRAB10", "Thunderstorm with rain began zero tree one zero Zulu."),  # precipitation, with its descriptor
        ("AO2 TSB0159E30", None),  # a thunderstorm alone isn't precipitation
        ("AO2 TSB25 RAB51", "Rain began zero tree five one Zulu."),
        ("AO2 RAB58", "Rain began zero two five eight Zulu."),  # later than the report's minute: the hour before
        ("AO2 SLP214", None),
    ],
)
def test_began_ended(remarks, said):
    report = raw_report(f"METAR KTST 110353Z 29012KT 10SM -RA OVC020 16/15 A3015 RMK {remarks}")
    assert spoken.began_ended(report) == said


def test_the_order_in_a_real_report():
    """Real: PASC 110053Z as fetched (tests/fixtures/metars_body.json): runway visual range, peak wind, began/ended."""
    assert spoken.spoken(real("metars_body.json", "PASC 110053Z"), "Prudhoe Bay", "PASC") == (
        "Prudhoe Bay. Weather at zero zero five tree Zulu. Wind zero six zero at two niner, gusting tree eight. "
        "Visibility one. "
        "Runway six R V R variable from five thousand five hundred to more than six thousand feet. "
        "Weather mist and unknown precipitation. Sky condition ceiling one thousand overcast. "
        "Temperature minus eight, dew point minus eight. Altimeter two niner five four. "
        "Peak wind zero six zero at tree eight, at zero zero five two Zulu. "
        "Unknown precipitation began zero zero tree six Zulu. Snow ended zero zero tree six Zulu."
    )  # no flight category in the fixture's fields


def test_the_order_with_lightning_and_a_wind_shift():
    """Real: KCRP 081551Z (tests/fixtures/metars_lightning.json), read from its raw text."""
    raw = next(r["rawOb"] for r in CORPORA["metars_lightning.json"] if " 081551Z " in r["rawOb"])
    report = raw_report(raw)
    text = spoken.spoken(report, "Corpus Christi", "KCRP")
    assert text == (
        "Corpus Christi. Weather at one five five one Zulu. Wind zero four zero at seven. Visibility one. "
        "Runway one tree R V R variable from two thousand six hundred to four thousand feet. "
        "Weather thunderstorm with heavy rain and mist. "
        "Frequent lightning overhead and south through southwest, distant west. "
        "Sky condition ceiling seven hundred broken, broken at one thousand four hundred, overcast at four thousand "
        "five hundred. Temperature two one, dew point two zero. Altimeter tree zero one one. "
        "Peak wind zero six zero at two six, at one four five two Zulu. Wind shift at one five one niner Zulu. IFR."
    )  # TSB07: a thunderstorm began, not said


def test_a_report_with_none_of_them_says_as_before():
    assert spoken.spoken(report(), "Hooks", "KDWH") == (
        "Hooks. Weather at zero zero five tree Zulu. Wind one tree zero at eight. Visibility one zero. Sky clear. "
        "Temperature two one, dew point one six. Altimeter tree zero zero five. VFR."
    )
    assert all(f(report()) is None for f in (spoken.runway_visual_range, spoken.peak_wind, spoken.wind_shift))
    assert spoken.began_ended(report()) is None


def test_a_sentence_without_a_name_that_fails_is_still_guarded(monkeypatch):
    monkeypatch.setattr(spoken, "_LOGGED", set())

    def broken(_metar, _extra):
        raise ValueError("a bug")

    assert spoken.guarded(functools.partial(broken, _extra=1), raw_report("METAR KTST 110353Z 29012KT 10SM")) is None


def test_a_sentence_that_fails_loses_only_itself(monkeypatch, caplog):
    monkeypatch.setattr(spoken, "_LOGGED", set())  # logged once per process: start clean, so a re-run passes too

    def broken(_body):
        raise ValueError("a bug")

    monkeypatch.setattr(spoken.decode, "reported_ranges", broken)
    metar = raw_report("METAR KTST 110353Z 29012KT 1SM R28/2400FT BR OVC005 16/15 A3015 RMK AO2 PK WND 29035/1450")
    text = spoken.spoken(metar, "Test", "KTST")
    assert "R V R" not in text
    assert "Visibility one. Weather mist." in text and "Peak wind two niner zero" in text and text.endswith("IFR.")
    spoken.spoken(metar, "Test", "KTST")
    assert [r.message for r in caplog.records].count(
        f"Could not say the runway_visual_range: ValueError('a bug') raw: {metar.raw}"
    ) == 1  # once per report


def test_tunings_apply_to_the_new_sentences():
    metar = raw_report("METAR KTST 110353Z 29012KT 1SM R28/2400FT BR OVC005 16/15 A3015 RMK AO2 WSHFT 0520 FROPA")
    tunings = [tuning("R V R", "visual range"), tuning("frontal passage", "a front went through")]
    text = spoken.spoken(metar, "Test", "KTST", tunings)
    assert "Runway two eight visual range two thousand four hundred feet." in text
    assert "Wind shift at zero five two zero Zulu, a front went through." in text
    untuned = spoken.spoken(metar, "Test", "KTST")
    assert "Runway two eight R V R two thousand four hundred feet." in untuned and "frontal passage." in untuned
    assert spoken.tune(untuned, tunings) == text  # tuned once, the whole text


# ---- every real report, and mutated ones: never raises, never a digit ---------------------------------------


def corpus_raws():
    return [r["rawOb"] for reports in CORPORA.values() for r in reports]


def test_every_real_report_is_said_in_words():
    from metarmap import metar

    for reports in CORPORA.values():
        for found in reports:
            for report in (metar.parse_report(found), raw_report(found["rawOb"])):
                text = spoken.spoken(report, "Test", "KTST")
                assert not any(c.isdigit() for c in text), (found["rawOb"], text)


def test_fuzz(caplog):
    """
    5,000 reports of the fixtures' real groups (body and remarks), shuffled, with characters changed: spoken() never
    raises, never says a digit and no new sentence fails (nothing logged). Seeded.
    """
    pool = [t for raw in corpus_raws() for t in raw.split()[2:]]
    rng = random.Random(9)
    for _ in range(5000):
        text = " ".join(rng.choice(pool) for _ in range(rng.randint(0, 16)))
        text = "".join(c if rng.random() > 0.03 else rng.choice("0123456789/VPMRBEFT ") for c in text)
        raw = "METAR KTST 110353Z " + text
        said = spoken.spoken(Report(raw=raw, wind_speed=5, visibility_sm=1.0, obs_time=OBS), "Test", "KTST")
        assert not any(c.isdigit() for c in said), (raw, said)
    assert [r for r in caplog.records if r.name == "metarmap.spoken"] == []
