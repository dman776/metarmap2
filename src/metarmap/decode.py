"""
A METAR in plain English, for the Map page's Decoded tab: one {"label", "text"} line per item the report has.

Works on the dict metar.METAR builds for each airport. Weather codes follow the FAA's METAR key (FMH-1, chapter 12:
intensity, descriptor, then precipitation, obscuration or other phenomena).
"""
from fractions import Fraction

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


def weather_group(group):
    code = group
    intensity, vicinity = "", False
    if code[:1] in INTENSITY:
        intensity, code = INTENSITY[code[0]], code[1:]
    if code.startswith("VC"):
        vicinity, code = True, code[2:]
    descriptor = None
    if code[:2] in DESCRIPTORS:
        descriptor, code = code[:2], code[2:]
    if len(code) % 2 or any(code[i:i + 2] not in PHENOMENA for i in range(0, len(code), 2)):
        return group  # not a code we know
    names = [PHENOMENA[code[i:i + 2]] for i in range(0, len(code), 2)]

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
    if vicinity:
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
