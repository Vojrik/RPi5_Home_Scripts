Home Assistant + Zigbee2MQTT + OctoPrint Backup
----------------------------------------------

Script: backup_home_automation.sh
Location: /home/vojrik/Scripts/home-automation-backup/
Schedule: daily at 19:01 (cron entry in /etc/cron.d/home_automation_backup)
Backup target: /home/vojrik/Desktop/md0/_RPi5_Home_OS/Apps_Backups
Retention: 30 most recent snapshots for each component (HA, Z2M, OctoPrint)
Log file: /var/log/home_automation_backup.log

What the script does
- Zigbee2MQTT: triggers a coordinator backup through MQTT (topic zigbee2mqtt/bridge/request/backup), vytvoří konzistentní snapshot dat přes `rsync` do dočasného adresáře a z něj vyrobí .tar.gz archiv.
- Home Assistant: nejprve zkusí přes API založit nativní HA Backup a nově vzniklý soubor zkopíruje do cílového adresáře; poté po ořezu starších nativních záloh vytvoří pomocí `rsync` neměnnou kopii celé konfigurace a z ní vytvoří .tar.gz.
- OctoPrint: spustí oficiální příkaz `plugins backup:backup` a uloží výsledné .zip (nastavení, pluginy, profily atd.).
- Po dokončení každého balíčku smaže snapshot z dočasného adresáře a v cíli drží pouze nejnovějších 30 souborů v každé podsložce.

Target directory layout
- .../Apps_Backups/
  - homeassistant/
  - zigbee2mqtt/
  - octoprint/

Manual execution
    sudo /home/vojrik/Scripts/home-automation-backup/backup_home_automation.sh

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
- OctoPrint exclusions: variable OCTO_EXCLUDES (e.g. "timelapse uploads")
- MQTT credentials for Z2M: read from /opt/home-automation/credentials/mqtt_password.txt (user 'ha')

Notes
- The script expects the mosquitto and zigbee2mqtt containers to be running to trigger the coordinator backup; the archival steps themselves will still run without them.
- Cron runs log progress to /var/log/home_automation_backup.log.
- Dočasné snapshoty se ukládají do `/tmp` (pomocí `mktemp`) a jsou odstraněny po doběhnutí skriptu, takže archivování neprobíhá nad živými soubory.
