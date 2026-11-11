"""
The remarks of a METAR (everything after RMK), read from the raw text: aviationweather.gov's JSON has only the
sea-level pressure and precipitation, so fetched and mock reports are read the same way. Groups follow the FAA's
METAR key (FMH-1, chapter 12). No I/O: parse() is a pure function of the raw METAR.

Lightning is read (OCNL LTGICCG E AND SW, FRQ LTGICCG OHD-S-SW AND DSNT W: Remarks.lightning). Thunderstorm or
cloud locations (TS E MOV NE, CB, VIRGA...) aren't read yet: like any group it doesn't know, they're kept as they are
in Remarks.other. A report whose remarks can't be read at all (a bug here) has them all in Remarks.other, so the
Decoded tab still shows.

Sources: FMH-1 (2019), chapter 12 (lightning: 12.7.1 j and table 12-5; locations: 12.7 c and 8.4.1):
https://www.icams-portal.gov/resources/ofcm/fmh/FMH1/fmh1_2019.pdf; the ASOS
User's Guide: https://www.weather.gov/media/asos/aum-toc.pdf; NWS Snow Measurement Guidelines:
https://www.weather.gov/media/coop/Snow_Measurement_Guidelines-2014.pdf
"""

import logging
import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Optional, Tuple

log = logging.getLogger(__name__)

# 5appp: how the pressure changed over the last 3 hours (WMO code 0200); a 0-3 is up, 4 the same, 5-8 down
TENDENCIES = {
    0: "rising, then falling",
    1: "rising, then steady",
    2: "rising steadily",
    3: "falling or steady, then rising",
    4: "steady",
    5: "falling, then rising",
    6: "falling, then steady",
    7: "falling steadily",
    8: "steady or rising, then falling",
}
# xxxxNO: a sensor out of service, as it's named on the Decoded tab
SENSORS = {
    "PWINO": "precipitation identifier",
    "PNO": "precipitation gauge",
    "FZRANO": "freezing rain sensor",
    "TSNO": "lightning detector",
    "RVRNO": "runway visual range",
    "VISNO": "visibility sensor",
    "CHINO": "ceiling sensor",
}
# lightning (FMH-1 12.7.1 j, Frequency_LTG(type)_[LOC]): how often (table 12-5), what kind, how far and which way
FREQUENCIES = {"OCNL": "occasional", "FRQ": "frequent", "CONS": "continuous"}  # <1, about 1-6, >6 flashes a minute
LIGHTNING_TYPES = {"IC": "in-cloud", "CC": "cloud-to-cloud", "CG": "cloud-to-ground", "CA": "cloud-to-air"}
# 12.7 c and 8.4.1: none is at the station (within 5 statute miles), VC 5 to 10, DSNT beyond 10; an automated station
# reports only LTG DSNT (10 to 30 nautical miles), its nearer lightning being TS or VCTS in the body (12.7.1 j 2)
DISTANCES = {"OHD": "overhead", "VC": "in the vicinity", "DSNT": "distant"}

# weather that can begin and end (RAB09E27): precipitation with an optional descriptor (SHRA), or a thunderstorm
# alone (TSB0159E30; FMH-1 12.7.1 k and l). A descriptor alone (SHB10, MIB10) isn't one: it's left unread
_PRECIP = r"(?:DZ|RA|SN|SG|IC|PL|GR|GS|UP)"
_WX = rf"(?:(?:MI|PR|BC|DR|BL|SH|TS|FZ)?{_PRECIP}+|TS)"
_HH, _MM = r"(?:[01]\d|2[0-3])", r"[0-5]\d"  # a time's hour and minute: RAB99 or WSHFT 2460 isn't read
_TIMES = rf"(?:[BE]{_HH}?{_MM})+"  # B or E with mm or hhmm
# statute miles: "1 1/2", "1/2", "3"; never a "1/0", nor the 1 of a "1 1/0"
_VIS = r"\d+ \d+/[1-9]\d*|\d+/[1-9]\d*|\d+(?! \d+/)"
_END = r"(?=\s|$)"
# a lightning group's places: directions, points of the compass (clockwise), a range of them (NE-SE, SE-S-SW,
# NW THRU SE), a list of those (E AND SW; DSNT S SW W, as manual stations write it) or ALQDS (all quadrants); after a
# distance or not (at the station); more than one place with AND or not (S-SW DSNT W, OHD-NE AND DSNT SW: overhead
# and northeast, distant southwest). Only the first place can be without a distance, so a list is read one way
# A bare LTG isn't one when a distance or ALQDS follows it that couldn't be read (LTG DSNT5 W, LTG VCY): that's not
# lightning at the station, so it stays in Other remarks and doesn't flash the pixel
_POINT = r"(?:N[EW]?|S[EW]?|E|W)"
_RANGE = rf"{_POINT}(?:(?:-| THRU ){_POINT})*"
_DIRECTIONS = rf"ALQDS|{_RANGE}(?:(?: AND | ){_RANGE})*"
_FAR = rf"(?:OHD|VC|DSNT)(?:[ -](?:{_DIRECTIONS}))?"
_PLACES = rf"(?:{_FAR}|{_DIRECTIONS})(?:(?: AND | ){_FAR})*"
GROUPS = [
    (name, re.compile(pattern + _END))
    for name, pattern in (
        # AO1: automated, can't tell rain from snow; AO2: can. A: augmented by an observer. A02 (a zero for the O)
        # is a typo seen in real reports
        ("station", r"A[O0]([12])(A?)"),
        ("slp_missing", r"SLPNO"),
        ("slp", r"SLP(\d{3})"),
        ("temps", r"T([01])(\d{3})(?:([01])(\d{3}))?"),
        ("hourly", r"P(\d{4}|////)"),
        ("precip_6", r"6(\d{4}|////)"),
        ("precip_24", r"7(\d{4}|////)"),
        ("max_6", r"1([01])(\d{3})"),
        ("min_6", r"2([01])(\d{3})"),
        ("extremes_24", r"4([01])(\d{3})([01])(\d{3})"),
        ("tendency", r"5([0-8])(\d{3})"),
        ("ice", r"I([136])(\d{3})"),
        ("snow_depth", r"4/(\d{3})"),
        ("snowfall", r"931(\d{3})"),
        ("snow_water", r"933(\d{3})"),
        ("pressure", r"PRES(RR|FR)"),
        ("peak_wind", rf"PK WND (\d{{3}})(\d{{2,3}})/({_HH})?({_MM})"),
        ("wind_shift", rf"WSHFT ({_HH})?({_MM})( FROPA)?"),
        ("vis_at", rf"(TWR|SFC) VIS ({_VIS})"),
        ("vis_varies", rf"VIS ({_VIS})V({_VIS})"),
        ("cig_varies", r"CIG (\d{3})V(\d{3})"),
        ("lightning", rf"(?:(OCNL|FRQ|CONS) )?LTG((?:IC|CC|CG|CA)*)(?: ({_PLACES})|(?! (?:OHD|VC|DSNT|ALQDS)))"),
        ("began_ended", rf"(?:{_WX}{_TIMES})+"),
        ("sensor", r"(PWINO|PNO|FZRANO|TSNO|RVRNO|VISNO|CHINO)(?: (RWY\d{2}[LCR]?))?"),
        ("no_speci", r"NOSPECI"),
        ("maintenance", r"\$"),
    )
]
_EVENT = re.compile(rf"({_WX})({_TIMES})")
_TIME = re.compile(rf"([BE])({_HH}?{_MM})")
_LIGHTNING = dict(GROUPS)["lightning"]


@dataclass(frozen=True)
class Amount:
    """An amount of precipitation (P, 6 or 7 group) or ice accretion (I group) over some hours."""

    hours: Optional[int]  # 1, 3, 6 or 24; None for a 6 group in a report not at 3 or 6 hours past 00Z
    inches: Optional[float]  # 0.0 for a trace (less than 0.01 in); None when it couldn't be measured (////)


@dataclass(frozen=True)
class PressureTendency:
    """5appp: how the pressure changed over the last 3 hours."""

    character: int  # 0-8, TENDENCIES
    change_hpa: float  # signed: up for a 0-3, down for a 5-8


@dataclass(frozen=True)
class PeakWind:
    direction: int  # degrees
    speed_kt: int
    hour: Optional[int]  # UTC; None when only the minute is given and the report's time isn't known
    minute: int


@dataclass(frozen=True)
class WindShift:
    hour: Optional[int]  # as PeakWind's
    minute: int
    frontal_passage: bool = False  # FROPA


@dataclass(frozen=True)
class WeatherEvent:
    """One begin or end time of a group like RAB09E27 (RA began at :09, ended at :27)."""

    weather: str  # e.g. "RA", "FZRA", "SHSN", "TS"
    began: bool  # False: ended
    hour: Optional[int]  # as PeakWind's
    minute: int


@dataclass(frozen=True)
class Place:
    """Where lightning is: how far, and which way. Codes are as reported."""

    distance: Optional[str] = None  # DISTANCES: OHD, VC or DSNT; None: at the station
    # each a point, ("E",), or a range, clockwise: ("NE", "SE") for NE-SE or NE THRU SE, ("SE", "S", "SW") for SE-S-SW
    directions: Tuple[Tuple[str, ...], ...] = ()
    all_quadrants: bool = False  # ALQDS


@dataclass(frozen=True)
class Lightning:
    """
    One lightning group (Frequency_LTG(type)_[LOC]): OCNL LTGICCG E AND SW is
    Lightning("OCNL", ("IC", "CG"), (Place(None, (("E",), ("SW",))),)). What it leaves out is None (or empty).
    """

    frequency: Optional[str] = None  # FREQUENCIES: OCNL, FRQ or CONS
    types: Tuple[str, ...] = ()  # LIGHTNING_TYPES, in the order reported: IC, CC, CG, CA
    places: Tuple[Place, ...] = ()  # in the order reported; none: at the station

    @property
    def at_station(self) -> bool:
        """Any at, over or near the station (no place, or one with no distance, OHD or VC): not only distant (DSNT)."""
        return not self.places or any(place.distance != "DSNT" for place in self.places)


@dataclass(frozen=True)
class Remarks:
    """
    What a METAR's remarks say. Values the remarks leave out are None (or empty, or False); a report with no RMK
    has Remarks().
    """

    text: str = ""  # the remarks as reported, without RMK
    station_type: Optional[str] = None  # AO1, AO2, AO1A or AO2A
    sea_level_pressure_hpa: Optional[float] = None
    sea_level_pressure_missing: bool = False  # SLPNO
    temp_c: Optional[float] = None  # the T group: to a tenth of a degree
    dewpoint_c: Optional[float] = None
    max_temp_6h_c: Optional[float] = None  # 1snnn / 2snnn
    min_temp_6h_c: Optional[float] = None
    max_temp_24h_c: Optional[float] = None  # 4snnnsnnn
    min_temp_24h_c: Optional[float] = None
    precipitation: Tuple[Amount, ...] = ()  # in the order reported
    ice_accretion: Tuple[Amount, ...] = ()  # I1nnn, I3nnn, I6nnn
    snow_depth_in: Optional[int] = None  # 4/sss; 0 for a trace (less than half an inch)
    snowfall_6h_in: Optional[float] = None  # 931sss; 0.0 for a trace (less than 0.1 in)
    snow_water_in: Optional[float] = None  # 933rrr: water equivalent of the snow on the ground; 0.0 for a trace
    pressure_tendency: Optional[PressureTendency] = None
    pressure_change: Optional[str] = None  # "rising rapidly" (PRESRR) or "falling rapidly" (PRESFR)
    peak_wind: Optional[PeakWind] = None
    wind_shift: Optional[WindShift] = None
    tower_visibility_sm: Optional[float] = None
    surface_visibility_sm: Optional[float] = None
    variable_visibility_sm: Optional[Tuple[float, float]] = None  # VIS 1/2V2: lowest, highest
    variable_ceiling_ft: Optional[Tuple[int, int]] = None  # CIG 005V010
    events: Tuple[WeatherEvent, ...] = ()  # in the order reported
    lightning: Tuple[Lightning, ...] = ()  # in the order reported
    sensors_out: Tuple[str, ...] = ()  # the codes, with a location if given: "TSNO", "VISNO RWY06"
    no_speci: bool = False  # NOSPECI: a manual station that doesn't send special reports
    maintenance: bool = False  # $: the station needs maintenance
    other: Tuple[str, ...] = ()  # what isn't read, as reported: each run of groups between ones that are


_LOGGED = set()  # the raw remarks a parse failure was logged for: once each


def parse(raw) -> Remarks:
    """
    The remarks of a raw METAR; Remarks() when it has none. Never raises: if reading them fails (a bug), they're all
    kept as Remarks.other, as reported, and the failure is logged once per remarks text.
    """
    tokens = str(raw or "").replace("=", " ").split()
    if "RMK" not in tokens:
        return Remarks()
    at = tokens.index("RMK")
    text = " ".join(tokens[at + 1 :])
    try:
        return _parse(tokens[:at], text)
    except Exception as e:
        if text not in _LOGGED and len(_LOGGED) < 1000:
            _LOGGED.add(text)
            log.warning(f"Could not read the remarks: {e!r} raw: {raw}")
        return Remarks(text=text, other=(text,) if text else ())


def _parse(body, text) -> Remarks:
    """parse() of the tokens before RMK and the remarks text after it."""
    observed = next((t for t in body if re.fullmatch(r"\d{2}" + _HH + _MM + "Z", t)), None)
    obs = (int(observed[2:4]), int(observed[4:6])) if observed else None  # a report time like 112460Z isn't one

    found = {"text": text}
    precipitation, ice, events, lightning, sensors, other, run = [], [], [], [], [], [], []
    pos = 0
    while pos < len(text):
        name, match = _group_at(text, pos)
        if match is None:
            end = text.find(" ", pos)
            end = len(text) if end < 0 else end
            run.append(text[pos:end])
            pos = end + 1
            continue
        if run:
            other.append(" ".join(run))
            run = []
        pos = match.end() + 1
        g = match.groups()
        if name == "station":
            found["station_type"] = f"AO{g[0]}{g[1]}"
        elif name == "slp_missing":
            found["sea_level_pressure_missing"] = True
        elif name == "slp":
            found["sea_level_pressure_hpa"] = sea_level_pressure(g[0])
        elif name == "temps":
            found["temp_c"] = _tenths(g[0], g[1])
            if g[2]:
                found["dewpoint_c"] = _tenths(g[2], g[3])
        elif name in ("hourly", "precip_6", "precip_24"):
            hours = {"hourly": 1, "precip_24": 24}.get(name) or _synoptic_hours(obs)
            precipitation.append(Amount(hours, None if g[0] == "////" else int(g[0]) / 100))
        elif name == "max_6":
            found["max_temp_6h_c"] = _tenths(*g)
        elif name == "min_6":
            found["min_temp_6h_c"] = _tenths(*g)
        elif name == "extremes_24":
            found["max_temp_24h_c"], found["min_temp_24h_c"] = _tenths(g[0], g[1]), _tenths(g[2], g[3])
        elif name == "tendency":
            character = int(g[0])
            sign = 1 if character < 4 else -1 if character > 4 else 0
            found["pressure_tendency"] = PressureTendency(character, sign * int(g[1]) / 10)
        elif name == "ice":
            ice.append(Amount(int(g[0]), int(g[1]) / 100))
        elif name == "snow_depth":
            found["snow_depth_in"] = int(g[0])
        elif name == "snowfall":
            found["snowfall_6h_in"] = int(g[0]) / 10
        elif name == "snow_water":
            found["snow_water_in"] = int(g[0]) / 10
        elif name == "pressure":
            found["pressure_change"] = "rising rapidly" if g[0] == "RR" else "falling rapidly"
        elif name == "peak_wind":
            found["peak_wind"] = PeakWind(int(g[0]), int(g[1]), *_clock(g[2], g[3], obs))
        elif name == "wind_shift":
            found["wind_shift"] = WindShift(*_clock(g[0], g[1], obs), frontal_passage=bool(g[2]))
        elif name == "vis_at":
            found["tower_visibility_sm" if g[0] == "TWR" else "surface_visibility_sm"] = _miles(g[1])
        elif name == "vis_varies":
            found["variable_visibility_sm"] = (_miles(g[0]), _miles(g[1]))
        elif name == "cig_varies":
            found["variable_ceiling_ft"] = (int(g[0]) * 100, int(g[1]) * 100)
        elif name == "began_ended":
            for event in _EVENT.finditer(match.group(0)):
                for kind, time in _TIME.findall(event.group(2)):
                    hh, mm = (time[:2], time[2:]) if len(time) == 4 else (None, time)
                    events.append(WeatherEvent(event.group(1), kind == "B", *_clock(hh, mm, obs)))
        elif name == "lightning":
            lightning.append(_lightning(g))
        elif name == "sensor":
            sensors.append(" ".join(t for t in g if t))
        elif name == "no_speci":
            found["no_speci"] = True
        elif name == "maintenance":
            found["maintenance"] = True
    if run:
        other.append(" ".join(run))
    return Remarks(
        **found,
        precipitation=tuple(precipitation),
        ice_accretion=tuple(ice),
        events=tuple(events),
        lightning=tuple(lightning),
        sensors_out=tuple(sensors),
        other=tuple(other),
    )


def lightning_groups(raw, found: Optional[Remarks] = None) -> Tuple[Lightning, ...]:
    """
    The lightning groups of a raw METAR: its remarks' (found: parse(raw), if it's been read already). When they have
    none and there's an LTG in the report outside them (a mock typed without RMK, or remarks that couldn't be read),
    the groups found anywhere in it. () when there's none. Never raises, as parse().
    """
    found = parse(raw) if found is None else found
    if found.lightning or "LTG" not in str(raw or ""):
        return found.lightning
    text = " ".join(str(raw).replace("=", " ").split())
    groups, end = [], 0
    try:
        for pos in [0] + [n + 1 for n, c in enumerate(text) if c == " "]:  # where each word starts
            match = _LIGHTNING.match(text, pos) if pos >= end else None
            if match:
                groups.append(_lightning(match.groups()))
                end = match.end()
    except Exception as e:
        if text not in _LOGGED and len(_LOGGED) < 1000:
            _LOGGED.add(text)
            log.warning(f"Could not read the lightning: {e!r} raw: {raw}")
        return ()
    return tuple(groups)


def lightning_at_station(groups) -> bool:
    """
    Whether lightning groups have any at, over or near the station (no distance, OHD or VC): the Report's lightning
    flag, which flickers the pixel. Distant lightning only (DSNT, beyond 10 miles) doesn't count.
    """
    return any(group.at_station for group in groups)


def _lightning(g) -> Lightning:
    """A Lightning of the lightning pattern's groups: frequency, types (ICCG) and places."""
    frequency, types, text = g
    kinds = tuple(dict.fromkeys(types[i : i + 2] for i in range(0, len(types), 2)))  # LTGICIC: in-cloud, once
    places, through = [], False
    for token in (text or "").split():
        head, _, rest = token.partition("-")  # OHD-S-SW: overhead, and south through southwest
        if head in DISTANCES or not places:
            distance = head if head in DISTANCES else None
            places.append({"distance": distance, "directions": [], "all_quadrants": False})
            token = rest if distance else token
        place = places[-1]
        if token == "ALQDS":
            place["all_quadrants"] = True
        elif token == "THRU":
            through = True
        elif token and token != "AND":
            points = tuple(token.split("-"))
            if through and place["directions"]:  # NW THRU SE: one range
                points = place["directions"].pop() + points
            place["directions"].append(points)
            through = False
    found = tuple(Place(p["distance"], tuple(p["directions"]), p["all_quadrants"]) for p in places)
    return Lightning(frequency, kinds, found)


def _group_at(text, pos):
    """(name, match) of the group starting at pos, or (None, None)."""
    for name, pattern in GROUPS:
        match = pattern.match(text, pos)
        if match:
            return name, match
    return None, None


def sea_level_pressure(digits) -> float:
    """SLPnnn in hPa: the last three digits of tenths, so 214 is 1021.4 and 927 is 992.7."""
    tenths = int(digits)
    return round((1000 if tenths < 500 else 900) + tenths / 10, 1)


def _tenths(sign, digits) -> float:
    """A temperature to a tenth of a degree: sign 1 is below zero ("1", "050" is -5.0)."""
    return round((-1 if sign == "1" else 1) * int(digits) / 10, 1)


def _miles(text) -> float:
    return float(sum(Fraction(part) for part in text.split()))


def _synoptic_hours(obs) -> Optional[int]:
    """
    The hours a 6 group covers: 6 in the reports nearest 00, 06, 12 and 18Z, 3 in those nearest 03, 09, 15 and 21Z
    (a 2353Z report is the 00Z one); None when the report's time isn't known or is neither.
    """
    if obs is None:
        return None
    hour = (obs[0] + (1 if obs[1] >= 30 else 0)) % 24
    return 6 if hour % 6 == 0 else 3 if hour % 3 == 0 else None


def _clock(hh, mm, obs):
    """
    (hour, minute) of a time given as hhmm, or as mm alone: then the report's hour, or the hour before when the
    minute is later than the report's (RAB55 in a 0353Z report began at 02:55). The hour is None with only the
    minute and no report time.
    """
    minute = int(mm)
    if hh is not None:
        return int(hh), minute
    if obs is None:
        return None, minute
    return (obs[0] if minute <= obs[1] else (obs[0] - 1) % 24), minute
