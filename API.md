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
    "visualizer.auto_rotate.skip": [],
    "lightning.animation": true,
    "display_screen.enabled": true,
    "display_screen.locate_active": true,
    "display_screen.delay": 5.0,
    "led.inittest": true,
    "led.dim_on_refresh": true,
    "led.brightness.normal": 0.5,
    "led.brightness.dimmed": 0.1,
    "led.brightness.off": 0.01
  },
  "display": { "enabled": true, "on": true },
  "suntimes": {
    "dawn": "2026-10-23T07:00:12-05:00",
    "sunrise": "2026-10-23T07:25:40-05:00",
    "sunset": "2026-10-23T18:45:03-05:00",
    "dusk": "2026-10-23T19:10:31-05:00"
  },
  "build": {
    "tag": "v2.9.2",
    "ahead": 3,
    "commit": "5c3e5a5",
    "sha": "5c3e5a5…",
    "modified": false,
    "release": false,
    "untagged": false,
    "describe": "v2.9.2+3",
    "chip": "v2.9.2 +3 · 5c3e5a5",
    "pill": "Unreleased: 3 commits after v2.9.2",
    "url": "https://github.com/dman776/metarmap2/commit/5c3e5a5…"
  },
  "update": {
    "current": "2.8.4",
    "channel": "releases",
    "commit": "41cd311",
    "available": "v2.9.0",
    "installed": null,
    "releases": ["v2.9.0", "v2.8.4", "v2.8.2"],
    "checked": "2026-10-26T14:00:00+00:00",
    "error": null
  },
  "lastFetchTime": "2026-10-23T12:00:00.123456",
  "missingStations": ["KXYZ"],
  "airports": [
    {
      "code": "KGLS",
      "pixel": 5,
      "text": "Galveston",
      "display": true,
      "virtual": false,
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
| `build` | What's running, read when the map started: `tag` is the release it's at or after (`null` if none), `ahead` how many commits after it, `commit` and `sha` the commit, `modified` whether the code was changed on the map itself (`config.json` and `airports.json` don't count). `release` is true on a release exactly; otherwise `pill` says why not ("Unreleased: 3 commits after v2.9.2", "Not tagged: v2.9.3" when `untagged`, "Pre-release: v2.9.0-rc1", "Modified: local changes to v2.9.2", "Unreleased: no release tag"). `chip` is the header's version text and `url` the commit on GitHub (`null` if the map isn't from GitHub). `null` outside a git checkout. |
| `update` | What's newest on GitHub: `current` is the running version, `commit` the running commit, `available` the release (or, on the `latest` channel, the commit) an update would install, or `null` when up to date; `installed` is what an update installed that needs a restart; `releases` lists the releases that can be installed, newest first; `checked` is when GitHub was last asked, and `error` why that failed. `null` if the map doesn't check. |
| `visualizer` | The visualizer that is running now. `exclusive` visualizers ignore `/locate`. |
| `visualizer.legend` | What the LEDs mean for that visualizer. `colors` are CSS hex colors; two or more mean a gradient across the range. `effect` is `solid`, `blink`, `pulse`, `flash` (the first color with flashes of the second), `chase` or `off`. `period` is the seconds per blink or pulse, or `null`. |
| `visualizers` | Every visualizer, in index order (the indexes used by `/visualizer/<n>`) |
| `config` | The saved `config.json` values, keyed by the dotted path accepted by `/config/edit` |
| `display` | The OLED screen: `enabled` is the Config setting (`display_screen.enabled`); `on` is whether it's showing now (false after `/display/off`, or when not enabled) |
| `suntimes` | Today's dimming schedule (ISO 8601 with time zone) |
| `lastFetchTime` | When METARs were last fetched, in the map's local time (ISO 8601, no time zone); `null` before the first fetch |
| `missingStations` | Airports that had no METAR in the last fetch |
| `airports` | Airports in LED order, skipping LEDs with no airport. `pixel` is the LED index (counting from 0). `text` is the airport's name (`""` if none) and `display` whether it's shown on the OLED. `virtual` is true for a virtual airport (after the LEDs, `pixel` at least `led.count`): no LED, so only on the Map page, here, and on the OLED if `display` is on (its code in a dashed box). An airport on two LEDs is listed twice. The METAR fields are `null` when the map has no data for the airport. `windDir` is a string because it can be `VRB`. |

### `GET /api/live`

What the physical map is doing right now. The Map page polls it every second. No authentication.

```json
{
  "now": 1792854523.9,
  "brightness": 0.5,
  "visualizer": { "active": 0, "name": "Flight Category", "exclusive": false },
  "strip": null,
  "leds": [
    { "code": "KLBX", "pixel": 4, "name": "", "virtual": false, "lat": 29.11, "lon": -95.46, "flightCategory": "IFR",
      "raw": "KLBX 241453Z ... LTG DSNT", "lightning": true,
      "look": { "effect": "cycle", "colors": ["#ff0000", "...", "#ffff00"], "step": 0.1 } }
  ],
  "locate": { "pixel": 5, "at": 1792854523.96 },
  "display": {
    "enabled": true,
    "screen": { "airport": "KGLS", "title": "KGLS", "virtual": false, "badge": "LIFR", "page": 1,
                "lines": [ { "icon": "wind", "text": "150@08" }, { "icon": "visibility", "text": "1SM" },
                           { "icon": "pressure", "text": "29.98" } ] }
  }
}
```

| Field | Description |
|---|---|
| `leds[].lat`, `leds[].lon` | Where the airport is: from its METAR, or for an airport without a report, from aviationweather.gov's station information. `null` if neither knows it. `raw` is `null` for an airport without a report. |
| `leds[].look` | The LED's current effect: `solid`, `off`, `blink` (`period` seconds per on/off cycle; with two `colors` it alternates between them instead of turning off), `pulse` (`period`; `low`, if present, is its dimmest point, e.g. `0.3`, otherwise it fades to off), or `cycle` (steps through `colors`, `step` seconds each). Colors are CSS hex colors. |
| `leds[].virtual` | A virtual airport: no LED on the strip, so the Map page draws it in a dashed circle. |
| `strip` | Set when one effect drives the whole strip instead: `rainbow` (`period`) or `chase` (`step`, `size`, `spacing`). The virtual airports keep their own `look` meanwhile: the same rainbow, or `off` for a chase (a wiring check). |
| `locate` | The last white locate pulse: LED `pixel` and Unix time `at`. `null` until the first one. A virtual airport's pulse is only shown on the Map page. |
| `display.on` | Whether the screen is showing; `false` after `/display/off` (then `screen` is `null`) |
| `display.screen` | What the OLED shows. `badge` is the flight category, with a `*` after one that's estimated from the visibility and ceiling (`VFR*`). `virtual` is true for a virtual airport, whose code is in a dashed box. `page` is 1 or 2 for an airport, 0 for "Data Unavailable" or a message (then `airport` is `null`). Icons: `wind`, `visibility`, `pressure`, `temp`, `dewpoint`, `date`. |

### `GET /api/metar/<code>`

One airport's METAR, raw and in plain English. The Map page's Summary and Decoded tabs use it. No authentication. The code is
case-insensitive; an airport that isn't on the map is a 404.

```json
{
  "code": "KHOU",
  "raw": "METAR KHOU 241753Z 10013G19KT 10SM SCT044 28/16 A3020 RMK AO2 ...",
  "flightCategory": "VFR",
  "obsTime": "2026-10-24T17:53:00+00:00",
  "decoded": [
    { "label": "Observed", "text": "24 Oct 17:53Z" },
    { "label": "Wind", "text": "100° at 13 kt, gusts 19 kt" },
    { "label": "Visibility", "text": "10+ miles" },
    { "label": "Clouds", "text": "Scattered 4,400 ft" },
    { "label": "Temperature", "text": "28°C / 82°F" },
    { "label": "Dewpoint", "text": "16°C / 61°F (spread 12°C)" },
    { "label": "Altimeter", "text": "30.20 inHg" }
  ],
  "summary": [
    "VFR: ceiling above 3,000 ft and visibility over 5 miles",
    "Wind from the east (100°) at 13 knots, gusting to 19",
    "No ceiling; scattered clouds at 4,400 ft",
    "Density altitude 1,300 ft (field elevation 46 ft)"
  ]
}
```

| Field | Description |
|---|---|
| `decoded` | One line per item the report has, in this order: `Observed`, `Wind`, `Visibility`, `Weather` (e.g. `Light rain, mist`), `Clouds` (one line per layer; later layers have an empty `label`, and the ceiling is marked), `Temperature`, `Dewpoint`, `Altimeter`, `Lightning`. Empty when the airport isn't reporting. Weather codes the map doesn't know are shown as they are. |
| `summary` | A few sentences about the weather, in this order, for what the report has: the flight category and what it means, the weather (e.g. `Light rain, mist`), `Lightning reported`, the wind, the ceiling (or the lowest clouds, or `Clear skies`), the density altitude (to the nearest 100 ft), a fog warning when the temperature and dewpoint are 2°C or less apart, and an icing warning between -20°C and 2°C with clouds or precipitation. Empty when the airport isn't reporting. |
| `raw`, `flightCategory`, `obsTime` | `null` when the airport isn't reporting |

## Control

These endpoints change the map immediately. Nothing they change is saved to `config.json`, so the changes are lost on restart. Each one returns the HTML of a UI page; ignore it.

| Endpoint | Description |
|---|---|
| `GET /brightness/<level>` | Set LED brightness, `0.0`–`1.0`; the map ignores values outside that range. The dimming schedule overrides it at the next dawn, sunrise, sunset or dusk. |
| `GET /display/on`, `GET /display/off` | Turn the OLED screen on or off (blank). Not saved: it's back on when the map restarts. A 409 if the screen is turned off in Config (`display_screen.enabled`), which is the saved setting. |
| `GET /visualizer/<n>` | Switch to visualizer number `n` (see the table below) |
| `GET /visualizer/next` | Next visualizer; after the last one it goes back to the first |
| `GET /visualizer/previous` | Previous visualizer; before the first one it goes to the last |
| `GET /locate/<pixel>` | Pulse one LED white. Ignored while an exclusive visualizer is running. |
| `GET /fetch` | Fetch METARs from aviationweather.gov now. **The request does not return until the fetch finishes**, which can take up to about 30 seconds; other requests are answered in the meantime. |

Visualizer indexes:

| # | Name | Exclusive |
|---|---|---|
| 0 | Flight Category | |
| 1 | Wind | |
| 2 | Wind Gusts | |
| 3 | Pressure | |
| 4 | Precipitation | |
| 5 | Temperature | |
| 6 | Visibility | |
| 7 | Density Altitude | |
| 8 | Ceiling | |
| 9 | Dewpoint Spread | |
| 10 | Rainbow | yes |
| 11 | Chase | yes |

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

Each value is checked against the setting's type: an unknown setting or a value that doesn't fit is a 400 with the reason.

Settings that apply right away:
- `display_screen.enabled`: turns the OLED screen on or off (blank)
- `lightning.animation`
- `display_screen.locate_active`
- `display_screen.delay`
- `update.channel`: what **Update** installs: `releases` (the newest release tag, never an older one; the default) or `latest` (the newest commit on GitHub, released or not, for testing)
- `led.brightness.normal`, `led.brightness.dimmed`, `led.brightness.off`: the level in use now changes right away; the others take over at their sun time
- `led.inittest`: turning it on also runs the test pattern once now
- `led.dim_on_refresh`: the LEDs fade to half their brightness while METARs are fetched (at least a second), then fade back
- `visualizer.active`, the default visualizer used at startup. Saving it doesn't change the visualizer that's running now; use `/visualizer/<n>` for that.
- `visualizer.auto_rotate.enabled`
- `visualizer.auto_rotate.delay_seconds` (the new delay starts counting when it's saved)
- `visualizer.auto_rotate.skip`: the visualizers auto-rotate leaves out, as a JSON list of names, e.g. `/config/edit/visualizer.auto_rotate.skip/%5B%22Wind%22%2C%22Wind%20Gusts%22%5D` for `["Wind","Wind Gusts"]` (`[]` leaves none out). Exclusive visualizers (`"exclusive": true` in `/api/status`) are always left out. The previous/next buttons still go to every visualizer.

Map page settings (apply the next time the Map page is opened):
- `geo.map.background`: `sectional`, `satellite` or `radar`
- `geo.map.chart_type`: `sectional`, `terminal` (VFR Terminal Area) or `ifr_low` (IFR Enroute Low)
- `geo.map.chart`: the sectional name, as listed in [sectionals.json](src/metarmap/web/static/sectionals.json), such as `Houston`. If it's missing or unknown, the map uses the sectional that covers the most airports.
- `geo.map.view`: `airports` (fit to the airports), `chart` (the whole sectional) or `custom` (`geo.map.center` and `geo.map.zoom`)

```sh
curl -u metar:map http://metarmap.local/config/edit/lightning.animation/false
curl -u metar:map http://metarmap.local/config/edit/display_screen.delay/10
```

### Airports

The airports are the `airports` list in `config.json`, one entry per LED in the order the LEDs are wired:
`{"code": "KHOU", "name": "Hobby", "display": true}`. An LED with no airport has `"code": ""`. The list has
`led.count` entries, then `led.virtual_count` virtual airports: airports with no LED, shown on the Map page and in
`/api/status` (for Home Assistant), and on the OLED if their `display` is on, with the code in a dashed box. `/config/edit/led.count/<n>`
also adds LEDs with no airport at the end of the strip, or removes the airports on the last LEDs; the virtual
airports after them are kept. `/config/edit/led.virtual_count/<n>` adds or removes virtual airports at the end. The
two together are at most 1000 airports (each is part of every METAR fetch). A new LED count takes effect after a
restart, except without an LED strip (the in-memory one), where it takes effect right away.

`<led>` counts from 0. In a URL, `-` stands for an empty code or name.

| Endpoint | Description |
|---|---|
| `GET /config/airports/<led>/code/<code>` | Set the airport on an LED: a 3-4 character ICAO code, or `-` for none. A new code replaces the name with the new airport's (from aviationweather.gov's station information), and METARs are fetched in the background. |
| `GET /config/airports/<led>/name/<name>` | Set the airport's name, shown in the web UI. An empty name (`-`) is filled in with the airport's name after the next METAR fetch. |
| `GET /config/airports/<led>/display/<true\|false>` | Whether the airport is shown on the OLED screen |
| `GET /config/airports/move/<from>/<to>` | Move the airport on LED `from` to LED `to`; the airports in between shift by one |
| `GET /config/airports/edit/<oldcode>/<newcode>` | Older, by code: change the first airport with `oldcode` to `newcode` |
| `GET /config/airports/edit/prop/<airport>/<key>/<value>` | Older, by code: set `text` (the name) or `display` of the first airport with that code |

All of them save `config.json`, update the LEDs, restart the OLED display loop, and redirect to `/config/airports`.
An LED number or code that doesn't exist is a 404; a bad code or value is a 400.

Older maps kept the airports in a separate `airports.json`. The first start of a version with the `airports` list
moves them into `config.json` (`NULL...` placeholders become LEDs with no airport) and leaves `airports.json` as a
backup. Airports past `led.count` in an older file (they were already on the Map page only) become virtual airports.

### Login and Wi-Fi

Both take a JSON body (`Content-Type: application/json`) so passwords never appear in a URL, and both need
authentication. A bad value is a 400 with the reason.

| Endpoint | Description |
|---|---|
| `POST /config/login` | `{"user": "pilot", "password": "..."}`: sets the web UI login. On a Raspberry Pi (only), the password also becomes the Linux password of the Pi's login user (the owner of the `metarmap2` folder, e.g. `pi`), set with `chpasswd`; that happens first, and if it fails nothing changes (500). Leave out `password` to change only the user name, which is stored in lower case. Returns `{"user": "pilot", "linux_password": "changed for pi"}` (or `"skipped (not a Raspberry Pi)"` on any other machine, or `"skipped (not running as root)"`). The old login stops working at once. |
| `POST /config/wifi` | `{"ssid": "Cabin", "password": "..."}` (no password for an open network): switches the Pi to that Wi-Fi network 3 seconds after answering `202 {"ssid": "Cabin", "current": "HomeNet", "delay": 3}`. The current network is kept, so if the Pi can't join the new one it goes back. Uses NetworkManager (Bookworm) or `wpa_supplicant` (Bullseye). |

```sh
curl -u metar:map -H 'Content-Type: application/json' -d '{"user": "pilot", "password": "n3w pass"}' \
     http://metarmap.local/config/login
```

## Maintenance (auth)

| Endpoint | Description |
|---|---|
| `GET /update` | Updates the map from GitHub as `update.channel` says, keeping `config.json` (and an older `airports.json`): on `releases`, the newest release tag (`v2.9.0`), only if it's newer than the running version; on `latest`, the newest commit. Waits until it's done and returns the output as HTML. Restart afterwards to use the new code. |
| `POST /update/start` | Starts the same update in the background (or reports the one already running) and returns its progress, as below. Used by the web UI's progress bar. With a JSON body `{"version": "v2.7.0"}` it installs that release instead, older or newer, whatever the channel. A `version` that isn't a release version is a 400. |
| `GET /update/progress` | Progress of the update started with `/update/start`: `{"fraction": 0.4, "label": "Downloading the update", "done": false, "ok": null, "changed": null, "target": "v2.9.0", "message": "", "errors": []}`. When `done`, `ok` says whether it worked, `changed` whether new code was installed, `target` what was installed (a release tag, or a commit on the `latest` channel), `message` a one-line summary such as `Installed v2.9.0` or `Already on the newest release (v2.8.4)`, and `errors` holds git's error messages. |
| `GET /update/check` | Asks GitHub now what's newest (the map also does this when it starts and every 6 hours) and returns the same object as `update` in `/api/status`. |
| `GET /restart` | Clears the LEDs and restarts the map's process. The connection usually drops before a response is sent. |

## Web UI pages

| Endpoint | Auth | Description |
|---|---|---|
| `GET /` | | Home: flight category counts, visualizer controls and legend, brightness and sun times |
| `GET /metars` | | Table of METARs for every airport |
| `GET /map` | | Live mirror of the LEDs and the OLED screen on an FAA chart, satellite or radar background |
| `GET /map/legend` | | The active visualizer's legend (HTML), which the Map page swaps in when the visualizer changes |
| `GET /raw` | | Raw METAR text for every airport, followed by the full parsed data |
| `GET /raw/<code>` | | Raw METAR text for one airport |
| `GET /debug` | | Debug information |
| `GET /config` | yes | Configuration page |
| `GET /config/airports` | yes | Airport configuration page |
| `GET /static/<file>` | | Stylesheet and script for the web UI |
