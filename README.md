## Updates
Forked from prueker/METARMap
Some portions by @lostlocalhost and @johnmarzulli

Items updated from orig:

* Completely re-wrote the core into a multi-threaded application

# METARMap
Raspberry Pi project to visualize flight conditions on a map using NeoPixel RGB pixels

## Built-in webserver for config and control
This allows you to browse to your map at http://raspberrypi.local (or appropriate hostname) to control and configure the
map.

### Web API
Everything in the web UI can also be done over HTTP, for scripts and home automation. `GET /api/status` returns the map's current state as JSON. See **[API.md](API.md)** for the full endpoint reference.

```sh
curl http://metarmap.local/api/status                            # current state (JSON)
curl http://metarmap.local/brightness/0.25                       # set LED brightness
curl http://metarmap.local/visualizer/next                       # next visualizer
curl -u metar:map http://metarmap.local/config/edit/lightning.animation/false
```

### Home Assistant
The [metarmap2_ha](https://github.com/dman776/metarmap2_ha) custom integration controls the map from Home Assistant through this API. It provides:
- a brightness light and a visualizer selector
- fetch and restart buttons
- config switches and numbers
- flight-category sensors
- a `metarmap.locate` action

## Mini OLED display
This functionality allows you to connect a small mini LED display to show the METAR information of the airports.
For this functionality to work, you will need to a compatible LED display.
I've written up some details on the display I used and the wiring
here: https://slingtsi.rueker.com/adding-a-mini-display-to-show-metar-information-to-the-metar-map/

## Multiple Visualizers
* Flight Category
* Wind
* Wind Gusts
* Temperature
* Pressure
* Precipitation
* Visibility
* Density Altitude
* Rainbow
* Chase

Switch between them from the web UI or the [API](API.md#control). If you turn on `visualizer.auto_rotate` in [config.json](config.json), the map rotates through them automatically.

## Detailed instructions
I've created detailed instructions about the setup and parts used
here: https://slingtsi.rueker.com/making-a-led-powered-metar-map-for-your-wall/

## Time of day automatic dimming
Automatically dims (2 levels) based on the current location of the map (via configuration) and sunrise/sunset times.

## Software Setup
* Install [Raspbian Bullseye Lite](https://www.raspberrypi.org/downloads/raspbian/) on SD card
* [Enable Wi-Fi and SSH](https://medium.com/@danidudas/install-raspbian-jessie-lite-and-setup-wi-fi-without-access-to-command-line-or-using-the-network-97f065af722e)
* Install SD card and power up Raspberry Pi
* SSH (using [Putty](https://www.putty.org) or some other SSH tool) into the Raspberry and configure
    * Set a new password for the 'pi' user: `passwd`
    * `sudo raspi-config`
        * Configure hostname (1, S4) (ie. metarmap)
        * Configure locale (5, L1) (ie. en_US.UTF-8)
      * Configure timezone (5, L2) (ie. America/Chicago)
      * `sudo reboot`
* SSH again and Update/install packages 
	* `sudo apt-get update`
	* `sudo apt-get upgrade`
    * `sudo apt-get -y install git`
	* `sudo apt-get -y install python3-pip`
    * `sudo apt-get -y install i2c-tools`
* Install required python libraries for the project
  	* `sudo pip3 install rpi_ws281x`
  	* `sudo pip3 install adafruit-circuitpython-neopixel`
  	* `sudo pip3 install adafruit-circuitpython-led-animation`
  	* `sudo pip3 install bottle astral xmltodict pytz oled-text schedule         Pillow????`
* Configure I2C
  * `sudo raspi-config`
      * Interface Options / I2C (3, I5)
      * Reboot the Raspberry Pi `sudo reboot`
      * Verify your wiring is working and I2C is enabled
          * `sudo i2cdetect -y 1` - this should show something connected at **3C**
* Clone the METARMap2 github repository (ssh)
  * `git clone https://github.com/dman776/metarmap2`
  * `cd metarmap2`
* Attach NeoPixel LEDs to Raspberry Pi. You can find [more details about wiring here](https://learn.adafruit.com/neopixels-on-raspberry-pi/raspberry-pi-wiring).
* Test the Neopixels (it needs to run with root permissions to access the GPIO pins):
  * `sudo python3 tools/test1.py`
  * Press 'CTRL-C' to stop the test
* Make appropriate changes to the **[airports](airports.json)** file for the airports you want to use (and 'display' on
  the OLED screen)
* Change the user and password in the web_server section of the **[config](config.json)** file from the defaults.

## Install the service
* To run the map automatically when you power the Raspberry Pi, install the systemd service
	* `sudo cp metarmap.service /lib/systemd/system`
	* `sudo systemctl daemon-reload`
	* `sudo systemctl enable metarmap.service`
* The service runs `python3 -m metarmap` from the `metarmap2` folder, which holds `config.json` and `airports.json`.
  An older service file that runs `controller.py` is switched to the new one when the map starts, unless you
  changed it (the old one is kept as `metarmap.service.controller-py.bak`).
* To start the service manually
  * `sudo systemctl start metarmap.service`
  * or use `./start.sh`
* To stop the service manually
    * `sudo systemctl stop metarmap.service`
    * or use `./stop.sh`

## Development
You can work on the map without a Raspberry Pi. When there's no LED strip or OLED screen, the map uses in-memory
stand-ins, and the web UI (including the live Map page and its OLED window) works as usual with real METARs.

* Set up: `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"`
* Run the tests: `.venv/bin/pytest`
* Check the code: `.venv/bin/ruff check .`
* Run the map: `.venv/bin/python -m metarmap` (or `.venv/bin/metarmap`), from the folder with `config.json`
  * The web server uses `web_server.port` from **[config](config.json)** (80 by default, which needs `sudo`).
    For a laptop, set it to something like 8080 and open http://localhost:8080.

### Code layout
The code is the `metarmap` package in `src/metarmap/`:
* `app.py` builds the map from `config.json` (settings, METARs, LED renderer, OLED loop, scheduled jobs) and runs it
* `config.py` and `settings.py`: `config.json` and `airports.json`
* `metar.py`: fetching METARs; `renderer.py` and `leds/`: the LEDs; `display.py` and `oled/`: the OLED screen
* `visualizers/`: how each visualizer colors the LEDs
* `web/`: the web UI and API. `create_app()` builds it; the routes are in `pages.py`, `api.py` and `control.py`,
  and `views.py` prepares what each page shows (templates in `web/templates/`, files in `web/static/`)

## Changelist
To see a list of changes to the metar script over time, refer to [CHANGELIST.md](CHANGELIST.md)
