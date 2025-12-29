Quick start:
    sudo /home/vojrik/Scripts/power_saving/power-saving.sh

Power Saving Script
===================

This script updates Raspberry Pi boot configuration and offers an interactive
menu to toggle:
- HDMI on/off (hdmi_blanking)
- Bluetooth on/off (dtoverlay=disable-bt)
- Wi-Fi on/off (dtoverlay=disable-wifi)
- Activity LED on/off (dtparam=act_led_*)
- Power LED on/off (dtparam=pwr_led_*)

How it works
------------
- Detects the boot config at /boot/firmware/config.txt or /boot/config.txt.
- Updates or appends the relevant parameters.
- Prompts to reboot so changes take effect.

Usage
-----
Run as root:
    sudo /home/vojrik/Scripts/power_saving/power-saving.sh

Notes
-----
- The menu shows the current state based on the last matching value in the
  config file.
- A reboot is required after changes to apply the settings.
