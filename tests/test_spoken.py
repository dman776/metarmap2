"""Tests for metarmap.spoken: a METAR as text to be read aloud."""

from datetime import datetime, timezone

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
        "Houston Hobby Airport. Weather at zero zero five three Zulu. "
        "Wind one three zero at one three, gusting one nine. Visibility one zero. "
        "Weather light rain and mist. Lightning observed. "
        "Sky condition few clouds at four thousand nine hundred, ceiling eight thousand broken, "
        "overcast at twelve thousand. "
        "Temperature two one, dew point one six. Altimeter three zero zero five. Marginal V F R."
    )


def test_a_plain_report():
    assert spoken.spoken(report(), "Hooks", "KDWH") == (
        "Hooks. Weather at zero zero five three Zulu. Wind one three zero at eight. Visibility one zero. Sky clear. "
        "Temperature two one, dew point one six. Altimeter three zero zero five. V F R."
    )


def test_no_report():
    assert spoken.spoken(None, "Crockett", "KDKR") == "Crockett. No weather report is available."
    assert spoken.spoken(None, "", "KDKR") == "K D K R. No weather report is available."


def test_missing_values_are_said_to_be_missing():
    metar = Report(obs_time=OBS)
    text = spoken.spoken(metar, "Hooks", "KDWH")
    assert text == (
        "Hooks. Weather at zero zero five three Zulu. Wind not reported. Visibility not reported. "
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
        (dict(wind_dir="90", wind_speed=5), "Wind zero nine zero at five."),
        (dict(wind_dir="360", wind_speed=22, wind_gust_speed=31), "Wind three six zero at two two, gusting three one."),
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
        (0.75, False, "Visibility three quarters."),
        (2.5, False, "Visibility two and one half."),
        (0.0625, False, "Visibility one sixteenth."),
        (0.375, False, "Visibility three eighths."),
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
        ((SkyLayer("SCT", 3800),), None, "Sky condition scattered at three thousand eight hundred."),
        ((SkyLayer("OVC", 800),), None, "Sky condition ceiling eight hundred overcast."),
        (
            (SkyLayer("SCT", 4300), SkyLayer("BKN", 8000), SkyLayer("OVC", 12000)),
            None,
            "Sky condition scattered at four thousand three hundred, ceiling eight thousand broken, "
            "overcast at twelve thousand.",
        ),
        ((SkyLayer("BKN", 25000),), None, "Sky condition ceiling twenty five thousand broken."),
        ((SkyLayer("OVX"),), 300, "Sky obscured, vertical visibility three hundred."),
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
        (-3, -8, "Temperature minus three, dew point minus eight."),
        (0, -1, "Temperature zero, dew point minus one."),
        (5, None, "Temperature five, dew point not reported."),
        (None, 4, "Temperature not reported, dew point four."),
    ],
)
def test_temperature(temp, dew, text):
    assert spoken.temperature(report(temp_c=temp, dewpoint_c=dew)) == text


def test_altimeter():
    assert spoken.altimeter(30.05) == "Altimeter three zero zero five."
    assert spoken.altimeter(29.92) == "Altimeter two nine nine two."
    assert spoken.altimeter(None) == "Altimeter not reported."


@pytest.mark.parametrize("category, text", [("IFR", "I F R."), ("LIFR", "Low I F R."), ("MVFR", "Marginal V F R.")])
def test_flight_category(category, text):
    assert spoken.spoken(report(flight_category=category), "Hooks").endswith(" " + text)


def test_no_flight_category_is_left_out():
    assert spoken.spoken(report(flight_category=None), "Hooks").endswith("Altimeter three zero zero five.")


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


def test_numbers():
    assert [spoken.number(n) for n in (0, 7, 10, 19, 20, 49, 99)] == [
        "zero",
        "seven",
        "ten",
        "nineteen",
        "twenty",
        "forty nine",
        "ninety nine",
    ]
    assert spoken.digits(130) == "one three zero"
    assert spoken.digits("0053") == "zero zero five three"
    assert spoken.digits(-8) == "eight"
    assert spoken.altitude(4900) == "four thousand nine hundred"
    assert spoken.altitude(800) == "eight hundred"
    assert spoken.altitude(12000) == "twelve thousand"
    assert spoken.altitude(4950) == "five thousand"  # to the nearest hundred (banker's rounding: 4950 -> 5000)
    assert spoken.altitude(0) == "zero"
