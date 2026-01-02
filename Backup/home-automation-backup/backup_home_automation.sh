#!/usr/bin/env bash
set -euo pipefail

# ---- Environment detection ----
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SCRIPTS_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
ENV_FILE="$SCRIPTS_ROOT/.rpi5_home_env"
if [ ! -f "$ENV_FILE" ]; then
  SCRIPTS_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
  ENV_FILE="$SCRIPTS_ROOT/.rpi5_home_env"
fi
if [ -f "$ENV_FILE" ]; then
  # shellcheck disable=SC1090
  . "$ENV_FILE"
fi

if [ -z "${TARGET_USER:-}" ]; then
  TARGET_USER=$(stat -c %U "$SCRIPT_DIR" 2>/dev/null || id -un)
fi

if [ -z "${TARGET_HOME:-}" ]; then
  if command -v getent >/dev/null 2>&1; then
    TARGET_HOME=$(getent passwd "$TARGET_USER" | cut -d: -f6)
  fi
fi

if [ -z "${TARGET_HOME:-}" ]; then
  TARGET_HOME=$(cd "$SCRIPTS_ROOT/.." && pwd)
fi

if [ -z "${TARGET_SCRIPTS_DIR:-}" ]; then
  TARGET_SCRIPTS_DIR="$SCRIPTS_ROOT"
fi

# ---- Config ----
BACKUP_DIR="${BACKUP_DIR:-$TARGET_HOME/Desktop/md0/_RPi5_Home_OS/Apps_Backups}"
# The real Home Assistant config lives in ${TARGET_HOME}/homeassistant (bind-mounted as /config)
# see: docker inspect homeassistant
HA_SRC="${HA_SRC:-$TARGET_HOME/homeassistant}"
Z2M_SRC="/opt/home-automation/zigbee2mqtt/data"
MQTT_USER="ha"
MQTT_PASS_FILE="/opt/home-automation/credentials/mqtt_password.txt"
# OctoPrint
OCTOPRINT_BIN="${OCTOPRINT_BIN:-$TARGET_HOME/OctoPrint/venv/bin/octoprint}"
OCTOPRINT_BASEDIR="${OCTOPRINT_BASEDIR:-$TARGET_HOME/.octoprint}"
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
RSYNC=/usr/bin/rsync
MKDIR=/bin/mkdir
RM=/bin/rm

# Temporary staging directory for consistent snapshots
STAGING_ROOT=""
cleanup() {
  if [ -n "${STAGING_ROOT:-}" ] && [ -d "$STAGING_ROOT" ]; then
    $RM -rf -- "$STAGING_ROOT"
  fi
}
trap cleanup EXIT

create_stage_dir() {
  if [ -z "${STAGING_ROOT}" ]; then
    STAGING_ROOT=$(mktemp -d -t home_automation_backup.XXXXXX)
  fi
  $MKDIR -p -- "$STAGING_ROOT"
}

rsync_stage() {
  # Usage: rsync_stage <source_dir> <target_dir> [extra rsync args...]
  # Runs rsync twice to reduce churn between passes.
  local src dest
  src="$1"
  dest="$2"
  shift 2 || true
  $MKDIR -p -- "$dest"
  $RSYNC -a --delete "$@" "$src/" "$dest/"
  $RSYNC -a --delete "$@" "$src/" "$dest/"
}

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

ha_prune_native_backups() {
  # Keep only the most recent native HA backup inside the config dir so
  # the full-config tarball does not grow without bound.
  local dir keep
  dir="$HA_SRC/backups"
  keep=1
  [ -d "$dir" ] || return 0

  local -a files=()
  mapfile -d '' -t files < <(find "$dir" -maxdepth 1 -type f -printf '%T@ %p\0' 2>/dev/null \
    | sort -z -n -r \
    | cut -z -d' ' -f2-)

  local total=${#files[@]}
  if (( total > keep )); then
    for ((i = keep; i < total; i++)); do
      rm -f -- "${files[i]}" || echo "[WARN] Failed to prune old HA backup ${files[i]}" >&2
    done
  fi
}

# --- Zigbee2MQTT: trigger coordinator backup & archive data ---
if [ -r "$MQTT_PASS_FILE" ]; then
  MQTT_PASS=$(cat "$MQTT_PASS_FILE")
  if $DOCKER exec mosquitto which mosquitto_pub >/dev/null 2>&1; then
    $DOCKER exec mosquitto mosquitto_pub -h localhost -p 1883 -u "$MQTT_USER" -P "$MQTT_PASS" -t zigbee2mqtt/bridge/request/backup -m '{}'
    sleep 2
  fi
fi
create_stage_dir
Z2M_STAGE="$STAGING_ROOT/zigbee2mqtt"
rsync_stage "$Z2M_SRC" "$Z2M_STAGE"
Z2M_ARCHIVE="$BACKUP_DIR/zigbee2mqtt/zigbee2mqtt_${TIMESTAMP}.tar.gz"
$NICE -n 10 $IONICE -c 3 $TAR -C "$Z2M_STAGE" -czf "$Z2M_ARCHIVE" .

# --- Home Assistant: native Backup (when available) + full config archive ---
# 1) Try to trigger native HA Backup via API (captures everything exposed by agents)
HA_NATIVE_BACKUP_COPIED=""
if ha_trigger_backup_via_api; then
  if NEWFILE=$(ha_wait_and_collect_backup_file); then
    # Copy the generated file to the target directory with a more descriptive name
    bn=$(basename "$NEWFILE")
    case "$bn" in
      *.tar.gz) suffix=".tar.gz" ;;
      *.tar.xz) suffix=".tar.xz" ;;
      *.tar.bz2) suffix=".tar.bz2" ;;
      *.tar.zst) suffix=".tar.zst" ;;
      *.tar.lz4) suffix=".tar.lz4" ;;
      *) suffix=".${bn##*.}" ;;
    esac
    new_dest="$BACKUP_DIR/homeassistant/Native_HA_backup_${TIMESTAMP}${suffix}"
    cp -f "$NEWFILE" "$new_dest" && HA_NATIVE_BACKUP_COPIED="$new_dest"
  fi
fi

# Trim old native backups inside Home Assistant so the config archive stays compact
ha_prune_native_backups

# 2) Always create a full config archive (includes logs, database, etc.)
create_stage_dir
HA_STAGE="$STAGING_ROOT/homeassistant"
rsync_stage "$HA_SRC" "$HA_STAGE"
HA_CFG_ARCHIVE="$BACKUP_DIR/homeassistant/Custom_HA_config_${TIMESTAMP}.tar.gz"
$NICE -n 10 $IONICE -c 3 $TAR -C "$HA_STAGE" -czf "$HA_CFG_ARCHIVE" .

# --- OctoPrint: create backup via official backup command ---
# Try to detect binary if configured path missing
if [ ! -x "$OCTOPRINT_BIN" ]; then
  if command -v octoprint >/dev/null 2>&1; then
    OCTOPRINT_BIN=$(command -v octoprint)
  elif [ -x "$TARGET_HOME/oprint/bin/octoprint" ]; then
    OCTOPRINT_BIN="$TARGET_HOME/oprint/bin/octoprint"
  fi
fi

if [ -x "$OCTOPRINT_BIN" ]; then
  OCTO_ARCHIVE="$BACKUP_DIR/octoprint/octoprint_${TIMESTAMP}.zip"
  if [ ! -d "$OCTOPRINT_BASEDIR" ]; then
    echo "[WARN] OctoPrint basedir $OCTOPRINT_BASEDIR not found, skipping OctoPrint backup" >&2
  else
    OCTO_ARGS=(--basedir "$OCTOPRINT_BASEDIR" plugins backup:backup --path "$OCTO_ARCHIVE")
  # Add excludes as repeated flags if set
  for ex in $OCTO_EXCLUDES; do
    OCTO_ARGS=("${OCTO_ARGS[@]}" --exclude "$ex")
  done
  # Run backup; if it fails, continue with other backups already created
  if ! "$OCTOPRINT_BIN" "${OCTO_ARGS[@]}"; then
    echo "[WARN] OctoPrint backup command failed" >&2
  fi
  fi
else
  echo "[INFO] OctoPrint CLI not found, skipping OctoPrint backup" >&2
fi

# --- Retention: keep last 30 of each ---
for d in "$BACKUP_DIR/homeassistant" "$BACKUP_DIR/zigbee2mqtt" "$BACKUP_DIR/octoprint"; do
  ls -1t "$d"/*.* 2>/dev/null | awk 'NR>30' | xargs -r rm -f --
done

exit 0
