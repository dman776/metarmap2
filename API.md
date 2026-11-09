# MetarMap2 Web API

The Chart runs a [Bottle](https://bottlepy.org) web server on the port set by `web_server.port` in [config.json](config.json) (default `80`).
Every endpoint uses `GET`. Most endpoints return the web UI's HTML pages. `/api/status` is the only one that returns JSON, so use it to read the Chart's state from scripts and integrations such as [Home Assistant](https://github.com/dman776/metarmap2_ha).

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

Returns a read-only snapshot of the Chart's state as `application/json`. No authentication.

```json
{
  "version": "1.16.2",
  "ip": "192.168.1.50",
  "brightness": 0.5,
  "visualizer": {
    "active": 0,
    "id": "flight_category",
    "name": "Flight Category",
    "shortName": "Flight Cat",
    "icon": "plane",
    "exclusive": false,
    "description": "Display the flight category (ie. VFR, MVFR, IFR, LIFR).",
    "legend": [
      { "key": "VFR", "label": "VFR", "detail": "Green", "colors": ["#00ff00"], "effect": "solid", "period": null,
        "inUse": true },
      { "key": "missing", "label": "Flight category missing", "detail": "Blinking red (other METAR data is available)",
        "colors": ["#ff0000"], "effect": "blink", "period": 2, "inUse": false }
    ]
  },
  "visualizers": [
    { "index": 0, "id": "flight_category", "name": "Flight Category", "shortName": "Flight Cat", "icon": "plane",
      "exclusive": false },
    { "index": 1, "id": "wind", "name": "Wind", "shortName": "Wind", "icon": "wind", "exclusive": false }
  ],
  "config": {
    "visualizer.active": "flight_category",
    "visualizer.auto_rotate.enabled": false,
    "visualizer.auto_rotate.delay_seconds": 60,
    "visualizer.auto_rotate.skip": [],
    "visualizer.auto_rotate.skip_dark": false,
    "visualizer.missing_data_blink": true,
    "visualizer.estimated_category_breathing": true,
    "lightning.animation": true,
    "lightning.color": "yellow",
    "display_screen.enabled": true,
    "display_screen.locate_active": true,
    "display_screen.delay": 5.0,
    "display_screen.shows": "airports",
    "led.inittest": true,
    "led.init_sequence": "comet",
    "led.init_sweep_from": "W",
    "led.dim_on_refresh": true,
    "led.brightness.normal": 0.5,
    "led.brightness.dimmed": 0.1,
    "led.brightness.off": 0.01,
    "led.quiet_hours.enabled": false,
    "led.quiet_hours.start": "23:00",
    "led.quiet_hours.end": "05:00"
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
    "dev_mode": false,
    "branch": "",
    "branches": [],
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
      "mock": false,
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
| `ip` | IP address of the Chart |
| `brightness` | Current pixel brightness, `0.0`–`1.0` |
| `build` | What's running, read when the Chart started: `tag` is the release it's at or after (`null` if none), `ahead` how many commits after it, `commit` and `sha` the commit, `modified` whether the code was changed on the Chart itself (`config.json` and `airports.json` don't count). `release` is true on a release exactly; otherwise `pill` says why not ("Unreleased: 3 commits after v2.9.2", "Not tagged: v2.9.3" when `untagged`, "Pre-release: v2.9.0-rc1", "Modified: local changes to v2.9.2", "Unreleased: no release tag"). `chip` is the header's version text and `url` the commit on GitHub (`null` if the Chart isn't from GitHub). `null` outside a git checkout. |
| `update` | What's newest on GitHub: `current` is the running version, `commit` the running commit, `channel` is the channel in use (`branch` counts as `releases` without `dev_mode`), `available` the release (or, on the `latest` and `branch` channels, the commit) an update would install, or `null` when up to date; `installed` is what an update installed that needs a restart; `releases` lists the releases that can be installed, newest first; with `dev_mode`, `branches` lists GitHub's branches and `branch` is the one the `branch` channel follows; `checked` is when GitHub was last asked, and `error` why that failed. `null` if the Chart doesn't check. |
| `visualizer` | The visualizer that is running now: `active` is its number, `id` its id (see the table under Control). `shortName` is its name where there's little room (at most 11 characters, e.g. "Density Alt"), and `icon` names what its icon shows: one of `plane`, `cloud`, `eye`, `wind`, `gust`, `compass`, `thermometer`, `droplet`, `mountain`, `gauge`, `rain`, `warning`, `ban`, `rainbow`, `chase` (each visualizer has its own; a client draws them its own way, and should show none for a name it doesn't know). `exclusive` visualizers ignore `/locate`. |
| `visualizer.legend` | What the pixels mean for that visualizer. `colors` are CSS hex colors; two or more mean a gradient across the range. `effect` is `solid`, `blink`, `pulse`, `flash` (the first color with flashes of the second), `chase` or `off`. `period` is the seconds per blink or pulse, or `null`. `key` names the entry (stable, unlike `label`, which can change with the settings); `inUse` is whether a pixel (or a virtual airport) shows it now, always `true` for a whole-strip visualizer (Rainbow, Chase). |
| `visualizers` | Every visualizer, in index order: `index` is its number and `id` its id, both accepted by `/visualizer/<id>`; `shortName` and `icon` as in `visualizer` |
| `config` | The saved `config.json` values, keyed by the dotted path accepted by `/config/edit` |
| `display` | MetarMap2 Micro, the OLED screen: `enabled` is the Config setting (`display_screen.enabled`); `on` is whether it's showing now (false after `/display/off`, or when not enabled) |
| `suntimes` | Today's dimming schedule (ISO 8601 with time zone) |
| `lastFetchTime` | When METARs were last fetched, in the Chart's local time (ISO 8601, no time zone); `null` before the first fetch |
| `missingStations` | Airports that had no METAR in the last fetch |
| `airports` | Airports in pixel order, skipping pixels with no airport. `pixel` is the pixel index (counting from 0). `text` is the airport's name (`""` if none) and `display` whether it's shown on the Micro. `virtual` is true for a virtual airport (after the pixels, `pixel` at least `led.count`): no pixel, so only on the Map page, here, and on the Micro if `display` is on (its code in a dashed box). An airport on two pixels is listed twice. The METAR fields are `null` when the Chart has no data for the airport. `windDir` is a string because it can be `VRB`. |

### `GET /api/live`

What the physical map is doing right now. The Map page polls it every second. No authentication.

```json
{
  "now": 1792854523.9,
  "brightness": 0.5,
  "visualizer": { "active": 0, "id": "flight_category", "name": "Flight Category", "shortName": "Flight Cat",
                  "icon": "plane", "exclusive": false, "areas": null,
                  "autoRotate": { "enabled": true, "seconds": 60, "next": 1792854560.0 },
                  "legendInUse": ["VFR", "IFR", "lightning"], "legendInUseOnly": false },
  "fetch": { "next": 1792854900.0, "seconds": 600, "fetched": 1792854300.2 },
  "strip": null,
  "leds": [
    { "code": "KLBX", "pixel": 4, "name": "", "virtual": false, "lat": 29.11, "lon": -95.46, "flightCategory": "IFR",
      "raw": "KLBX 241453Z ... LTG DSNT", "lightning": true,
      "look": { "effect": "cycle", "colors": ["#ff0000", "...", "#ffff00"], "step": 0.1 }, "wind": null }
  ],
  "locate": { "pixel": 5, "at": 1792854523.96 },
  "display": {
    "enabled": true,
    "screen": { "airport": "KGLS", "title": "KGLS", "virtual": false, "badge": "LIFR", "page": 1,
                "lines": [ { "icon": "wind", "text": "150@08" }, { "icon": "visibility", "text": "1SM" },
                           { "icon": "pressure", "text": "29.98" } ] }
  },
  "speech": true
}
```

| Field | Description |
|---|---|
| `leds[].lat`, `leds[].lon` | Where the airport is: from its METAR, or for an airport without a report, from aviationweather.gov's station information. `null` if neither knows it. `raw` is `null` for an airport without a report. |
| `leds[].look` | The pixel's current effect: `solid`, `off`, `blink` (`period` seconds per on/off cycle; with two `colors` it alternates between them instead of turning off), `pulse` (`period`; `low`, if present, is its dimmest point, e.g. `0.3`, otherwise it fades to off), or `cycle` (steps through `colors`, `step` seconds each). Colors are CSS hex colors. |
| `leds[].wind` | While a wind visualizer runs (Wind, Wind Gusts, Wind Direction): the airport's wind for its barb on the Map page, `{"dir": 270.0, "kt": 12}` (the direction it blows from, and the sustained speed). `null` when it's calm, variable (`VRB`), has no direction or no report, and for every other visualizer. |
| `leds[].virtual` | A virtual airport: no pixel on the strip, so the Map page draws it in a dashed circle. |
| `visualizer.shortName`, `visualizer.icon` | As in `/api/status`, for the visualizer running now |
| `visualizer.areas` | Which areas the Map page draws while the visualizer runs: `advisories` (Advisories, from `/api/advisories`), `tfrs` (TFR, from `/api/tfrs`), else `null` |
| `fetch` | The METAR fetch: `next` is when it next happens (Unix time, compare it with `now`; `null` if none is scheduled), `seconds` how long that wait is (600 for the regular fetch every 10 minutes; 60 for a retry after a failed fetch, which comes first), `fetched` when METARs were last fetched (`null` before the first). `GET /fetch` restarts the 10-minute wait. The Home page's Fetch METARs button counts down with it, and reloads once the next fetch has come |
| `visualizer.autoRotate` | Auto-rotate: `enabled` and `seconds` are its settings (`visualizer.auto_rotate`); `next` is when it next changes the visualizer (Unix time, compare it with `now`), `null` while it's off. Picking a visualizer by hand (`/visualizer/...`) starts the wait again, so `next` moves a whole delay ahead |
| `visualizer.legendInUse` | The `key`s of the legend entries the pixels (and virtual airports) show now, in the legend's order (see `/api/status`'s `visualizer.legend`); `null` for a whole-strip visualizer (Rainbow, Chase), whose legend is always shown whole. Follows the pixels: a fetch, an airport change or a different visualizer changes it |
| `visualizer.legendInUseOnly` | The `visualizer.legend_in_use_only` setting: whether the web pages list only those entries |
| `strip` | Set when one effect drives the whole strip instead: `rainbow` (`period`) or `chase` (`step`, `size`, `spacing`). The virtual airports keep their own `look` meanwhile: the same rainbow, or `off` for a chase (a wiring check). |
| `speech` | Whether spoken weather can be asked for (`/api/speak/<code>.audio`): `speech.enabled` on, with a server set for `speech.engine`. The METARs page's AWOS buttons, the Cockpit's AWOS mode (Info tab), the Map page popup's Listen tab and the touchscreen remote's hold-to-hear show only then |
| `leds[].atis` | The airport's real ATIS can be read aloud (`/api/atis/<code>.audio`): `speech.atis` and spoken weather are on, and it publishes a digital ATIS. The list of airports with one is refreshed every half hour. The ATIS buttons (METARs page, the Cockpit, the Map page popup's Listen tab) show only for these |
| `locate` | The last white locate pulse: the pixel number `pixel` and Unix time `at`. `null` until the first one. A virtual airport's pulse is only shown on the Map page. |
| `display.on` | Whether the screen is showing; `false` after `/display/off` (then `screen` is `null`) |
| `display.screen` | What the Micro shows. `badge` is the flight category, with a `*` after one that's estimated from the visibility and ceiling (`VFR*`). `virtual` is true for a virtual airport, whose code is in a dashed box. `page` is 1 or 2 for an airport, 0 for "Data Unavailable" or a message (then `airport` is `null`). Icons: `wind`, `visibility`, `pressure`, `temp`, `dewpoint`, `date`. For the first 5 seconds after the Chart starts, the splash: a message with `splash: true` and the title `MetarMap2` (the Micro draws the logo under it). With `display_screen.shows` `visualizer`: a message whose title is the visualizer's short name, with `visualizer_icon` its icon name (as `visualizer.icon`), drawn under the title. |

### `GET /api/metar/<code>`

One airport's METAR, raw and in plain English. The Map page's Summary and Decoded tabs use it. No authentication. The code is
case-insensitive; an airport that isn't on the Chart is a 404.

```json
{
  "code": "KHOU",
  "raw": "METAR KHOU 241753Z 10013G19KT 10SM SCT044 28/16 A3020 RMK AO2 ...",
  "mock": false,
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
| `decoded` | One line per item the report has, in this order: `Observed`, `Wind`, `Visibility`, `Weather` (e.g. `Light rain, mist`), `Clouds` (one line per layer; later layers have an empty `label`, and the ceiling is marked), `Temperature`, `Dewpoint`, `Altimeter`, `Lightning`. Empty when the airport isn't reporting. Weather codes the Chart doesn't know are shown as they are. |
| `summary` | A few sentences about the weather, in this order, for what the report has: the flight category and what it means, the weather (e.g. `Light rain, mist`), `Lightning reported`, the wind, the ceiling (or the lowest clouds, or `Clear skies`), the density altitude (to the nearest 100 ft), a fog warning when the temperature and dewpoint are 2°C or less apart, and an icing warning between -20°C and 2°C with clouds or precipitation. Empty when the airport isn't reporting. |
| `raw`, `flightCategory`, `obsTime` | `null` when the airport isn't reporting |

### `GET /api/speak/<code>`, `GET /api/speak`

An airport's METAR as text to be read aloud as an AWOS reads it, for text to speech (`text/plain`). No authentication. The code is
case-insensitive; an airport that isn't on the Chart is a 404. `/api/speak` gives every airport on the Chart as JSON,
`{code: text}`, in the Chart's order.

```
David Wayne Hooks Memorial. Weather at zero zero five tree Zulu. Wind not reported. Visibility one zero. Sky
condition few clouds at four thousand niner hundred, few clouds at seven thousand five hundred. Temperature two one,
dew point one six. Altimeter tree zero zero five. VFR.
```

Everything is spelled out as words, so a speech model can't read a number two ways: digit by digit for the wind, the
time, the temperature and the altimeter, in English for cloud heights and visibility fractions. The digits are said
as pilots and controllers say them: `tree` for 3 and `niner` for 9. In order: the
airport's name (the Chart's own, else the station's, with `Rgnl`, `Muni`, `Intl`... written out; else its letters), the
observation time in Zulu, the wind, the visibility, the weather, `Lightning observed`, the sky (the first broken or
overcast layer is the `ceiling`), the temperature and dew point (`minus` below zero), the altimeter and the flight
category. What the report leaves out is said to be `not reported`; an airport with no report says so. The words, the
airport's name too, follow `speech.tunings` (the Pronunciation page), as the ATIS does.

### `GET /api/speak/<code>.audio`

The same text, read aloud, as WAV (`audio/wav`, 16-bit mono at the voice's rate: 16 or 22.05 kHz from Piper, 24 kHz
from Kokoro). No authentication. With `speech.enabled` on, a speech server on another computer reads it
(`speech.engine`): Piper over the Wyoming protocol, such as Home Assistant's Piper add-on (`speech.wyoming_host`), or
Kokoro-FastAPI (`speech.kokoro_url`); README, *Spoken weather*. Each clip is kept until the airport's text changes,
so asking again is instant.

Errors are plain text saying why:

| Status | Why |
|---|---|
| 404 | The airport isn't on the Chart |
| 503 | Speech is off (`speech.enabled`), or no server is set for the engine |
| 502 | The server couldn't be reached, or failed (its reason, e.g. a voice it doesn't have) |

### `GET /api/atis/<code>`, `GET /api/atis/<code>.audio`, `GET /api/atis`

An airport's real ATIS, the FAA's digital ATIS (D-ATIS) from [atis.info](https://atis.info), as text to be read aloud
(`text/plain`), and read aloud as WAV, as `/api/speak` does. No authentication. Needs `speech.atis` on (and, for
the audio, spoken weather: `speech.enabled` and a server). Only about 75 large US airports publish one;
`/api/live`'s `leds[].atis` says which of the Chart's do. An airport with arrival and departure ATIS reads both,
arrival first.

```
Houston Hobby Airport information Quebec, one seven five tree Zulu. Wind zero niner zero at six. ... ILS approach
runway one tree right approach in use. Landing and departing runway one tree right. ... Taxiway Echo closed. ...
Advise you have information Quebec.
```

The FAA's contractions are written out as words (`DEPG` departing, `OTS` out of service, `TWY EA` taxiway Echo
Alpha, `RY8R` runway eight right, `126.225` one two six point two two five), and the weather groups are read as the
AWOS reads them; the altimeter's own words in parentheses and the remarks are left out. Letters said as letters
(`ILS`, `VOR`) and identifiers (`VNY`) stay in capitals.

`GET /api/atis/<code>/lines` is the same ATIS line by line, for reading along: each line the FAA's text (`raw`, as
written, with the altimeter's words and the remarks) and how it's said (`said`), with the entries it comes from:

```json
{ "code": "KHOU",
  "lines": [ { "raw": "HOU ATIS INFO Q 1753Z.", "said": "Houston Hobby Airport information Quebec, one seven five tree Zulu." },
             { "raw": "LNDG AND DEPG RWY 13R.", "said": "Landing and departing runway one tree right." } ],
  "entries": [ { "type": "combined", "code": "Q", "time": "1753", "updatedAt": "2026-11-07T17:54:35Z" } ] }
```

The words follow `speech.tunings` (the Pronunciation page): whole words or phrases said another way, for every airport
or one, before the Chart's own rules. The airport's name in the first line is tuned as the AWOS's is.

`/api/atis` lists the Chart's airports that have one, with each ATIS's `type` (`combined`, `arr` or `dep`), its
information letter (`code`), its `time` (HHMM, UTC) and when atis.info last updated it (`updatedAt`):

```json
{ "KHOU": [ { "type": "combined", "code": "Q", "time": "1753", "updatedAt": "2026-11-07T17:54:35Z" } ] }
```

The Chart asks atis.info only when an ATIS is asked for: one request for every airport, at most once a minute, and
longer after a failure. Errors are plain text saying why:

| Status | Why |
|---|---|
| 404 | The airport isn't on the Chart, or has no digital ATIS |
| 503 | Spoken ATIS is off (`speech.atis`), or speech is off or has no server (the audio) |
| 502 | atis.info, or the speech server, couldn't be reached or failed |

### `GET /api/advisories`

The G-AIRMETs and SIGMETs the Advisories visualizer shows, for the Map page's areas. No authentication. The Chart
fetches both from aviationweather.gov with the METARs (every 10 minutes). Only areas starting below 18,000 ft are
included (no high-level turbulence, and no freezing level lines), and only those in effect now.

- **G-AIRMETs** (graphical AIRMETs): over the contiguous US, text AIRMETs ended in January 2025 and G-AIRMETs
  replaced them. The Chart takes the forecast snapshot nearest the current time.
- **SIGMETs**: the US convective SIGMETs (thunderstorms) and the other SIGMETs, from the US and other countries:
  thunderstorms, severe turbulence and icing, mountain wave, volcanic ash, dust and sand storms, tropical cyclones.

```json
{
  "airmet": { "fetched": 1793576671.42, "error": null },
  "sigmet": { "fetched": 1793576671.52, "error": null },
  "areas": [
    { "kind": "SIGMET", "hazard": "CONV", "name": "Convective SIGMET", "series": "41C", "qualifier": null,
      "observed": true, "base": 0, "top": 37000, "moving": "Toward 320° at 5 kt", "from": 1793573700,
      "expires": 1793580900, "text": "CONVECTIVE SIGMET 41C\nVALID UNTIL 0055Z\nLA AND CSTL WTRS\n...",
      "coords": [[31.41, -92.07], [30.53, -91.56], [29.98, -92.3]], "color": "#ff0000" },
    { "kind": "AIRMET", "hazard": "IFR", "product": "SIERRA", "name": "IFR", "base": 0, "top": null,
      "due_to": "CIG BLW 010 VIS BLW 3SM PCPN BR", "severity": null, "valid": "2026-11-02T00:00:00.000Z", "from": null,
      "expires": 1793588400, "coords": [[36.12, -91.52], [35.81, -90.11], [34.95, -90.33]], "color": "#ff7e00" }
  ]
}
```

| Field | Description |
|---|---|
| `airmet`, `sigmet` | Each feed's last fetch that worked (`fetched`, Unix time; `null` before the first) and why its last one failed (`error`). A feed that fails keeps its last areas until they expire |
| `areas` | The SIGMETs first, then the G-AIRMETs |
| `areas[].kind`, `hazard` | `AIRMET`: `IFR`, `MT_OBSC` (mountain obscuration), `TURB-LO` / `TURB-HI` (turbulence), `LLWS` (low-level wind shear), `SFC_WND` (sustained surface wind of 30 kt or more) or `ICE`. `SIGMET`: `CONV` (US convective), `TS` (thunderstorms), `TC` (tropical cyclone), `ICE`, `TURB`, `MTW` (mountain wave), `VA` (volcanic ash), `DS` (dust storm) or `SS` (sandstorm) |
| `areas[].base`, `top` | Altitudes in feet: `base` 0 is the surface (G-AIRMET icing based at the freezing level gives its lowest); `top` is `null` when none is given |
| `areas[].product` | A G-AIRMET's group: `SIERRA`, `TANGO` or `ZULU` |
| `areas[].qualifier`, `observed`, `moving`, `series`, `text` | A SIGMET's qualifier as issued (`SEV`, `OCNL SEV`, `FRQ`, `EMBD`...), whether it's observed or forecast, where it's heading, its series and its text |
| `areas[].valid` | A G-AIRMET's snapshot time (ISO) |
| `areas[].from`, `expires` | When it's valid from (SIGMETs; `null` for G-AIRMETs) and until (Unix time) |
| `areas[].coords` | The area's outline, `[lat, lon]` pairs |
| `areas[].color` | The hazard's color in the Advisories visualizer (CSS hex) |

### `GET /api/tfrs`

The TFRs (temporary flight restrictions) the TFR visualizer shows, for the Map page's outlines. No authentication.
From the FAA's [tfr.faa.gov](https://tfr.faa.gov/): its list, fetched in the background with the METARs (every 10
minutes), and each new TFR's detail for its areas. Only areas in effect now or starting within 24 hours, with a floor
below 18,000 ft, are included. TFRs without an outline (some long-running security areas) are left out.

```json
{
  "fetched": 1793578000.5,
  "error": null,
  "nearby_nm": 10,
  "areas": [
    { "notam": "6/3889", "type": "HAZARDS", "description": "BAYOU GAUCHE, LA, Thursday, October 29, 2026 through ...",
      "upcoming": false, "name": "Hazard Area1", "floor": 0, "floor_ref": "AGL", "ceiling": 2500, "ceiling_ref": "AGL",
      "from": 1793299080, "until": 1794010500, "coords": [[29.79, -90.42], [29.8, -90.39], [29.77, -90.38]],
      "url": "https://tfr.faa.gov/tfr3/?page=detail_6_3889", "color": "#ff7e00" }
  ]
}
```

| Field | Description |
|---|---|
| `fetched`, `error` | When the list was last fetched (Unix time; `null` before the first) and why the last fetch failed. The TFRs from the last list that came are kept |
| `nearby_nm` | `tfr.nearby_nm`: the TFR visualizer also shows TFRs this close to an airport |
| `areas[].type` | `VIP`, `HAZARDS`, `SECURITY`, `SPECIAL`, `AIR SHOWS/SPORTS` or `UAS PUBLIC GATHERING` |
| `areas[].upcoming` | `true` for one starting within 24 hours, `false` for one in effect now |
| `areas[].floor`, `ceiling` | In feet, `AGL` or `MSL` (`floor_ref`, `ceiling_ref`); `ceiling` is `null` when none is given |
| `areas[].from`, `until` | When the area is in effect (Unix time): `from` is `null` when no start is given (in effect), `until` when no end is given (until further notice) |
| `areas[].coords` | The area's outline, `[lat, lon]` pairs |
| `areas[].url` | The TFR's page on tfr.faa.gov |
| `areas[].color` | The type's color in the TFR visualizer (CSS hex) |

### `GET /api/traffic`

The aircraft around the Chart's airports, from [adsb.fi](https://adsb.fi/)'s open data. The Map page asks for it while its
**Live traffic** box is ticked. No authentication.

The Chart asks adsb.fi only when this is requested and what it has is older than `geo.map.traffic_seconds`, so any number
of open pages share one fetch. Nothing is fetched while no page asks. A failed fetch waits longer each time (twice the
interval, doubling, at most 5 minutes; at least a minute after adsb.fi answers 429), and keeps the aircraft from the
last fetch that worked. adsb.fi's data is free for personal, non-commercial use, and must be credited.

```json
{
  "now": 1793466896.77,
  "interval": 5.0,
  "fetched": 1793466896.42,
  "error": null,
  "center": [30.41495, -93.75705],
  "radius": 216,
  "source": { "name": "adsb.fi", "url": "https://adsb.fi/" },
  "aircraft": [
    {
      "hex": "a0822c", "flight": "UCA4878", "reg": "N13161", "type": "E45X", "desc": "EMBRAER ERJ-145XR",
      "operator": "UNITED AIRLINES INC", "lat": 30.006683, "lon": -95.498765, "ground": false, "alt": 2450,
      "gs": 211.0, "track": 90.54, "vrate": -1152, "squawk": "4561", "emergency": null, "category": "A2",
      "kind": "small", "at": 1793466896.25
    }
  ]
}
```

| Field | Description |
|---|---|
| `now`, `fetched` | Unix times on the Chart's clock: now, and the last fetch that worked (`null` before the first) |
| `interval` | Seconds between fetches: `geo.map.traffic_seconds`, kept between 2 and 60 |
| `error` | Why the last fetch failed (e.g. `couldn't reach adsb.fi: …`, `no airport positions yet`), else `null` |
| `center`, `radius` | The circle asked about: around every airport plus 25 NM, at most 250 NM (adsb.fi's limit) |
| `aircraft[]` | Aircraft with a position no older than 60 s. Ones on the ground only with `geo.map.traffic_ground` |
| `aircraft[].alt` | Barometric altitude in feet (the GPS one if there's none); `null` on the ground |
| `aircraft[].gs`, `track`, `vrate` | Ground speed (kt), track (degrees true) and vertical rate (ft/min); `null` when not sent |
| `aircraft[].category` | The ADS-B emitter category the aircraft sends (`A1` to `A7`, `B1` to `B7`, `C1` to `C3`), `null` if none |
| `aircraft[].kind` | What the Map page draws, from `category`: `light` (A1, and B4 ultralights), `small` (A2, and A6 high performance), `large` (A3, A4), `heavy` (A5), `helicopter` (A7), `glider` (B1), `balloon` (B2), `drone` (B6), `vehicle` (C1, C2), else `unknown`. Some ICAO types override it: `super` for the biggest (A388, 747, An-124, C-5…), and `helicopter` for common helicopter types, since many send `A1` |
| `aircraft[].emergency` | adsb.fi's emergency status (e.g. `general`), `null` for none. Squawks 7500, 7600 and 7700 are in `squawk` |
| `aircraft[].at` | When the position was reported (the Chart's clock). The Map page moves each aircraft along its track from there |

## Control

These endpoints change the Chart immediately. Except for auto-rotate, nothing they change is saved to `config.json`, so the changes are lost on restart. Each one returns the HTML of a UI page; ignore it.

| Endpoint | Description |
|---|---|
| `GET /brightness/<level>` | Set pixel brightness, `0.0`–`1.0`; the Chart ignores values outside that range. The dimming schedule overrides it at the next dawn, sunrise, sunset or dusk. |
| `GET /display/on`, `GET /display/off` | Turn the Micro on or off (blank). Not saved: it's back on when the Chart restarts. A 409 if the screen is turned off in Config (`display_screen.enabled`), which is the saved setting. |
| `GET /visualizer/<id>` | Switch to a visualizer by its id, e.g. `/visualizer/wind_direction`, or by its number, `/visualizer/3` (see the table below). A 404 for one there isn't. |
| `GET /visualizer/next` | Next visualizer; after the last one it goes back to the first |
| `GET /visualizer/previous` | Previous visualizer; before the first one it goes to the last |
| `GET /visualizer/auto_rotate/on`, `GET /visualizer/auto_rotate/off` | Turn auto-rotate on or off (the Cockpit's switch). Saved, as `visualizer.auto_rotate.enabled`, though it needs no login: it changes only that setting. The timer starts again now. |
| `GET /locate/<pixel>` | Pulse one pixel white. Ignored while an exclusive visualizer is running. |
| `GET /led/init_sequence/play` | Play the startup sequence (`led.init_sequence`) once now, whether or not `led.inittest` is on. Returns at once. |
| `GET /fetch` | Fetch METARs from aviationweather.gov now. **The request does not return until the fetch finishes**, which can take up to about 30 seconds; other requests are answered in the meantime. The next regular fetch is then a whole 10 minutes later (`/api/live`'s `fetch.next`). |

With auto-rotate on, a visualizer picked with `/visualizer/<id>`, `next` or `previous` is shown for the whole auto-rotate delay before the next change.

Visualizers:

| # | Id | Name | Exclusive |
|---|---|---|---|
| 0 | `flight_category` | Flight Category | |
| 1 | `wind` | Wind | |
| 2 | `wind_gusts` | Wind Gusts | |
| 3 | `wind_direction` | Wind Direction | |
| 4 | `pressure` | Pressure | |
| 5 | `precipitation` | Precipitation | |
| 6 | `temperature` | Temperature | |
| 7 | `visibility` | Visibility | |
| 8 | `density_altitude` | Density Altitude | |
| 9 | `ceiling` | Ceiling | |
| 10 | `dewpoint_spread` | Dewpoint Spread | |
| 11 | `advisories` | Advisories | |
| 12 | `tfr` | TFR | |
| 13 | `rainbow` | Rainbow | yes |
| 14 | `chase` | Chase | yes |

Use the id in scripts and automations: it never changes, while a number moves when a visualizer is added before
it (Wind Direction after 3.0.1, Advisories and TFR after 3.1.0 each did) and a name can be reworded. `config.json`
saves ids; one saved before ids (`visualizer.active` a number, with `visualizer.numbering`) is converted when the
map starts, keeping the same visualizer.

```sh
curl http://metarmap.local/brightness/0.25
curl http://metarmap.local/visualizer/wind
```

## Configuration (auth)

### `GET /config/edit/<key>/<value>`

Saves one value to `config.json`, then refreshes the active visualizer. `key` is the dotted path to the setting, such as `lightning.animation` or `display_screen.delay`.

- **Booleans:** send `true` or `false`.
- **Numbers:** send them as-is, for example `5` or `0.25`.
- **Strings:** URL-encode them, for example `geo.map.chart` → `Dallas-Ft%20Worth`. Quoting them (`%22Dallas%22`) also still works.

Each value is checked against the setting's type: an unknown setting or a value that doesn't fit is a 400 with the reason.

Settings that apply right away:
- `display_screen.enabled`: turns the Micro on or off (blank)
- `tfr.nearby_nm`: the TFR visualizer also shows a TFR this close to an airport (dim), 0 to 50 NM; 0 is inside only. 10 by default. Applies right away
- `lightning.animation`: a double flicker every 2 s on airports with lightning (`LTG` in the report) or a thunderstorm (`TS`, `TSRA`, `VCTS`...), over whatever every weather visualizer shows; Rainbow and Chase are unaffected. Off: no flashes anywhere (Precipitation still shows a thunderstorm: its precipitation, else yellow)
- `visualizer.missing_data_blink`: the slow red blink on an airport whose report lacks what the visualizer shows (no flight category, visibility or sky condition; no wind speed; weather codes the Chart doesn't know...), in every visualizer. `false`: those pixels stay dark, and the legends say *Off*. `true` by default
- `visualizer.estimated_category_breathing`: an estimated flight category (the station reported visibility or clouds, but no category) breathes slowly. `false`: a steady color, like a reported category; the Micro still marks it (`VFR*`). `true` by default
- `visualizer.legend_in_use_only`: the legends on Home, Map and Cockpit list only the entries the pixels are showing now (e.g. only VFR and MVFR), and follow them as they change. `false` (everything the visualizer can show) by default
- `lightning.color`: the flicker's color, `yellow` (the default) or `white`; anything else is a 400. Precipitation's thunderstorm stays yellow either way (its snow is white)
- `display_screen.locate_active`
- `display_screen.delay`
- `display_screen.shows`: what the Micro shows: `airports` (each airport in turn, with its pixel's pulse; the default) or `visualizer` (the active visualizer's short name and icon, redrawn when it changes, with no pulses); anything else is a 400. Applies right away
- `update.channel`: what **Update** installs: `releases` (the newest release tag, never an older one; the default), `latest` (the newest commit on GitHub, released or not, for testing) or, only with `dev_mode`, `branch` (the newest commit of `update.branch`, even after a force push)
- `update.branch`: the branch on GitHub the `branch` channel follows, e.g. `/config/edit/update.branch/feature/radar`. A name starting with `-`, with `..` or with spaces is a 400

`dev_mode` (top level, `false` by default) can only be changed by editing `config.json` by hand: `/config/edit/dev_mode/…` is a 400. With it on, Config > System > Software offers **Branch** under *Update to*, with a list of GitHub's branches (refreshed by each check: push a branch, then **Check now**). Turning it off makes a `branch` channel act as `releases`; the saved channel and branch stay. It also turns on mock METARs on the Airports page (see *Mock METARs*).
- `led.brightness.normal`, `led.brightness.dimmed`, `led.brightness.off`: the level in use now changes right away; the others take over at their sun time
- `led.quiet_hours.enabled`, `led.quiet_hours.start`, `led.quiet_hours.end`: the pixels are off (0%), and the Micro blank, from the start time to the end time, in the Pi's local time; the window can cross midnight. Times are 24-hour `HH:MM` (e.g. `/config/edit/led.quiet_hours.start/22:30`); anything else is a 400. Changes apply right away
- `led.inittest`: whether the startup sequence plays when the Chart starts; turning it on also plays it once now. With quiet hours on, it also plays when they end, and when they begin the same sequence takes the Chart dark (the same path, each pixel from its color to dark; Comet runs the other way, leaving the strip dark). Only at the scheduled times, not when a settings change starts or ends quiet hours, and not while the pixels are at 0% anyway
- `led.init_sequence`: the startup sequence: `comet` (a rainbow along the strip; the default), `center_out` (the Chart fades in from the middle of the box around the airports out to its edges), `edges_in` (from the edges in to the middle), `sweep` (across the Chart, from `led.init_sweep_from`), `radar` (a beam from north, clockwise) or `sparkle` (one pixel at a time, in random order). All but `comet` fade each pixel in to its visualizer color over 3 seconds. Changing it plays it once now
- `led.init_sweep_from`: where `sweep` starts: `W` (west to east; the default), `NW`, `N`, `NE`, `E`, `SE`, `S` or `SW`. Changing it plays the sequence once now
- `led.dim_on_refresh`: the pixels fade to half their brightness while METARs are fetched (at least a second), then fade back
- `speech.enabled`: spoken weather on or off (`/api/speak/<code>.audio`, and the AWOS buttons on the METARs page and the Cockpit)
- `speech.engine`: the speech server: `wyoming` (Piper, e.g. Home Assistant's add-on) or `kokoro` (Kokoro-FastAPI)
- `speech.wyoming_host`, `speech.wyoming_port`, `speech.wyoming_voice`: the Piper server (Home Assistant's address; port 10200) and the voice to ask it for (e.g. `en_US-lessac-medium`; empty: its own). An empty host or voice is sent as `-`
- `speech.atis`: the spoken ATIS on or off (`/api/atis`, from atis.info; off by default)
- `speech.tunings`: the Pronunciation page's list, `[{"text": "MNSTR", "say": "monster", "airport": ""}]` (`airport` empty for every airport). Saved as a whole with `POST /config/tunings` and `{"tunings": [...]}` (login needed), not with `/config/edit`. `GET /config/say.audio?text=...` (login needed) reads any words aloud as WAV, at most 200 characters, for the page's speaker beside each tuning: 400 for no words or too many, 503 and 502 as for `/api/speak/<code>.audio`
- `speech.kokoro_url`, `speech.kokoro_voice`, `speech.kokoro_speed`: the Kokoro server (e.g. `/config/edit/speech.kokoro_url/192.168.0.164:8880`; `http://` is added), its voice (e.g. `af_heart`) and speed (0.5 to 2). An empty address is sent as `-`
- `visualizer.active`, the default visualizer used at startup, by id (`/config/edit/visualizer.active/wind`); a number is taken too and saved as the id. An unknown one is a 400. Saving it doesn't change the visualizer that's running now; use `/visualizer/<id>` for that.
- `visualizer.auto_rotate.enabled`
- `visualizer.auto_rotate.delay_seconds` (the new delay starts counting when it's saved)
- `visualizer.auto_rotate.skip`: the visualizers auto-rotate leaves out, as a JSON list of ids, e.g. `/config/edit/visualizer.auto_rotate.skip/%5B%22wind%22%2C%22wind_gusts%22%5D` for `["wind","wind_gusts"]` (`[]` leaves none out). Names and numbers are taken too, and saved as ids; an unknown one is a 400. Exclusive visualizers (`"exclusive": true` in `/api/status`) are always left out. The previous/next buttons still go to every visualizer.
- `visualizer.auto_rotate.skip_dark`: auto-rotate also leaves out a visualizer while it would show nothing: every pixel and virtual airport off (e.g. Precipitation on a dry day, or Advisories with none in effect). A red "METAR not available" blink counts as showing something. If every other visualizer is dark, the current one stays

Map page settings (apply the next time the Map page is opened):
- `geo.map.background`: `sectional`, `satellite` or `radar`
- `geo.map.chart_type`: `sectional`, `terminal` (VFR Terminal Area) or `ifr_low` (IFR Enroute Low)
- `geo.map.chart`: the sectional name, as listed in [sectionals.json](src/metarmap/web/static/sectionals.json), such as `Houston`. If it's missing or unknown, the Chart uses the sectional that covers the most airports.
- `geo.map.view`: `airports` (fit to the airports), `chart` (the whole sectional) or `custom` (`geo.map.center` and `geo.map.zoom`)
- `geo.map.traffic_seconds`: how often live traffic is fetched from adsb.fi (see `/api/traffic`), 2 to 60 seconds,
  5 by default. adsb.fi allows one request a second; anything outside that range is a 400. Applies right away
- `geo.map.traffic_ground`: `true` to show aircraft on the ground too (off by default). Applies right away

```sh
curl -u metar:map http://metarmap.local/config/edit/lightning.animation/false
curl -u metar:map http://metarmap.local/config/edit/display_screen.delay/10
```

### Airports

The airports are the `airports` list in `config.json`, one entry per pixel in the order the pixels are wired:
`{"code": "KHOU", "name": "Hobby", "display": true}`. A pixel with no airport has `"code": ""`. The list has
`led.count` entries, then `led.virtual_count` virtual airports: airports with no pixel, shown on the Map page and in
`/api/status` (for Home Assistant), and on the Micro if their `display` is on, with the code in a dashed box. `/config/edit/led.count/<n>`
also adds pixels with no airport at the end of the strip, or removes the airports on the last pixels; the virtual
airports after them are kept. `/config/edit/led.virtual_count/<n>` adds or removes virtual airports at the end. The
two together are at most 1000 airports (each is part of every METAR fetch). A new pixel count takes effect after a
restart, except without an LED strip (the in-memory one), where it takes effect right away.

`<led>` counts from 0. In a URL, `-` stands for an empty code or name.

| Endpoint | Description |
|---|---|
| `GET /config/airports/<led>/code/<code>` | Set the airport on a pixel: a 3-4 character ICAO code, or `-` for none. A new code replaces the name with the new airport's (from aviationweather.gov's station information), and METARs are fetched in the background. |
| `GET /config/airports/<led>/name/<name>` | Set the airport's name, shown in the web UI. An empty name (`-`) is filled in with the airport's name after the next METAR fetch. |
| `GET /config/airports/<led>/display/<true\|false>` | Whether the airport is shown on the Micro |
| `GET /config/airports/move/<from>/<to>` | Move the airport on pixel `from` to pixel `to`; the airports in between shift by one |
| `POST /config/airports/mock` | `dev_mode` only (a 400 without it): the Airports page's *Mock METAR* field. `{"pixel": 0, "metar": "METAR KDWH 272353Z AUTO 08003KT 9SM CLR 21/18 A3014"}` saves it as the airport's `mock_metar` in `config.json` and shows it at once, and after every fetch, in place of the fetched report; `"metar": ""` goes back to the real one. Text that doesn't start like a METAR (airport code, then the time) is a 400. Answers `{"code", "mock", "flightCategory"}`. See *Mock METARs* below. |
| `GET /config/airports/edit/<oldcode>/<newcode>` | Older, by code: change the first airport with `oldcode` to `newcode` |
| `GET /config/airports/edit/prop/<airport>/<key>/<value>` | Older, by code: set `text` (the name) or `display` of the first airport with that code (not `mock_metar`: a 400) |

#### Mock METARs (`dev_mode`)

To test a report on the Chart, type a raw METAR in an airport's *Mock METAR* field on the Airports page (shown only with `dev_mode`), or put it in `config.json` as the airport's `"mock_metar"` (then restart). It replaces that airport's real report everywhere: the pixels, the Micro, Home Assistant and the web pages, until it's cleared. The Chart reads the report's body (not the remarks): wind (`KT` or `MPS`), visibility (`9SM`, `1 1/2SM`, `M1/4SM`, `P6SM`, meters, `CAVOK`), weather codes, clouds and `VV`, temperature/dewpoint, and the altimeter (`A` or `Q`); `LTG` anywhere is lightning. The flight category comes from the visibility and ceiling (FAA limits), and the time from `DDHHMMZ` (this month, or last month if that day is still ahead). The airport's name and position stay its real station's. A mocked airport says `mock` on the Home, METARs and Airports pages and in the Map popup, and has `"mock": true` in `/api/status`, `/api/live` and `/api/metar/<code>`; the pixels and the Micro look as a real report would. With `dev_mode` off, saved mocks are ignored. Changing the airport's code removes its mock.

All of them save `config.json`, update the pixels, restart the Micro's loop, and redirect to `/config/airports`.
A pixel number or code that doesn't exist is a 404; a bad code or value is a 400.

Older maps kept the airports in a separate `airports.json`. The first start of a version with the `airports` list
moves them into `config.json` (`NULL...` placeholders become pixels with no airport) and leaves `airports.json` as a
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
| `GET /update` | Updates the Chart from GitHub as `update.channel` says, keeping `config.json` (and an older `airports.json`): on `releases`, the newest release tag (`v2.9.0`), only if it's newer than the running version; on `latest`, the newest commit; on `branch` (`dev_mode`), the newest commit of `update.branch`. Waits until it's done and returns the output as HTML. Restart afterwards to use the new code (the web UI's Update and Install buttons restart the Chart for you when new code was installed). |
| `POST /update/start` | Starts the same update in the background (or reports the one already running) and returns its progress, as below. Used by the web UI's progress bar. With a JSON body `{"version": "v2.7.0"}` it installs that release instead, older or newer, whatever the channel. A `version` that isn't a release version is a 400. |
| `GET /update/progress` | Progress of the update started with `/update/start`: `{"fraction": 0.4, "label": "Downloading the update", "done": false, "ok": null, "changed": null, "target": "v2.9.0", "message": "", "errors": []}`. When `done`, `ok` says whether it worked, `changed` whether new code was installed, `target` what was installed (a release tag, or a commit on the `latest` channel), `message` a one-line summary such as `Installed v2.9.0` or `Already on the newest release (v2.8.4)`, and `errors` holds git's error messages. |
| `GET /update/check` | Asks GitHub now what's newest (the Chart also does this when it starts and every 6 hours) and returns the same object as `update` in `/api/status`. |
| `GET /restart` | Clears the pixels and restarts the Chart's process. The connection usually drops before a response is sent. |

## Web UI pages

| Endpoint | Auth | Description |
|---|---|---|
| `GET /` | | Home: flight category counts, visualizer controls and legend, brightness and sun times |
| `GET /metars` | | Table of METARs for every airport |
| `GET /map` | | Live mirror of the Chart and the Micro on an FAA chart, satellite or radar background (a new radar scan every 5 minutes while radar is shown). An airport's popup has Summary, Raw and Decoded tabs, and with spoken weather on a Listen tab: its AWOS (showing the raw METAR), and its ATIS (the FAA's text, read along) where `leds[].atis` |
| `GET /map/legend` | | The active visualizer's legend (HTML), which the Map page and the Cockpit swap in when the visualizer changes |
| `GET /remote` | | MetarMap2 Cockpit: a remote control laid out for an iPad in kiosk mode, in three tabs: Visualizer (the visualizers and the legend, with a footer of controls: the auto-rotate switch with a countdown to the next visualizer, which is saved, and pixel brightness and the Micro switch, which aren't), Map (the Map page's live map) and Info (every airport; a press locates it, or with spoken weather on, reads its AWOS, or with `speech.atis` its ATIS: Locate, AWOS and ATIS modes, ATIS showing only the airports with one). It follows changes made anywhere else (it polls `/api/live`). `/remote#map` or `#info` opens that tab, and `#locator`, `#awos` or `#atis` the Info tab in that mode; otherwise it opens the tab and mode last used on that device. *Add to Home Screen* opens it full screen |
| `GET /raw` | | Raw METAR text for every airport, followed by the full parsed data |
| `GET /raw/<code>` | | Raw METAR text for one airport |
| `GET /debug` | | Debug information |
| `GET /config` | yes | Configuration page |
| `GET /config/airports` | yes | Airport configuration page |
| `GET /static/<file>` | | Stylesheet and script for the web UI |
