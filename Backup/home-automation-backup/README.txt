Home Assistant + Zigbee2MQTT + OctoPrint Backup
----------------------------------------------

Script: backup_home_automation.sh
Location: /home/vojrik/Scripts/Backup/home-automation-backup/
Schedule: daily at 19:01 (cron entry in /etc/cron.d/home_automation_backup)
Backup target: /home/vojrik/Desktop/md0/_RPi5_Home_OS/Apps_Backups
Retention: 30 most recent snapshots for each component (HA, Z2M, OctoPrint)
Log file: /var/log/home_automation_backup.log

What the script does
- Zigbee2MQTT: triggers a coordinator backup through MQTT (topic zigbee2mqtt/bridge/request/backup), creates a consistent data snapshot via `rsync` into a temporary directory, and archives it as .tar.gz.
- Home Assistant: first tries to create a native HA Backup via the API and copies the new file to the target directory; then, after trimming older native backups, it uses `rsync` to create an immutable copy of the full configuration and archives it as .tar.gz.
- OctoPrint: runs the official `plugins backup:backup` command and stores the resulting .zip (settings, plugins, profiles, etc.).
  The backup runs with an explicit `--basedir` so OctoPrint always uses the production profile even if cron runs as root.
- After each component finishes, the script deletes the snapshot from the temporary directory and keeps only the newest 30 files per subfolder in the destination.

Target directory layout
- .../Apps_Backups/
  - homeassistant/
  - zigbee2mqtt/
  - octoprint/

Manual execution
    sudo /home/vojrik/Scripts/Backup/home-automation-backup/backup_home_automation.sh

Restore procedure (summary)
1) Home Assistant + Zigbee2MQTT:
   - Stop the stack: sudo systemctl stop home-automation
   - Extract the backups:
     * HA:  sudo tar -xzf /path/to/homeassistant_YYYYMMDD_HHMMSS.tar.gz -C /opt/home-automation/homeassistant
     * Z2M: sudo tar -xzf /path/to/zigbee2mqtt_YYYYMMDD_HHMMSS.tar.gz -C /opt/home-automation/zigbee2mqtt/data
       (Optionally pick the desired coordinator_backup.json if several are present.)
   - Start again: sudo systemctl start home-automation

2) OctoPrint:
   - Stop the service (recommended): sudo systemctl stop octoprint
   - Restore via CLI:
     /home/vojrik/OctoPrint/venv/bin/octoprint plugins backup:restore /path/to/octoprint_YYYYMMDD_HHMMSS.zip
     (or simply `octoprint` if it is on PATH)
   - Start the service: sudo systemctl start octoprint

Script configuration hints
- Backup destination: variable BACKUP_DIR near the top of the script
- OctoPrint binary: variable OCTOPRINT_BIN (auto-detection is attempted as well)
- OctoPrint basedir: variable OCTOPRINT_BASEDIR (default `/home/<user>/.octoprint`); change only if your configuration lives elsewhere
- OctoPrint exclusions: variable OCTO_EXCLUDES (e.g. "timelapse uploads")
- MQTT credentials for Z2M: read from /opt/home-automation/credentials/mqtt_password.txt (user 'ha')

Notes
- The script expects the mosquitto and zigbee2mqtt containers to be running to trigger the coordinator backup; the archival steps themselves will still run without them.
- Cron runs log progress to /var/log/home_automation_backup.log.
- Temporary snapshots are stored in `/tmp` (via `mktemp`) and removed after the script finishes, so archiving never runs against live files.
