#!/usr/bin/env bash
set -euo pipefail

# ---- Config ----
BACKUP_DIR="/home/vojrik/Desktop/md0/_RPi5_Home_OS/Apps_Backups"
# The real Home Assistant config lives in /home/vojrik/homeassistant (bind-mounted as /config)
# see: docker inspect homeassistant
HA_SRC="/home/vojrik/homeassistant"
Z2M_SRC="/opt/home-automation/zigbee2mqtt/data"
MQTT_USER="ha"
MQTT_PASS_FILE="/opt/home-automation/credentials/mqtt_password.txt"
# OctoPrint
OCTOPRINT_BIN="/home/vojrik/OctoPrint/venv/bin/octoprint"
OCTO_EXCLUDES=""   # leave empty to include everything in the backup

# Home Assistant API for native "Backup" (if available)
HA_URL="http://127.0.0.1:8123"
HA_TOKEN_FILE="/opt/home-automation/credentials/ha_long_lived_token.txt"
HA_BACKUP_WAIT_SECS=300

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
DOCKER=/usr/bin/docker
TAR=/bin/tar
NICE=/usr/bin/nice
IONICE=/usr/bin/ionice
CURL=/usr/bin/curl

# Ensure target directories exist
mkdir -p "$BACKUP_DIR/homeassistant" "$BACKUP_DIR/zigbee2mqtt" "$BACKUP_DIR/octoprint"

# ---- Helper functions ----
ha_trigger_backup_via_api() {
  # Requires the Home Assistant Backup integration and local agent (recent HA versions).
  # Returns with an error when the token or curl is missing.
  local token payload name resp_code
  [ -r "$HA_TOKEN_FILE" ] || return 1
  [ -x "$CURL" ] || return 1

  name="Auto backup ${TIMESTAMP}"
  payload=$(printf '{"name":"%s"}' "$name")
  resp_code=$($CURL -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer $(cat "$HA_TOKEN_FILE")" \
    -H "Content-Type: application/json" \
    -X POST "$HA_URL/api/services/backup/create" \
    -d "$payload" || true)

  # Expect HTTP 200 / 201 (sometimes 200)
  if [ "$resp_code" != "200" ] && [ "$resp_code" != "201" ]; then
    return 1
  fi
  return 0
}

ha_wait_and_collect_backup_file() {
  # After triggering the backup, wait until a new file appears in "$HA_SRC/backups".
  # Prints the file path on stdout and returns 0, otherwise returns 1.
  local dir new_file deadline now
  dir="$HA_SRC/backups"
  [ -d "$dir" ] || return 1
  deadline=$(( $(date +%s) + HA_BACKUP_WAIT_SECS ))
  new_file=""
  while :; do
    # Latest file in the directory
    new_file=$(ls -1t "$dir" 2>/dev/null | head -n1 || true)
    if [ -n "$new_file" ]; then
      # Ensure the file is recent so we do not pick an old backup
      now=$(date +%s)
      if [ $(( now - $(stat -c %Y "$dir/$new_file" 2>/dev/null || echo 0) )) -le 600 ]; then
        echo "$dir/$new_file"
        return 0
      fi
    fi
    [ $(date +%s) -ge $deadline ] && break
    sleep 2
  done
  return 1
}

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

# --- Home Assistant: native Backup (when available) + full config archive ---
# 1) Try to trigger native HA Backup via API (captures everything exposed by agents)
HA_NATIVE_BACKUP_COPIED=""
if ha_trigger_backup_via_api; then
  if NEWFILE=$(ha_wait_and_collect_backup_file); then
    # Copy the generated file to the target directory (keep original name)
    cp -f "$NEWFILE" "$BACKUP_DIR/homeassistant/" && HA_NATIVE_BACKUP_COPIED="$BACKUP_DIR/homeassistant/$(basename "$NEWFILE")"
  fi
fi

# 2) Always create a full config archive (includes logs, database, etc.)
HA_CFG_ARCHIVE="$BACKUP_DIR/homeassistant/homeassistant_config_${TIMESTAMP}.tar.gz"
$NICE -n 10 $IONICE -c 3 $TAR -C "$HA_SRC" -czf "$HA_CFG_ARCHIVE" .

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
