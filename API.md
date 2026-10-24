# METARMap Web API

The map runs a [Bottle](https://bottlepy.org) web server on the port set by `web_server.port` in [config.json](config.json) (default `80`).
Every endpoint uses `GET`. Most endpoints return the web UI's HTML pages. `/api/status` is the only one that returns JSON, so use it to read the map's state from scripts and integrations such as [Home Assistant](https://github.com/dman776/metarmap2_ha).

```
http://<map-host>[:port]/<endpoint>
```

## Authentication

Endpoints marked **auth** use HTTP Basic authentication. The credentials are `web_server.user` and `web_server.password` in `config.json`; the defaults are `metar` / `map`, and you should change them. The username comparison ignores the case of what the client sends, so keep `web_server.user` lowercase.

```sh
curl -u metar:map http://metarmap.local/config
```

## Status (JSON)

### `GET /api/status`

Returns a read-only snapshot of the map's state as `application/json`. No authentication.

```json
{
  "version": "1.16.2",
  "ip": "192.168.1.50",
  "brightness": 0.5,
  "visualizer": {
    "active": 0,
    "name": "Flight Category",
    "exclusive": false,
    "description": "Display the flight category (ie. VFR, MVFR, IFR, LIFR).",
    "legend": [
      { "label": "VFR", "detail": "Green", "colors": ["#00ff00"], "effect": "solid", "period": null },
      { "label": "Flight category missing", "detail": "Blinking red (other METAR data is available)",
        "colors": ["#ff0000"], "effect": "blink", "period": 2 }
    ]
  },
  "visualizers": [
    { "index": 0, "name": "Flight Category", "exclusive": false },
    { "index": 1, "name": "Wind", "exclusive": false }
  ],
  "config": {
    "visualizer.active": 0,
    "visualizer.auto_rotate.enabled": false,
    "visualizer.auto_rotate.delay_seconds": 60,
    "lightning.animation": true,
    "display_screen.enabled": true,
    "display_screen.locate_active": true,
    "display_screen.delay": 5.0,
    "led.inittest": true,
    "led.brightness.normal": 0.5,
    "led.brightness.dimmed": 0.1,
    "led.brightness.off": 0.01
  },
  "suntimes": {
    "dawn": "2026-10-23T07:00:12-05:00",
    "sunrise": "2026-10-23T07:25:40-05:00",
    "sunset": "2026-10-23T18:45:03-05:00",
    "dusk": "2026-10-23T19:10:31-05:00"
  },
  "lastFetchTime": "2026-10-23T12:00:00.123456",
  "missingStations": ["KXYZ"],
  "airports": [
    {
      "code": "KGLS",
      "pixel": 5,
      "text": "Galveston",
      "display": true,
      "flightCategory": "IFR",
      "raw": "KGLS 231753Z 00000KT 2SM BR OVC004 24/23 A3000",
      "windDir": "0",
      "windSpeed": 0,
      "windGustSpeed": 0,
      "vis": 2,
      "obs": "BR",
      "tempC": 24,
      "dewpointC": 23,
      "altimHg": 30.0,
      "lightning": false,
      "obsTime": "2026-10-23T17:53:00+00:00"
    }
  ]
}
```

| Field | Description |
|---|---|
| `version` | metarmap2 software version |
| `ip` | IP address of the map |
| `brightness` | Current LED brightness, `0.0`–`1.0` |
| `visualizer` | The visualizer that is running now. `exclusive` visualizers ignore `/locate`. |
| `visualizer.legend` | What the LEDs mean for that visualizer. `colors` are CSS hex colors; two or more mean a gradient across the range. `effect` is `solid`, `blink`, `pulse`, `flash` (the first color with flashes of the second), `chase` or `off`. `period` is the seconds per blink or pulse, or `null`. |
| `visualizers` | Every visualizer, in index order (the indexes used by `/visualizer/<n>`) |
| `config` | The saved `config.json` values, keyed by the dotted path accepted by `/config/edit` |
| `suntimes` | Today's dimming schedule (ISO 8601 with time zone) |
| `lastFetchTime` | When METARs were last fetched, in the map's local time (ISO 8601, no time zone); `null` before the first fetch |
| `missingStations` | Airports that had no METAR in the last fetch |
| `airports` | Airports in `airports.json` order. `pixel` is the LED index. `text` and `display` are the OLED settings. The METAR fields are `null` when the map has no data for the airport. `windDir` is a string because it can be `VRB`. |

### `GET /api/live`

What the physical map is doing right now. The Map page polls it every second. No authentication.

```json
{
  "now": 1792854523.9,
  "brightness": 0.5,
  "visualizer": { "active": 0, "name": "Flight Category", "exclusive": false },
  "strip": null,
  "leds": [
    { "code": "KLBX", "pixel": 4, "name": "", "lat": 29.11, "lon": -95.46, "flightCategory": "IFR",
      "raw": "KLBX 241453Z ... LTG DSNT", "lightning": true,
      "look": { "effect": "cycle", "colors": ["#ff0000", "...", "#ffff00"], "step": 0.1 } }
  ],
  "locate": { "pixel": 5, "at": 1792854523.96 },
  "display": {
    "enabled": true,
    "screen": { "airport": "KGLS", "title": "KGLS", "badge": "LIFR", "page": 1,
                "lines": [ { "icon": "wind", "text": "150@08" }, { "icon": "visibility", "text": "1SM" },
                           { "icon": "pressure", "text": "29.98" } ] }
  }
}
```

| Field | Description |
|---|---|
| `leds[].look` | The LED's current effect: `solid`, `off`, `blink` (`period` seconds per on/off cycle), `pulse` (`period`), or `cycle` (steps through `colors`, `step` seconds each). Colors are CSS hex colors. |
| `strip` | Set when one effect drives the whole strip instead: `rainbow` (`period`) or `chase` (`step`, `size`, `spacing`). |
| `locate` | The last white locate pulse: LED `pixel` and Unix time `at`. `null` until the first one. |
| `display.screen` | What the OLED shows. `page` is 1 or 2 for an airport, 0 for "Data Unavailable" or a message (then `airport` is `null`). Icons: `wind`, `visibility`, `pressure`, `temp`, `dewpoint`, `date`. |

## Control

These endpoints change the map immediately. Nothing they change is saved to `config.json`, so the changes are lost on restart. Each one returns the HTML of a UI page; ignore it.

| Endpoint | Description |
|---|---|
| `GET /brightness/<level>` | Set LED brightness, `0.0`–`1.0`; the map ignores values outside that range. The dimming schedule overrides it at the next dawn, sunrise, sunset or dusk. |
| `GET /visualizer/<n>` | Switch to visualizer number `n` (see the table below) |
| `GET /visualizer/next` | Next visualizer; after the last one it goes back to the first |
| `GET /visualizer/previous` | Previous visualizer; before the first one it goes to the last |
| `GET /locate/<pixel>` | Pulse one LED white. Ignored while an exclusive visualizer is running. |
| `GET /fetch` | Fetch METARs from aviationweather.gov now. **The request does not return until the fetch finishes**, which can take up to about 30 seconds. |

Visualizer indexes:

| # | Name | Exclusive |
|---|---|---|
| 0 | Flight Category | |
| 1 | Wind | |
| 2 | Wind Gusts | |
| 3 | Pressure | |
| 4 | Precipitation | yes |
| 5 | Temperature | |
| 6 | Visibility | |
| 7 | Density Altitude | |
| 8 | Rainbow | yes |
| 9 | Chase | yes |

```sh
curl http://metarmap.local/brightness/0.25
curl http://metarmap.local/visualizer/1
```

## Configuration (auth)

### `GET /config/edit/<key>/<value>`

Saves one value to `config.json`, then refreshes the active visualizer. `key` is the dotted path to the setting, such as `lightning.animation` or `display_screen.delay`.

- **Booleans:** send `true` or `false`.
- **Numbers:** send them as-is, for example `5` or `0.25`.
- **Strings:** URL-encode them, for example `geo.map.chart` → `Dallas-Ft%20Worth`. Quoting them (`%22Dallas%22`) also still works.

The server runs the value as Python code. Only give this endpoint's credentials to people you trust.

Settings that apply right away:
- `lightning.animation`
- `display_screen.locate_active`
- `display_screen.delay`
- `visualizer.active`, the default visualizer used at startup. Saving it doesn't change the visualizer that's running now; use `/visualizer/<n>` for that.

Settings that need a restart:
- `display_screen.enabled`
- `led.inittest`
- `visualizer.auto_rotate.enabled`
- `visualizer.auto_rotate.delay_seconds`

Map page settings (apply the next time the Map page is opened):
- `geo.map.background`: `sectional`, `satellite` or `radar`
- `geo.map.chart_type`: `sectional`, `terminal` (VFR Terminal Area) or `ifr_low` (IFR Enroute Low)
- `geo.map.chart`: the sectional name, as listed in [static/sectionals.json](static/sectionals.json), such as `Houston`. If it's missing or unknown, the map uses the sectional that covers the most airports.
- `geo.map.view`: `airports` (fit to the airports), `chart` (the whole sectional) or `custom` (`geo.map.center` and `geo.map.zoom`)

The map loads `led.brightness.normal`, `led.brightness.dimmed` and `led.brightness.off` at midnight or when it restarts.

```sh
curl -u metar:map http://metarmap.local/config/edit/lightning.animation/false
curl -u metar:map http://metarmap.local/config/edit/display_screen.delay/10
```

### Airports

| Endpoint | Description |
|---|---|
| `GET /config/airports/edit/<oldcode>/<newcode>` | Rename an airport. Its position on the map (pixel) stays the same. |
| `GET /config/airports/edit/prop/<airport>/<key>/<value>` | Set one property of an airport in `airports.json`: `text` (the label on the OLED display) or `display` (`true`/`false`, whether it appears on the display) |

Both save `airports.json`, restart the OLED display loop, and redirect to `/config/airports`.

## Maintenance (auth)

| Endpoint | Description |
|---|---|
| `GET /update` | Runs `git reset --hard` and `git pull` in the install directory, keeping `config.json` and `airports.json`. Returns the output as HTML. Restart afterwards to use the new code. |
| `GET /restart` | Clears the LEDs and restarts the controller process. The connection usually drops before a response is sent. |

## Web UI pages

| Endpoint | Auth | Description |
|---|---|---|
| `GET /` | | Home: flight category counts, visualizer controls and legend, brightness and sun times |
| `GET /metars` | | Table of METARs for every airport |
| `GET /map` | | Live mirror of the LEDs and the OLED screen on an FAA chart, satellite or radar background |
| `GET /raw` | | Raw METAR text for every airport, followed by the full parsed data |
| `GET /raw/<code>` | | Raw METAR text for one airport |
| `GET /debug` | | Debug information |
| `GET /config` | yes | Configuration page |
| `GET /config/airports` | yes | Airport configuration page |
| `GET /static/<file>` | | Stylesheet and script for the web UI |
