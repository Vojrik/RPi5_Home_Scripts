# Automated Installer for Raspberry Pi Scripts

This directory ships with `install_all.sh`, a one-shot installer that prepares every helper script from [RPi5_Home_Scripts](https://github.com/Vojrik/RPi5_Home_Scripts) on a fresh Raspberry Pi.

## Quick start

```bash
wget https://raw.githubusercontent.com/Vojrik/RPi5_Home_Scripts/main/install_all.sh -O install_all.sh
chmod +x install_all.sh
sudo ./install_all.sh
```

The script prompts for the target user, backup locations, and SMTP credentials. Run it with `sudo` on a machine that has internet access.

## What the installer does

- installs required packages (smartmontools, mdadm, msmtp, Python + I²C tooling, Docker, rsync, etc.)
- copies every subdirectory into the selected user's `~/Scripts` and rewrites hard coded `/home/vojrik` paths to the new `$HOME`
- sets execute bits and reassigns ownership to the chosen account
- creates `/usr/local/bin/rpi_backup_pishrink` and downloads `pishrink.sh` when missing
- provisions systemd services `cpu-scheduler`, `fanctrl`, and `rockpi-penta` (including a local Python venv and `/etc/rockpi-penta.{conf,env}`)
- writes cron jobs for disk health checks and Home Assistant / Zigbee backups
- regenerates the msmtp configuration for alert e-mails using the provided credentials
- ensures the boot config contains `dtoverlay=pwm,pwmchip=0,pwmchannel=3,pin=19` so the fan PWM works

## Tips

- Run the installer on a clean system or after backing up, because it modifies system services and cron.
- You can rerun the script with different answers; it will simply overwrite previously generated files.
- After installation verify the core services:
  ```bash
  systemctl status cpu-scheduler fanctrl rockpi-penta
  ```
