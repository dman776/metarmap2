"""
Precipitation: shows each airport's observed weather (rain, snow, fog, thunderstorms...).
"""
import metarmap.lib.colors as colors_lib
import metarmap.lib.safe_logging as safe_logging
from metarmap.models import Look, Metar
from metarmap.visualizers.visualizer import legend_item

NAME = "Precipitation"
DESCRIPTION = "Display the current observed precipitation."
EXCLUSIVE = True


def legend(settings):
    c = colors_lib.get_colors()
    w = settings.color.weather
    return [
        legend_item("None", "Off"),
        legend_item("Haze", "Dark gray", w.haze),
        legend_item("Fog", "Dim white, pulsing every 4 seconds", w.fog, effect="pulse", period=4),
        legend_item("Light drizzle", "Green, pulsing every 4 seconds", w.drizzle, effect="pulse", period=4),
        legend_item("Drizzle", "Solid green", w.drizzle),
        legend_item("Light freezing drizzle", "Green, fast pulse", w.drizzle, effect="pulse", period=0.5),
        legend_item("Mist", "Dark blue", w.mist),
        legend_item("Light rain", "Blue, pulsing every 4 seconds", w.rain, effect="pulse", period=4),
        legend_item("Rain", "Solid blue", w.rain),
        legend_item("Light freezing rain", "Blue, pulsing every 2 seconds", w.rain, effect="pulse", period=2),
        legend_item("Heavy rain", "Blinking blue", w.rain, effect="blink", period=2),
        legend_item("Thunderstorms", "Blinking yellow", w.lightning, effect="blink", period=2),
        legend_item("Light snow", "White, pulsing every 2 seconds", c[colors_lib.WHITE], effect="pulse", period=2),
        legend_item("Snow", "White, pulsing every second", c[colors_lib.WHITE], effect="pulse", period=1),
        legend_item("Light unknown precipitation", "Blinking light red", c[colors_lib.LIGHT_RED],
                    effect="blink", period=2),
        legend_item("Other / unknown", "Blinking red", c[colors_lib.RED], effect="blink", period=2),
    ]


def look(metar: Metar, settings) -> Look:
    if not metar:
        return Look.off()
    return look_for_weather(metar['obs'], settings)


def look_for_weather(obs: str, settings) -> Look:
    """
    Given the observed weather codes from a METAR (e.g. "-RA BR"), return how the LED looks.
    The first matching code wins.
    """
    named = colors_lib.get_colors()
    w = settings.color.weather

    if obs is None or obs == "":
        return Look.off()
    if "VCTS" in obs or "TS" in obs:
        return Look.blink(w.lightning)
    if "-FZDZ" in obs:
        return Look.pulse(w.drizzle, period=0.5)
    if "-FZRA" in obs:
        return Look.pulse(w.rain, period=2)
    if "-SN" in obs:
        return Look.pulse(named[colors_lib.WHITE], period=2)
    if "SN" in obs:
        return Look.pulse(named[colors_lib.WHITE], period=1)
    if "-RA" in obs:
        return Look.pulse(w.rain, period=4)
    if "RA" in obs:
        return Look.solid(w.rain)
    if "+RA" in obs:  # never reached: "RA" above already matches heavy rain
        return Look.blink(w.rain)
    if "-DZ" in obs:
        return Look.pulse(w.drizzle, period=4)
    if "DZ" in obs:
        return Look.solid(w.drizzle)
    if "FG" in obs:
        return Look.pulse(w.fog, period=4)
    if "HZ" in obs:
        return Look.solid(w.haze)
    if "BR" in obs:
        return Look.solid(w.mist)
    if "-UP" in obs:
        return Look.blink(named[colors_lib.LIGHT_RED])
    if "UP" in obs:
        return Look.blink(named[colors_lib.RED])
    safe_logging.safe_log("[v]missing observation code=" + str(obs))
    return Look.blink(named[colors_lib.RED])
