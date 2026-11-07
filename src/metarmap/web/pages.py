"""
The web UI's pages. Each page function gathers its template's data from the map's parts and renders it.
"""

import io
import pprint
from typing import TYPE_CHECKING

from metarmap.speech import configured
from metarmap import system
from metarmap.config import MAX_LEDS
from metarmap.leds import intro
from metarmap.settings import LED_ORDERS, LED_PINS, LIGHTNING_COLORS, TRAFFIC_SECONDS
from metarmap.web import views
from metarmap.web.site import render

if TYPE_CHECKING:  # app.py imports the web, so only for the type checker
    from metarmap.app import App


def stations(services: "App"):
    return views.stations(
        services.config.airports,
        services.metars.data,
        services.metars.position,
        services.config.data.led.count,
    )


def index(services: "App", site):
    s = stations(services)
    return render(
        site,
        "index.tpl",
        stations=s,
        fetched=services.metars.lastFetchTime,
        cats=views.CATEGORIES,
        **views.summary(s),
        active=views.visualizer(services.renderer),
        visualizers=views.visualizer_choices(services.renderer),
        brightness=services.renderer.pixels().brightness,
        schedule=views.brightness_schedule(
            services.sun.times,
            services.config.data.led.brightness,
            services.config.data.led.quiet_hours,
        ),
        quiet_hours=services.config.data.led.quiet_hours,
        # the OLED switch only shows when the screen is turned on in Config
        oled_on=services.display.on if services.config.data.display_screen.enabled else None,
    )


def metars(services: "App", site):
    s = stations(services)
    return render(
        site,
        "metars.tpl",
        stations=s,
        fetched=services.metars.lastFetchTime,
        cats=views.CATEGORIES,
        speech=configured(services.config.data.speech),  # an AWOS button per airport: only with a speech server
        **views.summary(s),
    )


def map_page(services: "App", site):
    settings = views.map_settings(services.config.data.geo.map, site.sectionals, stations(services))
    return render(
        site,
        "map.tpl",
        settings=settings,
        active=views.visualizer(services.renderer),
        brightness=services.renderer.pixels().brightness,
    )


def remote(services: "App", site):
    """A remote control for the map, laid out for an iPad in kiosk mode."""
    s = stations(services)
    return render(
        site,
        "remote.tpl",
        stations=s,
        cats=views.CATEGORIES,
        settings=views.map_settings(services.config.data.geo.map, site.sectionals, s),
        active=views.visualizer(services.renderer),
        visualizers=views.visualizer_choices(services.renderer),
        brightness=services.renderer.pixels().brightness,
        auto_rotate=services.config.data.visualizer.auto_rotate.enabled,
        oled_on=services.display.on if services.config.data.display_screen.enabled else None,
        speech=configured(services.config.data.speech),  # the AWOS tab: only with a speech server to read aloud
    )


def legend(services: "App", site):
    """The active visualizer's legend on its own: the Map page swaps it in when the visualizer changes."""
    return render(site, "legend.tpl", legend=views.visualizer(services.renderer)["legend"])


def debug(services: "App", site):
    renderer = services.renderer
    return render(
        site,
        "debug.tpl",
        active=views.visualizer(renderer),
        fetched=services.metars.lastFetchTime,
        looks=renderer.looks,
        strip_look=renderer.strip_look,
        rows=list(enumerate(zip(services.metars.data, renderer.looks))),
    )


# Spoken weather's voice list: English Piper voices that Home Assistant's add-on has (any other can be typed)
SPEECH_VOICES = (
    "en_US-lessac-low",
    "en_US-lessac-medium",
    "en_US-lessac-high",
    "en_US-amy-medium",
    "en_US-ryan-medium",
    "en_US-ryan-high",
    "en_US-joe-medium",
    "en_US-john-medium",
    "en_US-kristin-medium",
    "en_US-hfc_female-medium",
    "en_US-hfc_male-medium",
    "en_GB-alan-medium",
    "en_GB-cori-high",
    "en_GB-jenny_dioco-medium",
)


# Kokoro's better-rated English voices (its own grades); any other it has can be typed
KOKORO_VOICES = (
    "af_heart",
    "af_bella",
    "af_nicole",
    "af_sarah",
    "af_kore",
    "af_aoede",
    "am_michael",
    "am_fenrir",
    "am_puck",
    "bf_emma",
    "bf_isabella",
    "bm_george",
    "bm_fable",
)


def config(services: "App", site):
    settings = views.map_settings(services.config.data.geo.map, site.sectionals, stations(services))
    return render(
        site,
        "config.tpl",
        d=services.config.data,
        visualizers=views.visualizer_choices(services.renderer),
        rotation=views.rotation(services.renderer, services.config.data.visualizer.auto_rotate.skip),
        map_settings=settings,
        sectionals=site.sectionals,
        chart_types=views.CHART_TYPES,
        led_pins=LED_PINS,
        led_orders=LED_ORDERS,
        init_sequences=intro.NAMES,
        sweep_sides={side: name for side, (name, _) in intro.SWEEP_FROM.items()},
        lightning_colors=LIGHTNING_COLORS,
        traffic_seconds=TRAFFIC_SECONDS,
        # the login user's password only changes on a Raspberry Pi with the map running as root
        linux_user=system.login_user() if system.can_set_login_password() else None,
        wifi=system.current_wifi(),
        speech_voices=SPEECH_VOICES,
        kokoro_voices=KOKORO_VOICES,
        first_airport=next((a.code for a in services.config.airports if a.code), ""),  # Spoken weather's Test
    )


def airports(services: "App", site):
    config = services.config
    count, virtual = config.data.led.count, config.data.led.virtual_count
    leds = views.leds(config.airports, count)
    with_airport = len([led for led in leds if led["code"]])
    return render(
        site,
        "airports.tpl",
        leds=leds,
        with_airport=with_airport,
        without_airport=len(leds) - with_airport,
        count=count,
        virtual=virtual,
        strip_leds=len(services.renderer.pixels()),
        max_leds=MAX_LEDS,
        dev_mode=config.data.dev_mode,
    )


def raw(services: "App"):
    data = services.metars.data
    buf = io.StringIO()
    buf.write("".join(f"<b>{s}</b>: {data[s].raw if data[s] else 'N/A'}<br />" for s in data.keys()))
    buf.write(f"<pre><code>{pprint.pformat(data, indent=4)}</code></pre>")
    return buf.getvalue()


def raw_code(services: "App", code):
    return "<b>" + code + "</b>: " + services.metars.data[code].raw + "<br />"


def add_routes(app, services: "App", site, auth):
    app.route("/", "GET", lambda: index(services, site))
    app.route("/metars", "GET", lambda: metars(services, site))
    app.route("/map", "GET", lambda: map_page(services, site))
    app.route("/map/legend", "GET", lambda: legend(services, site))
    app.route("/remote", "GET", lambda: remote(services, site))
    app.route("/debug", "GET", lambda: debug(services, site))
    app.route("/raw", "GET", lambda: raw(services))
    app.route("/raw/<code>", "GET", lambda code: raw_code(services, code))
    app.route("/config", "GET", lambda: config(services, site), apply=auth)
    app.route("/config/airports", "GET", lambda: airports(services, site), apply=auth)
