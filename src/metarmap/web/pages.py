"""
The web UI's pages. Each page function gathers its template's data from the map's parts and renders it.
"""
import io
import pprint

from metarmap import system
from metarmap.config import MAX_LEDS
from metarmap.web import views
from metarmap.web.site import render


def stations(services):
    return views.stations(services.config.airports, services.metars.data, getattr(services.metars, "position", None),
                          services.config.data.led.count)


def index(services, site):
    s = stations(services)
    return render(site, "index.tpl",
                  stations=s, fetched=services.metars.lastFetchTime, cats=views.CATEGORIES, **views.summary(s),
                  active=views.visualizer(services.renderer), visualizers=views.visualizer_names(services.renderer),
                  brightness=services.renderer.pixels().brightness,
                  schedule=views.sun_schedule(services.sun.times, services.config.data.led.brightness),
                  # the OLED switch only shows when the screen is turned on in Config
                  oled_on=services.display.on if services.config.data.display_screen.enabled else None)


def metars(services, site):
    s = stations(services)
    return render(site, "metars.tpl", stations=s, fetched=services.metars.lastFetchTime, cats=views.CATEGORIES,
                  **views.summary(s))


def map_page(services, site):
    settings = views.map_settings(services.config.data.geo.map, site.sectionals, stations(services))
    return render(site, "map.tpl", settings=settings, active=views.visualizer(services.renderer),
                  brightness=services.renderer.pixels().brightness)


def legend(services, site):
    """The active visualizer's legend on its own: the Map page swaps it in when the visualizer changes."""
    return render(site, "legend.tpl", legend=views.visualizer(services.renderer)["legend"])


def debug(services, site):
    renderer = services.renderer
    return render(site, "debug.tpl", active=views.visualizer(renderer), fetched=services.metars.lastFetchTime,
                  looks=renderer.looks, strip_look=renderer.strip_look,
                  rows=list(enumerate(zip(services.metars.data, renderer.looks))))


def config(services, site):
    settings = views.map_settings(services.config.data.geo.map, site.sectionals, stations(services))
    return render(site, "config.tpl", d=services.config.data, visualizers=views.visualizer_names(services.renderer),
                  rotation=views.rotation(services.renderer, services.config.data.visualizer.auto_rotate.skip),
                  map_settings=settings, sectionals=site.sectionals, chart_types=views.CHART_TYPES,
                  # the login user's password only changes on a Raspberry Pi with the map running as root
                  linux_user=system.login_user() if system.can_set_login_password() else None,
                  wifi=system.current_wifi())


def airports(services, site):
    config = services.config
    count, virtual = config.data.led.count, config.data.led.virtual_count
    leds = views.leds(config.airports, count)
    with_airport = len([led for led in leds if led["code"]])
    return render(site, "airports.tpl", leds=leds, with_airport=with_airport, without_airport=len(leds) - with_airport,
                  count=count, virtual=virtual, strip_leds=len(services.renderer.pixels()), max_leds=MAX_LEDS)


def raw(services):
    data = services.metars.data
    buf = io.StringIO()
    buf.write("".join(f"<b>{s}</b>: {data[s].get('raw', 'N/A')}<br />" for s in data.keys()))
    buf.write(f"<pre><code>{pprint.pformat(data, indent=4)}</code></pre>")
    return buf.getvalue()


def raw_code(services, code):
    return "<b>" + code + "</b>: " + services.metars.data[code]['raw'] + "<br />"


def add_routes(app, services, site, auth):
    app.route("/", "GET", lambda: index(services, site))
    app.route("/metars", "GET", lambda: metars(services, site))
    app.route("/map", "GET", lambda: map_page(services, site))
    app.route("/map/legend", "GET", lambda: legend(services, site))
    app.route("/debug", "GET", lambda: debug(services, site))
    app.route("/raw", "GET", lambda: raw(services))
    app.route("/raw/<code>", "GET", lambda code: raw_code(services, code))
    app.route("/config", "GET", lambda: config(services, site), apply=auth)
    app.route("/config/airports", "GET", lambda: airports(services, site), apply=auth)
