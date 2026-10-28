### Unreleased

- Wind Direction visualizer, after Wind Gusts: each airport in the color of the direction its wind blows from, in
  eight 45° sectors (red from the north, then orange, yellow, green, cyan, blue, purple and magenta clockwise).
  Calm is dim white and variable (`VRB`) breathes white
- The visualizers from Pressure on move up by one number (Rainbow is now 11, Chase 12). A `config.json` from before
  (no `visualizer.numbering`) keeps showing the same visualizer; scripts that call `/visualizer/<n>` need the new
  numbers. Home Assistant picks visualizers by name, so it's unaffected

### dman776 3.0.1 (2026-10-27)

- Remote page (`/remote`): a kiosk remote control for the map, laid out for an iPad, with Visualizer, Map, Locator
  and Config tabs. On the Map tab the radar ("Weather") background refreshes every few minutes
- Lightning: one double flicker (every 2 s) over every weather visualizer, for an airport reporting `LTG` or any
  thunderstorm (`TS`, including `VCTS`). It always honors `lightning.animation`: with it off, Precipitation shows the
  storm's precipitation and the other visualizers a steady yellow (dim for `VCTS`)
- `dev_mode` (top level in `config.json`, edited by hand only, off by default) for testing on a real map:
  - Config > Software > *Update to* gains **Branch**, with a list of GitHub's branches (refreshed by each check), to
    install a pushed branch. With `dev_mode` off, a saved `branch` channel acts as Releases
  - Update and Install restart the map when the new code is in
  - **Mock METARs**: each Airports row has a *Mock METAR* field that replaces the airport's real report on the LEDs,
    OLED, web pages and API, until cleared. It can't be set by URL. Airports with one say `mock` on the Home, METARs
    and Airports pages and the Map popup, and have `"mock": true` in the API. Changing the airport's code removes it
- Config > Software moved to the top of Config's right-hand column
- Every log message now starts with the module, class and function that logged it, and the line number

### dman776 3.0.0 (2026-10-26)

- Virtual airports: airports with no LED, after the strip's (`led.virtual_count`, set on Config > Airports below the
  number of LEDs). They're fetched and shown like the others on the Map page, in a dashed circle, and in
  `/api/status` for Home Assistant. On the OLED (if switched on) and its copy on the Map page, a virtual airport's
  code is in a dashed box, and so is its code on the map. Their effects always run. Rainbow covers them too, while
  Chase (a wiring check) leaves them dark. Locate pulses them on the Map page only. The LEDs and the virtual airports
  together are at most 1000 airports, since each one is part of every METAR fetch. Changing the number of LEDs keeps
  the virtual airports after them. In an older `config.json`, airports past `led.count` (already on the Map page
  only) become virtual airports. `/api/status` airports and `/api/live` LEDs have a new `virtual` field
- The pages' script and style links (`?v=`) change whenever a file in `static/` does, not only with the version.
  Between releases (an update on the `latest` channel) browsers kept running a cached `app.js` with the new pages,
  so the new Virtual airports number did nothing until a hard refresh

### dman776 2.9.3 (2026-10-26)

- `install.sh` installs the newest release (a tag such as `v2.9.2`) instead of the newest commit of the branch that
  was cloned, then carries on with that release's own installer. A folder that's already on a release (picked over
  SSH or on the web UI), has changes to the code, or has `update.channel` set to `latest` is left as it is, and
  `./install.sh --latest` keeps the newest commit, for testing. If GitHub can't be reached or has no releases yet, it
  installs what's there and says so
- The header shows when the map isn't running a release: the dot by the version turns amber, the version reads
  `v2.9.2 +3 · 5c3e5a5` (commits after the last release, and the commit; `*` for code changed on the map), and an
  amber pill ("Unreleased: 3 commits after v2.9.2") links to the commit on GitHub. It also catches a version bump
  that hasn't been tagged ("Not tagged: v2.9.3") and pre-releases. The footer, Config > Software (with a link to the
  commit) and `build` in `/api/status` say the same. It's read when the map starts, so it's what's running, not what
  an update has put on disk before the restart

### dman776 2.9.2 (2026-10-26)

- Flight Category: a station that doesn't report a flight category, but reports its visibility or sky condition, gets
  an estimate from them (FAA limits; the worse of ceiling and visibility decides). Its LED breathes slowly in that
  category's color instead of shining steadily, with an "Estimated" entry in the legend. With only one of the two
  reported, the real category could be worse than shown, never better. Checked against live reports: the estimate
  matched the reported category for all 249 stations that report both. A station that reports neither still
  blinks red
- OLED: an estimated flight category has a `*` after it (`VFR*`), on the screen and its copy on the Map page. The
  category moved 4 px left to make room for `MVFR*`; the widest airport code (`KWWW`) still clears it

### dman776 2.9.1 (2026-10-26)

- README credits: the project started from prueker/METARMap, with portions by @lostlocalhost and John Marzulli, and
  has since been rewritten from scratch (it's no longer a GitHub fork). Removed the "free for personal use" header
  from `app.py`, which contradicted the MIT `LICENSE`
- **Dim while updating** fades instead of cutting: about 0.6 s down to half brightness, and 0.6 s back up after the
  download. At night levels (around 1%) it takes fewer, larger steps, because the Pi's LED library ignores
  brightness changes under 0.001; that way the brightness always comes back exactly where it was
- Config > LED pixels: the brightness levels and the test pattern no longer need a restart. A changed level applies
  right away if it's the one in use now (daytime, dawn/dusk or night), and the others at their time of day; turning
  on **Test pattern on startup** runs it once now. No setting needs a restart any more

### dman776 2.9.0 (2026-10-26)

- Updates install releases (git tags like `v2.9.0`) instead of the newest commit, and never go back to an older
  version. The map asks GitHub for a new release when it starts and every 6 hours; when there is one, every page
  shows **Update available** at the top, and the Home page's button reads **Update to v2.9.0**. After installing,
  the note says to restart
- Config > Software: **Check now**, the update channel (**Releases**, or **Latest commit** for a map you test
  unreleased changes on), and **Install a release** to install any release, older ones too (it asks before going
  back). `update.channel` setting; `POST /update/start` takes `{"version": "v2.7.0"}`; new `GET /update/check`;
  `update` in `/api/status`
- A map that installed a release isn't on a branch any more, so `git pull` over SSH needs `git checkout master`
  first. Maps on 2.8.4 and earlier still have the old Update button: their next update pulls the newest commit
  (including this change), and the one after that uses releases
- Release routine: bump the version, commit, `git tag -a vX.Y.Z`, push the commit and the tag

### dman776 2.8.4 (2026-10-25)

- Map page fullscreen: previous/next visualizer buttons, with the visualizer's name, under the background switcher
  (the page's own buttons are out of sight in fullscreen). They only show in fullscreen
- Removed the `tools/` folder (the old LED test, a Wi-Fi access point experiment and some scratch scripts). The
  README's LED troubleshooting step and the installer's closing message now point to the Chase visualizer and the
  "Test pattern on startup" setting instead of `tools/test1.py`

### dman776 2.8.3 (2026-10-25)

- Wind Gusts now shows how much stronger the gusts are than the wind (the gust spread) instead of repeating Wind's
  colors with a flash: dim white with no gusts, then blue (1-9 kt above the wind), yellow (10-14), orange (15-19)
  and red (20 or more). Wind shows how strong the wind is; this shows how much it swings, in steady colors. Its
  name and number are unchanged
- Fixed: the map used a whole CPU core (100%) all the time. The LED loop asked the animations "is it time yet?"
  thousands of times a second; it now rests 10 ms between checks (the fastest effect changes every 100 ms), so
  an idle map uses under 1%. The LEDs look the same, and the tests run faster too
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
