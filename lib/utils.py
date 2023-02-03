from datetime import datetime

try:
    import lib.safe_logging as safe_logging
except ModuleNotFoundError as e:
    import safe_logging as safe_logging

def get_sun_times(config):
    import astral.geocoder
    import astral.sun

    try:
        city = astral.geocoder.lookup(config.data().dimming.dynamic_base.location, astral.geocoder.database())
    except KeyError:
        safe_logging.safe_log("Error: Location not recognized, please check list of supported cities and reconfigure")
    else:
        safe_logging.safe_log(city)
        sun = astral.sun.sun(city.observer, date=datetime.now().date(), tzinfo=city.timezone)

        DAWN = sun['dawn'].time()
        SUNRISE = sun['sunrise'].time()
        SUNSET = sun['sunset'].time()
        DUSK = sun['dusk'].time()

        safe_logging.safe_log("Dawn=" + DAWN.strftime('%H:%M') +
                              " Sunrise=" + SUNRISE.strftime('%H:%M') +
                              " Sunset=" + SUNSET.strftime('%H:%M') +
                              " Dusk=" + DUSK.strftime('%H:%M'))

    return DAWN, SUNRISE, SUNSET, DUSK