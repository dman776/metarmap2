from datetime import datetime
import io
import os
import sys
import subprocess
import shutil

try:
    import lib.safe_logging as safe_logging
except ModuleNotFoundError as e:
    import safe_logging as safe_logging


def wheel(pos):
    # Input a value 0 to 255 to get a color value.
    # The colours are a transition r - g - b - back to r.
    if pos < 0 or pos > 255:
        r = g = b = 0
    elif pos < 85:
        r = int(pos * 3)
        g = int(255 - pos * 3)
        b = 0
    elif pos < 170:
        pos -= 85
        r = int(255 - pos * 3)
        g = 0
        b = int(pos * 3)
    else:
        pos -= 170
        r = 0
        g = int(pos * 3)
        b = int(255 - pos * 3)
    return r, g, b


def get_location(city):
    import astral.geocoder
    import astral.sun
    try:
        return astral.geocoder.lookup(city, astral.geocoder.database())
    except KeyError:
        safe_logging.safe_log("Error: Location not recognized, please check list of supported cities and reconfigure")


def get_sun_times(config):
    import astral.geocoder
    import astral.sun

    try:
        city = get_location(config.data.geo.city)
    except KeyError:
        safe_logging.safe_log("Error: Location not recognized, please check list of supported cities and reconfigure")
    else:
        safe_logging.safe_log("[u]" + str(city))
        sun = astral.sun.sun(city.observer, date=datetime.now().date(), tzinfo=city.timezone)
        DAWN = sun['dawn']
        SUNRISE = sun['sunrise']
        SUNSET = sun['sunset']
        DUSK = sun['dusk']
    return DAWN, SUNRISE, SUNSET, DUSK


def find_in_list(akey, avalue, alist):
    return list(filter(lambda alist: alist[akey] == avalue, alist))


def index_in_list(akey, alist):
    return list(alist.keys()).index(akey)


def get_proportion_between_floats(
    start: float,
    current: float,
    end: float
):
    """
    Gets the "distance" (0.0 to 1.0) between the start and the end where the current is.
    IE:
        If the Current is the same as Start, then the result will be 0.0
        If the Current is the same as the End, then the result will be 1.0
        If the Current is halfway between Start and End, then the result will be 0.5
    Arguments:
        start {float} -- The starting temp.
        current {float} -- The temp we want to get the proportion for.
        end {float} -- The end temp to calculate the interpolaton for.
    Returns:
        float -- The amount of interpolaton for Current between Start and End
    """

    total_delta = (end - start)
    time_in = (current - start)

    return time_in / total_delta


def celsius_to_fahrenheit(temperature_celsius: float):
    """
    Converts a temperature in celsius to fahrenheit.
    Args:
        temperature_celsius (float): A temperature in C
    Returns:
        [type]: The temperature converted to F
    """
    if temperature_celsius is None:
        return 0

    return (temperature_celsius * (9.0 / 5.0)) + 32.0


def update():
    buf = io.StringIO()

    buf.write(safe_logging.safe_log("[u]starting update... "))
    buf.write(safe_logging.safe_log("[u]saving config files to /tmp... "))
    shutil.copy2(os.getcwd() + "/config.json", "/tmp")
    shutil.copy2(os.getcwd() + "/airports.json", "/tmp")
    buf.write(safe_logging.safe_log("[u]git reset... "))
    result = subprocess.run(["/usr/bin/git", "reset", "--hard"], capture_output=True, text=True)
    buf.write(safe_logging.safe_log("[u]" + result.stdout))
    buf.write(safe_logging.safe_log("[u]updating from github... " + os.getcwd()))
    result2 = subprocess.run(["/usr/bin/git", "pull"], capture_output=True, text=True)
    buf.write(safe_logging.safe_log("[u]" + result2.stdout))
    buf.write(safe_logging.safe_log("[u]restoring config files from /tmp... "))
    shutil.copy2("/tmp/config.json", os.getcwd())
    shutil.copy2("/tmp/airports.json", os.getcwd())
    buf.write(safe_logging.safe_log("[u]update complete"))
    buf.seek(0)
    return buf.read()


def restart():
    safe_logging.safe_log("[u]restarting... " + os.path.abspath(sys.argv[0]))
    os.execl(sys.executable, os.path.abspath(sys.argv[0]), *sys.argv)


def is_pingable(site="www.aviationweather.gov"):
    return subprocess.run(["ping", "-c", "1", site], capture_output=True).returncode
