"""
The web UI's pages. Each page function gathers its template's data from the map's parts and renders it.
"""
import io
import pprint

from metarmap.config import MAX_LEDS
from metarmap.web import views
from metarmap.web.site import render


def stations(services):
    return views.stations(services.config.airports, services.metars.data)


def index(services, site):
    s = stations(services)
    return render(site, "index.tpl",
                  stations=s, fetched=services.metars.lastFetchTime, cats=views.CATEGORIES, **views.summary(s),
                  active=views.visualizer(services.renderer), visualizers=views.visualizer_names(services.renderer),
                  brightness=services.renderer.pixels().brightness,
                  schedule=views.sun_schedule(services.sun.times, services.config.data.led.brightness))


def metars(services, site):
    s = stations(services)
    return render(site, "metars.tpl", stations=s, fetched=services.metars.lastFetchTime, cats=views.CATEGORIES,
                  **views.summary(s))


def map_page(services, site):
    settings = views.map_settings(services.config.data.geo.map, site.sectionals, stations(services))
    return render(site, "map.tpl", settings=settings, active=views.visualizer(services.renderer),
                  brightness=services.renderer.pixels().brightness)


def debug(services, site):
    renderer = services.renderer
    return render(site, "debug.tpl", active=views.visualizer(renderer), fetched=services.metars.lastFetchTime,
                  looks=renderer.looks, strip_look=renderer.strip_look,
                  rows=list(enumerate(zip(services.metars.data, renderer.looks))))


def config(services, site):
    settings = views.map_settings(services.config.data.geo.map, site.sectionals, stations(services))
    return render(site, "config.tpl", d=services.config.data, visualizers=views.visualizer_names(services.renderer),
                  map_settings=settings, sectionals=site.sectionals, chart_types=views.CHART_TYPES)


def airports(services, site):
    config = services.config
    return render(site, "airports.tpl", leds=views.leds(config.airports, config.data.led.count),
                  count=config.data.led.count, strip_leds=len(services.renderer.pixels()), max_leds=MAX_LEDS)


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
    app.route("/debug", "GET", lambda: debug(services, site))
    app.route("/raw", "GET", lambda: raw(services))
    app.route("/raw/<code>", "GET", lambda code: raw_code(services, code))
    app.route("/config", "GET", lambda: config(services, site), apply=auth)
    app.route("/config/airports", "GET", lambda: airports(services, site), apply=auth)
