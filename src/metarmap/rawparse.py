"""
A METAR typed by hand, read into a Report: the mock METARs (dev_mode) and the AWOS's spoken weather. Only the body is
read here, as aviationweather.gov's JSON gives it for a fetched report (metar.parse_report); Report.body and
Report.remarks read the rest from the raw text. No I/O: parse_raw() is a pure function of the text and the time.
"""

import re
from dataclasses import replace
from datetime import datetime, timedelta
from fractions import Fraction
from typing import Any, Dict, List, Optional, Sequence, Tuple

from metarmap import remarks
from metarmap.body import TREND_KINDS
from metarmap.decode import estimate_category, parse_weather_group
from metarmap.models import Report, SkyLayer

HPA_PER_INHG = 33.8639
MPS_TO_KT = 1.94384
METERS_PER_SM = 1609.344


def observed(day: int, hour: int, minute: int, now: datetime) -> datetime:
    """The time of a report's DDHHMMZ: this month, or last month if that day is still ahead."""
    month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    for _ in range(2):
        try:
            at: Optional[datetime] = month.replace(day=day, hour=hour, minute=minute)
        except ValueError:  # e.g. the 31st in a 30-day month
            at = None
        if at is not None and at <= now + timedelta(minutes=5):
            return at
        month = (month - timedelta(days=1)).replace(day=1)
    raise ValueError(f"{day:02d}{hour:02d}{minute:02d}Z isn't a time in the last month")


def _split_header(raw: Any, now: Optional[datetime]) -> Tuple[str, Optional[datetime], List[str]]:
    """(raw tidied, the observation time or None, the tokens after the station and time) of a typed METAR."""
    raw = " ".join(str(raw or "").split())
    tokens = raw.split(" RMK ")[0].split()
    if tokens and tokens[0] in ("METAR", "SPECI"):
        tokens = tokens[1:]
    if not tokens or not re.fullmatch(r"[A-Z0-9]{3,4}", tokens[0]):
        raise ValueError("a METAR starts with the airport code, e.g. METAR KDWH 272353Z ...")
    tokens = tokens[1:]
    obs_time = None
    if tokens and re.fullmatch(r"\d{6}Z", tokens[0]):
        # `now` is None only for the AWOS's words: a time there is skipped, and the report has no obs_time
        if now is not None:
            obs_time = observed(int(tokens[0][:2]), int(tokens[0][2:4]), int(tokens[0][4:6]), now)
        tokens = tokens[1:]
    return raw, obs_time, tokens


def _read_tokens(tokens: Sequence[str]) -> Dict[str, Any]:
    """The Report fields the body's tokens give, up to a trend."""
    wind_dir, wind_speed, gust = "", None, 0
    visibility: Optional[float] = None
    visibility_m: Optional[int] = None  # the same, as reported in metres (outside the US)
    after_wind = False  # a 4-digit visibility comes after the wind: one before it is something else (COR 1955)
    more = False
    wx: List[str] = []
    sky: List[SkyLayer] = []
    vert_vis: Optional[int] = None
    temp_c: Optional[int] = None
    dewpoint_c: Optional[int] = None
    altim: Optional[float] = None
    i = 0
    while i < len(tokens):
        t = tokens[i]
        wind = re.fullmatch(r"(\d{3}|VRB)(\d{2,3})(?:G(\d{2,3}))?(KT|MPS)", t)
        miles = re.fullmatch(r"([MP])?(\d+(?:/\d+)?)SM", t)
        clouds = re.fullmatch(r"(FEW|SCT|BKN|OVC)(\d{3})(?:CB|TCU|///)?", t)  # ///: type not known (automated)
        temps = re.fullmatch(r"(M?\d{2})/(M?\d{2})?", t)
        if t in TREND_KINDS:  # the rest is a forecast
            break
        if t.endswith(("KT", "MPS")):  # the wind group, read or not (/////KT)
            after_wind = True
        if wind:
            factor = MPS_TO_KT if wind.group(4) == "MPS" else 1
            wind_dir = wind.group(1) if wind.group(1) == "VRB" else str(int(wind.group(1)))  # as the JSON: "80"
            wind_speed = int(round(int(wind.group(2)) * factor))
            gust = int(round(int(wind.group(3)) * factor)) if wind.group(3) else 0
        elif re.fullmatch(r"\d{3}V\d{3}", t):  # varying wind direction
            pass
        elif re.fullmatch(r"[0-9]+", t) and i + 1 < len(tokens) and re.fullmatch(r"\d/\dSM", tokens[i + 1]):  # 1 1/2SM
            visibility = float(int(t) + _miles(tokens[i + 1][:-2]))
            i += 1
        elif miles:
            visibility = float(_miles(miles.group(2)))
            more = miles.group(1) == "P"
        # meters, outside the US; 9999: 10 km or more
        elif re.fullmatch(r"\d{4}(?:NDV)?", t) and visibility is None and after_wind:
            visibility_m = int(t[:4])
            visibility = round(visibility_m / METERS_PER_SM, 2)
            more = t[:4] == "9999"
        elif t == "CAVOK":  # visibility 10 km or more
            visibility, visibility_m, more = 10.0, 9999, True
            sky.append(SkyLayer("CAVOK"))
        elif clouds:
            sky.append(SkyLayer(clouds.group(1), int(clouds.group(2)) * 100))
        elif re.fullmatch(r"VV(\d{3}|///)", t):  # sky obscured
            vert_vis = int(t[2:]) * 100 if re.fullmatch(r"[0-9]+", t[2:]) else 0
            sky.append(SkyLayer("OVX"))
        elif t in ("CLR", "SKC", "NSC", "NCD"):
            sky.append(SkyLayer(t))
        elif temps:
            temp_c, dewpoint_c = (int(v.replace("M", "-")) if v else None for v in temps.groups())
        elif re.fullmatch(r"A\d{4}", t):
            altim = int(t[1:]) / 100
        elif re.fullmatch(r"Q\d{4}", t):
            altim = round(int(t[1:]) / HPA_PER_INHG, 2)
        elif parse_weather_group(t):
            wx.append(t)
        i += 1  # anything else (AUTO, COR, RVR...) is skipped here: Report.body reads it
    return {
        "wind_dir": wind_dir,
        "wind_speed": wind_speed,
        "wind_gust_speed": gust,
        "visibility_sm": visibility,
        "visibility_more": more,
        "visibility_m": visibility_m,
        "vert_vis_ft": vert_vis,
        "weather": " ".join(wx),
        "temp_c": temp_c,
        "dewpoint_c": dewpoint_c,
        "altimeter_inhg": altim,
        "sky_conditions": tuple(sky),
    }


def parse_raw(raw: Any, now: Optional[datetime]) -> Report:
    """
    A METAR typed by hand ("METAR KDWH 272353Z AUTO 08003KT 9SM CLR 21/18 A3014 RMK ...") as parse_report() gives
    one from the JSON, for the mock METARs. The flight category comes from the visibility and ceiling (FAA limits).
    Only the body is read here (Report.remarks reads the remarks from raw, as for a fetched report), up to its trend
    (NOSIG, BECMG, TEMPO): like the JSON, the weather and clouds are what's observed, not what's forecast (Report.body
    reads the trend). Raises ValueError if it doesn't start like a METAR, or for a visibility over zero (1/0SM).
    """
    raw, obs_time, tokens = _split_header(raw, now)
    report = Report(
        raw=raw,
        **_read_tokens(tokens),
        lightning=remarks.lightning_at_station(remarks.lightning_groups(raw)),
        obs_time=obs_time,
    )
    return replace(report, flight_category=estimate_category(report))


def metric_visibility(raw: Any) -> Optional[int]:
    """
    The visibility in metres when the report gave it so ("6000", "9999NDV"; CAVOK as 9999), for a fetched report:
    the JSON's visib is always in statute miles. None for one in miles (10SM), without one, or not like a METAR.
    """
    try:
        return _read_tokens(_split_header(raw, None)[2])["visibility_m"]
    except ValueError:
        return None


def _miles(text: str) -> Fraction:
    """A visibility in miles, "3" or "1/2", as a Fraction. Raises ValueError for one over zero (1/0SM)."""
    try:
        return Fraction(text)
    except ZeroDivisionError:
        raise ValueError(f"{text}SM is not a visibility") from None
