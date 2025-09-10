#!/usr/bin/env bash
set -euo pipefail

# ---- Config ----
BACKUP_DIR="/home/vojrik/Desktop/md0/_RPi5_Home_OS/Apps_Backups"
HA_SRC="/opt/home-automation/homeassistant"
Z2M_SRC="/opt/home-automation/zigbee2mqtt/data"
MQTT_USER="ha"
MQTT_PASS_FILE="/opt/home-automation/credentials/mqtt_password.txt"
# OctoPrint
OCTOPRINT_BIN="/home/vojrik/OctoPrint/venv/bin/octoprint"
OCTO_EXCLUDES=""   # nechává prázdné pro kompletní zálohu

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
DOCKER=/usr/bin/docker
TAR=/bin/tar
NICE=/usr/bin/nice
IONICE=/usr/bin/ionice

# Ensure target directories exist
mkdir -p "$BACKUP_DIR/homeassistant" "$BACKUP_DIR/zigbee2mqtt" "$BACKUP_DIR/octoprint"

# --- Zigbee2MQTT: trigger coordinator backup & archive data ---
if [ -r "$MQTT_PASS_FILE" ]; then
  MQTT_PASS=$(cat "$MQTT_PASS_FILE")
  if $DOCKER exec mosquitto which mosquitto_pub >/dev/null 2>&1; then
    $DOCKER exec mosquitto mosquitto_pub -h localhost -p 1883 -u "$MQTT_USER" -P "$MQTT_PASS" -t zigbee2mqtt/bridge/request/backup -m '{}'
    sleep 2
  fi
fi
Z2M_ARCHIVE="$BACKUP_DIR/zigbee2mqtt/zigbee2mqtt_${TIMESTAMP}.tar.gz"
$NICE -n 10 $IONICE -c 3 $TAR -C "$Z2M_SRC" -czf "$Z2M_ARCHIVE" .

# --- Home Assistant: archive config dir ---
HA_ARCHIVE="$BACKUP_DIR/homeassistant/homeassistant_${TIMESTAMP}.tar.gz"
$NICE -n 10 $IONICE -c 3 $TAR -C "$HA_SRC" -czf "$HA_ARCHIVE" .

# --- OctoPrint: create backup via official backup command ---
# Try to detect binary if configured path missing
if [ ! -x "$OCTOPRINT_BIN" ]; then
  if command -v octoprint >/dev/null 2>&1; then
    OCTOPRINT_BIN=$(command -v octoprint)
  elif [ -x "/home/vojrik/oprint/bin/octoprint" ]; then
    OCTOPRINT_BIN="/home/vojrik/oprint/bin/octoprint"
  fi
fi

if [ -x "$OCTOPRINT_BIN" ]; then
  OCTO_ARCHIVE="$BACKUP_DIR/octoprint/octoprint_${TIMESTAMP}.zip"
  OCTO_ARGS=(plugins backup:backup --path "$OCTO_ARCHIVE")
  # Add excludes as repeated flags if set
  for ex in $OCTO_EXCLUDES; do
    OCTO_ARGS=("${OCTO_ARGS[@]}" --exclude "$ex")
  done
  # Run backup; if it fails, continue with other backups already created
  if ! "$OCTOPRINT_BIN" "${OCTO_ARGS[@]}"; then
    echo "[WARN] OctoPrint backup command failed" >&2
  fi
else
  echo "[INFO] OctoPrint CLI not found, skipping OctoPrint backup" >&2
fi

# --- Retention: keep last 30 of each ---
for d in "$BACKUP_DIR/homeassistant" "$BACKUP_DIR/zigbee2mqtt" "$BACKUP_DIR/octoprint"; do
  ls -1t "$d"/*.* 2>/dev/null | awk 'NR>30' | xargs -r rm -f --
done

exit 0
