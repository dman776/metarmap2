"""
An airport's digital ATIS (metarmap.atis) as text to be read aloud, for text to speech:

    George Bush Intercontinental Airport information Sierra, one six five tree Zulu. Wind one one zero at seven.
    Visibility one zero. Sky condition scattered at eight thousand, ceiling two five thousand broken. ... Arrivals
    expect ILS or RNAV Yankee runway eight right. ... Advise you have information Sierra.

The FAA's text is written in its contractions (FAA Order JO 7340.2): "DEPG RY 15L", "TWY EA CLSD", "A3013 (THREE ZERO
ONE THREE)". A speech voice would read those as letters or nonsense, so they're written out here:

- the header ("IAH ATIS INFO S 1653Z") as the airport's name, the information letter in the phonetic alphabet and the
  time; an arrival or departure ATIS says so
- the weather groups through metarmap.spoken, so they sound like the AWOS: wind, visibility, weather, sky, temperature,
  altimeter. The altimeter's own words in parentheses and the remarks (RMK ...) are left out
- the rest word by word: contractions (CONTRACTIONS), runways ("runway two six left"), taxiways in the phonetic
  alphabet ("taxiway echo alpha"), frequencies ("one two six point two two five"), times, heights and distances.
  Letters said as letters (ILS, VOR) stay capitals, so the voice spells them; ordinary words become lower case, as
  a voice may spell a word in capitals. A contraction this doesn't know is left as it is (unknown() lists them)

The digits are said as pilots say them ("tree", "niner"), as in metarmap.spoken.
"""

import re
from typing import Iterable, List, Set, Tuple

from metarmap import metar, spoken

PHONETIC = {
    "A": "Alpha",
    "B": "Bravo",
    "C": "Charlie",
    "D": "Delta",
    "E": "Echo",
    "F": "Foxtrot",
    "G": "Golf",
    "H": "Hotel",
    "I": "India",
    "J": "Juliett",
    "K": "Kilo",
    "L": "Lima",
    "M": "Mike",
    "N": "November",
    "O": "Oscar",
    "P": "Papa",
    "Q": "Quebec",
    "R": "Romeo",
    "S": "Sierra",
    "T": "Tango",
    "U": "Uniform",
    "V": "Victor",
    "W": "Whiskey",
    "X": "X-ray",
    "Y": "Yankee",
    "Z": "Zulu",
}
SIDES = {"L": "left", "R": "right", "C": "center"}
KINDS = {"ATIS": "", "ARR": "arrival", "DEP": "departure", "ARVL": "arrival", "DEPARTURE": "departure"}

# FAA contractions (JO 7340.2) and the shorthand the ATIS texts use, as words. Spelling slips seen in real ATIS
# texts are here too (VICINTY, PERMANANTLY): a voice reads the word right then.
CONTRACTIONS = {
    "ACFT": "aircraft",
    "ADVS": "advise",
    "ADVSD": "advised",
    "ADVY": "advisory",
    "ADVZY": "advisory",
    "AGL": "above ground level",
    "ALT": "altitude",
    "ALTS": "altitudes",
    "AOA": "at or above",
    "AOB": "at or below",
    "APCH": "approach",
    "APCHS": "approaches",
    "APP": "approach",
    "APPS": "approaches",
    "ARPT": "airport",
    "ARR": "arrival",
    "ARRS": "arrivals",
    "ARVNG": "arriving",
    "ASGND": "assigned",
    "ATTN": "attention",
    "AVBL": "available",
    "AVL": "available",
    "BTN": "between",
    "BTWN": "between",
    "BYD": "beyond",
    "CD": "clearance delivery",
    "CL": "centerline",
    "CLDS": "clouds",
    "CLNC": "clearance",
    "CLSD": "closed",
    "CNTR": "center",
    "CTC": "contact",
    "DEP": "departure",
    "DEPS": "departures",
    "DEPG": "departing",
    "DEPTG": "departing",
    "DEPTNG": "departing",
    "EFCT": "effect",
    "EXP": "expect",
    "EXPT": "expect",
    "FLT": "flight",
    "FREQ": "frequency",
    "FREQS": "frequencies",
    "GA": "general aviation",
    "GC": "ground control",
    "GND": "ground",
    "GS": "glide slope",
    "HAZD": "hazardous",
    "IM": "inner marker",
    "INFO": "information",
    "INSTRCNS": "instructions",
    "INT": "intersecting",
    "LAHSO": "land and hold short operations",
    "LDG": "landing",
    "LFT": "left",
    "LGTS": "lights",
    "LNDG": "landing",
    "MM": "middle marker",
    "MOVMT": "movement",
    "MSL": "mean sea level",
    "NA": "not available",
    "NTFY": "notify",
    "MTNS": "mountains",
    "MVMT": "movement",
    "NUM": "numerous",
    "OBSC": "obscured",
    "OBSG": "obscuring",
    "OM": "outer marker",
    "OPR": "operating",
    "OTS": "out of service",
    "PARL": "parallel",
    "PERMANANTLY": "permanently",
    "REIL": "runway end identifier lights",
    "REILS": "runway end identifier lights",
    "RGT": "right",
    "RWY": "runway",
    "RWYS": "runways",
    "RY": "runway",
    "RYS": "runways",
    "SFL": "sequenced flashing lights",
    "SIMUL": "simultaneous",
    "SIMULAPP": "simultaneous approaches",
    "SVC": "service",
    "TFC": "traffic",
    "TWR": "tower",
    "TWY": "taxiway",
    "TWYS": "taxiways",
    "UNUSBL": "unusable",
    "ADJ": "adjacent",
    "ADZ": "advise",
    "AFCT": "aircraft",
    "AZM": "azimuth",
    "BLDG": "building",
    "BLK": "block",
    "BTW": "between",
    "CC": "condition codes",
    "CNTD": "conducted",
    "CNVGG": "converging",
    "CONST": "construction",
    "CTL": "control",
    "CTN": "caution",
    "DLVRY": "delivery",
    "DLVY": "delivery",
    "DP": "departure procedure",
    "EXPC": "expect",
    "FM": "from",
    "FTBAL": "football",
    "HAZUS": "hazardous",
    "HDSRT": "hold short",
    "HLD": "hold",
    "HND": "hundred",
    "HS": "hold short",
    "INVOF": "in the vicinity of",
    "ISNS": "instructions",
    "LGTD": "lighted",
    "MI": "miles",
    "MIN": "minimum",
    "NMRS": "numerous",
    "OBST": "obstruction",
    "OPS": "operations",
    "PAJA": "parachute jumping activity",
    "RDC": "reduce",
    "RLS": "release",
    "RPTD": "reported",
    "RQ": "request",
    "RQRD": "required",
    "SHRT": "short",
    "SPD": "speed",
    "SQK": "squawk",
    "STADM": "stadium",
    "STD": "standard",
    "THRU": "through",
    "THSD": "thousand",
    "TPNDR": "transponder",
    "TRSN": "transition",
    "TXG": "taxiing",
    "TXY": "taxiway",
    "VC": "vicinity",
    "VCNTY": "vicinity",
    "VCTR": "vector",
    "VCTRS": "vectors",
    "VCY": "vicinity",
    "VICINTY": "vicinity",
    "VIS": "visual",
    "WX": "weather",
    "XPECT": "expect",
}
UNITS = {"FT": "feet", "'": "feet", "NM": "nautical miles", "KT": "knots", "KTS": "knots", "SM": "statute miles"}
COMPASS = {
    "N": "north",
    "NNE": "north northeast",
    "NE": "northeast",
    "ENE": "east northeast",
    "E": "east",
    "ESE": "east southeast",
    "SE": "southeast",
    "SSE": "south southeast",
    "S": "south",
    "SSW": "south southwest",
    "SW": "southwest",
    "WSW": "west southwest",
    "W": "west",
    "WNW": "west northwest",
    "NW": "northwest",
    "NNW": "north northwest",
}
# said as letters: kept in capitals, so the voice spells them
LETTERS = {
    "ATC",
    "CPDLC",
    "CVFP",
    "DME",
    "FDC",
    "FSS",
    "GPS",
    "IFR",
    "ILS",
    "LDA",
    "LOC",
    "NDB",
    "RVR",
    "RWSL",
    "SID",
    "TDWR",
    "TFR",
    "UTC",
    "VFR",
    "VOR",
}
# how a few are said, written so a voice says them so
SAY = {"RNAV": "R-NAV", "RNP": "R-N-P", "PAPI": "papi", "VASI": "vasi", "TACAN": "tacan", "LOC": "localizer"}
# said as words, though written in capitals (a voice might spell them otherwise): lower case
WORDS = {"NOTAM", "NOTAMS", "TACAN", "PAPI", "VASI", "RNAV", "RNP", "MALS", "MALSR", "ALSF", "BASH", "LAHSO", "ATIS"}
VOWEL = re.compile(r"[AEIOU]")  # a word without one (CTN, VNY) is a contraction or an identifier: spelled
RUNWAY_WORDS = {"RWY", "RWYS", "RY", "RYS", "RUNWAY", "RUNWAYS"}
TAXIWAY_WORDS = {"TWY", "TWYS", "TXY", "TAXIWAY", "TAXIWAYS", "TAXILANE", "TAXILANES"}
# between the names of a list of runways or taxiways ("BTN D AND E"): the next name is one too
CONNECTORS = {"AND", "OR", "BTN", "BTWN", "BTW", "BETWEEN", "THRU"}
GLUED_RUNWAY = re.compile(r"^(RWY|RY)(?P<designator>\d{1,2}[LRC]?)$")  # RY8R, RWY16R
APPROACH_WORDS = {"RNAV", "GPS", "ILS", "LOC", "VOR", "RNP", "LDA", "NDB"}
# short words of plain English that look like contractions: lower case, not spelled
ENGLISH = {
    "A",
    "AM",
    "AN",
    "AND",
    "ARE",
    "AS",
    "AT",
    "BE",
    "BY",
    "DO",
    "FOR",
    "IF",
    "IN",
    "IS",
    "IT",
    "NO",
    "NOT",
    "OF",
    "OFF",
    "ON",
    "OR",
    "OUT",
    "THE",
    "TO",
    "UP",
    "USE",
    "VIA",
    "WAS",
    "WHO",
    "YOU",
    "ALL",
    "ANY",
    "CAN",
    "HAS",
    "MAY",
    "NEW",
    "NOW",
    "ONE",
    "TWO",
    "SIX",
    "TEN",
    "WET",
    "DRY",
    "ICE",
    "GO",
    "AIR",
    "ARE",
    "BIRD",
    "MID",
    "WILL",
    "WITH",
    "WHEN",
}

HEADER = re.compile(
    r"^\s*(?P<id>[A-Z0-9]{3,4})\s+(?P<kind>ATIS|ARR|DEP|ARVL|DEPARTURE)\s+INFO\s+(?P<letter>[A-Z])\s+"
    r"(?P<time>\d{4})Z?(?P<rest>[^.]*)\.\s*"
)
WIND = re.compile(r"^(?P<dir>\d{3}|VRB)(?P<speed>\d{2,3})(G(?P<gust>\d{2,3}))?KT$")
ALTIMETER = re.compile(r"^A(?P<value>\d{4})$")
VISIBILITY = re.compile(r"^[PM]?\d+(/\d+)?SM$")
DESIGNATOR = re.compile(r"^(?P<number>\d{1,2})(?P<side>[LRC])?$")
NAMED = re.compile(r"^(?P<letters>[A-Z]{1,2})(?P<number>\d{0,4})$")  # a taxiway (A, EA, R10), an area (R2403)
FREQUENCY = re.compile(r"^1[1-3]\d\.\d{1,3}$")
DECIMAL = re.compile(r"^\d*\.\d+$")  # 2.7, .3
TIME = re.compile(r"^(?P<time>\d{4})Z$")
WITH_UNIT = re.compile(r"^(?P<number>\d*\.?\d+)(?P<unit>FT|NM|KTS?|SM|')$")  # 100FT, .3NM, 100' (feet)


def spoken_atis(entries: Iterable[dict], name: str = "", code: str = "", ids: Iterable[str] = ()) -> str:
    """
    One airport's ATIS as text to be spoken: a combined one, or the arrival then the departure ATIS. entries: what
    metarmap.atis has for the airport ({"type", "code", "datis"}); name, code: as for metarmap.spoken. ids: airport
    identifiers to spell when the text names them (KABQ and ABQ, for "KABQ"), e.g. every airport with an ATIS.
    """
    place = spoken.airport_name(name, code)
    order = {"arr": 0, "combined": 1, "dep": 2}
    known = identifiers(list(ids) + [code])
    texts = [expand(e["datis"], place, known) for e in sorted(entries, key=lambda e: order.get(e.get("type"), 1))]
    return " ".join(texts) if texts else f"{place}. No ATIS is available."


def identifiers(codes: Iterable[str]) -> Set[str]:
    """KIAH and IAH for "KIAH": an ATIS names airports by either."""
    found = set()
    for code in codes:
        code = (code or "").upper()
        if code:
            found.add(code)
            if len(code) == 4 and code[0] in "KP":
                found.add(code[1:])
    return found


def expand(text: str, place: str = "", ids: Set[str] = frozenset()) -> str:
    """
    One ATIS text as words (see the module's notes). place: the airport's name to say in the header; ids: airport
    identifiers to spell.
    """
    text = tidy(text)
    sentences = []
    match = HEADER.match(text)
    if match:
        sentences.append(header(match, place))
        text = text[match.end() :]
    body = sentences_of(text)
    if body and looks_like_weather(body[0]):
        sentences += weather_sentences(body.pop(0))
    sentences += [s for s in (sentence(words, ids) for words in body) if s]
    return " ".join(sentences)


def unknown(text: str) -> Set[str]:
    """The contractions expand() leaves as they are (capitals it doesn't know), to find ones worth adding."""
    found = set()
    for word in re.findall(r"\b[A-Z][A-Z]+\b", expand(text)):
        bare = word
        if (
            bare not in CONTRACTIONS
            and bare not in LETTERS
            and bare not in WORDS
            and bare not in ENGLISH
            and bare not in COMPASS
            and bare not in KINDS
            and not VOWEL.search(bare)
        ):
            found.add(bare)
    return found


# ---- pieces ---------------------------------------------------------------------------------------------------


def tidy(text: str) -> str:
    """Spaces and stray punctuation: "RWY 3 ." -> "RWY 3.", ". . ." and "..." -> ".", "BTN TWY, M" kept."""
    text = re.sub(r"\(([A-Z ]+)\)", " ", text)  # the altimeter's own words, said from A3013 instead
    text = re.sub(r"\s*\.(\s*\.)+\s*", ". ", text)  # ". . ." or "...": one sentence's end
    text = re.sub(r"\s*;", ",", text)
    text = re.sub(r"\s+([.,])(?=\s|$)", r"\1", text)  # "RWY 3 ." (not ".3NM", a distance)
    text = re.sub(r",(?=[A-Z0-9])", ", ", text)  # "5L,23R"
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)  # "2,200": one number
    text = re.sub(r",(\s*,)+", ",", text)
    text = re.sub(r"\.\s*,|,\s*\.", ".", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def sentences_of(text: str) -> List[List[str]]:
    """The text's sentences as words: a period ends one when a space or the end follows (not in 132.82)."""
    parts = re.split(r"\.(?=\s|$)", text)
    return [p.split() for p in (part.strip() for part in parts) if p]


def header(match, place: str) -> str:
    kind = KINDS.get(match["kind"], "")
    name = place or spoken.airport_name("", match["id"])
    special = ", special" if "SPECIAL" in match["rest"] else ""
    what = f"{kind} information" if kind else "information"
    return f"{name} {what} {PHONETIC[match['letter']]}, {spoken.digits(match['time'])} Zulu{special}."


def looks_like_weather(words: List[str]) -> bool:
    return any(WIND.match(w) or VISIBILITY.match(w) or ALTIMETER.match(w) for w in words)


def weather_sentences(words: List[str]) -> List[str]:
    """The weather groups ("11007KT 10SM SCT080 BKN250 23/13 A3013 RMK ...") as the AWOS says them."""
    report = metar.parse_raw("ATIS " + " ".join(w.strip(",") for w in words), now=None)  # the remarks are left out
    return [
        s
        for s in (
            spoken.wind(report) if report.wind_speed is not None else None,
            spoken.visibility(report.visibility_sm, report.visibility_more)
            if report.visibility_sm is not None
            else None,
            spoken.weather(report.weather),
            spoken.sky(report) if report.sky_conditions else None,
            spoken.temperature(report) if report.temp_c is not None else None,
            spoken.altimeter(report.altimeter_inhg) if report.altimeter_inhg else None,
        )
        if s
    ]


def sentence(words: List[str], ids: Set[str] = frozenset()) -> str:
    """One sentence of the rest of the ATIS, word by word."""
    out: List[str] = []
    context = ""  # "runway", "taxiway", "approach", "information": what a bare number or letter belongs to
    for i, raw in enumerate(words):
        raw = raw.rstrip(".")
        word, comma = (raw[:-1], ",") if raw.endswith(",") else (raw, "")
        following = words[i + 1].rstrip(",") if i + 1 < len(words) else ""
        said, context = say(word, context, following, ids)
        if said:
            out.append(said + comma)
    text = " ".join(out).strip(" ,")
    return (text[0].upper() + text[1:] + ".") if text else ""


def say(word: str, context: str, following: str, ids: Set[str] = frozenset()) -> Tuple[str, str]:
    """A word as it's spoken, and the context it leaves for the next one."""
    if m := GLUED_RUNWAY.match(word):
        return f"runway {say(m['designator'], 'runway', following, ids)[0]}", "runway"
    if word in RUNWAY_WORDS:
        return CONTRACTIONS.get(word, word.lower()), "runway"
    if word in TAXIWAY_WORDS:
        return CONTRACTIONS.get(word, word.lower()), "taxiway"
    if word in ("INFO", "INFORMATION"):
        return "information", "information"
    if context == "information" and word in PHONETIC:
        return PHONETIC[word], ""
    if context == "approach" and len(word) == 1 and word in PHONETIC:
        return PHONETIC[word], "approach"
    if context == "taxiway" and (m := NAMED.match(word)) and word not in ENGLISH and word not in CONTRACTIONS:
        letters = " ".join(PHONETIC[c] for c in m["letters"])
        return (letters + (f" {spoken.digits(m['number'])}" if m["number"] else "")), "taxiway"
    if m := DESIGNATOR.match(word):
        if m["side"] or context == "runway":
            side = f" {SIDES[m['side']]}" if m["side"] else ""
            return spoken.digits(int(m["number"])) + side, ("runway" if context == "runway" else context)
        return number(word, following), context
    if word.isdigit():
        return number(word, following), context
    if m := TIME.match(word):
        return f"{spoken.digits(m['time'])} Zulu", ""
    if FREQUENCY.match(word) or DECIMAL.match(word):
        return number(word), ""
    if m := WITH_UNIT.match(word):
        return f"{number(m['number'], m['unit'])} {UNITS[m['unit']]}", ""
    if word in CONNECTORS and context in ("runway", "taxiway", "approach"):
        return CONTRACTIONS.get(word, word.lower()), context
    if word in APPROACH_WORDS:
        return SAY.get(word, word if word in LETTERS else word.lower()), "approach"
    if word in COMPASS and len(word) > 1:
        return COMPASS[word], ""
    if word in CONTRACTIONS:
        return CONTRACTIONS[word], ""
    if word in UNITS:
        return UNITS[word], ""
    if word in LETTERS:
        return word, ""
    if word in SAY:
        return SAY[word], ""
    if word == "H/S":
        return "hold short", ""
    for mark in "/-":  # TACAN/AZIMUTH, RNAV/GPS, ASR-9, R2403-B
        if mark in word and all(word.split(mark)):
            return " ".join(say(part, context, "", ids)[0] for part in word.split(mark)), ""
    if (m := NAMED.match(word)) and m["number"]:  # a taxiway named outside "TWY ...": B4, D3
        return f"{' '.join(PHONETIC[c] for c in m['letters'])} {spoken.digits(m['number'])}", context
    if word in ids:
        return word, ""  # an airport: spelled
    if word.isalpha() and word not in WORDS and word not in ENGLISH and not VOWEL.search(word):
        return word, ""  # a contraction or identifier this doesn't know (CTN, VNY): spelled
    return word.lower(), ""


def number(text: str, following: str = "") -> str:
    """A number in the text: a height in feet as the AWOS says heights ("eight hundred"), else digit by digit."""
    if "." in text:
        whole, part = text.split(".")
        return f"{spoken.digits(whole) + ' ' if whole else ''}point {spoken.digits(part)}"
    value = int(text)
    if following in ("FT", "FEET", "MSL", "AGL") and value >= 100 and value % 100 == 0:
        return spoken.altitude(value)
    if following in ("PERCENT",) and value in (100,):
        return "one hundred"
    return spoken.digits(text)
