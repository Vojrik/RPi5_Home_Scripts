#!/usr/bin/env bash
# /home/vojrik/Scripts/Disck_checks/raid_check.sh
set -euo pipefail

DRY_RUN=false
while (( "$#" )); do
  case "$1" in
    --dry-run)
      DRY_RUN=true; shift ;;
    *)
      echo "Neznámý argument: $1" >&2; exit 2 ;;
  esac
done

# --- mail/MSMTP ---
export MSMTP_CONFIG=/home/vojrik/Scripts/Disck_checks/.msmtprc
RECIPIENT="Vojta.Hamacek@seznam.cz"

LOG_DIR_SYS="/var/log/Disck_checks"
LOG_NAME="raid_check.log"
LOG_DIR_FALLBACK="$HOME/Disck_checks/logs"
# Bezpečné nastavení logu s fallbackem do $HOME při nedostatku práv
if mkdir -p "$LOG_DIR_SYS" 2>/dev/null && : > "$LOG_DIR_SYS/$LOG_NAME" 2>/dev/null; then
  LOG="$LOG_DIR_SYS/$LOG_NAME"
else
  mkdir -p "$LOG_DIR_FALLBACK" 2>/dev/null || true
  LOG="$LOG_DIR_FALLBACK/$LOG_NAME"
  : > "$LOG" 2>/dev/null || true
fi

ts() { date '+%F %T'; }

echo "$(ts): RAID consistency check started. DRY_RUN=$DRY_RUN" >> "$LOG"

# Spouštět pouze první úterý v měsíci
dow="$(date +%u)"   # 1=Mon, 2=Tue, ... 7=Sun
dom="$(date +%d)"   # 01..31
if [[ "$dow" != "2" || $((10#$dom)) -gt 7 ]]; then
  echo "[$(ts)] STATUS: OK – není první úterý (dow=$dow, dom=$dom). E‑mail se neposílá." >> "$LOG"
  chown vojrik:vojrik "$LOG" 2>/dev/null || true
  ln -sfn "$LOG" "/home/vojrik/Desktop/$LOG_NAME" 2>/dev/null || true
  chown -h vojrik:vojrik "/home/vojrik/Desktop/$LOG_NAME" 2>/dev/null || true
  exit 0
fi

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
      if $DRY_RUN; then
        echo "$(ts): [DRY] $a -> would set 'idle'" >> "$LOG"
      else
        echo idle > "/sys/block/$a/md/sync_action" 2>/dev/null || true
      fi
    fi
  done
}

trap 'echo "$(ts): interrupted, stopping checks." >> "$LOG"; stop_arrays; exit 1' INT TERM

# Spusť kontrolu všech polí
for a in "${arrays[@]}"; do
  if [[ -w "/sys/block/$a/md/sync_action" ]]; then
    if $DRY_RUN; then
      echo "$(ts): [DRY] $a -> would set 'check'" >> "$LOG"
    else
      echo check > "/sys/block/$a/md/sync_action" 2>/dev/null || true
      echo "$(ts): $a -> check" >> "$LOG"
    fi
  else
    echo "$(ts): $a nemá sync_action (skip)" >> "$LOG"
  fi
done

# Čekej, dokud všechny nejsou idle
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

# Doporučení k opravě (pokud byly neshody)
echo "Pokud byly nalezeny neshody (mismatch_cnt > 0), lze spustit opravu: echo repair > /sys/block/<mdX>/md/sync_action" >> "$LOG"
echo "------------------------------------------------------------" >> "$LOG"

# E-mail při problému
sent_mail=false
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
  } | msmtp -C /home/vojrik/Scripts/Disck_checks/.msmtprc -a default "$RECIPIENT" && sent_mail=true || true
  if $sent_mail; then
    echo "$(ts): ALERT odeslán na $RECIPIENT" >> "$LOG"
  else
    echo "$(ts): pokus o odeslání e‑mailu selhal (zkontroluj msmtp)" >> "$LOG"
  fi
fi

# Jednoznačný závěrečný status – analogicky k raid_watch.sh
if (( ${#problems[@]} > 0 )); then
  if $sent_mail; then
    echo "[$(ts)] STATUS: ALERT – e‑mail odeslán" >> "$LOG"
  else
    echo "[$(ts)] STATUS: ALERT – e‑mail se NEpodařilo odeslat" >> "$LOG"
  fi
else
  echo "[$(ts)] STATUS: OK – e‑mail se neposílá" >> "$LOG"
fi

# Vlastnictví logu a symlink na plochu – vždy ukazuj na aktuální zdroj
chown vojrik:vojrik "$LOG" 2>/dev/null || true
ln -sfn "$LOG" "/home/vojrik/Desktop/$LOG_NAME" 2>/dev/null || true
chown -h vojrik:vojrik "/home/vojrik/Desktop/$LOG_NAME" 2>/dev/null || true
