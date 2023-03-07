## Updates
Forked from prueker/METARMap  
  
Items updated from orig:  
* Completely re-wrote the core into a multi-threaded application

# METARMap
Raspberry Pi project to visualize flight conditions on a map using WS8211 LEDs addressed via NeoPixel

## Detailed instructions
I've created detailed instructions about the setup and parts used here: https://slingtsi.rueker.com/making-a-led-powered-metar-map-for-your-wall/

## Software Setup
* Install [Raspbian Buster Lite](https://www.raspberrypi.org/downloads/raspbian/) on SD card
* [Enable Wi-Fi and SSH](https://medium.com/@danidudas/install-raspbian-jessie-lite-and-setup-wi-fi-without-access-to-command-line-or-using-the-network-97f065af722e)
* Install SD card and power up Raspberry Pi
* SSH (using [Putty](https://www.putty.org) or some other SSH tool) into the Raspberry and configure password and timezones
	* `passwd`
	* `sudo raspi-config`
* Update packages 
	* `sudo apt-get update`
	* `sudo apt-get upgrade`
* Copy the **[metar.py](metar_orig.py)**, **[pixelsoff.py](pixelsoff.py)**, **[airports](airports.json)**, **[refresh.sh](refresh.sh)** and **[lightsoff.sh](lightsoff.sh)** scripts into the pi home directory (/home/pi)
* Install python3 and pip3 if not already installed
	* `sudo apt-get install python3`
	* `sudo apt-get install python3-pip`
* Install required python libraries for the project
	* [Neopixel](https://learn.adafruit.com/neopixels-on-raspberry-pi/python-usage): `sudo pip3 install rpi_ws281x adafruit-circuitpython-neopixel`
* Attach WS8211 LEDs to Raspberry Pi, if you are using just a few, you can connect the directly, otherwise you may need to also attach external power to the LEDs. For my purpose with 22 powered LEDs it was fine to just connect it directly. You can find [more details about wiring here](https://learn.adafruit.com/neopixels-on-raspberry-pi/raspberry-pi-wiring).
* Test the script by running it directly (it needs to run with root permissions to access the GPIO pins):
	* `sudo python3 metar.py`
* Make appropriate changes to the **[airports](airports.json)** file for the airports you want to use and change the **[metar.py](metar_orig.py)** and **[pixelsoff.py](pixelsoff.py)** script to the correct **`LED_COUNT`** (including NULLs if you have LEDS in between airports that will stay off) and **`LED_BRIGHTNESS`** if you want to change it
* To run the script automatically when you power the Raspberry Pi, you will need to grant permissions to execute the **[refresh.sh](refresh.sh)** and **[lightsoff.sh](lightsoff.sh)** script and read permissions to the **[airports](airports.json)**, **[metar.py](metar_orig.py)** and **[pixelsoff.py](pixelsoff.py)** script using chmod:
	* `chmod +x filename` will grant execute permissions
	* `chmod +r filename` will grant write permissions
* To have the script start up automatically and refresh in regular intervals, use crontab and set the appropriate interval. For an example you can refer to the [crontab](crontab) file in the GitHub repo (make sure you grant the file execute permissions beforehand to the refresh.sh and lightsoff.sh file). To edit your crontab type: **`crontab -e`**, after you are done with the edits, exit out by pressing **ctrl+x** and confirm the write operation
	* The sample crontab will run the script every 5 minutes (the */5) between the hours of 7 to 21, which includes the 21 hour, so it means it will run until 21:55
	* Then at 22:05 it will run the lightsoff.sh script, which will turn all the lights off


## Mini display to show METAR information functionality
This functionality allows you to connect a small mini LED display to show the METAR information of the airports.
For this functionality to work, you will need to buy a compatible LED display and enable and install a few additional things.
I've written up some details on the display I used and the wiring here: https://slingtsi.rueker.com/adding-a-mini-display-to-show-metar-information-to-the-metar-map/

To support the display you need to enable a few new libraries and settings on the raspberry pi.
* [Enable I2C](https://learn.adafruit.com/adafruits-raspberry-pi-lesson-4-gpio-setup/configuring-i2c)
	* `sudo raspi-config`
	* Interface Options
	* I2C
	* reboot the Reboot the Raspberry Pi `sudo reboot`
	* Verify your wiring is working and I2C is enabled
		* `sudo apt-get install i2c-tools`
		* `sudo i2cdetect -y 1` - this should show something connected at **3C**
* install python library for the display
	* `sudo pip3 install adafruit-circuitpython-ssd1306`
	* `sudo pip3 install pillow`
* install additional libraries needed to fill the display
	* `sudo apt-get install ttf-dejavu`
	* `sudo apt-get install libjpeg-dev -y`
	* `sudo apt-get install zlib1g-dev -y`
	* `sudo apt-get install libfreetype6-dev -y`
	* `sudo apt-get install liblcms1-dev -y`
	* `sudo apt-get install libopenjp2-7 -y`
	* `sudo apt-get install libtiff5 -y`

## Changelist
To see a list of changes to the metar script over time, refer to [CHANGELIST.md](CHANGELIST.md)
