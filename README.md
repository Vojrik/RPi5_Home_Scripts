# Automated Installer for Raspberry Pi Scripts

This directory ships with `install_all.sh`, a one-shot installer that prepares every helper script from [RPi5_Home_Scripts](https://github.com/Vojrik/RPi5_Home_Scripts) on a fresh Raspberry Pi.

## Quick start

```bash
wget https://raw.githubusercontent.com/Vojrik/RPi5_Home_Scripts/main/install_all.sh -O install_all.sh
chmod +x install_all.sh
sudo ./install_all.sh
```

The script prompts for the target user, backup locations, and SMTP credentials. Run it with `sudo` on a machine that has internet access.

## What gets installed

- `Backup/`: image-backup script exposed as `rpi_backup_pishrink` for shrinking SD/SSD clones.
- `CPU_freq/`: `cpu-scheduler` service that enforces day/night CPU frequencies and coordinates with the fan profile.
- `Fan/`: `fanctrl` PWM daemon writing duty cycle to pin 19 and reacting to `/run/fan_mode`.
- `Disck_checks/`: SMART + mdraid health monitors with msmtp e-mail alerts and cron schedules.
- `home-automation-backup/`: daily backups of Home Assistant, Zigbee2MQTT, and OctoPrint into your chosen destination.
- `rockpi-penta/`: OLED display app with its own Python virtual environment and systemd unit.

The installer also adjusts paths for the selected user, wires the services into systemd, and regenerates msmtp credentials so alerts are sent using the details you provide.

## Tips

- Run the installer on a clean system or after backing up, because it modifies system services and cron.
- You can rerun the script with different answers; it will simply overwrite previously generated files.
- After installation verify the core services:
  ```bash
  systemctl status cpu-scheduler fanctrl rockpi-penta
  ```
