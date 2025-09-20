#!/usr/bin/env bash
# /home/vojrik/Scripts/Disck_checks/daily_checks.sh
set -Eeuo pipefail

PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

LOG="/home/vojrik/Desktop/daily_checks.log"
: > "$LOG"
ts(){ date '+%F %T'; }

echo "$(ts): Daily disk checks start" >> "$LOG"

# 1) SMART daily check (without self-test) - quick
nice -n 10 ionice -c3 \
  /home/vojrik/Scripts/Disck_checks/smart_daily.sh >> "$LOG" 2>&1 || true

# 2) RAID watch - array state
nice -n 10 ionice -c3 \
  /home/vojrik/Scripts/Disck_checks/raid_watch.sh >> "$LOG" 2>&1 || true

echo "$(ts): Daily disk checks end" >> "$LOG"

# Pass the log to the user
chown vojrik:vojrik "$LOG" 2>/dev/null || true
