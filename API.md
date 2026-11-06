# MetarMap2 Web API

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
    "id": "flight_category",
    "name": "Flight Category",
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
    { "index": 0, "id": "flight_category", "name": "Flight Category", "exclusive": false },
    { "index": 1, "id": "wind", "name": "Wind", "exclusive": false }
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
| `ip` | IP address of the map |
| `brightness` | Current LED brightness, `0.0`–`1.0` |
| `build` | What's running, read when the map started: `tag` is the release it's at or after (`null` if none), `ahead` how many commits after it, `commit` and `sha` the commit, `modified` whether the code was changed on the map itself (`config.json` and `airports.json` don't count). `release` is true on a release exactly; otherwise `pill` says why not ("Unreleased: 3 commits after v2.9.2", "Not tagged: v2.9.3" when `untagged`, "Pre-release: v2.9.0-rc1", "Modified: local changes to v2.9.2", "Unreleased: no release tag"). `chip` is the header's version text and `url` the commit on GitHub (`null` if the map isn't from GitHub). `null` outside a git checkout. |
| `update` | What's newest on GitHub: `current` is the running version, `commit` the running commit, `channel` is the channel in use (`branch` counts as `releases` without `dev_mode`), `available` the release (or, on the `latest` and `branch` channels, the commit) an update would install, or `null` when up to date; `installed` is what an update installed that needs a restart; `releases` lists the releases that can be installed, newest first; with `dev_mode`, `branches` lists GitHub's branches and `branch` is the one the `branch` channel follows; `checked` is when GitHub was last asked, and `error` why that failed. `null` if the map doesn't check. |
| `visualizer` | The visualizer that is running now: `active` is its number, `id` its id (see the table under Control). `exclusive` visualizers ignore `/locate`. |
| `visualizer.legend` | What the LEDs mean for that visualizer. `colors` are CSS hex colors; two or more mean a gradient across the range. `effect` is `solid`, `blink`, `pulse`, `flash` (the first color with flashes of the second), `chase` or `off`. `period` is the seconds per blink or pulse, or `null`. `key` names the entry (stable, unlike `label`, which can change with the settings); `inUse` is whether an LED (or a virtual airport) shows it now, always `true` for a whole-strip visualizer (Rainbow, Chase). |
| `visualizers` | Every visualizer, in index order: `index` is its number and `id` its id, both accepted by `/visualizer/<id>` |
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
  "visualizer": { "active": 0, "id": "flight_category", "name": "Flight Category", "exclusive": false, "areas": null,
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
  }
}
```

| Field | Description |
|---|---|
| `leds[].lat`, `leds[].lon` | Where the airport is: from its METAR, or for an airport without a report, from aviationweather.gov's station information. `null` if neither knows it. `raw` is `null` for an airport without a report. |
| `leds[].look` | The LED's current effect: `solid`, `off`, `blink` (`period` seconds per on/off cycle; with two `colors` it alternates between them instead of turning off), `pulse` (`period`; `low`, if present, is its dimmest point, e.g. `0.3`, otherwise it fades to off), or `cycle` (steps through `colors`, `step` seconds each). Colors are CSS hex colors. |
| `leds[].wind` | While a wind visualizer runs (Wind, Wind Gusts, Wind Direction): the airport's wind for its barb on the Map page, `{"dir": 270.0, "kt": 12}` (the direction it blows from, and the sustained speed). `null` when it's calm, variable (`VRB`), has no direction or no report, and for every other visualizer. |
| `leds[].virtual` | A virtual airport: no LED on the strip, so the Map page draws it in a dashed circle. |
| `visualizer.areas` | Which areas the Map page draws while the visualizer runs: `advisories` (Advisories, from `/api/advisories`), `tfrs` (TFR, from `/api/tfrs`), else `null` |
| `fetch` | The METAR fetch: `next` is when it next happens (Unix time, compare it with `now`; `null` if none is scheduled), `seconds` how long that wait is (600 for the regular fetch every 10 minutes; 60 for a retry after a failed fetch, which comes first), `fetched` when METARs were last fetched (`null` before the first). `GET /fetch` restarts the 10-minute wait. The Home page's Fetch METARs button counts down with it, and reloads once the next fetch has come |
| `visualizer.autoRotate` | Auto-rotate: `enabled` and `seconds` are its settings (`visualizer.auto_rotate`); `next` is when it next changes the visualizer (Unix time, compare it with `now`), `null` while it's off. Picking a visualizer by hand (`/visualizer/...`) starts the wait again, so `next` moves a whole delay ahead |
| `visualizer.legendInUse` | The `key`s of the legend entries the LEDs (and virtual airports) show now, in the legend's order (see `/api/status`'s `visualizer.legend`); `null` for a whole-strip visualizer (Rainbow, Chase), whose legend is always shown whole. Follows the LEDs: a fetch, an airport change or a different visualizer changes it |
| `visualizer.legendInUseOnly` | The `visualizer.legend_in_use_only` setting: whether the web pages list only those entries |
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
| `decoded` | One line per item the report has, in this order: `Observed`, `Wind`, `Visibility`, `Weather` (e.g. `Light rain, mist`), `Clouds` (one line per layer; later layers have an empty `label`, and the ceiling is marked), `Temperature`, `Dewpoint`, `Altimeter`, `Lightning`. Empty when the airport isn't reporting. Weather codes the map doesn't know are shown as they are. |
| `summary` | A few sentences about the weather, in this order, for what the report has: the flight category and what it means, the weather (e.g. `Light rain, mist`), `Lightning reported`, the wind, the ceiling (or the lowest clouds, or `Clear skies`), the density altitude (to the nearest 100 ft), a fog warning when the temperature and dewpoint are 2°C or less apart, and an icing warning between -20°C and 2°C with clouds or precipitation. Empty when the airport isn't reporting. |
| `raw`, `flightCategory`, `obsTime` | `null` when the airport isn't reporting |

### `GET /api/advisories`

The G-AIRMETs and SIGMETs the Advisories visualizer shows, for the Map page's areas. No authentication. The map
fetches both from aviationweather.gov with the METARs (every 10 minutes). Only areas starting below 18,000 ft are
included (no high-level turbulence, and no freezing level lines), and only those in effect now.

- **G-AIRMETs** (graphical AIRMETs): over the contiguous US, text AIRMETs ended in January 2025 and G-AIRMETs
  replaced them. The map takes the forecast snapshot nearest the current time.
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

The aircraft around the map's airports, from [adsb.fi](https://adsb.fi/)'s open data. The Map page asks for it while its
**Live traffic** box is ticked. No authentication.

The map asks adsb.fi only when this is requested and what it has is older than `geo.map.traffic_seconds`, so any number
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
| `now`, `fetched` | Unix times on the map's clock: now, and the last fetch that worked (`null` before the first) |
| `interval` | Seconds between fetches: `geo.map.traffic_seconds`, kept between 2 and 60 |
| `error` | Why the last fetch failed (e.g. `couldn't reach adsb.fi: …`, `no airport positions yet`), else `null` |
| `center`, `radius` | The circle asked about: around every airport plus 25 NM, at most 250 NM (adsb.fi's limit) |
| `aircraft[]` | Aircraft with a position no older than 60 s. Ones on the ground only with `geo.map.traffic_ground` |
| `aircraft[].alt` | Barometric altitude in feet (the GPS one if there's none); `null` on the ground |
| `aircraft[].gs`, `track`, `vrate` | Ground speed (kt), track (degrees true) and vertical rate (ft/min); `null` when not sent |
| `aircraft[].category` | The ADS-B emitter category the aircraft sends (`A1` to `A7`, `B1` to `B7`, `C1` to `C3`), `null` if none |
| `aircraft[].kind` | What the Map page draws, from `category`: `light` (A1, and B4 ultralights), `small` (A2, and A6 high performance), `large` (A3, A4), `heavy` (A5), `helicopter` (A7), `glider` (B1), `balloon` (B2), `drone` (B6), `vehicle` (C1, C2), else `unknown`. Some ICAO types override it: `super` for the biggest (A388, 747, An-124, C-5…), and `helicopter` for common helicopter types, since many send `A1` |
| `aircraft[].emergency` | adsb.fi's emergency status (e.g. `general`), `null` for none. Squawks 7500, 7600 and 7700 are in `squawk` |
| `aircraft[].at` | When the position was reported (map's clock). The Map page moves each aircraft along its track from there |

## Control

These endpoints change the map immediately. Except for auto-rotate, nothing they change is saved to `config.json`, so the changes are lost on restart. Each one returns the HTML of a UI page; ignore it.

| Endpoint | Description |
|---|---|
| `GET /brightness/<level>` | Set LED brightness, `0.0`–`1.0`; the map ignores values outside that range. The dimming schedule overrides it at the next dawn, sunrise, sunset or dusk. |
| `GET /display/on`, `GET /display/off` | Turn the OLED screen on or off (blank). Not saved: it's back on when the map restarts. A 409 if the screen is turned off in Config (`display_screen.enabled`), which is the saved setting. |
| `GET /visualizer/<id>` | Switch to a visualizer by its id, e.g. `/visualizer/wind_direction`, or by its number, `/visualizer/3` (see the table below). A 404 for one there isn't. |
| `GET /visualizer/next` | Next visualizer; after the last one it goes back to the first |
| `GET /visualizer/previous` | Previous visualizer; before the first one it goes to the last |
| `GET /visualizer/auto_rotate/on`, `GET /visualizer/auto_rotate/off` | Turn auto-rotate on or off (the Remote page's switch). Saved, as `visualizer.auto_rotate.enabled`, though it needs no login: it changes only that setting. The timer starts again now. |
| `GET /locate/<pixel>` | Pulse one LED white. Ignored while an exclusive visualizer is running. |
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
- `display_screen.enabled`: turns the OLED screen on or off (blank)
- `tfr.nearby_nm`: the TFR visualizer also shows a TFR this close to an airport (dim), 0 to 50 NM; 0 is inside only. 10 by default. Applies right away
- `lightning.animation`: a double flicker every 2 s on airports with lightning (`LTG` in the report) or a thunderstorm (`TS`, `TSRA`, `VCTS`...), over whatever every weather visualizer shows; Rainbow and Chase are unaffected. Off: no flashes anywhere (Precipitation still shows a thunderstorm: its precipitation, else yellow)
- `visualizer.missing_data_blink`: the slow red blink on an airport whose report lacks what the visualizer shows (no flight category, visibility or sky condition; no wind speed; weather codes the map doesn't know...), in every visualizer. `false`: those LEDs stay dark, and the legends say *Off*. `true` by default
- `visualizer.estimated_category_breathing`: an estimated flight category (the station reported visibility or clouds, but no category) breathes slowly. `false`: a steady color, like a reported category; the OLED still marks it (`VFR*`). `true` by default
- `visualizer.legend_in_use_only`: the legends on Home, Map and Remote list only the entries the LEDs are showing now (e.g. only VFR and MVFR), and follow them as they change. `false` (everything the visualizer can show) by default
- `lightning.color`: the flicker's color, `yellow` (the default) or `white`; anything else is a 400. Precipitation's thunderstorm stays yellow either way (its snow is white)
- `display_screen.locate_active`
- `display_screen.delay`
- `update.channel`: what **Update** installs: `releases` (the newest release tag, never an older one; the default), `latest` (the newest commit on GitHub, released or not, for testing) or, only with `dev_mode`, `branch` (the newest commit of `update.branch`, even after a force push)
- `update.branch`: the branch on GitHub the `branch` channel follows, e.g. `/config/edit/update.branch/feature/radar`. A name starting with `-`, with `..` or with spaces is a 400

`dev_mode` (top level, `false` by default) can only be changed by editing `config.json` by hand: `/config/edit/dev_mode/…` is a 400. With it on, Config > Software offers **Branch** under *Update to*, with a list of GitHub's branches (refreshed by each check: push a branch, then **Check now**). Turning it off makes a `branch` channel act as `releases`; the saved channel and branch stay. It also turns on mock METARs on the Airports page (see *Mock METARs*).
- `led.brightness.normal`, `led.brightness.dimmed`, `led.brightness.off`: the level in use now changes right away; the others take over at their sun time
- `led.quiet_hours.enabled`, `led.quiet_hours.start`, `led.quiet_hours.end`: the LEDs are off (0%), and the OLED screen blank, from the start time to the end time, in the Pi's local time; the window can cross midnight. Times are 24-hour `HH:MM` (e.g. `/config/edit/led.quiet_hours.start/22:30`); anything else is a 400. Changes apply right away
- `led.inittest`: whether the startup sequence plays when the map starts; turning it on also plays it once now. With quiet hours on, it also plays when they end, and when they begin the same sequence takes the map dark (the same path, each LED from its color to dark; Comet runs the other way, leaving the strip dark). Only at the scheduled times, not when a settings change starts or ends quiet hours, and not while the LEDs are at 0% anyway
- `led.init_sequence`: the startup sequence: `comet` (a rainbow along the strip; the default), `center_out` (the map fades in from the middle of the box around the airports out to its edges), `edges_in` (from the edges in to the middle), `sweep` (across the map, from `led.init_sweep_from`), `radar` (a beam from north, clockwise) or `sparkle` (one LED at a time, in random order). All but `comet` fade each LED in to its visualizer color over 3 seconds. Changing it plays it once now
- `led.init_sweep_from`: where `sweep` starts: `W` (west to east; the default), `NW`, `N`, `NE`, `E`, `SE`, `S` or `SW`. Changing it plays the sequence once now
- `led.dim_on_refresh`: the LEDs fade to half their brightness while METARs are fetched (at least a second), then fade back
- `visualizer.active`, the default visualizer used at startup, by id (`/config/edit/visualizer.active/wind`); a number is taken too and saved as the id. An unknown one is a 400. Saving it doesn't change the visualizer that's running now; use `/visualizer/<id>` for that.
- `visualizer.auto_rotate.enabled`
- `visualizer.auto_rotate.delay_seconds` (the new delay starts counting when it's saved)
- `visualizer.auto_rotate.skip`: the visualizers auto-rotate leaves out, as a JSON list of ids, e.g. `/config/edit/visualizer.auto_rotate.skip/%5B%22wind%22%2C%22wind_gusts%22%5D` for `["wind","wind_gusts"]` (`[]` leaves none out). Names and numbers are taken too, and saved as ids; an unknown one is a 400. Exclusive visualizers (`"exclusive": true` in `/api/status`) are always left out. The previous/next buttons still go to every visualizer.
- `visualizer.auto_rotate.skip_dark`: auto-rotate also leaves out a visualizer while it would show nothing: every LED and virtual airport off (e.g. Precipitation on a dry day, or Advisories with none in effect). A red "METAR not available" blink counts as showing something. If every other visualizer is dark, the current one stays

Map page settings (apply the next time the Map page is opened):
- `geo.map.background`: `sectional`, `satellite` or `radar`
- `geo.map.chart_type`: `sectional`, `terminal` (VFR Terminal Area) or `ifr_low` (IFR Enroute Low)
- `geo.map.chart`: the sectional name, as listed in [sectionals.json](src/metarmap/web/static/sectionals.json), such as `Houston`. If it's missing or unknown, the map uses the sectional that covers the most airports.
- `geo.map.view`: `airports` (fit to the airports), `chart` (the whole sectional) or `custom` (`geo.map.center` and `geo.map.zoom`)
- `geo.map.traffic_seconds`: how often live traffic is fetched from adsb.fi (see `/api/traffic`), 2 to 60 seconds,
  5 by default. adsb.fi allows one request a second; anything outside that range is a 400. Applies right away
- `geo.map.traffic_ground`: `true` to show aircraft on the ground too (off by default). Applies right away

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
| `POST /config/airports/mock` | `dev_mode` only (a 400 without it): the Airports page's *Mock METAR* field. `{"pixel": 0, "metar": "METAR KDWH 272353Z AUTO 08003KT 9SM CLR 21/18 A3014"}` saves it as the airport's `mock_metar` in `config.json` and shows it at once, and after every fetch, in place of the fetched report; `"metar": ""` goes back to the real one. Text that doesn't start like a METAR (airport code, then the time) is a 400. Answers `{"code", "mock", "flightCategory"}`. See *Mock METARs* below. |
| `GET /config/airports/edit/<oldcode>/<newcode>` | Older, by code: change the first airport with `oldcode` to `newcode` |
| `GET /config/airports/edit/prop/<airport>/<key>/<value>` | Older, by code: set `text` (the name) or `display` of the first airport with that code (not `mock_metar`: a 400) |

#### Mock METARs (`dev_mode`)

To test a report on the physical map, type a raw METAR in an airport's *Mock METAR* field on the Airports page (shown only with `dev_mode`), or put it in `config.json` as the airport's `"mock_metar"` (then restart). It replaces that airport's real report everywhere: the LEDs, the OLED, Home Assistant and the web pages, until it's cleared. The map reads the report's body (not the remarks): wind (`KT` or `MPS`), visibility (`9SM`, `1 1/2SM`, `M1/4SM`, `P6SM`, meters, `CAVOK`), weather codes, clouds and `VV`, temperature/dewpoint, and the altimeter (`A` or `Q`); `LTG` anywhere is lightning. The flight category comes from the visibility and ceiling (FAA limits), and the time from `DDHHMMZ` (this month, or last month if that day is still ahead). The airport's name and position stay its real station's. A mocked airport says `mock` on the Home, METARs and Airports pages and in the Map popup, and has `"mock": true` in `/api/status`, `/api/live` and `/api/metar/<code>`; the LEDs and OLED look as a real report would. With `dev_mode` off, saved mocks are ignored. Changing the airport's code removes its mock.

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
| `GET /update` | Updates the map from GitHub as `update.channel` says, keeping `config.json` (and an older `airports.json`): on `releases`, the newest release tag (`v2.9.0`), only if it's newer than the running version; on `latest`, the newest commit; on `branch` (`dev_mode`), the newest commit of `update.branch`. Waits until it's done and returns the output as HTML. Restart afterwards to use the new code (the web UI's Update and Install buttons restart the map for you when new code was installed). |
| `POST /update/start` | Starts the same update in the background (or reports the one already running) and returns its progress, as below. Used by the web UI's progress bar. With a JSON body `{"version": "v2.7.0"}` it installs that release instead, older or newer, whatever the channel. A `version` that isn't a release version is a 400. |
| `GET /update/progress` | Progress of the update started with `/update/start`: `{"fraction": 0.4, "label": "Downloading the update", "done": false, "ok": null, "changed": null, "target": "v2.9.0", "message": "", "errors": []}`. When `done`, `ok` says whether it worked, `changed` whether new code was installed, `target` what was installed (a release tag, or a commit on the `latest` channel), `message` a one-line summary such as `Installed v2.9.0` or `Already on the newest release (v2.8.4)`, and `errors` holds git's error messages. |
| `GET /update/check` | Asks GitHub now what's newest (the map also does this when it starts and every 6 hours) and returns the same object as `update` in `/api/status`. |
| `GET /restart` | Clears the LEDs and restarts the map's process. The connection usually drops before a response is sent. |

## Web UI pages

| Endpoint | Auth | Description |
|---|---|---|
| `GET /` | | Home: flight category counts, visualizer controls and legend, brightness and sun times |
| `GET /metars` | | Table of METARs for every airport |
| `GET /map` | | Live mirror of the LEDs and the OLED screen on an FAA chart, satellite or radar background (a new radar scan every 5 minutes while radar is shown) |
| `GET /map/legend` | | The active visualizer's legend (HTML), which the Map page and the Remote page swap in when the visualizer changes |
| `GET /remote` | | A remote control laid out for an iPad in kiosk mode, in three tabs: Visualizer (the visualizers and the legend, with a footer of controls: the auto-rotate switch with a countdown to the next visualizer, which is saved, and LED brightness and the OLED switch, which aren't), Map (the Map page's live map) and Locator (Locate for every airport). It follows changes made anywhere else (it polls `/api/live`). `/remote#map` or `#locator` opens that tab; otherwise it opens the one last used on that device. *Add to Home Screen* opens it full screen |
| `GET /raw` | | Raw METAR text for every airport, followed by the full parsed data |
| `GET /raw/<code>` | | Raw METAR text for one airport |
| `GET /debug` | | Debug information |
| `GET /config` | yes | Configuration page |
| `GET /config/airports` | yes | Airport configuration page |
| `GET /static/<file>` | | Stylesheet and script for the web UI |
