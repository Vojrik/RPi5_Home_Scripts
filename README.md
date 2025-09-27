# Automated Installer for Raspberry Pi Scripts

This directory ships with `install_rpi5_home.sh`, an interactive installer that prepares every helper script from [RPi5_Home_Scripts](https://github.com/Vojrik/RPi5_Home_Scripts) on a fresh Raspberry Pi. The previous monolithic script is still available as `install_all_OLD.sh` for reference.

## Quick start

```bash
git clone https://github.com/Vojrik/RPi5_Home_Scripts.git
cd RPi5_Home_Scripts
chmod +x install_rpi5_home.sh
sudo ./install_rpi5_home.sh
```

The script describes the available modules, asks which ones to run, and then prompts for the target user, installation paths, and service credentials. Each interactive question pauses inside a magenta banner so it is obvious when input is required. Run it with `sudo` on a machine that has internet access. If `git` is not installed yet, add `sudo apt update && sudo apt install -y git` before the first command.

## What gets installed

- `Backup/`: image-backup script exposed as `rpi_backup_pishrink` for shrinking SD/SSD clones (thanks to Drew Bonasera for [PiShrink](https://github.com/Drewsif/PiShrink); see `Backup/PiShrink_LICENSE`).
- `CPU_freq/`: `cpu-scheduler` service that enforces day/night CPU frequencies and coordinates with the fan profile.
- `Fan/`: `fanctrl` PWM daemon writing duty cycle to pin 19 and reacting to `/run/fan_mode`.
- `Disck_checks/`: SMART + mdraid health monitors with msmtp e-mail alerts and cron schedules.
- `home-automation-backup/`: daily backups of Home Assistant, Zigbee2MQTT, and OctoPrint into your chosen destination.
- `rockpi-penta/`: OLED display app (customised from Radxa's [rockpi-penta](https://github.com/radxa/rockpi-penta); see `rockpi-penta/ROCKPi_Penta_LICENSE` and `rockpi-penta/README.md` for licence details and local changes).

The installer also adjusts paths for the selected user, wires the services into systemd, and regenerates msmtp credentials so alerts are sent using the details you provide.

## Tips

- Run the installer on a clean system or after backing up, because it modifies system services and cron.
- You can rerun the script with different answers; it will simply overwrite previously generated files.
- After installation verify the core services:
  ```bash
  systemctl status cpu-scheduler fanctrl rockpi-penta
  ```

### Raspberry Pi 4 overclock profile

When the installer detects a Raspberry Pi 4 it asks whether to apply the bundled overclock. The prompt defaults to **No**; only the explicit `y`/`yes` answer or setting the environment variable `RPi_HOME_PI4_OC=1` (or `true`) applies the tweak.

The profile represents the highest configuration that has been tested without enabling the firmware turbo bit:

```
over_voltage=5
arm_freq=2000
gpu_freq=650
```

These settings are appended to `/boot/firmware/config.txt` inside a block marked `RPi Home Installer Overclock (RPi 4)`. If you need to revert them later, remove that block manually or rerun the installer and answer **No** at the prompt.
