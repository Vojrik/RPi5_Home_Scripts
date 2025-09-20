#!/usr/bin/env bash
# /home/vojrik/Scripts/Disck_checks/raid_check.sh
set -euo pipefail

DRY_RUN=false
while (( "$#" )); do
  case "$1" in
    --dry-run)
      DRY_RUN=true; shift ;;
    *)
      echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

# --- mail/MSMTP ---
export MSMTP_CONFIG=/home/vojrik/Scripts/Disck_checks/.msmtprc
RECIPIENT="Vojta.Hamacek@seznam.cz"

LOG_DIR_SYS="/var/log/Disck_checks"
LOG_NAME="raid_check.log"
LOG_DIR_FALLBACK="$HOME/Disck_checks/logs"
# Safe log configuration with fallback to $HOME when permissions are insufficient
if mkdir -p "$LOG_DIR_SYS" 2>/dev/null && : > "$LOG_DIR_SYS/$LOG_NAME" 2>/dev/null; then
  LOG="$LOG_DIR_SYS/$LOG_NAME"
else
  mkdir -p "$LOG_DIR_FALLBACK" 2>/dev/null || true
  LOG="$LOG_DIR_FALLBACK/$LOG_NAME"
  : > "$LOG" 2>/dev/null || true
fi

ts() { date '+%F %T'; }

echo "$(ts): RAID consistency check started. DRY_RUN=$DRY_RUN" >> "$LOG"

# Run only on the first Tuesday of the month
dow="$(date +%u)"   # 1=Mon, 2=Tue, ... 7=Sun
dom="$(date +%d)"   # 01..31
if [[ "$dow" != "2" || $((10#$dom)) -gt 7 ]]; then
  echo "[$(ts)] STATUS: OK - not the first Tuesday (dow=$dow, dom=$dom). Email not sent." >> "$LOG"
  chown vojrik:vojrik "$LOG" 2>/dev/null || true
  ln -sfn "$LOG" "/home/vojrik/Desktop/$LOG_NAME" 2>/dev/null || true
  chown -h vojrik:vojrik "/home/vojrik/Desktop/$LOG_NAME" 2>/dev/null || true
  exit 0
fi

# Find md arrays
mapfile -t arrays < <(awk '/^md[0-9]+/ {print $1}' /proc/mdstat)
if (( ${#arrays[@]} == 0 )); then
  echo "$(ts): no md arrays found." >> "$LOG"
  exit 0
fi

# Helper to stop active checks
stop_arrays() {
  for a in "${arrays[@]}"; do
    if [[ -w "/sys/block/$a/md/sync_action" ]]; then
      if $DRY_RUN; then
        echo "$(ts): [DRY] $a -> would set 'idle'" >> "$LOG"
      else
        echo idle > "/sys/block/$a/md/sync_action" 2>/dev/null || true
      fi
    fi
  done
}

trap 'echo "$(ts): interrupted, stopping checks." >> "$LOG"; stop_arrays; exit 1' INT TERM

# Start the consistency check for all arrays
for a in "${arrays[@]}"; do
  if [[ -w "/sys/block/$a/md/sync_action" ]]; then
    if $DRY_RUN; then
      echo "$(ts): [DRY] $a -> would set 'check'" >> "$LOG"
    else
      echo check > "/sys/block/$a/md/sync_action" 2>/dev/null || true
      echo "$(ts): $a -> check" >> "$LOG"
    fi
    else
      echo "$(ts): $a does not expose sync_action (skip)" >> "$LOG"
  fi
done

# Wait until all arrays return to idle
if ! $DRY_RUN; then
  while :; do
    busy=0
    for a in "${arrays[@]}"; do
      if [[ -r "/sys/block/$a/md/sync_action" ]]; then
        action=$(<"/sys/block/$a/md/sync_action")
        [[ "$action" != "idle" ]] && busy=1
      fi
    done
    (( busy == 0 )) && break
    sleep 10
  done
else
  echo "$(ts): [DRY] skipping wait loop" >> "$LOG"
fi

# Log results and collect problems
problems=()
for a in "${arrays[@]}"; do
  if [[ -r "/sys/block/$a/md/mismatch_cnt" ]]; then
    MISMATCH=$(<"/sys/block/$a/md/mismatch_cnt")
    echo "$(ts): $a mismatches: $MISMATCH" >> "$LOG"
    if [[ "$MISMATCH" =~ ^[1-9][0-9]*$ ]]; then
      problems+=("$a: mismatches=$MISMATCH (recommendation: echo repair > /sys/block/$a/md/sync_action)")
    fi
  else
    echo "$(ts): $a is missing mismatch_cnt" >> "$LOG"
  fi
done

# Repair recommendation (if mismatches were detected)
echo "If mismatches were detected (mismatch_cnt > 0), run: echo repair > /sys/block/<mdX>/md/sync_action" >> "$LOG"
echo "------------------------------------------------------------" >> "$LOG"

# Email notification when a problem is found
sent_mail=false
if (( ${#problems[@]} > 0 )); then
  {
    echo "From: Vojta.Hamacek@seznam.cz"
    echo "To: $RECIPIENT"
    echo "Subject: [RAID ALERT] $(hostname) - parity mismatches detected"
    echo "Content-Type: text/plain; charset=UTF-8"
    echo
    echo "Problem summary:"
    for p in "${problems[@]}"; do echo "$p"; done
    echo
    echo "Recommendation:"
    echo "  for each affected array run: echo repair > /sys/block/<mdX>/md/sync_action"
    echo
    echo "Full log:"
    echo
    cat "$LOG"
  } | msmtp -C /home/vojrik/Scripts/Disck_checks/.msmtprc -a default "$RECIPIENT" && sent_mail=true || true
  if $sent_mail; then
    echo "$(ts): ALERT sent to $RECIPIENT" >> "$LOG"
  else
    echo "$(ts): attempt to send email failed (check msmtp)" >> "$LOG"
  fi
fi

# Clear final status - same format as raid_watch.sh
if (( ${#problems[@]} > 0 )); then
  if $sent_mail; then
    echo "[$(ts)] STATUS: ALERT - email sent" >> "$LOG"
  else
    echo "[$(ts)] STATUS: ALERT - email failed to send" >> "$LOG"
  fi
else
  echo "[$(ts)] STATUS: OK - email not sent" >> "$LOG"
fi

# Ensure the log ownership and desktop symlink always point to the current file
chown vojrik:vojrik "$LOG" 2>/dev/null || true
ln -sfn "$LOG" "/home/vojrik/Desktop/$LOG_NAME" 2>/dev/null || true
chown -h vojrik:vojrik "/home/vojrik/Desktop/$LOG_NAME" 2>/dev/null || true
