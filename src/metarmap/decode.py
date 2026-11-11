"""
A METAR in plain English, for the Map page's Decoded tab: one {"label", "text"} line per item the report has.

Works on the Report (models.Report) metar.Reports keeps for each airport. Weather codes follow the FAA's METAR key
(FMH-1, chapter 12: intensity, descriptor, then precipitation, obscuration or other phenomena). What the JSON doesn't
have (runway visual range, the trend, runway state...) is read from the raw text: Report.body (metarmap.body) and
Report.remarks (metarmap.remarks).
"""

import re
from collections import Counter
from dataclasses import dataclass
from fractions import Fraction
from typing import TYPE_CHECKING, Optional, Sequence, Tuple

from metarmap.body import BRAKING, COMPASS_POINTS, DEPOSITS, DEPTHS, EXTENTS, SIDES
from metarmap.lib.units import celsius_to_fahrenheit
from metarmap.remarks import DISTANCES, FREQUENCIES, LIGHTNING_TYPES, SENSORS, TENDENCIES

if TYPE_CHECKING:  # models imports nothing from here, but metar imports both
    from metarmap.body import Body, Cloud, RunwayRange, RunwayState, Trend
    from metarmap.models import Report, SkyLayer
    from metarmap.remarks import Lightning, Place, Remarks

INTENSITY = {"-": "light", "+": "heavy"}
DESCRIPTORS = {
    "MI": "shallow",
    "PR": "partial",
    "BC": "patches of",
    "DR": "low drifting",
    "BL": "blowing",
    "SH": "showers",
    "TS": "thunderstorm",
    "FZ": "freezing",
}
PHENOMENA = {
    # precipitation
    "DZ": "drizzle",
    "RA": "rain",
    "SN": "snow",
    "SG": "snow grains",
    "IC": "ice crystals",
    "PL": "ice pellets",
    "GR": "hail",
    "GS": "small hail",
    "UP": "unknown precipitation",
    # obscuration
    "BR": "mist",
    "FG": "fog",
    "FU": "smoke",
    "VA": "volcanic ash",
    "DU": "dust",
    "SA": "sand",
    "HZ": "haze",
    "PY": "spray",
    # other
    "PO": "dust whirls",
    "SQ": "squalls",
    "FC": "funnel cloud",
    "SS": "sandstorm",
    "DS": "duststorm",
}
COVER = {"FEW": "Few", "SCT": "Scattered", "BKN": "Broken", "OVC": "Overcast"}
CEILING = ("BKN", "OVC", "OVX")


def decode(metar: Optional["Report"]):
    """The plain-English lines for one airport's METAR (None when it isn't reporting: no lines)."""
    if not metar:
        return []
    lines = []

    def add(label, text):
        if text:
            lines.append({"label": label, "text": text})

    obs = metar.obs_time
    body = metar.body
    add("Observed", obs.strftime("%d %b %H:%MZ") if obs else None)
    add("Report type", report_type(body))
    add("Wind", wind(metar))
    add("Wind variability", wind_varies(body.wind_varies))
    add("Visibility", visibility(metar.visibility_sm, metar.visibility_more))
    for label, text in body_visibility(body, shown=metar.visibility_sm is not None):
        add(label, text)
    add("Weather", weather(metar.weather))
    for label, text in sky(metar, body):
        add(label, text)
    add("Temperature", temperature(metar.temp_c))
    add("Dewpoint", dewpoint(metar.dewpoint_c, metar.temp_c))
    altim = metar.altimeter_inhg
    add("Altimeter", f"{altim:.2f} inHg" if altim else None)
    for label, text in body_after_altimeter(body):
        add(label, text)
    for label, text in lightning_lines(metar):
        add(label, text)
    for label, text in remarks(metar.remarks):
        add(label, text)
    return lines


CATEGORY_TEXT = {
    "VFR": "VFR: ceiling above 3,000 ft and visibility over 5 miles",
    "MVFR": "Marginal VFR: ceiling 1,000-3,000 ft or visibility 3-5 miles",
    "IFR": "IFR: ceiling 500-999 ft or visibility 1 to 3 miles",
    "LIFR": "Low IFR: ceiling below 500 ft or visibility below 1 mile",
}
COMPASS = ("north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest")
FOG_SPREAD_C = 2  # temperature-dewpoint spread at or below which fog or low clouds can form
ICING_C = (-20, 2)  # temperatures at which visible moisture can ice an airplane


def summary(metar: Optional["Report"]):
    """
    A few sentences about the airport's weather for the Map page's popup, e.g. "Light rain", "Lightning distant
    north" or "Density altitude 1,200 ft". Only what the report has; none when it isn't reporting.
    """
    if not metar:
        return []
    temp = metar.temp_c
    lines = [
        CATEGORY_TEXT.get(metar.flight_category),
        weather(metar.weather),
        *lightning_summary(metar),
        wind_sentence(metar),
        sky_sentence(metar.sky_conditions, metar.vert_vis_ft),
        density_altitude_sentence(metar),
    ]
    spread = temp - metar.dewpoint_c if temp is not None and metar.dewpoint_c is not None else None
    if spread is not None and spread <= FOG_SPREAD_C:
        lines.append(f"Temperature and dewpoint are {spread}°C apart: fog or low clouds can form")
    moisture = metar.weather or any(layer.cover in CEILING for layer in metar.sky_conditions)
    if temp is not None and ICING_C[0] <= temp <= ICING_C[1] and moisture:
        lines.append(f"Temperature {temp}°C with clouds or precipitation: icing is possible")
    return [line for line in lines if line]


def wind_sentence(metar: "Report"):
    """ "Wind from the south at 12 knots, gusting to 20"."""
    speed = metar.wind_speed
    if speed is None:
        return None
    if speed == 0:
        return "Calm wind"
    direction = str(metar.wind_dir or "").upper()
    gust = f", gusting to {metar.wind_gust_speed}" if metar.wind_gust else ""
    if not _digits(direction):  # VRB
        return f"Variable wind at {speed} knots{gust}"
    degrees = int(direction)
    return f"Wind from the {COMPASS[round(degrees / 45) % 8]} ({degrees:03d}°) at {speed} knots{gust}"


def sky_sentence(layers: Sequence["SkyLayer"], vert_vis_ft=None):
    """The ceiling (lowest broken or overcast layer), else the lowest clouds, else a clear sky."""
    layers = [layer for layer in layers or () if layer.cover]
    if not layers:
        return None
    for layer in layers:
        if layer.cover == "OVX":
            return "Sky obscured" + (f": vertical visibility {vert_vis_ft:,} ft" if vert_vis_ft else "")
        if layer.cover in ("BKN", "OVC") and layer.base_ft:
            return f"Ceiling {layer.base_ft:,} ft ({COVER[layer.cover].lower()})"
    lowest = layers[0]
    if lowest.cover in COVER and lowest.base_ft:
        return f"No ceiling; {COVER[lowest.cover].lower()} clouds at {lowest.base_ft:,} ft"
    return "Clear skies" if lowest.cover in ("CLR", "SKC", "CAVOK", "NSC") else None


def ceiling_ft(layers: Sequence["SkyLayer"], vert_vis_ft=None):
    """
    The ceiling in feet: the lowest broken or overcast layer, or the vertical visibility when the sky is obscured.
    None when there's no ceiling (clear, or only few or scattered clouds).
    """
    for layer in layers or ():
        if layer.cover == "OVX":
            return vert_vis_ft or 0
        if layer.cover in ("BKN", "OVC"):
            return layer.base_ft or 0
    return None


CATEGORIES = ("VFR", "MVFR", "IFR", "LIFR")  # best to worst


def category_from(visibility_sm, layers=(), vert_vis_ft=None):
    """
    The flight category from a visibility (statute miles) and sky layers (FAA limits), or None if both are missing.
    The worse of the two decides; a sky with no broken or overcast layer (or a clear one) has no ceiling. With only
    one of the two, the real category could be worse, never better.
    """
    found = []
    if visibility_sm is not None:
        found.append(
            "LIFR" if visibility_sm < 1 else "IFR" if visibility_sm < 3 else "MVFR" if visibility_sm <= 5 else "VFR"
        )
    if layers:
        feet = ceiling_ft(layers, vert_vis_ft)
        found.append(
            "VFR" if feet is None or feet > 3000 else "MVFR" if feet >= 1000 else "IFR" if feet >= 500 else "LIFR"
        )
    return max(found, key=CATEGORIES.index) if found else None


def estimate_category(metar: "Report"):
    """
    The flight category from the visibility and ceiling the report has (FAA limits), for a station that doesn't
    report one; None if it has neither (see category_from).
    """
    return category_from(metar.visibility_sm, metar.sky_conditions, metar.vert_vis_ft)


def density_altitude_sentence(metar: "Report"):
    """ "Density altitude 1,200 ft (field elevation 46 ft)", to the nearest 100 ft."""
    # imported here: the visualizers import this module
    from metarmap.visualizers.density_altitude import calculate_density_altitude, meters_to_feet

    if not metar.altimeter_inhg or metar.elevation_m is None or metar.temp_c is None:
        return None
    feet = calculate_density_altitude(metar.altimeter_inhg, metar.elevation_m, metar.temp_c)
    field = meters_to_feet(metar.elevation_m)
    return f"Density altitude {round(feet, -2):,.0f} ft (field elevation {field:,.0f} ft)"


def wind(metar: "Report"):
    speed = metar.wind_speed
    if speed is None:
        return None
    direction = str(metar.wind_dir or "").upper()
    if speed == 0:
        return "Calm"
    gust = f", gusts {metar.wind_gust_speed} kt" if metar.wind_gust else ""
    if direction in ("VRB", ""):
        return f"Variable at {speed} kt{gust}"
    return f"{int(direction):03d}° at {speed} kt{gust}"


def visibility(miles, more=False):
    """ "10+ miles", "6 miles", "1 1/2 miles", "1/4 mile"."""
    if miles is None:
        return None
    value = Fraction(miles).limit_denominator(16)
    whole, part = divmod(value, 1)
    text = " ".join(t for t in (str(whole) if whole else "", str(part) if part else "") if t) or "0"
    return f"{text}{'+' if more else ''} {'mile' if 0 < value <= 1 and not more else 'miles'}"


def weather(wx):
    """ "-RA BR" -> "Light rain, mist". Codes it doesn't know are shown as they are."""
    text = ", ".join(weather_group(group) for group in str(wx or "").split())
    return text[:1].upper() + text[1:] or None


@dataclass(frozen=True)
class WeatherGroup:
    """One group of a METAR's weather, e.g. "-SHRA": intensity "-", descriptor "SH", phenomena ("RA",)."""

    code: str  # as reported
    intensity: str = ""  # "-" light, "" moderate, "+" heavy
    vicinity: bool = False  # VC: in the vicinity, not at the airport
    descriptor: Optional[str] = None  # MI, PR, BC, DR, BL, SH, TS, FZ
    phenomena: Tuple[str, ...] = ()  # RA, SN, FG, ...


def parse_weather(wx):
    """The groups in a weather string ("-RA BR"), in order. Groups it can't read are left out."""
    return [group for group in (parse_weather_group(code) for code in str(wx or "").split()) if group]


def parse_weather_group(group):
    """One weather group, or None if it isn't one (e.g. "NSW", or a code that isn't in the METAR key)."""
    code, intensity, vicinity = group, "", False
    if code[:1] in INTENSITY:
        intensity, code = code[0], code[1:]
    if code.startswith("VC"):
        vicinity, code = True, code[2:]
    descriptor = None
    if code[:2] in DESCRIPTORS:
        descriptor, code = code[:2], code[2:]
    if len(code) % 2 or any(code[i : i + 2] not in PHENOMENA for i in range(0, len(code), 2)):
        return None
    if not code and not descriptor:
        return None
    return WeatherGroup(group, intensity, vicinity, descriptor, tuple(code[i : i + 2] for i in range(0, len(code), 2)))


def weather_group(group):
    parsed = parse_weather_group(group)
    if parsed is None:
        return group  # not a code we know: shown as it is
    intensity = INTENSITY.get(parsed.intensity, "")
    names = [PHENOMENA[p] for p in parsed.phenomena]
    descriptor = parsed.descriptor

    if names == ["funnel cloud"] and intensity == "heavy":
        text = "tornado or waterspout"
    else:
        what = " ".join(t for t in (intensity, " and ".join(names)) if t)
        if descriptor == "TS":
            text = "thunderstorm" + (f" with {what}" if what else "")
        elif descriptor == "SH":
            text = f"{what} showers" if what else "showers"
        elif descriptor:
            text = " ".join(t for t in (intensity, DESCRIPTORS[descriptor], " and ".join(names)) if t)
        else:
            text = what
    if parsed.vicinity:
        text += " in the vicinity"
    return text


def clouds(layers: Sequence["SkyLayer"], vert_vis_ft=None, kinds: Sequence[Optional[str]] = ()):
    """
    One line per cloud layer, lowest first, with the ceiling (the lowest broken or overcast layer) marked. kinds:
    each layer's cloud type, CB or TCU (or None), when known (cloud_kinds).
    """
    lines, ceiling_found = [], False
    for n, layer in enumerate(layers or ()):
        cover, base = layer.cover, layer.base_ft
        if cover in ("CLR", "SKC", "CAVOK", "NSC"):
            lines.append("Clear")
            continue
        if cover == "OVX":
            text = "Sky obscured" + (f", vertical visibility {vert_vis_ft:,} ft" if vert_vis_ft else "")
        elif cover in COVER:
            text = f"{COVER[cover]} {base:,} ft" if base else COVER[cover]
        else:
            text = cover
        kind = kinds[n] if n < len(kinds) else None
        if kind in CLOUD_KINDS:
            text += f", {CLOUD_KINDS[kind]}"
        if cover in CEILING and not ceiling_found:
            text += " (ceiling)"
            ceiling_found = True
        lines.append(text)
    return lines


def temperature(celsius):
    if celsius is None:
        return None
    return f"{celsius}°C / {celsius_to_fahrenheit(celsius):.0f}°F"


def dewpoint(celsius, temperature_c=None):
    text = temperature(celsius)
    if text and temperature_c is not None:
        text += f" (spread {temperature_c - celsius}°C)"
    return text


# ---- the body, for what the JSON doesn't have (metarmap.body) -------------------------------------------------

REPORT_TYPES = {"METAR": "Routine report", "SPECI": "Special report (unscheduled)"}
# AUTO has no text: most US reports are automated, and the remarks' Station type says so (AO1, AO2)
MODIFIERS = {"COR": "corrected", "RTD": "delayed"}
ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth")
CLOUD_KINDS = {"CB": "cumulonimbus", "TCU": "towering cumulus"}
# ICAO Annex 3, appendix 3, 4.5: the 5,000 ft is the highest minimum sector altitude where that's higher
CAVOK = (
    "Ceiling and visibility OK: visibility 10 km or more, no cloud below 5,000 ft, no cumulonimbus or towering "
    "cumulus, no significant weather"
)
NO_CLOUD = {
    "NSC": "No significant cloud: none below 5,000 ft, no cumulonimbus or towering cumulus",
    "NCD": "No clouds detected (automated)",
}
CLEAR = ("CLR", "SKC", "CAVOK", "NSC", "NCD")
RVR_BOUNDS = {"M": "less than ", "P": "more than "}
RVR_TRENDS = {"U": "improving", "D": "worsening", "N": "no change"}
TREND_KINDS = {"BECMG": "Becoming", "TEMPO": "Temporarily"}
TREND_TIMES = {"FM": "from", "TL": "until", "AT": "at"}
WIND_UNITS = {"KT": "kt", "MPS": "m/s", "KMH": "km/h"}


def report_type(body: "Body"):
    """
    "Special report (unscheduled)", "Routine report, corrected (first correction)": only for a special report (SPECI)
    or a corrected one (COR, CCA...), None for any other. AUTO isn't shown (most US reports are automated, and the
    Station type line says so); RTD (delayed) is, after the rest, on a report that has the line.
    """
    corrected = any(code == "COR" or code.startswith("CC") for code in body.modifiers)
    if body.report_type != "SPECI" and not corrected:
        return None
    parts = [REPORT_TYPES.get(body.report_type)] + [modifier(code) for code in body.modifiers]
    text = ", ".join(part for part in parts if part)
    return text[:1].upper() + text[1:]


def modifier(code):
    """ "COR" -> "corrected"; "CCA" -> "corrected (first correction)"; None for AUTO (not shown)."""
    if code.startswith("CC") and len(code) == 3:
        n = ord(code[2]) - ord("A")
        return f"corrected ({ORDINALS[n]} correction)" if 0 <= n < len(ORDINALS) else "corrected"
    return MODIFIERS.get(code)


def wind_varies(directions):
    """(350, 50) -> "Varying between 350° and 050°"."""
    if not directions:
        return None
    return "Varying between {:03d}° and {:03d}°".format(*directions)


def body_visibility(body: "Body", shown=True):
    """
    (label, text) for what the body adds to the visibility: NDV, the lowest visibility and the runway visual range.
    shown: whether the Visibility line is there, which NDV continues.
    """
    found = []
    if body.no_directional_variation:
        found.append(("" if shown else "Visibility", "Directional variation not available"))
    if body.lowest_visibility_m is not None:
        toward = COMPASS_POINTS.get(body.lowest_visibility_toward)
        found.append(("Lowest visibility", f"{body.lowest_visibility_m:,} m" + (f" to the {toward}" if toward else "")))
    ranges = [r for r in body.runway_ranges if r.low is not None]  # R24/////: not reported, not shown
    found.extend(("Runway visual range" if n == 0 else "", runway_range(r)) for n, r in enumerate(ranges))
    return found


def runway_name(code):
    """ "24L" -> "24 left"."""
    return code[:2] + (f" {SIDES[code[2:]]}" if code[2:] in SIDES else "")


def runway_range(found: "RunwayRange"):
    """ "Runway 28: 2,400 ft", "Runway 24 left: varying 550 to 800 m, improving", "Runway 06: more than 6,000 ft"."""
    where = f"Runway {runway_name(found.runway)}"
    if found.low is None:  # R24///// (body_visibility leaves it out)
        return f"{where}: not reported"
    unit = "ft" if found.feet else "m"
    low = f"{RVR_BOUNDS.get(found.low_bound, '')}{found.low:,}"
    if found.high is not None:
        text = f"varying {low} to {RVR_BOUNDS.get(found.high_bound, '')}{found.high:,} {unit}"
    else:
        text = f"{low} {unit}"
    trend = RVR_TRENDS.get(found.trend)
    return f"{where}: {text}" + (f", {trend}" if trend else "")


def sky(metar: "Report", body: "Body"):
    """
    (label, text) for the sky: the Clouds lines (with each layer's CB or TCU), or one CAVOK line, or what NSC or NCD
    means (the JSON gives those as a clear sky, CLR). A CB or TCU whose height isn't known (FEW///CB), which the JSON
    leaves out, goes on after them (unknown_height_clouds).
    """
    layers = metar.sky_conditions or ()
    covers = [layer.cover for layer in layers]
    if "CAVOK" in covers or (body.sky == "CAVOK" and set(covers) <= set(CLEAR)):
        return [("CAVOK", CAVOK)]
    found = None
    if set(covers) <= set(CLEAR):
        code = body.sky if body.sky in NO_CLOUD else next((c for c in covers if c in NO_CLOUD), None)
        if code:
            found = [NO_CLOUD[code]]
    if found is None:
        found = clouds(layers, metar.vert_vis_ft, cloud_kinds(layers, body.clouds))
    found += unknown_height_clouds(layers, body.clouds)
    return [("Clouds" if n == 0 else "", text) for n, text in enumerate(found)]


def unknown_height_clouds(layers: Sequence["SkyLayer"], groups: Sequence["Cloud"]):
    """
    A line for each CB or TCU group of the body whose height isn't known (FEW///CB, //////TCU): "Few cumulonimbus,
    height not known", "Towering cumulus, cover and height not known". The JSON leaves these out; one it does have
    (a layer of the same cover with no height) is shown already, so it isn't again.
    """
    shown = Counter(layer.cover for layer in layers or () if layer.cover in COVER and not layer.base_ft)
    found = []
    for group in groups:
        if group.base_ft is not None or group.kind not in CLOUD_KINDS:
            continue
        if shown[group.cover]:
            shown[group.cover] -= 1
            continue
        kind = CLOUD_KINDS[group.kind]
        if group.cover in COVER:
            found.append(f"{COVER[group.cover]} {kind}, height not known")
        else:
            found.append(f"{kind[:1].upper()}{kind[1:]}, cover and height not known")
    return found


def cloud_kinds(layers: Sequence["SkyLayer"], groups: Sequence["Cloud"]):
    """
    Each layer's CB or TCU (or None) from the body's cloud groups, which the JSON leaves out; () unless the groups are
    the same layers (cover and height) as the report's, so a type is never put on the wrong one.
    """
    at = [n for n, layer in enumerate(layers or ()) if layer.cover in COVER]
    if len(at) < len(groups):  # the JSON leaves out a layer whose height isn't known (FEW///TCU)
        groups = [group for group in groups if group.base_ft is not None]
    if len(at) != len(groups):
        return ()
    for n, group in zip(at, groups):
        if group.cover != layers[n].cover or (group.base_ft is not None and group.base_ft != layers[n].base_ft):
            return ()
    kinds = [None] * len(layers)
    for n, group in zip(at, groups):
        kinds[n] = group.kind
    return kinds


def body_after_altimeter(body: "Body"):
    """(label, text) for the groups after the altimeter, in the report's order: RE, WS, runway state and trend."""
    found = []

    def add(label, texts):
        found.extend((label if n == 0 else "", text) for n, text in enumerate(texts))

    if body.recent_weather:
        add("Recent weather", [weather(" ".join(body.recent_weather)) + " (since the last routine report, not now)"])
    add("Wind shear", ["All runways" if r == "ALL" else f"Runway {runway_name(r)}" for r in body.wind_shear])
    add("Runway state", [runway_state(state) for state in body.runway_states])
    add("Trend", [trend(group) for group in body.trends])
    return found


def runway_state(found: "RunwayState"):
    """
    "Runway 24 left: wet or water patches, covering 51-100%, 1 mm deep, friction coefficient 0.45" (WMO code
    tables, in metarmap.body). A group with a code that isn't in the tables (or a runway 99, which repeats the last
    report's state) is shown as reported.
    """
    if found.runway is None:
        return "Airport closed by snow"
    runway = found.runway
    if runway == "88":
        where = "All runways"
    elif runway != "99" and 1 <= int(runway[:2]) <= 36:
        where = f"Runway {runway_name(runway)}"
    else:
        return found.code
    if found.cleared:
        braking = _braking(found.braking)
        return found.code if braking is False else f"{where}: cleared" + (f", {braking}" if braking else "")
    parts = [
        DEPOSITS.get(found.deposit, False),
        EXTENTS.get(found.extent, False),
        _depth(found.depth),
        _braking(found.braking),
    ]
    if any(part is False for part in parts):
        return found.code
    return f"{where}: " + ", ".join(part for part in parts if part)


def _digits(text) -> bool:
    """Whether text is ASCII digits: str.isdigit() is also true for ², which int() rejects."""
    return re.fullmatch(r"[0-9]+", text) is not None


def _depth(code):
    """A depth of deposit (code table 1079): its text, None for // (none to show), False for a code that isn't one."""
    if _digits(code) and 1 <= int(code) <= 90:
        return f"{int(code)} mm deep"
    return DEPTHS.get(code, False)


def _braking(code):
    """Friction or braking action (code table 0366), as _depth."""
    if _digits(code) and 1 <= int(code) <= 90:
        return f"friction coefficient 0.{code}"
    return BRAKING.get(code, False)


def trend(found: "Trend"):
    """
    "No significant change expected in the next 2 hours" (NOSIG); "Temporarily from 04:30Z until 05:00Z: visibility
    4,000 m, thunderstorm with rain". Items it can't read (Trend.other) are shown as reported, after the rest; military
    color states aren't among them (metarmap.body leaves them out).
    """
    if found.kind == "NOSIG":
        head = "No significant change expected in the next 2 hours"
    else:
        head = TREND_KINDS[found.kind]
    for kind, hhmm in found.times:
        head += f" {TREND_TIMES[kind]} {hhmm[:2]}:{hhmm[2:]}Z"
    parts = [trend_wind(found.wind)]
    shown = found.visibility
    if found.cavok:
        parts.append("ceiling and visibility OK")
    elif shown and shown.metres is not None:
        parts.append("visibility 10 km or more" if shown.metres == 9999 else f"visibility {shown.metres:,} m")
    elif shown:
        parts.append(f"visibility {visibility(shown.miles, shown.more)}")
    parts.extend(weather_group(code) for code in found.weather)
    parts.append("no significant weather" if found.no_significant_weather else None)
    parts.extend(trend_cloud(cloud) for cloud in found.clouds)
    parts.append("no significant cloud" if found.no_significant_cloud else None)
    parts.extend(found.other)
    parts = [part for part in parts if part]
    return head + (": " + ", ".join(parts) if parts else "")


def trend_wind(found):
    """ "wind 290° at 12 kt", "wind variable at 3 kt", "wind 140° at 18 kt gusting 30 kt", "wind calm"."""
    if found is None:
        return None
    if found.speed == 0 and not found.gust:
        return "wind calm"
    unit = WIND_UNITS[found.unit]
    where = "variable" if found.direction is None else f"{found.direction:03d}°"
    return f"wind {where} at {found.speed} {unit}" + (f" gusting {found.gust} {unit}" if found.gust else "")


def trend_cloud(found: "Cloud"):
    """ "broken 1,400 ft", "few 1,500 ft cumulonimbus", "sky obscured (vertical visibility 100 ft)"."""
    if found.cover == "VV":
        return "sky obscured" + (f" (vertical visibility {found.base_ft:,} ft)" if found.base_ft else "")
    kind = f" {CLOUD_KINDS[found.kind]}" if found.kind in CLOUD_KINDS else ""
    return f"{COVER[found.cover].lower()} {found.base_ft:,} ft{kind}"


# ---- the remarks (metarmap.remarks) ------------------------------------------------------------------------------

STATION_TYPES = {
    "AO1": "Automated, without a precipitation discriminator",
    "AO2": "Automated, with a precipitation discriminator",
}
# P: since the last METAR (FMH-1 12.7.2 a), which a SPECI isn't. Others: "Precipitation (last 6 hours)"
PRECIPITATION_LABELS = {1: "Precipitation (since the last hourly report)"}


def remarks(rmk: "Remarks"):
    """
    (label, text) for each thing the remarks say, in a fixed order (not the report's); a label continued on the
    next line is "". Groups it doesn't read are one "Other remarks" line, as reported.
    """
    found = []

    def add(label, *texts):
        texts = [t for t in texts if t]
        found.extend((label if n == 0 else "", t) for n, t in enumerate(texts))

    if rmk.station_type:
        augmented = ", augmented by an observer" if rmk.station_type.endswith("A") else ""
        add("Station type", STATION_TYPES[rmk.station_type[:3]] + augmented)
    if rmk.sea_level_pressure_hpa is not None:
        add("Sea-level pressure", f"{rmk.sea_level_pressure_hpa:.1f} hPa")
    elif rmk.sea_level_pressure_missing:
        add("Sea-level pressure", "Not available")
    add("Precise temperature", precise(rmk.temp_c))
    add("Precise dewpoint", precise(rmk.dewpoint_c))
    add("Temperature (last 6 hours)", high_low(rmk.max_temp_6h_c, rmk.min_temp_6h_c))
    add("Temperature (last 24 hours)", high_low(rmk.max_temp_24h_c, rmk.min_temp_24h_c))
    add("Pressure tendency", tendency(rmk.pressure_tendency), (rmk.pressure_change or "").capitalize())
    wind = rmk.peak_wind
    if wind:
        add("Peak wind", f"{wind.direction:03d}° at {wind.speed_kt} kt ({clock(wind.hour, wind.minute)})")
    shift = rmk.wind_shift
    if shift:
        fropa = ", frontal passage" if shift.frontal_passage else ""
        add("Wind shift", f"At {clock(shift.hour, shift.minute)}{fropa}")
    add("Tower visibility", visibility(rmk.tower_visibility_sm))
    add("Surface visibility", visibility(rmk.surface_visibility_sm))
    if rmk.variable_visibility_sm:
        low, high = rmk.variable_visibility_sm
        add("Variable visibility", f"{visibility(low).rsplit(' ', 1)[0]} to {visibility(high)}")
    if rmk.variable_ceiling_ft:
        add("Variable ceiling", "{:,} to {:,} ft".format(*rmk.variable_ceiling_ft))
    for amount in rmk.precipitation:
        hours = amount.hours
        label = PRECIPITATION_LABELS.get(hours) or f"Precipitation (last {hours or '3 or 6'} hours)"
        add(label, inches(amount.inches))
    for amount in rmk.ice_accretion:
        when = "since the last hourly report" if amount.hours == 1 else f"last {amount.hours} hours"
        add(f"Ice accretion ({when})", inches(amount.inches))
    if rmk.snow_depth_in is not None:
        add("Snow depth", inches(rmk.snow_depth_in, 0))
    if rmk.snowfall_6h_in is not None:
        add("Snowfall (last 6 hours)", inches(rmk.snowfall_6h_in, 1))
    if rmk.snow_water_in is not None:
        add("Snow water equivalent", inches(rmk.snow_water_in, 1))
    add("Precipitation began/ended", *began_ended(e for e in rmk.events if e.weather != "TS"))
    add("Thunderstorm began/ended", *began_ended(e for e in rmk.events if e.weather == "TS"))
    sensors = ", ".join(sensor_name(code) for code in rmk.sensors_out)
    add("Sensors out of service", sensors[:1].upper() + sensors[1:])
    add("Special reports", "Not sent by this station" if rmk.no_speci else None)
    add("Maintenance", "The station needs maintenance" if rmk.maintenance else None)
    add("Other remarks", " ".join(rmk.other))
    return found


def precise(celsius):
    """ "16.1°C / 61.0°F", to a tenth."""
    if celsius is None:
        return None
    return f"{celsius:.1f}°C / {celsius_to_fahrenheit(celsius):.1f}°F"


def high_low(high, low):
    """ "High 27.2°C / 81.0°F, low 14.4°C / 57.9°F" (either may be missing)."""
    parts = [f"{word} {precise(value)}" for word, value in (("high", high), ("low", low)) if value is not None]
    text = ", ".join(parts)
    return text[:1].upper() + text[1:] or None


def tendency(found):
    """ "Up 1.6 hPa in 3 hours (rising, then steady)"."""
    if found is None:
        return None
    change = found.change_hpa
    how = "Unchanged" if change == 0 else f"{'Up' if change > 0 else 'Down'} {abs(change):.1f} hPa"
    return f"{how} in 3 hours ({TENDENCIES[found.character]})"


def inches(amount, places=2):
    """
    "0.01 in", "Couldn't be measured" for None (an amount reported as ////), and "Trace" for 0. Every group this
    shows is coded only when something fell or lies on the ground, so all zeros mean less than the group's unit:
    P0000 and 60000 are a trace (FMH-1 12.7.2 a 3 a and b; the ASOS User's Guide: "If only a trace of precipitation
    has occurred, the Prrrr remark will report P0000"), and so is a 7, 931 (tenths), 933 (tenths) or I (hundredths)
    group of zeros. 4/sss is coded only for more than a trace of snow, and the NWS reports a depth under half an inch
    as a trace, so a 4/000 is one too. Sources: remarks.py's docstring.
    """
    if amount is None:
        return "Couldn't be measured"
    return f"{amount:.{places}f} in" if amount else "Trace"


def clock(hour, minute):
    """ "03:09Z", or ":09 past the hour" when the hour isn't known."""
    return f"{hour:02d}:{minute:02d}Z" if hour is not None else f":{minute:02d} past the hour"


def began_ended(events):
    """One line per weather, in the order reported: "Rain began 03:09Z, ended 03:27Z"."""
    by_weather = {}
    for event in events:
        when = f"{'began' if event.began else 'ended'} {clock(event.hour, event.minute)}"
        by_weather.setdefault(event.weather, []).append(when)
    return [f"{weather_group(code).capitalize()} {', '.join(times)}" for code, times in by_weather.items()]


def lightning_lines(metar: "Report"):
    """
    (label, text) for the report's lightning, one line per group (later ones unlabeled): "Occasional in-cloud and
    cloud-to-ground, east and southwest", "Distant north" (shown, though it doesn't flicker the pixel). A report
    with the lightning flag and no group (one made with it) has "Lightning observed".
    """
    texts = [lightning(group) for group in metar.lightning_groups]
    if not texts and metar.lightning:
        texts = ["Lightning observed"]
    return [("Lightning" if n == 0 else "", text) for n, text in enumerate(texts)]


def lightning(group: "Lightning"):
    """
    One lightning group as the Decoded tab says it: how often and what kind (FMH-1 table 12-5), then where:
    "Frequent in-cloud and cloud-to-ground, overhead and south through southwest, distant west", "Distant north".
    "Lightning observed" for an LTG alone.
    """
    kinds = _listed([LIGHTNING_TYPES[kind] for kind in group.types])
    what = " ".join(t for t in (FREQUENCIES.get(group.frequency, ""), kinds) if t)
    text = ", ".join(t for t in (what, lightning_where(group)) if t)
    return text[:1].upper() + text[1:] if text else "Lightning observed"


def lightning_where(group: "Lightning"):
    """Where a lightning group is, its places in order: "distant north", "in the vicinity, east and southwest"."""
    return ", ".join(t for t in (place_text(place) for place in group.places) if t)


def place_text(place: "Place"):
    """
    How far and which way: "distant north", "distant in all quadrants", "in the vicinity, east and southwest",
    "overhead", "overhead and northeast" (OHD-NE), "east and southwest" (at the station: no distance).
    """
    if place.all_quadrants:
        toward = "in all quadrants"
    else:
        toward = _listed([_points(item) for item in place.directions])
    distance = DISTANCES.get(place.distance, "")
    if not distance or not toward:
        return distance or toward
    if place.distance == "DSNT" or place.all_quadrants:
        return f"{distance} {toward}"
    return f"{distance} and {toward}" if place.distance == "OHD" else f"{distance}, {toward}"


def _listed(words):
    """ "a", "a and b", "a, b and c"; "" for none."""
    return ", ".join(words[:-1]) + (" and " if len(words) > 1 else "") + (words[-1] if words else "")


def _points(points):
    """("E",) -> "east"; a range, clockwise, ("SE", "S", "SW") -> "southeast through southwest"."""
    if len(points) == 1:
        return COMPASS_POINTS[points[0]]
    return f"{COMPASS_POINTS[points[0]]} through {COMPASS_POINTS[points[-1]]}"


def lightning_sentence(group: "Lightning", plain="Lightning observed"):
    """
    One lightning group as a sentence, without its kind: "Occasional lightning distant north", "Frequent lightning
    overhead", "Lightning in the vicinity, east and southwest", "Occasional lightning, east and southwest" (at the
    station); `plain` for an LTG alone. For the Map popup (summary) and the spoken weather (spoken.py).
    """
    where = lightning_where(group)
    frequency = FREQUENCIES.get(group.frequency)
    if not where and not frequency:
        return plain
    text = f"{frequency} lightning" if frequency else "lightning"
    if where:
        text += f" {where}" if group.places[0].distance else f", {where}"
    return text[:1].upper() + text[1:]


def lightning_summary(metar: "Report"):
    """The popup's lightning sentences, one per group (distant ones too); "Lightning reported" when it says no more."""
    texts = [lightning_sentence(group, "Lightning reported") for group in metar.lightning_groups]
    if not texts and metar.lightning:
        texts = ["Lightning reported"]
    return list(dict.fromkeys(texts))


def sensor_name(code):
    """ "TSNO" -> "lightning detector"; "VISNO RWY06" -> "visibility sensor at RWY06"."""
    sensor, _, where = code.partition(" ")
    return SENSORS.get(sensor, sensor) + (f" at {where}" if where else "")
