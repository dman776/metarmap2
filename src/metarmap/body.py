"""
The body of a METAR (everything before RMK), read from the raw text, for what aviationweather.gov's JSON leaves out:
the report type and modifiers (SPECI, AUTO, COR), the wind's variable direction, the lowest visibility, runway visual
range, CAVOK / NSC / NCD, cloud types (CB, TCU), recent weather, wind shear, runway state and the trend forecast
(NOSIG, BECMG, TEMPO). The wind, visibility, weather, clouds, temperatures and altimeter still come from the JSON (or
metar.parse_raw for a mock): they're only recognized here. No I/O: parse() is a pure function of the raw METAR.

Groups it doesn't know (military color states like BLU or YLO1, sea temperature like W12/S2) are in Body.unread, and
not shown, as before. In a trend, color states are left out too (COLOR_STATE), and any other code it can't read is in
Trend.other, which the Decoded tab shows as reported. Numbers are ASCII digits only (re.ASCII): a token with another
digit, like ², is a group it doesn't know. A body that can't be read at all (a bug here) is Body(text=...) with nothing
read, so the Decoded tab shows what it did before.

Sources: WMO Manual on Codes (WMO-No. 306) Vol. I.1, FM 15 METAR and FM 16 SPECI, and its code tables 0366, 0519,
0919 and 1079 for the runway state; ICAO Annex 3, appendix 3, 4.5 (CAVOK) and 4.8 (trend); FMH-1 (2019), chapter 12, for
the US groups: https://www.icams-portal.gov/resources/ofcm/fmh/FMH1/fmh1_2019.pdf
"""

import logging
import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Optional, Tuple

log = logging.getLogger(__name__)

TREND_KINDS = ("NOSIG", "BECMG", "TEMPO")
# report modifiers: AUTO a fully automated report, COR a corrected one (CCA, CCB... the first, second... correction,
# as Canada codes it), RTD a delayed routine one
MODIFIER = re.compile(r"AUTO|COR|CC[A-Z]|RTD", re.ASCII)
# military airfield color states (NATO): BLU, WHT, GRN, YLO1, YLO2, AMB, RED, BLACK before one when the airfield is
# closed for something other than the weather (BLACKBLU), and a + when the next state up is expected (BLU+)
COLOR_STATE = re.compile(r"(?:BLACK)?(?:BLU|WHT|GRN|YLO[12]?|AMB|RED)\+?|BLACK", re.ASCII)
COMPASS_POINTS = {
    "N": "north",
    "NE": "northeast",
    "E": "east",
    "SE": "southeast",
    "S": "south",
    "SW": "southwest",
    "W": "west",
    "NW": "northwest",
}
SIDES = {"L": "left", "C": "center", "R": "right"}

# the runway state (WMO code tables), R24L/290145: deposit 2, extent 9, depth 01, friction 45
DEPOSITS = {  # 0919
    "0": "clear and dry",
    "1": "damp",
    "2": "wet or water patches",
    "3": "rime or frost (normally less than 1 mm deep)",
    "4": "dry snow",
    "5": "wet snow",
    "6": "slush",
    "7": "ice",
    "8": "compacted or rolled snow",
    "9": "frozen ruts or ridges",
    "/": "deposit not reported",
}
# 0519; / (not reported) has no text. 1 is "less than 10%", as WMO words it: WMO-No. 306 code table 0519, and the
# same in its BUFR code table 0 20 087 (https://codes.wmo.int/bufr4/codeflag/0-20-087: "Less than 10% of runway
# covered") and the IWXXM schema WMO publishes ("less than 10%; between 11% and 25%...")
EXTENTS = {
    "1": "covering less than 10%",
    "2": "covering 11-25%",
    "5": "covering 26-50%",
    "9": "covering 51-100%",
    "/": None,
}
DEPTHS = {  # 1079; 01-90 are millimetres; // (not significant or not measurable) has no text
    "00": "less than 1 mm deep",
    "92": "10 cm deep",
    "93": "15 cm deep",
    "94": "20 cm deep",
    "95": "25 cm deep",
    "96": "30 cm deep",
    "97": "35 cm deep",
    "98": "40 cm or more deep",
    # WMO: runway(s) non-operational due to snow, slush, ice, large drifts or runway clearance, but depth not reported
    "99": "runway not operational (snow, slush, ice, drifts or clearance), depth not reported",
    "//": None,
}
BRAKING = {  # 0366; 01-90 are a friction coefficient (28: 0.28); // (not reported) has no text
    "91": "braking action poor",
    "92": "braking action medium to poor",
    "93": "braking action medium",
    "94": "braking action medium to good",
    "95": "braking action good",
    "99": "braking figures unreliable",
    "//": None,
}

_RUNWAY = r"(\d{2}[LCR]?)"
_HHMM = r"(?:[01]\d|2[0-3])[0-5]\d|2400"
_WIND = re.compile(r"(\d{3}|VRB|///)(\d{2,3}|//)(?:G(\d{2,3}))?(KT|MPS|KMH)", re.ASCII)
_WIND_VARIES = re.compile(r"(\d{3})V(\d{3})", re.ASCII)
_METRES = re.compile(r"(\d{4})(NDV)?", re.ASCII)
_LOWEST = re.compile(r"(\d{4})(N|NE|E|SE|S|SW|W|NW|//)?", re.ASCII)
_MILES = re.compile(r"([MP])?(\d+|\d+/[1-9]\d*)SM", re.ASCII)
_FRACTION_MILES = re.compile(r"[1-9]\d*/[1-9]\d*SM", re.ASCII)
# RVR: R28/2400FT, R13R/1200VP6000FT, R16/2600V3500FT/U (US and Canada, feet); R24/0600N, R24/0900V1600D (metres)
_RVR = re.compile(rf"R{_RUNWAY}/(?:([MP]?)(\d{{4}})(?:V([MP]?)(\d{{4}}))?(FT)?(?:/?([UDN]))?|////)", re.ASCII)
_STATE = re.compile(rf"R{_RUNWAY}/(?:([0-9/])([0-9/])(\d\d|//)(\d\d|//)|CLRD(\d\d|//))", re.ASCII)
_CLOUD = re.compile(r"(FEW|SCT|BKN|OVC)(\d{3}|///)(CB|TCU|///)?", re.ASCII)
_UNKNOWN_CLOUD = re.compile(r"//////(?:CB|TCU|///)?|///(?:CB|TCU)", re.ASCII)  # automated: cover and/or height unknown
_VERTICAL = re.compile(r"VV(\d{3}|///)", re.ASCII)
_TEMPS = re.compile(r"(?:M?\d{2}|//)/(?:M?\d{2}|//)?", re.ASCII)
_ALTIMETER = re.compile(r"[AQ](?:\d{4}|////)", re.ASCII)
_DIGITS = re.compile(r"[0-9]+")  # ASCII digits: str.isdigit() is true for ², which int() rejects
_TIME = re.compile(rf"(FM|TL|AT)({_HHMM})", re.ASCII)


@dataclass(frozen=True)
class RunwayRange:
    """One runway visual range group: R28/2400FT, R24/0550V0800U, R24/////."""

    runway: str  # "28", "24L"
    low: Optional[int] = None  # feet or metres; None when not available (R24/////)
    low_bound: str = ""  # "M": less than, "P": more than
    high: Optional[int] = None  # when it varies: the highest
    high_bound: str = ""
    feet: bool = False  # FT; metres otherwise
    trend: Optional[str] = None  # "U" up, "D" down, "N" no change


@dataclass(frozen=True)
class RunwayState:
    """One runway state group (WMO): R24L/290145, R88/CLRD70, R/SNOCLO. Codes are as reported."""

    code: str  # the group as reported
    runway: Optional[str]  # "24L"; "88" all runways, "99" repeated from the last report; None for R/SNOCLO
    deposit: Optional[str] = None  # one character of DEPOSITS
    extent: Optional[str] = None  # EXTENTS
    depth: Optional[str] = None  # two characters, DEPTHS (or 01-90 mm)
    braking: Optional[str] = None  # BRAKING (or 01-90: a friction coefficient)
    cleared: bool = False  # CLRD: the deposit has been cleared
    closed: bool = False  # SNOCLO: closed by snow


@dataclass(frozen=True)
class Wind:
    direction: Optional[int]  # degrees; None for VRB
    speed: int
    gust: Optional[int] = None
    unit: str = "KT"  # KT, MPS or KMH


@dataclass(frozen=True)
class Visibility:
    metres: Optional[int] = None  # 9999: 10 km or more
    miles: Optional[float] = None
    more: bool = False  # P6SM, or 9999


@dataclass(frozen=True)
class Cloud:
    cover: str  # FEW, SCT, BKN, OVC; VV for an obscured sky; "" when not known (//////CB)
    base_ft: Optional[int] = None  # None when not reported (///)
    kind: Optional[str] = None  # CB or TCU


@dataclass(frozen=True)
class Trend:
    """
    The trend forecast at the end of a METAR (the next 2 hours): NOSIG, or a BECMG or TEMPO group and what it says
    will change, each item as the METAR body codes it. Items it can't read are kept, as reported, in other.
    """

    kind: str  # NOSIG, BECMG or TEMPO
    times: Tuple[Tuple[str, str], ...] = ()  # (FM, TL or AT, hhmm)
    wind: Optional[Wind] = None
    visibility: Optional[Visibility] = None
    cavok: bool = False
    weather: Tuple[str, ...] = ()  # weather codes, e.g. "-RA", "BR"
    no_significant_weather: bool = False  # NSW
    clouds: Tuple[Cloud, ...] = ()
    no_significant_cloud: bool = False  # NSC
    other: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Body:
    """
    What a METAR's body says that the JSON doesn't. Values the body leaves out are None (or empty, or False); an empty
    report is Body().
    """

    text: str = ""  # the body as reported, without the remarks
    report_type: Optional[str] = None  # METAR or SPECI; None when the text doesn't start with either
    modifiers: Tuple[str, ...] = ()  # AUTO, COR, CCA..., RTD, in the order reported
    wind_varies: Optional[Tuple[int, int]] = None  # 350V050: from 350° to 050° (clockwise)
    lowest_visibility_m: Optional[int] = None  # 0400NW, or 0700 after the visibility: metres
    lowest_visibility_toward: Optional[str] = None  # its direction: N, NE...; None when not given
    no_directional_variation: bool = False  # 9999NDV: the station can't tell visibility by direction
    runway_ranges: Tuple[RunwayRange, ...] = ()
    sky: Optional[str] = None  # CAVOK, NSC or NCD when reported
    # the cloud groups, lowest first, with their CB or TCU; one of unknown cover and height (//////CB) only with a type
    clouds: Tuple[Cloud, ...] = ()
    # RERA, RESHSN: "RA", "SHSN": seen since the last routine report (or in the last hour, if that's shorter: ICAO
    # Annex 3, appendix 3, 4.8.1.1), not now
    recent_weather: Tuple[str, ...] = ()
    wind_shear: Tuple[str, ...] = ()  # runways, "20", "24L", or "ALL"
    runway_states: Tuple[RunwayState, ...] = ()
    trends: Tuple[Trend, ...] = ()
    unread: Tuple[str, ...] = ()  # the groups it doesn't know, as reported (not shown)


_LOGGED = set()  # the raw bodies a parse failure was logged for: once each


def parse(raw) -> Body:
    """
    The body of a raw METAR (before RMK); Body() when it's empty. Never raises: if reading it fails (a bug), it's
    Body(text=...) with nothing read, and the failure is logged once per body.
    """
    tokens = str(raw or "").replace("=", " ").split()
    if "RMK" in tokens:
        tokens = tokens[: tokens.index("RMK")]
    text = " ".join(tokens)
    if not tokens:
        return Body()
    try:
        return _parse(tokens, text)
    except Exception as e:
        if text not in _LOGGED and len(_LOGGED) < 1000:
            _LOGGED.add(text)
            log.warning(f"Could not read the METAR's body: {e!r} raw: {raw}")
        return Body(text=text)


def _parse(tokens, text) -> Body:
    found = {"text": text}
    modifiers, ranges, clouds, recent, shear, states, trends, unread = [], [], [], [], [], [], [], []
    i = 0
    if tokens[0] in ("METAR", "SPECI"):
        found["report_type"] = tokens[0]
        i = 1
    if i < len(tokens) and tokens[i] == "COR":  # WMO's place for it: METAR COR LFPG ...
        modifiers.append("COR")
        i += 1
    if i < len(tokens) and re.fullmatch(r"[A-Z][A-Z0-9]{2,3}", tokens[i], re.ASCII):  # the station
        i += 1
    if i < len(tokens) and re.fullmatch(r"\d{6}Z", tokens[i], re.ASCII):
        i += 1

    previous = None  # what the token before was: "wind", "visibility"
    while i < len(tokens):
        t = tokens[i]
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        i += 1
        kind = None
        if t in TREND_KINDS:
            trends.append(_trend(t, tokens, i))
            while i < len(tokens) and tokens[i] not in TREND_KINDS:
                i += 1
            continue
        if MODIFIER.fullmatch(t):
            modifiers.append(t)
        elif _WIND.fullmatch(t):
            kind = "wind"
        elif _WIND_VARIES.fullmatch(t) and previous == "wind" and _varies(t):
            found["wind_varies"] = _varies(t)
        elif _METRES.fullmatch(t) and previous not in ("visibility", "lowest"):
            kind = "visibility"
            if t.endswith("NDV"):
                found["no_directional_variation"] = True
        elif _LOWEST.fullmatch(t) and previous == "visibility":
            kind = "lowest"
            match = _LOWEST.fullmatch(t)
            found["lowest_visibility_m"] = int(match.group(1))
            found["lowest_visibility_toward"] = match.group(2) if match.group(2) in COMPASS_POINTS else None
        elif t in ("////", "////SM") and previous != "visibility":  # visibility not reported (automated)
            kind = "visibility"
        elif _DIGITS.fullmatch(t) and _FRACTION_MILES.fullmatch(nxt):  # 1 1/2SM
            i += 1
            kind = "visibility"
        elif _MILES.fullmatch(t):
            kind = "visibility"
        elif t == "CAVOK":
            found["sky"] = t
        elif _RVR.fullmatch(t) and _runway(_RVR.fullmatch(t).group(1)):
            ranges.append(_range(_RVR.fullmatch(t)))
        elif _STATE.fullmatch(t) or t in ("R/SNOCLO", "SNOCLO"):
            states.append(_state(t))
        elif t in ("//", "RE//") or _weather_group(t):  # //: weather not observed (automated), RE//: recent weather
            pass
        elif t.startswith("RE") and _recent(t[2:]):
            recent.append(t[2:])
        elif _CLOUD.fullmatch(t):
            match = _CLOUD.fullmatch(t)
            base, cloud_kind = match.group(2), match.group(3)
            clouds.append(
                Cloud(
                    match.group(1),
                    int(base) * 100 if _DIGITS.fullmatch(base) else None,
                    cloud_kind if cloud_kind != "///" else None,
                )
            )
        elif _UNKNOWN_CLOUD.fullmatch(t):  # //////CB: kept for its type; ////// says nothing
            if t.endswith(("CB", "TCU")):
                clouds.append(Cloud("", None, t[-3:].lstrip("/")))
        elif _VERTICAL.fullmatch(t) or t in ("CLR", "SKC"):
            pass
        elif t in ("NSC", "NCD"):
            found["sky"] = t
        elif _TEMPS.fullmatch(t) or _ALTIMETER.fullmatch(t):
            pass
        elif t == "WS" and _shear(tokens, i):
            runway, used = _shear(tokens, i)
            shear.append(runway)
            i += used
        else:
            unread.append(t)
        previous = kind
    return Body(
        **found,
        modifiers=tuple(modifiers),
        runway_ranges=tuple(ranges),
        clouds=tuple(clouds),
        recent_weather=tuple(recent),
        wind_shear=tuple(shear),
        runway_states=tuple(states),
        trends=tuple(trends),
        unread=tuple(unread),
    )


def _weather_group(code):
    """decode.parse_weather_group: the METAR key's weather codes (imported here: decode imports this module)."""
    from metarmap.decode import parse_weather_group

    return parse_weather_group(code)


def _recent(code):
    """Whether code (after RE) is a recent weather: a weather group with no intensity and not in the vicinity."""
    group = _weather_group(code) if code[:1] not in "+-" else None
    return bool(group) and not group.vicinity


def _varies(text) -> Optional[Tuple[int, int]]:
    """350V050 as (350, 50); None if a direction isn't one (over 360)."""
    low, high = int(text[:3]), int(text[4:])
    return (low, high) if low <= 360 and high <= 360 else None


def _runway(code) -> bool:
    """Whether a runway designator is one: 01 to 36, with L, C or R."""
    return 1 <= int(code[:2]) <= 36


def _range(match) -> RunwayRange:
    runway, low_bound, low, high_bound, high, feet, trend = match.groups()
    if low is None:  # R24/////
        return RunwayRange(runway)
    return RunwayRange(
        runway,
        int(low),
        low_bound,
        int(high) if high else None,
        high_bound if high else "",
        feet == "FT",
        trend,
    )


def _state(text) -> RunwayState:
    if text in ("R/SNOCLO", "SNOCLO"):
        return RunwayState(text, None, closed=True)
    match = _STATE.fullmatch(text)
    runway, deposit, extent, depth, braking, cleared = match.groups()
    if cleared is not None:
        return RunwayState(text, runway, braking=cleared, cleared=True)
    return RunwayState(text, runway, deposit, extent, depth, braking)


def _shear(tokens, i):
    """
    The runway of a wind shear group starting after WS at tokens[i], and how many tokens it takes: WS R20 or
    WS RWY25 is ("20", 1); WS ALL RWY is ("ALL", 2). None if it isn't one.
    """
    nxt = tokens[i] if i < len(tokens) else ""
    match = re.fullmatch(rf"(?:R|RWY){_RUNWAY}", nxt, re.ASCII)
    if match and _runway(match.group(1)):
        return match.group(1), 1
    if nxt == "ALL" and i + 1 < len(tokens) and tokens[i + 1] == "RWY":
        return "ALL", 2
    return None


def _trend(kind, tokens, i) -> Trend:
    """The trend group `kind` (NOSIG, BECMG, TEMPO) with the tokens from i up to the next one."""
    found = {}
    times, weather, clouds, other = [], [], [], []
    while i < len(tokens) and tokens[i] not in TREND_KINDS:
        t = tokens[i]
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        i += 1
        wind, miles = _WIND.fullmatch(t), _MILES.fullmatch(t)
        cloud, vertical = _CLOUD.fullmatch(t), _VERTICAL.fullmatch(t)
        if _TIME.fullmatch(t) and not _given(times, t[:2]):
            times.append((t[:2], t[2:]))
        elif wind and wind.group(1) != "///" and wind.group(2) != "//" and "wind" not in found:
            direction = None if wind.group(1) == "VRB" else int(wind.group(1))
            if direction is not None and direction > 360:
                other.append(t)
                continue
            gust = int(wind.group(3)) if wind.group(3) else None
            found["wind"] = Wind(direction, int(wind.group(2)), gust, wind.group(4))
        elif re.fullmatch(r"\d{4}", t, re.ASCII) and "visibility" not in found:
            found["visibility"] = Visibility(metres=int(t), more=t == "9999")
        elif _DIGITS.fullmatch(t) and _FRACTION_MILES.fullmatch(nxt) and "visibility" not in found:
            found["visibility"] = Visibility(miles=float(int(t) + Fraction(nxt[:-2])))
            i += 1
        elif miles and "visibility" not in found:
            found["visibility"] = Visibility(miles=float(Fraction(miles.group(2))), more=miles.group(1) == "P")
        elif t == "CAVOK":
            found["cavok"] = True
        elif t == "NSW":
            found["no_significant_weather"] = True
        elif _weather_group(t):
            weather.append(t)
        elif cloud and _DIGITS.fullmatch(cloud.group(2)):
            cloud_kind = cloud.group(3) if cloud.group(3) in ("CB", "TCU") else None
            clouds.append(Cloud(cloud.group(1), int(cloud.group(2)) * 100, cloud_kind))
        elif vertical:
            clouds.append(Cloud("VV", int(vertical.group(1)) * 100 if _DIGITS.fullmatch(vertical.group(1)) else None))
        elif t == "NSC":
            found["no_significant_cloud"] = True
        elif COLOR_STATE.fullmatch(t):  # a military color state: not shown, as in the body
            pass
        else:
            other.append(t)
    return Trend(kind, times=tuple(times), weather=tuple(weather), clouds=tuple(clouds), other=tuple(other), **found)


def _given(times, prefix) -> bool:
    """Whether a time of this kind (FM, TL, AT) was already given: a second one isn't read."""
    return any(kind == prefix for kind, _ in times)
