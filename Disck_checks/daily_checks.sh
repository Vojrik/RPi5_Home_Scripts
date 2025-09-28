#!/usr/bin/env bash
# /home/vojrik/Scripts/Disck_checks/daily_checks.sh
set -Eeuo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SCRIPTS_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
ENV_FILE="$SCRIPTS_ROOT/.rpi5_home_env"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  . "$ENV_FILE"
fi

if [[ -z ${TARGET_USER:-} ]]; then
  TARGET_USER=$(stat -c %U "$SCRIPT_DIR" 2>/dev/null || id -un)
fi

if [[ -z ${TARGET_HOME:-} ]]; then
  if command -v getent >/dev/null 2>&1; then
    TARGET_HOME=$(getent passwd "$TARGET_USER" | cut -d: -f6)
  fi
fi

if [[ -z ${TARGET_HOME:-} ]]; then
  TARGET_HOME=$(cd "$SCRIPTS_ROOT/.." && pwd)
fi

if [[ -z ${TARGET_SCRIPTS_DIR:-} ]]; then
  TARGET_SCRIPTS_DIR="$SCRIPTS_ROOT"
fi

TARGET_DESKTOP="$TARGET_HOME/Desktop"
mkdir -p "$TARGET_DESKTOP" 2>/dev/null || true

PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

LOG="$TARGET_DESKTOP/daily_checks.log"
: > "$LOG"
ts(){ date '+%F %T'; }

echo "$(ts): Daily disk checks start" >> "$LOG"

# 1) SMART daily check (without self-test) - quick
nice -n 10 ionice -c3 \
  "$TARGET_SCRIPTS_DIR/Disck_checks/smart_daily.sh" >> "$LOG" 2>&1 || true

# 2) RAID watch - array state
nice -n 10 ionice -c3 \
  "$TARGET_SCRIPTS_DIR/Disck_checks/raid_watch.sh" >> "$LOG" 2>&1 || true

echo "$(ts): Daily disk checks end" >> "$LOG"

# Pass the log to the user
chown "$TARGET_USER":"$TARGET_USER" "$LOG" 2>/dev/null || true
