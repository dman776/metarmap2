"""
A METAR as it would be read aloud, ATIS style, for text to speech:

    David Wayne Hooks Memorial. Weather at zero zero five tree Zulu. Wind not reported. Visibility one zero. Sky
    condition few clouds at four thousand niner hundred, few clouds at seven thousand five hundred. Temperature two
    one, dew point one six. Altimeter tree zero zero five. VFR.

Everything is written as words, so a speech model can't read "10" or "30.05" two ways: digit by digit for winds,
times, temperatures and the altimeter, in English for cloud heights; a digit is said as pilots say it ("tree",
"niner"). What the report leaves out is said to be not
reported (as the LEDs blink red for it), so a listener can tell a missing value from a calm one. Each item is its own
sentence, which a speech model gives a pause.
"""

from fractions import Fraction
from typing import Optional

from metarmap import decode
from metarmap.models import Report

# the digits as pilots and controllers say them: "tree" and "niner" can't be heard as "free" or "nein"
DIGITS = ("zero", "one", "two", "tree", "four", "five", "six", "seven", "eight", "niner")
ONES = DIGITS + (
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
)
TENS = {2: "twenty", 3: "thirty", 4: "forty", 5: "fifty", 6: "sixty", 7: "seventy", 8: "eighty", 9: "ninety"}
DENOMINATORS = {2: "half", 3: "third", 4: "quarter", 5: "fifth", 8: "eighth", 16: "sixteenth"}

COVER = {"FEW": "few clouds", "SCT": "scattered", "BKN": "broken", "OVC": "overcast"}
CEILING = ("BKN", "OVC")
CLEAR = ("CLR", "SKC", "CAVOK", "NSC")
CATEGORY = {"VFR": "VFR", "MVFR": "Marginal VFR", "IFR": "IFR", "LIFR": "Low IFR"}

# how a station's name abbreviates words (aviationweather.gov's "Houston/Hobby Arpt"), written out
ABBREVIATIONS = {
    "aaf": "Army Airfield",
    "afb": "Air Force Base",
    "apt": "Airport",
    "arpt": "Airport",
    "cnty": "County",
    "ctr": "Center",
    "fld": "Field",
    "intcntl": "Intercontinental",
    "intl": "International",
    "mem": "Memorial",
    "muni": "Municipal",
    "nas": "Naval Air Station",
    "natl": "National",
    "ne": "Northeast",
    "nw": "Northwest",
    "rgnl": "Regional",
    "se": "Southeast",
    "st": "Saint",
    "sw": "Southwest",
}


def spoken(metar: Optional[Report], name: str = "", code: str = "") -> str:
    """
    The report as text to be spoken. name: the airport's name (a station's, e.g. "Houston/Hobby Arpt, TX, US", or the
    map's own); code: its identifier, spelled out when there's no name. An airport with no report says so.
    """
    place = airport_name(name or (metar.name if metar else ""), code)
    if not metar:
        return f"{place}. No weather report is available."
    sentences = [place + "."]
    if metar.obs_time:
        sentences.append(f"Weather at {digits(metar.obs_time.strftime('%H%M'))} Zulu.")
    sentences += [
        wind(metar),
        visibility(metar.visibility_sm, metar.visibility_more),
        weather(metar.weather),
        "Lightning observed." if metar.lightning else None,
        sky(metar),
        temperature(metar),
        altimeter(metar.altimeter_inhg),
        f"{CATEGORY[metar.flight_category]}." if metar.flight_category in CATEGORY else None,
    ]
    return " ".join(s for s in sentences if s)


def airport_name(name: str, code: str = "") -> str:
    """ "Houston/Hobby Arpt, TX, US" as "Houston Hobby Airport"; with no name, the code's letters: "K D W H"."""
    text = (name or "").split(",")[0].replace("/", " ").strip()
    if not text:
        return " ".join(code.upper()) or "This airport"
    return " ".join(ABBREVIATIONS.get(word.strip(".").lower(), word) for word in text.split())


# ---- numbers as words ---------------------------------------------------------------------------------------------


def digits(value) -> str:
    """Digit by digit: 130 -> "one tree zero", "0053" -> "zero zero five tree". A sign is dropped."""
    text = value if isinstance(value, str) else str(abs(int(value)))
    return " ".join(DIGITS[int(c)] for c in text if c.isdigit())


def number(n: int) -> str:
    """0 to 99 as English, with the digits as pilots say them: 49 -> "forty niner". Larger ones digit by digit."""
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + (f" {ONES[n % 10]}" if n % 10 else "")
    return digits(n)


def altitude(feet: int) -> str:
    """To the nearest hundred feet: 4900 -> "four thousand niner hundred", 800 -> "eight hundred"."""
    thousands, hundreds = divmod(round(feet, -2), 1000)
    parts = []
    if thousands:
        parts.append(f"{number(thousands)} thousand")
    if hundreds >= 100:
        parts.append(f"{DIGITS[hundreds // 100]} hundred")
    return " ".join(parts) or "zero"


def fraction(part: Fraction) -> str:
    """A fraction of a mile: 3/4 -> "tree quarters", 1/2 -> "one half"."""
    n, d = part.numerator, part.denominator
    word = DENOMINATORS.get(d)
    if word is None:
        return f"{number(n)} over {number(d)}"
    return f"{number(n)} {word}" + ("s" if n > 1 else "")


# ---- the sentences ------------------------------------------------------------------------------------------------


def wind(metar: Report) -> str:
    speed = metar.wind_speed
    if speed is None:
        return "Wind not reported."
    if speed == 0:
        return "Wind calm."
    gust = f", gusting {digits(metar.wind_gust_speed)}" if metar.wind_gust else ""
    direction = str(metar.wind_dir or "").upper()
    if not direction.isdigit():  # VRB
        return f"Wind variable at {digits(speed)}{gust}."
    return f"Wind {digits(f'{int(direction):03d}')} at {digits(speed)}{gust}."


def visibility(miles: Optional[float], more: bool = False) -> str:
    """ "Visibility one zero" for a report of 10+ miles, "Visibility one and one half" for 1 1/2."""
    if miles is None:
        return "Visibility not reported."
    value = Fraction(miles).limit_denominator(16)
    whole, part = divmod(value, 1)
    words = [w for w in (digits(whole) if whole else "", fraction(part) if part else "") if w]
    text = " and ".join(words) or "zero"
    if more and value < 10:  # P6SM: more than six
        return f"Visibility more than {text}."
    return f"Visibility {text}."


def weather(wx: str) -> Optional[str]:
    """ "-RA BR" as "Weather light rain and mist." Codes decode.py doesn't know are left out."""
    groups = [decode.weather_group(group.code) for group in decode.parse_weather(wx)]
    if not groups:
        return None
    text = ", ".join(groups[:-1]) + (" and " if len(groups) > 1 else "") + groups[-1]
    return f"Weather {text}."


def sky(metar: Report) -> str:
    layers = [layer for layer in metar.sky_conditions or () if layer.cover]
    if not layers:
        return "Sky condition not reported."
    if all(layer.cover in CLEAR for layer in layers):
        return "Sky clear."
    parts, ceiling_said = [], False
    for layer in layers:
        if layer.cover == "OVX":
            vertical = f", vertical visibility {altitude(metar.vert_vis_ft)}" if metar.vert_vis_ft else ""
            return f"Sky obscured{vertical}."
        cover = COVER.get(layer.cover)
        if cover is None:
            continue  # a cover we don't know, or clear among clouds
        if not layer.base_ft:
            parts.append(cover)
        elif layer.cover in CEILING and not ceiling_said:
            parts.append(f"ceiling {altitude(layer.base_ft)} {cover}")
            ceiling_said = True
        else:
            parts.append(f"{cover} at {altitude(layer.base_ft)}")
    return f"Sky condition {', '.join(parts)}." if parts else "Sky condition not reported."


def temperature(metar: Report) -> str:
    def celsius(value):
        return None if value is None else ("minus " if value < 0 else "") + digits(value)

    temp, dewpoint = celsius(metar.temp_c), celsius(metar.dewpoint_c)
    return f"Temperature {temp or 'not reported'}, dew point {dewpoint or 'not reported'}."


def altimeter(inhg: Optional[float]) -> str:
    """30.05 as "Altimeter tree zero zero five"."""
    if not inhg:
        return "Altimeter not reported."
    return f"Altimeter {digits(round(inhg * 100))}."
