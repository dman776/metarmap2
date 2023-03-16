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
* Visibility
* Density Altitude

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
  * `sudo python3 test1.py`
  * Press 'CTRL-C' to stop the test
* Make appropriate changes to the **[airports](airports.json)** file for the airports you want to use (and 'display' on
  the OLED screen)
* Change the user and password in the web_server section of the **[config](config.json)** file from the defaults.

## Install the service
* To run the script automatically when you power the Raspberry Pi, install the systemd service
	* `sudo cp metarmap.service /lib/systemd/system`
	* `sudo systemctl enable metarmap.service`
* To start the service manually
  * `sudo systemctl start metarmap.service`
* To stop the service manually
  * `sudo systemctl stop metarmap.service`

## Changelist
To see a list of changes to the metar script over time, refer to [CHANGELIST.md](CHANGELIST.md)
