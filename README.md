# METARMap2

A Raspberry Pi turns a wall map into a live weather display: an LED at each airport shows its current conditions from
[aviationweather.gov](https://aviationweather.gov) (VFR green, MVFR blue, IFR red, LIFR purple, and more). An
optional small OLED screen cycles through the details for the airports you pick, and a web UI lets you control and
set up the map from your phone.

Started from [prueker/METARMap](https://github.com/prueker/METARMap), and since rewritten from the ground up with a
web UI, an API and a Home Assistant integration (see [Credits](#credits)).

## Features

- **Visualizers**: show the flight category, wind, wind gusts, temperature, pressure, precipitation, visibility,
  density altitude, ceiling or dewpoint spread (fog risk) on the LEDs, plus Rainbow and Chase patterns. Switch
  between them on the web UI, or let the map rotate through them.
- **Lightning**: airports reporting lightning flash yellow.
- **Dimming by time of day**: the LEDs dim at sunset, go nearly dark at dusk, dim again at dawn and are back to full
  brightness at sunrise, using the sun times for your city.
- **OLED screen** (optional): wind, visibility, pressure, temperature, dewpoint and report time for each airport you
  choose, with that airport's LED pulsing while it's shown.
- **Web UI**: current conditions, a METAR list, a live map that mirrors the LEDs and the OLED screen, and settings.
  Click an airport on the map for its weather in plain English, its raw METAR, or the METAR decoded line by line.
  The map can go fullscreen, and follows the visualizer as it changes. Update and restart the map from the Home
  page.
- **API and Home Assistant**: everything in the web UI also works over HTTP (see [API.md](API.md)); the
  [metarmap2_ha](https://github.com/dman776/metarmap2_ha) integration adds the map to Home Assistant.

## What you need

- A Raspberry Pi with Wi-Fi (a Zero W, 3, 4 or 5) and a microSD card
- A strip or string of WS2811/WS2812 ("NeoPixel") LEDs, one per airport, and a 5V power supply big enough for them
- A map, and a frame or board to mount it and the LEDs
- Optional: a 128x64 SSD1306 I2C OLED screen

Wiring:

- **LEDs**: data to GPIO 18 (pin 12), ground to a Pi ground, power from the 5V supply. See Adafruit's
  [NeoPixels on Raspberry Pi](https://learn.adafruit.com/neopixels-on-raspberry-pi/raspberry-pi-wiring) guide.
- **OLED screen**: SDA to GPIO 2 (pin 3), SCL to GPIO 3 (pin 5), VCC to 3.3V, GND to ground.

The original project's write-ups cover the build in detail:
[making the map](https://slingtsi.rueker.com/making-a-led-powered-metar-map-for-your-wall/) and
[adding the display](https://slingtsi.rueker.com/adding-a-mini-display-to-show-metar-information-to-the-metar-map/).

## Install

1. With [Raspberry Pi Imager](https://www.raspberrypi.com/software/), write **Raspberry Pi OS Lite** to the microSD
   card. In Imager's settings, set:
   - a hostname, such as `metarmap`
   - a user name and password
   - your Wi-Fi network
   - your time zone (the map dims at your local sunset and sunrise)
   - SSH turned on
2. Put the card in the Pi, power it up, and wait a minute or two for it to join your Wi-Fi.
3. Connect to it from your computer with `ssh pi@metarmap.local`, using your hostname and user name.
4. Install git, download the map and run the installer:

   ```sh
   sudo apt update && sudo apt install -y git
   git clone https://github.com/dman776/metarmap2
   cd metarmap2
   ./install.sh
   ```

   The installer sets up everything the map needs and asks for:
   - a user name and password for the web UI's settings pages
   - your city, for the sunrise and sunset times (a larger city nearby works too)

   It then starts the map and prints its web address. Installing takes a few minutes, longer on a Pi Zero. Running
   `./install.sh` again is safe; it keeps your settings.
5. Open the web address, go to **Config > Airports**, and set up your airports (next section).

## Setting up your airports

On **Config > Airports**:

1. Set **Number of LEDs** to the number of LEDs on your strip, then restart the map when it asks. (Without a
   strip, the web map changes right away.)
2. Enter the ICAO code (such as `KDFW`) of the airport at each LED, in the order the LEDs are wired, starting
   from the one nearest the Pi. Leave a code empty for an LED that isn't at an airport.
3. Turn on **OLED** for the airports you want on the screen. Each airport's name fills itself in; change it if
   you like (an emptied name fills in again).
4. Use the up and down arrows to move an airport to another LED; the others shift along.

Changes save right away. To check the wiring order:
- Choose the **Chase** visualizer on the Home page, which lights each LED in turn.
- Or use the locate button next to an airport on the **METARs** page, which pulses that airport's LED.

## Settings

**Config** has the rest of the settings:
- the default visualizer and auto-rotate, including which visualizers it shows
- lightning
- the OLED screen
- the map page's chart
- the LED brightness for day, dawn and dusk, and night
- whether the LEDs fade down for a moment while new METARs download (**Dim while updating**, on by default)

Every setting takes effect right away; none needs a restart.

**Config > Access** changes:
- the web UI login. On a Raspberry Pi, the new password also becomes the password of the Pi's login user
  (e.g. `pi`), so you don't have two to remember. On any other machine only the web UI login changes.
- the Wi-Fi network. The Pi switches a few seconds after you save, and keeps the old network: if it can't join
  the new one, it goes back. To reach the map afterwards, put your phone or computer on the new network too.

Everything is saved in `config.json` in the `metarmap2` folder. To edit that file by hand, stop the map first
(`./stop.sh`), then start it again (`./start.sh`).

## Updating

The map checks GitHub for a new release when it starts and every 6 hours. When there is one, every page shows
**Update available** at the top, and the Home page's button reads **Update to v2.9.0** (for example). Click it, then
use **Restart**. Your `config.json` is kept.

**Config > Software** has more:
- **Check now** asks GitHub straight away.
- **Update to**: **Releases** (the default) installs only released versions, and never goes back to an older one.
  **Latest commit** installs the newest code on GitHub, released or not. Use it on a map you test changes on.
- **Install a release** installs any release, older ones too, to go back if a new one has a problem. It asks first
  before going back.

Or, over SSH, the newest release:

```sh
cd metarmap2
git fetch --tags
git checkout v2.9.0      # the release you want
./install.sh
```

Running `./install.sh` after an update also installs any new packages the map needs. On a map that has installed a
release, `git pull` says it isn't on a branch: `git checkout master` first (or pick **Latest commit** above).

## Web API and Home Assistant

`GET /api/status` returns the map's state as JSON. The web UI's controls are plain HTTP requests too, so scripts and
home automation can use them. See **[API.md](API.md)** for every endpoint.

```sh
curl http://metarmap.local/api/status                            # current state (JSON)
curl http://metarmap.local/brightness/0.25                       # set LED brightness
curl http://metarmap.local/visualizer/next                       # next visualizer
curl -u metar:map http://metarmap.local/config/edit/lightning.animation/false
```

The [metarmap2_ha](https://github.com/dman776/metarmap2_ha) custom integration controls the map from Home Assistant
through this API. It provides:
- a brightness light and a visualizer selector
- fetch and restart buttons
- config switches and numbers
- flight-category sensors
- a `metarmap.locate` action

## Troubleshooting

- **Is it running?** `systemctl status metarmap`. Start and stop it with `./start.sh` and `./stop.sh`.
- **What happened?** The map's log is `metarmap.log` in the `metarmap2` folder; crashes also go to
  `journalctl -u metarmap`.
- **LEDs stay dark or show the wrong colors**:
  1. Check the data wire goes to GPIO 18 and that the strip shares a ground with the Pi.
  2. Run a test pattern: choose the **Chase** visualizer on the Home page (it lights each LED in turn), or turn on
     **Test pattern on startup** in Config (it runs a rainbow comet along the strip once, right away).
  3. If the colors are swapped, change `led.order` in `config.json` (such as `RGB` or `GRB`).
- **OLED screen stays blank**: `sudo i2cdetect -y 1` should show the screen at address `3c`. If it shows nothing,
  check the wiring, and that I2C is on (`sudo raspi-config`, Interface Options).
- **An airport's LED is off**: it hasn't reported in the last 5 hours, or its code is wrong. The METARs page shows
  which airports have no data.

## Development

You can work on the map without a Raspberry Pi. With no LED strip or OLED screen, the map uses in-memory stand-ins,
and the web UI (including the live Map page and its OLED window) works as usual with real METARs.

- Set up: `uv sync --extra dev` (or `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"`)
- Run the tests: `.venv/bin/pytest`
- Check the code: `.venv/bin/ruff check .`
- Run the map: `.venv/bin/python -m metarmap` (or `.venv/bin/metarmap`), from the folder with `config.json`.
  The web server uses `web_server.port` from `config.json`. Port 80 needs `sudo`, so on a laptop use something like
  8080 and open http://localhost:8080.

To release a version, so maps see it as an update: bump the version (`bump2version patch` or `minor`), commit, tag
the commit with the version, and push both:

```sh
git tag -a v2.9.0 -m "Release 2.9.0"
git push origin master v2.9.0
```

Maps only install tags that look like `v2.9.0` (or `2.9.0`); a pre-release such as `v2.9.0-rc1` is skipped.

The code is the `metarmap` package in `src/metarmap/`:
- `app.py` builds the map from `config.json` (settings, METARs, LED renderer, OLED loop, scheduled jobs) and runs it
- `config.py` and `settings.py`: `config.json`, including the airport on each LED
- `metar.py`: reading METARs (`process()`, `parse_report()`) and fetching them (`METAR`); `decode.py`: a METAR in
  plain English; `renderer.py` and `leds/`: the LEDs; `display.py` and `oled/`: the OLED screen
- `visualizers/`: how each visualizer colors the LEDs. Each is a module of functions (`NAME`, `legend()`, and
  `look()` or `strip_look()`); `visualizers.ALL` lists them in order
- `web/`: the web UI and API. `create_app()` builds it; the routes are in `pages.py`, `api.py` and `control.py`,
  and `views.py` prepares what each page shows (templates in `web/templates/`, files in `web/static/`)
- `releases.py`: what's newest on GitHub (the "Update available" check); `lib/utils.py`'s `run_update()` installs it
- `service.py`: switches an older installed `metarmap.service` (one that runs `controller.py`) to the current one

`install.sh` sets up a Pi; `metarmap.service` is the systemd service it installs.

## Changes

See [CHANGELIST.md](CHANGELIST.md).

## Credits

METARMap2 started from [prueker/METARMap](https://github.com/prueker/METARMap), Philip Rueker's Raspberry Pi METAR
map, with portions by [@lostlocalhost](https://github.com/lostlocalhost) and John Marzulli. It has since been
rewritten from scratch, with a web UI, an API, a Home Assistant integration and more, and shares little, if any, of
their code. Their work is where the idea and the first version came from, and John Marzulli's visualizer ideas were
a particular inspiration. Thank you.
