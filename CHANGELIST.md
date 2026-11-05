### Unreleased

- **Startup sequences**: besides the rainbow Comet, the map can fade in to the visualizer from where each airport
  is, over 3 seconds:
  - **Center out** from the middle of the box around the airports to its edges, and **Edges in** the other way
  - **Sweep** across the map from one of 8 sides (`led.init_sweep_from`: west to east, northwest to southeast...)
  - **Radar sweep**: a beam turning clockwise from north
  - **Sparkle in**: one LED at a time, in random order
  - Config > Physical display: the switch is now "Startup sequence" (still `led.inittest`, so Home Assistant's
    switch works as before), with a Sequence select (`led.init_sequence`, Comet by default), a Sweep direction and
    **Play now**. Changing either plays it once. A visualizer that drives the whole strip (Rainbow, Chase) fades
    in white, then starts. New `GET /led/init_sequence/play`

- **A parsed METAR is a `Report`** (inside the code; the web UI, the API and Home Assistant work as before):
  - Each airport's report is a frozen dataclass (`models.Report`, with `SkyLayer` for the clouds) with snake_case
    fields, instead of a dict with the API's camelCase keys; an airport with no report is `None` instead of `{}`
  - `Report.to_api()` gives the field names `/api/status` uses, and a test checks they're the same as before
  - The class that fetches them is `metar.Reports` (was `metar.METAR`)
- **A report without wind, visibility or an altimeter setting shows dashes** on the OLED instead of
  `CALM / 0SM / 0.00`, and the Map page's Decoded and Summary tabs leave out the wind instead of saying "Calm".
  The Wind and Wind Gusts LEDs show missing data for it instead of calm. A calm wind (`00000KT`) is still CALM, and
  the API still sends 0 for all three
- **At startup the LEDs show the visualizer first**, then the first "Highlight active airport" pulse 2 seconds
  later. It used to come right after the test pattern, before any visualizer color. The OLED shows the first
  airport at once
- **A misspelled `geo.city` no longer stops the map at startup.** A hand-edited city the sun times don't know is
  logged and replaced by Houston when the map starts, as other invalid settings are, and setting one through
  `/config/edit/geo.city` is refused. It used to fail with an `AttributeError` while loading the sun times
- **The METAR fetches say who they are**: every request to aviationweather.gov, the FAA's TFR list and adsb.fi
  sends `metarmap2/<version> (+https://github.com/dman776/metarmap2)`. The METAR and station fetches sent a fake
  Edge browser's User-Agent; the TFR, advisory and traffic fetches sent `metarmap/<version>`
- Cleanups inside the code: the standard library's `zoneinfo` instead of `pytz` (no longer a dependency);
  `pyproject.toml` is the one list of dependencies (`requirements.txt`, which nothing used, is gone); no more
  `class X(object)`

### dman776 3.2.0 (2026-11-03)

- **Settings follow their own rules** (inside the code; the web UI and the API work as before):
  - What each setting accepts (the LED pins and color orders, the lightning colors, the TFR distance, the traffic
    interval, quiet hours times, the update channel and branch) is part of the settings themselves (`settings.py`),
    with the same error messages
  - A hand-edited `config.json` value a setting doesn't accept is logged and replaced by its default when the map
    starts, as quiet hours times already were (e.g. `led.pin` 7 becomes 18)
  - Every change to the settings or the airports is announced, and the map follows it from one list in `app.py`
    (the LEDs, the OLED, auto-rotate and quiet hours timers, the update check, a new airport's name and METAR).
    Saving a value it already had no longer redoes those; one of them failing is logged and no longer fails the
    page
- **Visualizers have ids** (`wind_direction`), which `config.json` saves instead of a number (`visualizer.active`)
  and names (`visualizer.auto_rotate.skip`), so adding a visualizer anywhere in the list or rewording a name no longer
  moves anyone's settings. An older `config.json` is converted once when the map starts, keeping the same visualizers
  (`visualizer.numbering` is no longer needed)
  - `/visualizer/<id>` and `/config/edit/visualizer.active/<id>`; numbers still work, so Home Assistant and scripts
    that use them keep working
  - `/api/status` and `/api/live` add each visualizer's `id`; `visualizer.active` in `/api/status`'s `config` is the
    id
  - Inside the code: each visualizer declares itself as one `Visualizer` (id, name, description, legend, look or
    strip look, barbs, areas), checked when the map starts; `exclusive` comes from having a strip look
- **The log** (`metarmap.log`):
  - Problems are logged as `WARNING` or `ERROR` (everything was `INFO`), so `grep -E "WARNING|ERROR" metarmap.log`
    finds them
  - A line says where it was logged as `metarmap.metar.fetch:379`, the standard way (the class name is gone), in
    local time
  - Tracebacks are on lines of their own, as Python prints them, instead of one long line with `\n` in it
  - The journal (`journalctl -u metarmap`) gets warnings, errors and crashes only, in the same format, instead of a
    second copy of the whole log
  - Inside the code: every module logs with Python's `logging` (`metarmap/logs.py` sets it up when the map starts);
    `lib/safe_logging.py` and `lib/logger.py` are gone. Running the tests no longer writes to `metarmap.log`

### dman776 3.1.5 (2026-11-03)

- **Current brightness schedule highlight** (Home): highlight the active sun-brightness period rather than the next
  event; while quiet hours are active, highlight the Quiet hours row instead. From Travis Cole (traviscole)
- Remote: the visualizer's name is larger, to read across the room (it grows with the screen)
- **Remote: controls in a footer** (Visualizer tab, under the legend, which still scrolls): an auto-rotate switch with a
  small clock counting down to the next visualizer, LED brightness and the OLED switch. The Config tab is gone. The
  auto-rotate switch is saved (`visualizer.auto_rotate.enabled`), with no login, through the new
  `/visualizer/auto_rotate/on` and `/off`; `/api/live` has `visualizer.autoRotate` for the countdown
- Remote: spacing that works on an older iPad's Safari (before 14.1)

### dman776 3.1.4 (2026-11-02)

- **Estimated flight category breathing** (Config > Visualizers, `visualizer.estimated_category_breathing`,
  on by default): off shows an estimated flight category in a steady color instead of breathing. The estimate and
  its color are unchanged, the OLED still marks it (`VFR*`), and the Map page's popup says *No category*; the
  legend follows the setting. From Travis Cole (traviscole)

- **Quiet hours** (Config > Physical display, `led.quiet_hours`, off by default): override physical LED
  brightness to 0% between local start/end times, including overnight intervals, then return to the sun schedule.
  The Home page displays one quiet-hours row and mutes only sun events within that interval; the original next-event
  highlight remains unchanged. Invalid hand-edited time values are logged and quiet hours are disabled at startup.
  From Travis Cole (traviscole)

### dman776 3.1.3 (2026-11-01)

- Faster LEDs on a long strip: the animations draw into the strip first and the renderer sends it once per frame.
  Each LED's animation used to send the whole strip itself, so a 252-LED map made 252 transfers a frame and the LEDs
  updated one after the other. Found and fixed by Travis Cole (traviscole), who tested it on a Raspberry Pi Zero W
  with 252 LEDs
- **Missing data blink** (Config > Visualizers, `visualizer.missing_data_blink`, on by default): off leaves an airport
  dark instead of blinking slow red when its report lacks what the visualizer shows, such as no flight category,
  visibility or sky condition. It applies in every visualizer, on the LEDs, the Map page and the legends (which say
  *Off*); lightning still flashes over a dark airport. Idea from Travis Cole (traviscole)
- **Lightning color** (Config > Visualizers, `lightning.color`): the lightning flashes can be yellow (the default) or
  white, on the LEDs, the Map page and the legends. Precipitation's thunderstorm with no precipitation stays yellow,
  since its snow is white. Idea from Travis Cole (traviscole)

### dman776 3.1.2 (2026-11-01)

- `python -m metarmap --port 8080` runs the web server on another port for that run, without editing `config.json`
  (which keeps its port): for trying the map on a computer, where port 80 needs `sudo`. `--version` prints the
  version, and `--help` lists both
- The LED colors live in the code now, not in `config.json`: its `color` section is gone, and an older file's is
  dropped when the map starts. Only Flight Category, Precipitation and the lightning flash used it (every other
  visualizer already had its colors in code), and the web UI couldn't change it. The colors are the same as before;
  a color changed by hand in `config.json` goes back to the default

### dman776 3.1.1 (2026-11-01)

- Advisories visualizer (G-AIRMETs and SIGMETs), after Dewpoint Spread: each airport in the color of the advisory it's
  inside, below 18,000 ft. G-AIRMETs in steady colors: IFR orange, mountain obscuration magenta, turbulence yellow,
  low-level wind shear red, strong surface wind blue, icing cyan; two at once alternate (the more important first),
  none is dim white. A SIGMET takes over, with a fast bright-and-dim blink in its hazard's color: thunderstorms
  (including the US convective SIGMETs) and tropical cyclones red, severe icing cyan, severe turbulence and mountain
  wave yellow, volcanic ash, dust and sand storms orange. The legend names each G-AIRMET's group: Sierra (IFR,
  mountain obscuration), Tango (turbulence, wind) or Zulu (icing). G-AIRMETs replaced text AIRMETs over the contiguous
  US in January 2025; the map fetches them and the SIGMETs from aviationweather.gov with the METARs (every 10
  minutes): the G-AIRMET snapshot nearest the current time, and the SIGMETs valid now. On the Map page, the areas are
  drawn in their hazard's color while Advisories is showing, SIGMETs with a heavier dashed outline; click one for its
  altitudes, cause, movement and times, and a SIGMET's text. New `GET /api/advisories`; `visualizer.areas` in
  `/api/live`
- TFR visualizer, after Advisories: each airport in the color of the TFR (temporary flight restriction) it's in or
  near, by type: VIP red, hazards (wildfires, disasters, launches) orange, security magenta, special blue, air shows
  and sports yellow, drone restrictions over public gatherings cyan. Solid inside a TFR, dim within the new **TFR
  nearby distance** (Config > Visualizers, `tfr.nearby_nm`, 10 NM by default, 0 for inside only), breathing for one
  that starts within 24 hours; none is dim white. Only TFRs with a floor below 18,000 ft count. The map fetches the
  FAA's TFR list from tfr.faa.gov with the METARs (every 10 minutes, in the background), and each new TFR's detail
  once, for its areas' outlines, altitudes and times. On the Map page, the TFRs are drawn in their type's color while
  TFR is showing (upcoming ones dashed); click one for its NOTAM, altitudes and times, with a link to its page on
  tfr.faa.gov. New `GET /api/tfrs`; `visualizer.areas` in `/api/live` is now which areas the Map page draws
  (`advisories` or `tfrs`), or `null`
- Rainbow and Chase move up by two (now 13 and 14). A `config.json` from before (`visualizer.numbering` 2 or 3) keeps
  showing the same visualizer; scripts that call `/visualizer/<n>` need the new numbers. Home Assistant picks
  visualizers by name, so it's unaffected

### dman776 3.1.0 (2026-10-31)

- Live traffic on the Map page, from [adsb.fi](https://adsb.fi/): tick **Live traffic** (under the background
  switcher; remembered in that browser) to show the aircraft around your airports, each pointing along its track and
  gliding between updates. Click one for its details (type, operator, registration, altitude and climb, speed,
  track, squawk, with a link to globe.adsb.fi): the map follows it and draws its trail until the popup closes or the
  map is dragged. Emergency squawks are red
- Each aircraft's icon shows its class, from the category it broadcasts and its type: light aircraft (a C172) are a
  small straight-wing plane, then bigger jets for small, large and heavy (twin engines) and the biggest (A380, 747:
  four engines), plus helicopters, gliders, balloons, drones and airport vehicles, each class in its own color
  (light blue, small lime, large white, heavy pink, super purple, helicopters yellow; red only for emergencies). The
  live traffic note has a key to the classes on the map, and the popup names the class. The followed aircraft keeps
  its color in an amber glow. `kind` and `category` in `/api/traffic`
- Config > Virtual map > Live traffic: **Update every** (2 to 60 s, 5 by default; adsb.fi allows one request a
  second) and **Ground traffic** (off by default). The map only asks adsb.fi while a page shows live traffic, and
  every open page shares one fetch. New `GET /api/traffic` (see API.md); `geo.map.traffic_seconds` and
  `geo.map.traffic_ground` settings
- Wind barbs on the Map page while Wind, Wind Gusts or Wind Direction runs: each airport's staff points where the
  wind blows from, with a pennant for 50 kt, a full feather for 10 and a half for 5 (sustained speed, rounded to
  5 kt; gusts stay in the popup). White with a dark edge, so they read on every background. Calm, variable (`VRB`)
  and no direction have none. An airport whose barb points east has its code on the left of the dot instead.
  `wind` (`{"dir", "kt"}`) in `/api/live`'s `leds`, `null` otherwise
- Precipitation legend: removed "Moderate (rain)", which repeated "Rain" (both solid blue). Moderate is solid, as
  each kind's own entry shows; the legend still lists Light (breathing), Heavy (fast blink) and In the vicinity (dim)

### dman776 3.0.3 (2026-10-30)

- Config > LED pixels: Data pin (GPIO 18, 12, 13, 21 or 10) and Color order (GRB or RGB), both after a restart.
  Before, they could only be changed in `config.json`
- The Config page has tabs: Physical display (LED pixels and the OLED screen), Visualizers, Airports, Virtual map
  (the Map page's settings) and System (software updates, the web login and Wi-Fi). The address keeps the tab
  (`/config#system`) and the last one is remembered; the System tab has a dot when an update is available
- After Restart, the web page waits 10 s (was 5) before it starts checking whether the map is back

### dman776 3.0.2 (2026-10-29)

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
