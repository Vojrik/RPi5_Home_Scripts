#!/usr/bin/env bash
# /home/vojrik/Scripts/Disck_checks/raid_check.sh
set -euo pipefail

# --- mail/MSMTP ---
export MSMTP_CONFIG=/home/vojrik/Scripts/Disck_checks/.msmtprc
RECIPIENT="Vojta.Hamacek@seznam.cz"

LOG="/home/vojrik/Desktop/raid_check.log"
: > "$LOG"   # vždy přepsat log

ts() { date '+%F %T'; }

echo "$(ts): RAID consistency check started." >> "$LOG"

# Najdi md pole
mapfile -t arrays < <(awk '/^md[0-9]+/ {print $1}' /proc/mdstat)
if (( ${#arrays[@]} == 0 )); then
  echo "$(ts): žádná md pole nenalezena." >> "$LOG"
  exit 0
fi

# Funkce pro stop akce
stop_arrays() {
  for a in "${arrays[@]}"; do
    if [[ -w "/sys/block/$a/md/sync_action" ]]; then
      echo idle > "/sys/block/$a/md/sync_action" 2>/dev/null || true
    fi
  done
}

trap 'echo "$(ts): interrupted, stopping checks." >> "$LOG"; stop_arrays; exit 1' INT TERM

# Spusť kontrolu všech polí
for a in "${arrays[@]}"; do
  if [[ -w "/sys/block/$a/md/sync_action" ]]; then
    echo check > "/sys/block/$a/md/sync_action" 2>/dev/null || true
    echo "$(ts): $a -> check" >> "$LOG"
  else
    echo "$(ts): $a nemá sync_action (skip)" >> "$LOG"
  fi
done

# Čekej, dokud všechny nejsou idle
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

# Zaloguj výsledky a seber problémy
problems=()
for a in "${arrays[@]}"; do
  if [[ -r "/sys/block/$a/md/mismatch_cnt" ]]; then
    MISMATCH=$(<"/sys/block/$a/md/mismatch_cnt")
    echo "$(ts): $a mismatches: $MISMATCH" >> "$LOG"
    if [[ "$MISMATCH" =~ ^[1-9][0-9]*$ ]]; then
      problems+=("$a: mismatches=$MISMATCH (doporučení: echo repair > /sys/block/$a/md/sync_action)")
    fi
  else
    echo "$(ts): $a – chybí mismatch_cnt" >> "$LOG"
  fi
done

echo "If mismatches were found, you can run: echo repair > /sys/block/<mdX>/md/sync_action" >> "$LOG"
echo "------------------------------------------------------------" >> "$LOG"

# E-mail při problému
if (( ${#problems[@]} > 0 )); then
  {
    echo "From: Vojta.Hamacek@seznam.cz"
    echo "To: $RECIPIENT"
    echo "Subject: [RAID ALERT] $(hostname) – nalezeny neshody parity"
    echo "Content-Type: text/plain; charset=UTF-8"
    echo
    echo "Shrnutí problémů:"
    for p in "${problems[@]}"; do echo "$p"; done
    echo
    echo "Doporučení:"
    echo "  pro každé pole s problémem spusť: echo repair > /sys/block/<mdX>/md/sync_action"
    echo
    echo "Plný log:"
    echo
    cat "$LOG"
  } | msmtp -C /home/vojrik/Scripts/Disck_checks/.msmtprc -a default "$RECIPIENT" || true
fi
