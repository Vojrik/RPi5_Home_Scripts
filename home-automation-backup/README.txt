Zálohování Home Assistant + Zigbee2MQTT + OctoPrint + OctoPrint
--------------------------------------------------

Skript: backup_home_automation.sh
Umístění: /home/vojrik/Scripts/home-automation-backup/
Plán: denně v 16:00 (cron /etc/cron.d/home_automation_backup)
Cíl záloh: /home/vojrik/Desktop/md0/_RPi5_Home_OS/Apps_Backups
Retence: posledních 30 záloh pro každý komponent (HA, Z2M, OctoPrint)
Log: /var/log/home_automation_backup.log

Co skript dělá
- Zigbee2MQTT: přes MQTT vyvolá vytvoření koordinátorového backupu (topic zigbee2mqtt/bridge/request/backup), poté zazálohuje celý adresář data (coordinator_backup.json, database.db, konfigurace) do .tar.gz.
- Home Assistant: zazálohuje celý konfigurační adresář do .tar.gz.
- OctoPrint: použije oficiální zálohovací příkaz „plugins backup:backup“ a uloží .zip balíček (obsahuje nastavení, pluginy, profily atd.).
- V každé podsložce záloh udržuje posledních 30 souborů a starší maže.

Struktura cílové složky
- .../Apps_Backups/
  - homeassistant/
  - zigbee2mqtt/
  - octoprint/

Ruční spuštění
  sudo /home/vojrik/Scripts/home-automation-backup/backup_home_automation.sh

Obnova (stručně)
1) Home Assistant + Zigbee2MQTT:
   - Zastavte stack: sudo systemctl stop home-automation
   - Rozbalte zálohy:
     * HA:  sudo tar -xzf /cesta/k/homeassistant_YYYYMMDD_HHMMSS.tar.gz -C /opt/home-automation/homeassistant
     * Z2M: sudo tar -xzf /cesta/k/zigbee2mqtt_YYYYMMDD_HHMMSS.tar.gz -C /opt/home-automation/zigbee2mqtt/data
       (Volitelně vyberte konkrétní coordinator_backup.json podle potřeby.)
   - Spusťte zpět: sudo systemctl start home-automation

2) OctoPrint:
   - Doporučeno zastavit službu: sudo systemctl stop octoprint
   - Obnova přes CLI:
     /home/vojrik/OctoPrint/venv/bin/octoprint plugins backup:restore /cesta/k/octoprint_YYYYMMDD_HHMMSS.zip
     (případně pomocí `octoprint` v PATH, pokud je dostupné)
   - Spusťte službu: sudo systemctl start octoprint

Konfigurace skriptu
- Cílová cesta: proměnná BACKUP_DIR v hlavičce skriptu
- OctoPrint binárka: proměnná OCTOPRINT_BIN (skript se pokusí najít i automaticky)
- Vyloučení v OctoPrint backupu: proměnná OCTO_EXCLUDES (např. "timelapse uploads")
- MQTT přihlášení pro Z2M: čte se z /opt/home-automation/credentials/mqtt_password.txt (uživatel 'ha')

Poznámky
- Skript očekává běžící kontejnery mosquitto a zigbee2mqtt kvůli triggeru koordinátorového backupu; samotné archivace běží i bez toho.
- Log průběhu najdete v /var/log/home_automation_backup.log při běhu z cronu.
