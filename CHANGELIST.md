### dman776 Unreleased

- Rainbow and Chase are always at the end of the visualizer list. Ceiling and Dewpoint Spread are now 8 and 9,
  Rainbow 10 and Chase 11. A saved default visualizer (`visualizer.active`) of 8 or 9 now means Ceiling or
  Dewpoint Spread instead of Rainbow or Chase; set it again on the Config page if it was one of those. Home
  Assistant picks visualizers by name, so it isn't affected

### dman776 2.8.0 (2026-10-25)

- New visualizer, Ceiling: the lowest broken or overcast layer (or the vertical visibility when the sky is
  obscured), at the flight category limits: white above 3,000 ft, yellow 1,000-3,000, orange 500-999, red below
  500, and dim white with no ceiling. Flight Category shows the worse of ceiling and visibility; this shows the
  ceiling on its own
- New visualizer, Dewpoint Spread (fog risk): red at 1°C or less, orange at 2°C, yellow at 3-4°C, white when it's
  drier
- Both are added at the end of the list (numbers 10 and 11), so the numbers of the others, and a saved default
  visualizer, don't change

### dman776 2.7.0 (2026-10-25)

- Precipitation is in auto-rotate now, and the OLED's locate pulse works while it's shown (it was marked as using
  the whole strip, like Rainbow and Chase, though it lights each airport on its own)
- Config > Visualizer: untick visualizers to leave them out of auto-rotate (`visualizer.auto_rotate.skip`, a list
  of names). Applies right away; the previous/next buttons still go to every visualizer. If nothing is left to
  rotate to, the visualizer stays where it is
- The LEDs dim to half their brightness while new METARs download (at least a second), as a sign of an update.
  Turn it off with **Config > LED pixels > Dim while updating** (`led.dim_on_refresh`)
- Auto-rotate (on/off and the delay) takes effect right away, without a restart
- Restart waits 5 seconds (was 15) before checking whether the map is back
- Map page: a fullscreen button (on a phone without fullscreen, the map fills the window; Esc or the button
  closes it)
- Map page: the visualizer name and legend follow the visualizer when it changes, including auto-rotate and Home
  Assistant, and the previous/next buttons no longer reload the page, so the zoom and position stay
- Map page: the legend starts closed, and the browser remembers whether you opened it
- Map popup: a new Summary tab (the first one) with the weather in plain English: what the flight category
  means, the weather, wind, ceiling, density altitude, and fog and icing warnings. Also `summary` in
  `/api/metar/<code>`
- Without an LED strip, a new number of LEDs takes effect right away, without a restart
- New data, a new visualizer or new airports show on the LEDs right away, instead of after the current animation
  finishes
- Airports page: airports with an empty name get their name filled in from aviationweather.gov (e.g. "Houston/
  Hobby Arpt"), and changing an airport's code changes its name to the new airport's. Names you type are kept
- METARs come from aviationweather.gov's JSON API instead of XML: about half the download, and one fewer
  package (`xmltodict` is no longer needed). The map shows exactly the same data; each airport's data also has
  its `name` now (e.g. "Houston/Hobby Arpt, TX, US")
- The OLED screen turns on and off right away from Config (or Home Assistant's switch, or
  `/config/edit/display_screen.enabled/...`), without a restart
- Home page: an OLED display switch under LED brightness turns the screen, and its copy on the Map page, on or
  off. Like the brightness it isn't saved; the screen is back on when the map restarts. Also `/display/on` and
  `/display/off`, and `display` in `/api/status`
- Fixed: turning off an airport's OLED switch on the Airports page gave "400 Bad Request"
- API.md no longer says config edits run the value as Python code (they haven't since 2.2.4)

### dman776 2.6.1 (2026-10-25)

- Fewer greens: only Flight Category's VFR is green now. Wind (and Wind Gusts) 1-9 kt is blue, Density Altitude under
  1,000 ft above the field is cyan, Temperature 65-79°F is cyan, and Visibility is white over 5 miles, then yellow
  (3-5), orange (1-3) and red (under 1)

### dman776 2.6.0 (2026-10-25)

The LEDs now follow one set of rules in every visualizer (see the legends):

- An airport with no report is off; a report without the value a visualizer shows is a slow red blink
- Light weather (`-`) breathes without going dark, moderate is solid, heavy (`+`) blinks between bright and dim,
  and "in the vicinity" (`VC`) is dim, whatever the weather
- Precipitation: the color is what it is (rain blue, drizzle dim blue, snow white, freezing rain and drizzle, ice
  pellets and hail cyan, thunderstorms yellow, squalls, funnel clouds and similar magenta, unknown precipitation
  orange, fog, smoke, haze and mist as before). The most significant weather wins, two kinds at once (e.g. `-RASN`)
  alternate, and a thunderstorm with rain or snow alternates their color with yellow. Fixes heavy rain showing solid,
  freezing rain looking like rain, and ice pellets, hail, squalls and showers nearby blinking red as "unknown". New
  color settings: `color.weather.snow`, `ice`, `hazard` and `unknown`; `color.weather.drizzle` is no longer used
- Wind, Temperature, Pressure and Density Altitude use a few solid bands instead of blended colors. Wind: calm dim
  white, 1-9 kt green, 10-14 yellow, 15-24 orange, 25+ red. Temperature has its own band below freezing. Density
  Altitude shows how far the density altitude is above the field (under 1,000 ft green ... 3,000 ft or more red)
- Wind Gusts: the wind's color, alternating with the gusts' color when it's gusting
- Visibility uses the flight category limits and colors (over 5 miles VFR ... under 1 mile LIFR)
- The legends are built from the same tables as the colors, so they always match. (Before: Wind said calm was off
  but showed dark gray, and Wind Gusts described the wrong color)
- A density altitude for a sea-level airport or at 0°C is no longer treated as missing

### dman776 2.5.0 (2026-10-25)

- Config > Access: change the web UI login and the Pi's Wi-Fi network from the web UI. On a Raspberry Pi (only), a
  new web UI password also becomes the Linux password of the Pi's login user (e.g. `pi`); if that can't be set,
  nothing changes. A Wi-Fi change keeps the old network, so the Pi goes back to it if it can't join the new one
- New `POST /config/login` and `POST /config/wifi` (see API.md); passwords go in the request body, never a URL

### dman776 2.4.3 (2026-10-25)

- Code: the visualizers are modules of plain functions instead of classes; METAR parsing is plain functions
  (`process()`, `parse_report()`) separate from fetching; attributes like `self.__data__` are now `self._data`.
  The LEDs, pages and API are unchanged

### dman776 2.4.2 (2026-10-25)

- Map page: an airport's popup has Raw and Decoded tabs. Decoded shows the report in plain English (wind, visibility,
  weather, clouds with the ceiling marked, temperature, dewpoint, altimeter, lightning) and how long ago it was made.
  The popup remembers the tab you used last
- New `GET /api/metar/<code>`: an airport's METAR, raw and decoded (see API.md)
- Visibility reported as a fraction (`1/2`, `1 1/2`) no longer stops an airport's METAR from being read
- Map page popups open below the zoom and background buttons instead of under them
- Airports page: the heading says how many LEDs have an airport and how many don't (it said "one airport each")
- Map page: airports that aren't reporting are shown as empty, uncolored rings with their code, instead of being left off
  the map. Their positions come from aviationweather.gov's station information, looked up once per airport; a
  failed lookup is retried every minute, like a failed METAR fetch
- A failed METAR fetch (e.g. aviationweather.gov answering 502 Bad Gateway) is retried every minute until it
  works, instead of leaving the map without data until the next fetch 10 minutes later
- `install.sh` no longer says the web UI password can be changed on the Config page (it can't yet)

### dman776 2.4.1 (2026-10-25)

- New `install.sh` sets up a Pi in one step: system packages, I2C, a Python environment (`.venv`) with the map's
  packages, the web UI login and city, and the service. It works on Raspberry Pi OS Bullseye and Bookworm (which no
  longer allows `sudo pip3 install`), and is safe to run again
- Rewrote the README: features, parts and wiring, installing with `install.sh`, setting up airports, settings,
  updating and troubleshooting
- New installs serve the web UI on port 80 (http://metarmap.local/) instead of 8080; existing maps keep their setting

### dman776 2.4.0 (2026-10-25)

- Airports now live in `config.json` as a list, one entry per LED (`code`, `name`, `display`). On its first start the
  map moves them there from `airports.json`, which it keeps as a backup. `NULL...` placeholders become LEDs with no
  airport
- Airports page: set the number of LEDs, move airports up and down, edit names, and clear an LED; changes show on
  the LEDs right away, and a new airport's METAR is fetched straight away
- The same airport can be on more than one LED
- New API routes for airports by LED (see API.md); the older by-code routes still work
- `/api/status`: an airport's `text` is its name, or `""` (older `airports.json` files had numbers there)
- Fixed an error when the OLED loop was restarted before it had started (e.g. an airport edit right after startup)
- Restart waits 15 seconds (was 30) before checking whether the map is back
- The web server answers requests in parallel, so a slow METAR fetch (`/fetch`) no longer holds up the Map page,
  Home Assistant or loading pages
- `config.json` is saved safely: changes from parallel requests take turns, and the file is written in full before
  it replaces the old one, so a power cut while saving can't leave it half-written
- If the web server can't start (e.g. its port is in use), the LEDs and OLED keep running and the error is logged

### dman776 2.3.1 (2026-10-25)

- Restructured the web UI and API into `metarmap/web/`: `create_app()` replaces the `WebServer` class, the routes are
  split into pages, API and control, and each page's data is prepared in Python instead of in its template
- Added tests for the API's fields, the control routes and the background update
- The pages, API and URLs are unchanged

### dman776 2.3.0 (2026-10-24)

- The code is now a Python package, `metarmap`, in `src/metarmap/`; run the map with `python3 -m metarmap`
  (`controller.py` still works, so maps with the old service file keep starting after an update)
- `metarmap.service` runs `python3 -m metarmap` as root directly instead of through `sudo`. At startup the map
  switches an installed service file that still runs `controller.py` to the new one (only if it's one of the
  service files this project shipped; the old one is kept as `metarmap.service.controller-py.bak`). The new service
  is used from the next reboot or `sudo systemctl restart metarmap`
- `metarmap/app.py` builds the map in one place instead of using globals; the settings object no longer carries the
  renderer, OLED loop or sun times around
- Restart (from the web UI or after an update) starts `python3 -m metarmap`
- The web UI and API are unchanged

### dman776 2.2.6 (2026-10-24)

- Map page: the "What the LEDs mean" legend is now on the map (bottom left), collapsible, and starts collapsed on phones

### dman776 2.2.5 (2026-10-24)

- Fixed stale METARs: the map now asks for each station's latest report (asking for 5 hours of reports could hit the
  API's 400-report limit and drop the newest ones); a latest report older than 5 hours counts as not reporting
- Update shows a progress bar instead of git's output, and only shows details if it fails
- Restart closes any open popup, waits 30 seconds, then reloads the page once the map is back
- Update runs git as the owner of the map's folder (e.g. `pi`) instead of root, and gives back files earlier updates
  left owned by root, so file permissions stay consistent
- Fixed a startup crash on the Pi caused by a conflicting `GPIO.setmode()` call
- Crashes are now written to metarmap.log as well as the system journal
- Removed "Raw" from the menu (the `/raw` page is still there)
- The map runs without a Raspberry Pi: with no LED strip or OLED screen it uses in-memory stand-ins, and the web UI
  works as usual (see Development in the README)
- Restructured the LED renderer and OLED loop behind small interfaces, with tests; the LEDs and OLED show exactly
  what they did before

### dman776 2.2.4 (2026-10-24)

- Restructured the visualizers so each one only decides how an airport's LED looks; the LEDs show exactly what they did before
- `config.json` now has a schema: missing settings get defaults, and Config edits are checked against each setting's type
- Config edits with an unknown setting or a bad value now return a clear error (HTTP 400) instead of failing or adding a stray key
- Config edits no longer run the value as Python code
- Chase visualizer adapts to the number of LEDs (`led.count`)
- Added unit tests (pytest), linting (ruff) and GitHub Actions; development setup is in `pyproject.toml`
- Moved the LED test and other one-off scripts to `tools/` (the LED test is now `sudo python3 tools/test1.py`)

### dman776 2.2.3 (2026-10-24)

- Fixed the OLED display occasionally getting stuck and no longer rotating
  - METAR data is now replaced all at once, so the display never reads a half-updated set of airports
  - A malformed METAR only affects its own airport (and is logged) instead of stopping processing for the rest
  - The display loop recovers from errors, picks up airport edits safely, and shows "--" for values it can't format
  - A watchdog restarts the display if it stops changing for 60 seconds
  - LED updates from the display's locate pulse and the main loop no longer overlap
- Errors in background threads are now written to metarmap.log
- Fixed error handling for METAR fetches that could stop the whole map

### dman776 2.2.2 (2026-10-24)

- Home page shows the last METAR fetch time with how long ago it was, and flags it when it is over 20 minutes old

### dman776 2.2.1 (2026-10-24)

- New airplane logo in the web UI, plus a matching browser tab icon

### dman776 2.2 (2026-10-24)

- Map page is now a live mirror of the physical map: every LED's real color and effect (blinking, pulsing, lightning flashes, rainbow, chase), the white locate pulse, and a window showing the OLED screen
- Map page backgrounds: FAA chart (VFR Sectional, VFR Terminal Area or IFR Enroute Low), satellite, or live NEXRAD weather radar
- Map page works with any FAA sectional; choose your chart and starting view under Config → Map page (new `geo.map` settings)
- Added `GET /api/live` for the Map page; the OLED and renderer now report what they are showing
- Config edits accept plain text values (such as a chart name)

### dman776 2.1 (2026-10-24)

- Redesigned the web UI: dark theme, top navigation bar, and layouts that work on phones
- Home page shows flight category counts, the airports below VFR, and highlights the next scheduled brightness change
- Added a "What the LEDs mean" legend for every visualizer on the home page (also in `/api/status`)
- Visualizer descriptions are now plain text; each visualizer lists its legend in a new `legend` property
- METARs page: filter by flight category, search by ICAO code, and a Locate button on every row
- Config page: toggle switches, auto-rotate and schedule brightness settings, and a reminder when a change needs a restart
- Map page: darker map with markers colored by flight category
- Removed Bootstrap, jQuery and Font Awesome; the UI now uses its own stylesheet and script served from `/static`
- Copyright year in the footer updates automatically

### dman776 2.0 (2026-10-23)

- Added a JSON REST API (`GET /api/status`) for scripts and home automation, documented in API.md
- Used by the Home Assistant integration ([metarmap2_ha](https://github.com/dman776/metarmap2_ha))

### dman776 1.16 (2025-09-18)

- Updated to the new aviationweather.gov API (Sept 2025)
- Handle METARs that report a variable (VRB) wind direction

### dman776 1.15 (2024-07-01)

- Fixed startup check now that aviationweather.gov no longer answers pings
- Reload sun times every day so the home page stays accurate

### dman776 1.14 (2024-01-15)

- Added light freezing rain to the Precipitation visualizer
- Adjusted the order precipitation codes are checked in

### dman776 1.13 (2024-01-15)

- Precipitation visualizer now runs in exclusive mode
- Changed snow visuals

### dman776 1.12 (2024-01-15)

- Added light unknown precipitation to the Precipitation visualizer
- Light snow is now white

### dman776 1.11 (2024-01-15)

- Added light freezing drizzle to the Precipitation visualizer

### dman776 1.10 (2024-01-14)

- Added light snow and snow to the Precipitation visualizer

### dman776 1.9 (2023-11-12)

- Fixed the OLED display when wind speed is variable (VRB)

### dman776 1.8 (2023-10-22)

- Fixed broken aviationweather.gov API call
- Fixed visibility when it isn't reported

### dman776 1.7 (2023-05-08)

- Added the map's IP address to the home page
- Visualizer and brightness changes no longer need authentication

### dman776 1.6 (2023-03-21)

- Added auto-rotate of visualizers (`visualizer.auto_rotate` in config.json)
- Added the UP (unknown precipitation) code to the Precipitation visualizer
- Fixes for METARs that don't report temperature or dewpoint
- Fixed the Density Altitude and Flight Category visualizers; moved colors out of metar.py

### dman776 1.5 (2023-03-16)

- Added DensityAltitude visualizer (and others)
- Added config page for airports (including OLED display)
- Added authentication to webserver for config edits
- Added sunrise (etc) times to web server index page
- Added self-update and restart buttons
- Added online map of FlightCategory to web server

### dman776 1.0 (2023-02-01)

- Completely rewritten and multi-threaded
- Added webserver (Bottle) with templates
- Added multiple visualizers of data
- Added Renderer class for map display
- Added Display class for OLED display
- Added Metar class for metar data management
- Added Scheduler for various tasks
- Added Completely new configuration management
- Added Auto-restart capability
