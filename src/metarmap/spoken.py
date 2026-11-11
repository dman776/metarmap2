"""
A METAR as an AWOS would read it aloud, for text to speech:

    David Wayne Hooks Memorial. Weather at zero zero five tree Zulu. Wind not reported. Visibility one zero. Sky
    condition few clouds at four thousand niner hundred, few clouds at seven thousand five hundred. Temperature two
    one, dew point one six. Altimeter tree zero zero five. VFR.

Everything is written as words, so a speech model can't read "10" or "30.05" two ways: digit by digit for winds,
times, temperatures and the altimeter, in English for cloud heights; a digit is said as pilots say it ("tree",
"niner"). What the report leaves out is said to be not
reported (as the LEDs blink red for it), so a listener can tell a missing value from a calm one. Each item is its own
sentence, which a speech model gives a pause.

A few more items are said when the report has them, as a pilot would read them out, and nothing when it doesn't: the
runway visual range from the body, after the visibility ("Runway two eight R V R two thousand four hundred feet."),
and from the remarks, after the altimeter, the peak wind ("Peak wind two niner zero at tree five, at one four five
zero Zulu."), a wind shift ("Wind shift at zero five two zero Zulu, frontal passage.") and when precipitation began
and ended ("Rain began zero tree zero niner Zulu, ended zero tree two seven Zulu."). A time given only as minutes,
in a report whose own time isn't known, is said as minutes past the hour ("at five zero past the hour"). They're
worded as the Decoded tab words them (metarmap.decode), and one that can't be said (a bug) is left out, not the rest.
"""

import logging
import re
from fractions import Fraction
from typing import Callable, Optional, Sequence

from metarmap import decode
from metarmap.body import SIDES
from metarmap.models import Report

log = logging.getLogger(__name__)

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


def spoken(metar: Optional[Report], name: str = "", code: str = "", tunings: Sequence = ()) -> str:
    """
    The report as text to be spoken. name: the airport's name (a station's, e.g. "Houston/Hobby Arpt, TX, US", or the
    map's own); code: its identifier, spelled out when there's no name. An airport with no report says so. tunings:
    words or phrases said another way (the Pronunciation page's, for this airport; see atis_spoken.for_airport()),
    applied to the whole text, the airport's name too.
    """
    return tune(_spoken(metar, name, code), tunings)


def _spoken(metar: Optional[Report], name: str, code: str) -> str:
    place = airport_name(name or (metar.name if metar else ""), code)
    if not metar:
        return f"{place}. No weather report is available."
    sentences = [place + "."]
    if metar.obs_time:
        sentences.append(f"Weather at {digits(metar.obs_time.strftime('%H%M'))} Zulu.")
    sentences += [
        wind(metar),
        visibility(metar.visibility_sm, metar.visibility_more),
        guarded(runway_visual_range, metar),
        weather(metar.weather),
        lightning(metar),
        sky(metar),
        temperature(metar),
        altimeter(metar.altimeter_inhg),
        guarded(peak_wind, metar),
        guarded(wind_shift, metar),
        guarded(began_ended, metar),
        f"{CATEGORY[metar.flight_category]}." if metar.flight_category in CATEGORY else None,
    ]
    return " ".join(s for s in sentences if s)


_LOGGED = set()  # the raw reports a sentence's failure was logged for: once each


def guarded(sentence: Callable[[Report], Optional[str]], metar: Report) -> Optional[str]:
    """
    sentence(metar), or None if it raises (a bug), logged once per report and sentence: the rest is still said, as
    the body and remarks parsers keep what they can. (Once 1000 have been logged, later ones aren't.)
    """
    try:
        return sentence(metar)
    except Exception as e:
        name = getattr(sentence, "__name__", None) or repr(sentence)  # a partial has none
        key = (name, metar.raw)
        if key not in _LOGGED and len(_LOGGED) < 1000:
            _LOGGED.add(key)
            log.warning(f"Could not say the {name}: {e!r} raw: {metar.raw}")
        return None


def airport_name(name: str, code: str = "") -> str:
    """ "Houston/Hobby Arpt, TX, US" as "Houston Hobby Airport"; with no name, the code's letters: "K D W H"."""
    text = (name or "").split(",")[0].replace("/", " ").strip()
    if not text:
        return " ".join(code.upper()) or "This airport"
    return " ".join(ABBREVIATIONS.get(word.strip(".").lower(), word) for word in text.split())


def tune(text: str, tunings: Sequence) -> str:
    """
    The text with each tuning's words (whole words, any case) said as it's tuned, in one pass, so what one tuning
    says isn't tuned again. tunings: the longest first (atis_spoken.for_airport()), so a phrase wins over a word in it.
    """
    found = [t for t in tunings if t.text and t.text.split()]
    if not found:
        return text
    words = [r"\s+".join(re.escape(w) for w in t.text.split()) for t in found]
    pattern = re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(f"({w})" for w in words) + r")(?![A-Za-z0-9])", re.I)
    return pattern.sub(lambda m: found[m.lastindex - 1].say, text)


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


def count(n: int) -> str:
    """
    A whole number exactly, as English: 2400 -> "two thousand four hundred", 550 -> "five hundred fifty", 35000 ->
    "thirty five thousand" (altitude() rounds to the hundred, which a range in metres can't be).
    """
    thousands, rest = divmod(abs(int(n)), 1000)
    hundreds, ones = divmod(rest, 100)
    parts = [f"{number(thousands)} thousand" if thousands else "", f"{DIGITS[hundreds]} hundred" if hundreds else ""]
    parts.append(number(ones) if ones else "")
    return " ".join(p for p in parts if p) or "zero"


def clock(hour: Optional[int], minute: int) -> str:
    """
    A time as decode.clock() writes it, said: "one four five zero Zulu"; with only the minute (the report's time not
    known), "five zero past the hour".
    """
    if hour is None:
        return f"{digits(f'{minute:02d}')} past the hour"
    return f"{digits(f'{hour:02d}{minute:02d}')} Zulu"


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


def lightning(metar: Report) -> Optional[str]:
    """
    How often, how far and which way, a sentence per lightning group, without its kind: "Occasional lightning distant
    north.", "Frequent lightning overhead.", "Lightning in the vicinity, east and southwest." "Lightning observed."
    when the report says no more; None for none.
    """
    texts = [decode.lightning_sentence(group) for group in metar.lightning_groups]
    if not texts and metar.lightning:
        texts = ["Lightning observed"]
    return " ".join(f"{text}." for text in dict.fromkeys(texts)) or None


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


# ---- what the body and the remarks add, when the report has it --------------------------------------------------


def runway_visual_range(metar: Report) -> Optional[str]:
    """
    A sentence per runway with a range, in the order reported: "Runway two eight R V R two thousand four hundred
    feet.", "Runway one tree R V R variable from two thousand six hundred to more than six thousand feet.". A runway
    with no value (R24/////) isn't said, as the Decoded tab doesn't show it; None for none.
    """
    return " ".join(runway_range(found) for found in decode.reported_ranges(metar.body)) or None


def runway_range(found) -> str:
    """One runway visual range (body.RunwayRange with a value) as a sentence, with its trend as decode words it."""
    side = SIDES.get(found.runway[2:])
    where = f"Runway {digits(int(found.runway[:2]))}" + (f" {side}" if side else "")
    unit = "feet" if found.feet else "meters"
    low = f"{decode.RVR_BOUNDS.get(found.low_bound, '')}{count(found.low)}"
    if found.high is not None:
        text = f"variable from {low} to {decode.RVR_BOUNDS.get(found.high_bound, '')}{count(found.high)} {unit}"
    else:
        text = f"{low} {unit}"
    trend = decode.RVR_TRENDS.get(found.trend)
    return f"{where} R V R {text}" + (f", {trend}" if trend else "") + "."


def peak_wind(metar: Report) -> Optional[str]:
    """PK WND 29035/1450: "Peak wind two niner zero at tree five, at one four five zero Zulu."; None for none."""
    wind = metar.remarks.peak_wind
    if wind is None:
        return None
    return (
        f"Peak wind {digits(f'{wind.direction:03d}')} at {digits(wind.speed_kt)}, at {clock(wind.hour, wind.minute)}."
    )


def wind_shift(metar: Report) -> Optional[str]:
    """WSHFT 0520 FROPA: "Wind shift at zero five two zero Zulu, frontal passage."; None for none."""
    shift = metar.remarks.wind_shift
    if shift is None:
        return None
    fropa = ", frontal passage" if shift.frontal_passage else ""
    return f"Wind shift at {clock(shift.hour, shift.minute)}{fropa}."


def began_ended(metar: Report) -> Optional[str]:
    """
    When precipitation began and ended, a sentence per weather as the Decoded tab groups them: RAB09E27 in a 0353Z
    report is "Rain began zero tree zero niner Zulu, ended zero tree two seven Zulu."; None for none. A thunderstorm
    alone (TSB07) isn't said: its own line on the Decoded tab, not precipitation.
    """
    events = [event for event in metar.remarks.events if event.weather != "TS"]
    return " ".join(f"{line}." for line in decode.began_ended(events, clock)) or None
