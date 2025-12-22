# ROCK Pi Penta OLED helpers

This folder contains a customized fork of the Radxa ROCK Pi Penta OLED utilities, adapted for Raspberry Pi 5 with the Radxa ROCK Penta SATA HAT.

## OLED quick commands
- Status: `/home/vojrik/Scripts/rockpi-penta/oled-control.py status`
- Full white test: `sudo /home/vojrik/Scripts/rockpi-penta/oled-control.py full-white on`
- Return to normal: `sudo /home/vojrik/Scripts/rockpi-penta/oled-control.py full-white off`

## Origin
- Upstream project: https://github.com/radxa/rockpi-penta (MIT licence)
- Local licence copy: `ROCKPi_Penta_LICENSE`

## Local adjustments
- removed Radxa's original fan-control routines; fan handling is delegated to the separate `Fan/` PWM daemon
- fixed crashes and I²C recovery issues we saw on the OLED refresh path
- pruned and reworked the displayed statistics to match our Home Server deployment
- added a white-test OLED mode via `/etc/rockpi-penta.conf` (`[oled] white-test = true`)

## Thanks
Many thanks to the Radxa team for the original implementation – it provided an excellent starting point and let us finish our Raspberry Pi 5 + Radxa ROCK Penta SATA HAT setup much faster.
