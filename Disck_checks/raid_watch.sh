#!/usr/bin/env bash
# /home/vojrik/Scripts/Disck_checks/raid_watch.sh
set -euo pipefail

export MSMTP_CONFIG=/home/vojrik/Scripts/Disck_checks/.msmtprc
RECIPIENT="Vojta.Hamacek@seznam.cz"
LOG_DIR_SYS="/var/log/Disck_checks"
LOG_NAME="raid_watch.log"
LOG_DIR_FALLBACK="$HOME/Disck_checks/logs"
# Safe log configuration with fallback to $HOME when permissions are insufficient
if mkdir -p "$LOG_DIR_SYS" 2>/dev/null && : > "$LOG_DIR_SYS/$LOG_NAME" 2>/dev/null; then
  LOG="$LOG_DIR_SYS/$LOG_NAME"
else
  mkdir -p "$LOG_DIR_FALLBACK" 2>/dev/null || true
  LOG="$LOG_DIR_FALLBACK/$LOG_NAME"
  : > "$LOG" 2>/dev/null || true
fi

ts(){ date '+%F %T'; }
host="$(hostname)"

echo "$(ts): RAID watch start" >> "$LOG"

# Find md arrays
mapfile -t arrays < <(awk '/^md[0-9]+/ {print $1}' /proc/mdstat)
if (( ${#arrays[@]} == 0 )); then
  echo "$(ts): no md arrays found" >> "$LOG"
  echo "[$(ts)] STATUS: OK - email not sent" >> "$LOG"
  chown vojrik:vojrik "$LOG" 2>/dev/null || true
  ln -sfn "$LOG" "/home/vojrik/Desktop/$LOG_NAME" 2>/dev/null || true
  chown -h vojrik:vojrik "/home/vojrik/Desktop/$LOG_NAME" 2>/dev/null || true
  exit 0
fi

issues=()

for a in "${arrays[@]}"; do
  dev="/dev/$a"
  detail="$(sudo mdadm --detail "$dev" 2>&1 || true)"
  state="$(grep -m1 'State :' <<<"$detail" | sed 's/^[ \t]*State :[ \t]*//')"
  raid_devices="$(grep -m1 'Raid Devices :' <<<"$detail" | awk '{print $4+0}')"
  active_devices="$(grep -m1 'Active Devices :' <<<"$detail" | awk '{print $4+0}')"
  failed_devices="$(grep -m1 'Failed Devices :' <<<"$detail" | awk '{print $4+0}')"

  # Check member states
  bad_members=()
  for s in /sys/block/$a/md/dev-*/state; do
    [[ -r "$s" ]] || continue
    mname="$(basename "$(dirname "$s")")"       # dev-sdX...
    mstate="$(<"$s")"
    [[ "$mstate" != "in_sync" ]] && bad_members+=("$mname=$mstate")
  done

  echo "$(ts): $a state='$state' raid=$raid_devices active=$active_devices failed=$failed_devices" >> "$LOG"
  echo "$detail" >> "$LOG"

  # Problem conditions
  if grep -qi 'degraded' <<<"$state" \
     || (( failed_devices > 0 )) \
     || (( active_devices < raid_devices )) \
     || (( ${#bad_members[@]} > 0 )); then
    msg="$a: state='$state', active=$active_devices/$raid_devices, failed=$failed_devices"
    (( ${#bad_members[@]} )) && msg+="; members: ${bad_members[*]}"
    issues+=("$msg")
  fi

  echo "------------------------------------------------------------" >> "$LOG"
done

sent_mail=false
if (( ${#issues[@]} > 0 )); then
  {
    echo "From: Vojta.Hamacek@seznam.cz"
    echo "To: $RECIPIENT"
    echo "Subject: [RAID ALERT] $host - problem detected"
    echo "Content-Type: text/plain; charset=UTF-8"
    echo
    echo "Summary:"
    for i in "${issues[@]}"; do echo " - $i"; done
    echo
    echo "Recommendation: for any affected array run 'echo repair > /sys/block/<mdX>/md/sync_action' and monitor /proc/mdstat."
    echo
    echo "The latest mdadm --detail output is stored in the attached desktop log ($LOG)."
  } | msmtp -C /home/vojrik/Scripts/Disck_checks/.msmtprc -a default "$RECIPIENT" && sent_mail=true || true
  if $sent_mail; then
    echo "$(ts): ALERT sent to $RECIPIENT" >> "$LOG"
  else
    echo "$(ts): attempt to send email failed (check msmtp)" >> "$LOG"
  fi
else
  echo "$(ts): all OK, email not sent" >> "$LOG"
fi

chown vojrik:vojrik "$LOG" 2>/dev/null || true
ln -sfn "$LOG" "/home/vojrik/Desktop/$LOG_NAME" 2>/dev/null || true
chown -h vojrik:vojrik "/home/vojrik/Desktop/$LOG_NAME" 2>/dev/null || true

# Clear final status in a consistent format
if (( ${#issues[@]} > 0 )); then
  if $sent_mail; then
    echo "[$(ts)] STATUS: ALERT - email sent" >> "$LOG"
  else
    echo "[$(ts)] STATUS: ALERT - email failed to send" >> "$LOG"
  fi
else
  echo "[$(ts)] STATUS: OK - email not sent" >> "$LOG"
fi
