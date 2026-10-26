"""
A METAR in plain English, for the Map page's Decoded tab: one {"label", "text"} line per item the report has.

Works on the dict metar.METAR builds for each airport. Weather codes follow the FAA's METAR key (FMH-1, chapter 12:
intensity, descriptor, then precipitation, obscuration or other phenomena).
"""
from dataclasses import dataclass
from fractions import Fraction
from typing import Optional, Tuple

from metarmap.lib import utils

INTENSITY = {"-": "light", "+": "heavy"}
DESCRIPTORS = {
    "MI": "shallow", "PR": "partial", "BC": "patches of", "DR": "low drifting", "BL": "blowing",
    "SH": "showers", "TS": "thunderstorm", "FZ": "freezing",
}
PHENOMENA = {
    # precipitation
    "DZ": "drizzle", "RA": "rain", "SN": "snow", "SG": "snow grains", "IC": "ice crystals", "PL": "ice pellets",
    "GR": "hail", "GS": "small hail", "UP": "unknown precipitation",
    # obscuration
    "BR": "mist", "FG": "fog", "FU": "smoke", "VA": "volcanic ash", "DU": "dust", "SA": "sand", "HZ": "haze",
    "PY": "spray",
    # other
    "PO": "dust whirls", "SQ": "squalls", "FC": "funnel cloud", "SS": "sandstorm", "DS": "duststorm",
}
COVER = {"FEW": "Few", "SCT": "Scattered", "BKN": "Broken", "OVC": "Overcast"}
CEILING = ("BKN", "OVC", "OVX")


def decode(metar):
    """The plain-English lines for one airport's METAR ({} or None when it isn't reporting: no lines)."""
    if not metar:
        return []
    lines = []

    def add(label, text):
        if text:
            lines.append({"label": label, "text": text})

    obs = metar.get("obsTime")
    add("Observed", obs.strftime("%d %b %H:%MZ") if obs else None)
    add("Wind", wind(metar))
    add("Visibility", visibility(metar.get("visibilitySM"), metar.get("visibilityMore")))
    add("Weather", weather(metar.get("obs")))
    for n, text in enumerate(clouds(metar.get("skyConditions"), metar.get("vertVisFt"))):
        add("Clouds" if n == 0 else "", text)
    add("Temperature", temperature(metar.get("tempC")))
    add("Dewpoint", dewpoint(metar.get("dewpointC"), metar.get("tempC")))
    altim = metar.get("altimHg")
    add("Altimeter", f"{altim:.2f} inHg" if altim else None)
    add("Lightning", "Lightning observed" if metar.get("lightning") else None)
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


def summary(metar):
    """
    A few sentences about the airport's weather for the Map page's popup, e.g. "Light rain" or "Density altitude
    1,200 ft". Only what the report has; none when it isn't reporting.
    """
    if not metar:
        return []
    temp = metar.get("tempC")
    lines = [
        CATEGORY_TEXT.get(metar.get("flightCategory")),
        weather(metar.get("obs")),
        "Lightning reported" if metar.get("lightning") else None,
        wind_sentence(metar),
        sky_sentence(metar.get("skyConditions"), metar.get("vertVisFt")),
        density_altitude_sentence(metar),
    ]
    spread = temp - metar["dewpointC"] if temp is not None and metar.get("dewpointC") is not None else None
    if spread is not None and spread <= FOG_SPREAD_C:
        lines.append(f"Temperature and dewpoint are {spread}°C apart: fog or low clouds can form")
    moisture = metar.get("obs") or any(layer.get("cover") in CEILING for layer in metar.get("skyConditions") or [])
    if temp is not None and ICING_C[0] <= temp <= ICING_C[1] and moisture:
        lines.append(f"Temperature {temp}°C with clouds or precipitation: icing is possible")
    return [line for line in lines if line]


def wind_sentence(metar):
    """ "Wind from the south at 12 knots, gusting to 20"."""
    speed = metar.get("windSpeed")
    if speed is None:
        return None
    if speed == 0:
        return "Calm wind"
    direction = str(metar.get("windDir") or "").upper()
    gust = f", gusting to {metar['windGustSpeed']}" if metar.get("windGust") else ""
    if not direction.isdigit():  # VRB
        return f"Variable wind at {speed} knots{gust}"
    degrees = int(direction)
    return f"Wind from the {COMPASS[round(degrees / 45) % 8]} ({degrees:03d}°) at {speed} knots{gust}"


def sky_sentence(layers, vert_vis_ft=None):
    """The ceiling (lowest broken or overcast layer), else the lowest clouds, else a clear sky."""
    layers = [layer for layer in layers or [] if layer.get("cover")]
    if not layers:
        return None
    for layer in layers:
        if layer["cover"] == "OVX":
            return "Sky obscured" + (f": vertical visibility {vert_vis_ft:,} ft" if vert_vis_ft else "")
        if layer["cover"] in ("BKN", "OVC") and layer.get("cloudBaseFt"):
            return f"Ceiling {layer['cloudBaseFt']:,} ft ({COVER[layer['cover']].lower()})"
    lowest = layers[0]
    if lowest["cover"] in COVER and lowest.get("cloudBaseFt"):
        return f"No ceiling; {COVER[lowest['cover']].lower()} clouds at {lowest['cloudBaseFt']:,} ft"
    return "Clear skies" if lowest["cover"] in ("CLR", "SKC", "CAVOK", "NSC") else None


def ceiling_ft(layers, vert_vis_ft=None):
    """
    The ceiling in feet: the lowest broken or overcast layer, or the vertical visibility when the sky is obscured.
    None when there's no ceiling (clear, or only few or scattered clouds).
    """
    for layer in layers or []:
        if layer.get("cover") == "OVX":
            return vert_vis_ft or 0
        if layer.get("cover") in ("BKN", "OVC"):
            return layer.get("cloudBaseFt") or 0
    return None


def density_altitude_sentence(metar):
    """ "Density altitude 1,200 ft (field elevation 46 ft)", to the nearest 100 ft."""
    # imported here: the visualizers import this module
    from metarmap.visualizers.density_altitude import calculate_density_altitude, meters_to_feet
    if not metar.get("altimHg") or metar.get("elevation_m") is None or metar.get("tempC") is None:
        return None
    feet = calculate_density_altitude(metar["altimHg"], metar["elevation_m"], metar["tempC"])
    field = meters_to_feet(metar["elevation_m"])
    return f"Density altitude {round(feet, -2):,.0f} ft (field elevation {field:,.0f} ft)"


def wind(metar):
    speed = metar.get("windSpeed")
    if speed is None:
        return None
    direction = str(metar.get("windDir") or "").upper()
    if speed == 0:
        return "Calm"
    gust = f", gusts {metar['windGustSpeed']} kt" if metar.get("windGust") else ""
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
    if len(code) % 2 or any(code[i:i + 2] not in PHENOMENA for i in range(0, len(code), 2)):
        return None
    if not code and not descriptor:
        return None
    return WeatherGroup(group, intensity, vicinity, descriptor, tuple(code[i:i + 2] for i in range(0, len(code), 2)))


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


def clouds(layers, vert_vis_ft=None):
    """One line per cloud layer, lowest first, with the ceiling (the lowest broken or overcast layer) marked."""
    lines, ceiling_found = [], False
    for layer in layers or []:
        cover, base = layer.get("cover", ""), layer.get("cloudBaseFt")
        if cover in ("CLR", "SKC", "CAVOK", "NSC"):
            lines.append("Clear")
            continue
        if cover == "OVX":
            text = "Sky obscured" + (f", vertical visibility {vert_vis_ft:,} ft" if vert_vis_ft else "")
        elif cover in COVER:
            text = f"{COVER[cover]} {base:,} ft" if base else COVER[cover]
        else:
            text = cover
        if cover in CEILING and not ceiling_found:
            text += " (ceiling)"
            ceiling_found = True
        lines.append(text)
    return lines


def temperature(celsius):
    if celsius is None:
        return None
    return f"{celsius}°C / {utils.celsius_to_fahrenheit(celsius):.0f}°F"


def dewpoint(celsius, temperature_c=None):
    text = temperature(celsius)
    if text and temperature_c is not None:
        text += f" (spread {temperature_c - celsius}°C)"
    return text
