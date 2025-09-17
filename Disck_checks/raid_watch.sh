#!/usr/bin/env bash
# /home/vojrik/Scripts/Disck_checks/raid_watch.sh
set -euo pipefail

export MSMTP_CONFIG=/home/vojrik/Scripts/Disck_checks/.msmtprc
RECIPIENT="Vojta.Hamacek@seznam.cz"
LOG_DIR_SYS="/var/log/Disck_checks"
LOG_NAME="raid_watch.log"
LOG_DIR_FALLBACK="$HOME/Disck_checks/logs"
# Bezpečné nastavení logu s fallbackem do $HOME při nedostatku práv
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

# najdi md pole
mapfile -t arrays < <(awk '/^md[0-9]+/ {print $1}' /proc/mdstat)
if (( ${#arrays[@]} == 0 )); then
  echo "$(ts): žádná md pole nenalezena" >> "$LOG"
  echo "[$(ts)] STATUS: OK – e-mail se neposílá" >> "$LOG"
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

  # zkontroluj stavy členů
  bad_members=()
  for s in /sys/block/$a/md/dev-*/state; do
    [[ -r "$s" ]] || continue
    mname="$(basename "$(dirname "$s")")"       # dev-sdX...
    mstate="$(<"$s")"
    [[ "$mstate" != "in_sync" ]] && bad_members+=("$mname=$mstate")
  done

  echo "$(ts): $a state='$state' raid=$raid_devices active=$active_devices failed=$failed_devices" >> "$LOG"
  echo "$detail" >> "$LOG"

  # podmínky problému
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
    echo "Subject: [RAID ALERT] $host – problém detekován"
    echo "Content-Type: text/plain; charset=UTF-8"
    echo
    echo "Shrnutí:"
    for i in "${issues[@]}"; do echo " - $i"; done
    echo
    echo "Doporučení: pro postižené pole spusť 'echo repair > /sys/block/<mdX>/md/sync_action' a sleduj /proc/mdstat."
    echo
    echo "Poslední výpis mdadm --detail je v přiloženém logu na ploše ($LOG)."
  } | msmtp -C /home/vojrik/Scripts/Disck_checks/.msmtprc -a default "$RECIPIENT" && sent_mail=true || true
  if $sent_mail; then
    echo "$(ts): ALERT odeslán na $RECIPIENT" >> "$LOG"
  else
    echo "$(ts): pokus o odeslání e‑mailu selhal (zkontroluj msmtp)" >> "$LOG"
  fi
else
  echo "$(ts): vše OK, e-mail se neposílá" >> "$LOG"
fi

chown vojrik:vojrik "$LOG" 2>/dev/null || true
ln -sfn "$LOG" "/home/vojrik/Desktop/$LOG_NAME" 2>/dev/null || true
chown -h vojrik:vojrik "/home/vojrik/Desktop/$LOG_NAME" 2>/dev/null || true

# Jednoznačný závěrečný status v jednotném formátu
if (( ${#issues[@]} > 0 )); then
  if $sent_mail; then
    echo "[$(ts)] STATUS: ALERT – e‑mail odeslán" >> "$LOG"
  else
    echo "[$(ts)] STATUS: ALERT – e‑mail se NEpodařilo odeslat" >> "$LOG"
  fi
else
  echo "[$(ts)] STATUS: OK – e‑mail se neposílá" >> "$LOG"
fi
