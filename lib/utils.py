from datetime import datetime

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

def get_sun_times(config):
    import astral.geocoder
    import astral.sun

    try:
        city = astral.geocoder.lookup(config.data().dimming.dynamic_base.location, astral.geocoder.database())
    except KeyError:
        safe_logging.safe_log("Error: Location not recognized, please check list of supported cities and reconfigure")
    else:
        safe_logging.safe_log("[u]" + str(city))
        sun = astral.sun.sun(city.observer, date=datetime.now().date(), tzinfo=city.timezone)

        DAWN = sun['dawn'].time()
        SUNRISE = sun['sunrise'].time()
        SUNSET = sun['sunset'].time()
        DUSK = sun['dusk'].time()

        safe_logging.safe_log("[u]" + "Dawn=" + DAWN.strftime('%H:%M') +
                              " Sunrise=" + SUNRISE.strftime('%H:%M') +
                              " Sunset=" + SUNSET.strftime('%H:%M') +
                              " Dusk=" + DUSK.strftime('%H:%M'))

    return DAWN, SUNRISE, SUNSET, DUSK

def find_in_list(akey, avalue, alist):
    return list(filter(lambda alist: alist[akey] == avalue, alist))