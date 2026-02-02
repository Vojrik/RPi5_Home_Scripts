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

# Mail config (shared with smart_daily.sh defaults)
: "${MSMTP_CONFIG:=${TARGET_SCRIPTS_DIR}/Disck_checks/.msmtprc}"
export MSMTP_CONFIG
RECIPIENT="Vojta.Hamacek@seznam.cz"
HOST="$(hostname)"
fail=0
declare -a ISSUES

# 1) SMART daily check (without self-test) - quick
nice -n 10 ionice -c3 \
  "$TARGET_SCRIPTS_DIR/Disck_checks/smart_daily.sh" >> "$LOG" 2>&1 || true

# 2) RAID watch - array state
nice -n 10 ionice -c3 \
  "$TARGET_SCRIPTS_DIR/Disck_checks/raid_watch.sh" >> "$LOG" 2>&1 || true

# 3) MicroSD/system disk health hints (journal scan)
{
  echo "$(ts): MicroSD/system disk check start"
  if command -v findmnt >/dev/null 2>&1; then
    findmnt -n -o SOURCE,FSTYPE,OPTIONS / || true
  fi
  sd_matches=""
  # Only flag genuine error signals, not normal boot/mount messages.
  error_regex="I/O error|Buffer I/O error|EXT4-fs error|ext4 error|read-only|remounting filesystem read-only|Aborting journal|journal check failed|mmc.*error|sdhci.*error"
  if command -v journalctl >/dev/null 2>&1; then
    sd_matches="$(journalctl -k --since "24 hours ago" \
      | egrep -i "$error_regex" \
      | tail -n 200 || true)"
  else
    sd_matches="$(dmesg \
      | egrep -i "$error_regex" \
      | tail -n 200 || true)"
  fi
  if [[ -n "$sd_matches" ]]; then
    echo "$sd_matches"
  else
    echo "No kernel warnings matched for microSD/system disk."
  fi
  echo "$(ts): MicroSD/system disk check end"
} >> "$LOG" 2>&1

if grep -qiE "I/O error|Buffer I/O error|EXT4-fs error|ext4 error|read-only|remounting filesystem read-only|Aborting journal|journal check failed|mmc.*error|sdhci.*error" "$LOG"; then
  fail=1
  ISSUES+=("microSD/system: kernel log contains storage errors in the last 24h (see log)")
fi

echo "$(ts): Daily disk checks end" >> "$LOG"

# MAIL
if (( fail )); then
  {
    echo "From: Vojta.Hamacek@seznam.cz"
    echo "To: $RECIPIENT"
    echo "Subject: [DISK ALERT] $HOST - microSD/system warnings"
    echo "Content-Type: text/plain; charset=UTF-8"
    echo
    echo "---- SUMMARY ----"
    for i in "${ISSUES[@]}"; do printf '%s\n' "$i"; done
    echo
    echo "---- FULL LOG ----"
    echo
    cat "$LOG"
  } | msmtp -C "$MSMTP_CONFIG" -a default "$RECIPIENT" || true
fi

# Pass the log to the user
chown "$TARGET_USER":"$TARGET_USER" "$LOG" 2>/dev/null || true
