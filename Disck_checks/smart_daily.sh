#!/usr/bin/env bash
# /home/vojrik/Scripts/Disck_checks/smart_daily.sh
set -Eeuo pipefail

export MSMTP_CONFIG=/home/vojrik/Scripts/Disck_checks/.msmtprc

RECIPIENT="Vojta.Hamacek@seznam.cz"
LOG_DIR_SYS="/var/log/Disck_checks"
LOG_NAME="smart_daily.log"
LOG_DIR_FALLBACK="$HOME/Disck_checks/logs"
# Bezpečné nastavení logu s fallbackem do $HOME při nedostatku práv
if mkdir -p "$LOG_DIR_SYS" 2>/dev/null && : > "$LOG_DIR_SYS/$LOG_NAME" 2>/dev/null; then
  LOG="$LOG_DIR_SYS/$LOG_NAME"
else
  mkdir -p "$LOG_DIR_FALLBACK" 2>/dev/null || true
  LOG="$LOG_DIR_FALLBACK/$LOG_NAME"
  : > "$LOG" 2>/dev/null || true
fi
RUN_SHORT_TEST=false
RUN_LONG_TEST=false
WAIT_FOR_COMPLETION=false
ABORT_RUNNING=false
DRY_RUN=false

# Volby:
#  -s|--short  ... spustí krátké self‑testy (ekvivalent RUN_SHORT_TEST=true)
#  --long      ... spustí dlouhé/extended self‑testy (RUN_LONG_TEST=true)
#  --dry-run   ... pouze loguje, nic nespouští
#  --wait      ... pokud běží --short/--long, čeká na dokončení self-testů
#  --abort-running ... ukončí právě běžící self-testy na všech nesystémových discích
while (( "$#" )); do
  case "$1" in
    -s|--short)
      RUN_SHORT_TEST=true
      shift
      ;;
    --long)
      RUN_LONG_TEST=true
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --wait)
      WAIT_FOR_COMPLETION=true
      shift
      ;;
    --abort-running)
      ABORT_RUNNING=true
      shift
      ;;
    *)
      echo "Neznámý argument: $1" >&2
      exit 2
      ;;
  esac
done

HOST="$(hostname)"
DATE_ISO="$(date -Is)"

: > "$LOG"
log(){ echo "[$(date +%F\ %T)] $*" | tee -a "$LOG"; }

# Stavové soubory pro sledování dlouho běžících self-testů
STATE_DIR_SYS="/var/lib/Disck_checks"
STATE_DIR_FALLBACK="$HOME/.local/state/Disck_checks"
if mkdir -p "$STATE_DIR_SYS" 2>/dev/null; then
  STATE_DIR="$STATE_DIR_SYS"
else
  mkdir -p "$STATE_DIR_FALLBACK" 2>/dev/null || true
  STATE_DIR="$STATE_DIR_FALLBACK"
fi

# Přeskočení krátkých testů v den dlouhých testů (první úterý v měsíci)
if $RUN_SHORT_TEST; then
  dow=$(date +%u)   # 1=Po .. 7=Ne
  dom=$(date +%d)   # 01-31
  if [[ "$dow" == "2" ]] && (( 10#$dom <= 7 )); then
    log "Short self-test skip: první úterý v měsíci (v 18:30 běží dlouhý test)."
    RUN_SHORT_TEST=false
  fi
fi

ROOT_PART="$(findmnt -n -o SOURCE /)"
ROOT_BLK="/dev/$(lsblk -no pkname "$ROOT_PART")"
[[ "$ROOT_BLK" == "/dev/" ]] && ROOT_BLK="$ROOT_PART"

mapfile -t DISKS < <(lsblk -dpno NAME,TYPE | awk '$2=="disk"{print $1}' | grep -vE 'loop|zram' || true)

# Volitelně: abort všech běžících self-testů a skončit
if $ABORT_RUNNING; then
  log "ABORT požadován – pokusím se ukončit běžící self-testy."
  for d in "${DISKS[@]}"; do
    [[ "$d" == "$ROOT_BLK" ]] && continue
    if [[ "$d" == /dev/nvme* ]]; then
      set +e; status_line=$(sudo smartctl -a "$d" 2>/dev/null | grep -i 'Self-test' | head -n1); set -e || true
      if grep -qi 'in progress' <<<"$status_line"; then
        log "$d: self-test in progress → abortuji (smartctl -X)"
        set +e; sudo smartctl -X "$d" >> "$LOG" 2>&1; set -e || true
      fi
    else
      set +e; status_line=$(sudo smartctl -c -d auto "$d" 2>/dev/null | grep -i 'Self-test execution status'); rc=$?; set -e || true
      if (( rc != 0 )); then
        set +e; status_line=$(sudo smartctl -c -d sat "$d" 2>/dev/null | grep -i 'Self-test execution status'); set -e || true
      fi
      if grep -qi 'in progress' <<<"$status_line"; then
        log "$d: self-test in progress → abortuji (smartctl -X)"
        set +e; sudo smartctl -X -d auto "$d" >> "$LOG" 2>&1; rcx=$?; set -e || true
        if (( rcx != 0 )); then
          set +e; sudo smartctl -X -d sat "$d" >> "$LOG" 2>&1; set -e || true
        fi
      fi
    fi
  done
  log "ABORT dokončen."
  # po abortu ukonči běh
  chown vojrik:vojrik "$LOG" 2>/dev/null || true
  ln -sfn "$LOG" "/home/vojrik/Desktop/$LOG_NAME" 2>/dev/null || true
  chown -h vojrik:vojrik "/home/vojrik/Desktop/$LOG_NAME" 2>/dev/null || true
  exit 0
fi

wake_disk() {
  local dev="$1" tries=10 state
  if [[ "$dev" =~ ^/dev/sd ]]; then
    while (( tries-- > 0 )); do
      $DRY_RUN && return 0
      state="$(sudo hdparm -C "$dev" 2>/dev/null | awk '/drive state/ {print $4}')"
      [[ "$state" == "active/idle" ]] && return 0
      sudo dd if="$dev" of=/dev/null bs=512 count=1 status=none 2>/dev/null || true
      sleep 5
    done
  fi
  return 0
}

log "SMART kontrola | host: $HOST | $DATE_ISO"
echo >> "$LOG"

fail=0
declare -a ISSUES
declare -a LIFE     # životní čítače k přehledu

for d in "${DISKS[@]}"; do
  if [[ "$d" == "$ROOT_BLK" ]]; then
    log "SKIP systémový disk: $d"
    echo -e "==== $d ====\n(Skipped: system disk)\n" >> "$LOG"
    continue
  fi

  wake_disk "$d"
  tmp="$(mktemp)"

  if [[ "$d" == /dev/nvme* ]]; then
    log "NVMe: $d"
    if $DRY_RUN; then
      rc=0
      echo -e "==== $d ====\n[DRY RUN] would run: smartctl -H -A -l error; optional self-test: $( $RUN_LONG_TEST && echo long || $RUN_SHORT_TEST && echo short || echo none )\n" >> "$LOG"
    else
      if $RUN_LONG_TEST; then
        set +e; sudo smartctl -t long "$d" >"$tmp.start" 2>&1; set -e
        cat "$tmp.start" >> "$LOG"
      elif $RUN_SHORT_TEST; then
        set +e; sudo smartctl -t short "$d" >"$tmp.start" 2>&1; set -e
        cat "$tmp.start" >> "$LOG"
      fi
    set +e; sudo smartctl -H -A -l error "$d" >"$tmp" 2>&1; rc=$?; set -e
    out="$(cat "$tmp")"
    echo -e "==== $d ====\n$out\n" >> "$LOG"

    # Zapiš i self-test log (pokud je k dispozici)
    set +e; sudo smartctl -l selftest "$d" >"$tmp.st" 2>&1; set -e || true
    echo -e "---- SELF-TEST LOG ($d) ----\n$(cat "$tmp.st")\n" >> "$LOG"

    # Krátký status + evidence běžících testů
    status_line="$(sudo smartctl -a "$d" 2>/dev/null | grep -i 'Self-test' | head -n1 || true)"
    if grep -qi 'in progress' <<<"$status_line"; then
      echo "[$(date +%F\ %T)] $d Self-test status: $status_line" >> "$LOG"
      # pokus o určení typu testu z logu
      test_type="unknown"
      if grep -qi 'Extended' "$tmp.st"; then test_type="long"; fi
      if grep -qi 'Short' "$tmp.st"; then test_type="short"; fi
      sf="$STATE_DIR/selftest_$(basename "$d").state"
      now=$(date +%s)
      if [[ -f "$sf" ]]; then
        # načti start
        start=$(awk -F= '/^start=/{print $2}' "$sf" 2>/dev/null || echo "$now")
        prev_type=$(awk -F= '/^type=/{print $2}' "$sf" 2>/dev/null || echo "$test_type")
        [[ -z "$start" ]] && start=$now
        elapsed=$(( now - start ))
        # prahy: short 2h, long 24h, unknown 24h
        case "${prev_type:-$test_type}" in
          short) threshold=$((2*3600));;
          long)  threshold=$((24*3600));;
          *)     threshold=$((24*3600));;
        esac
        if (( elapsed > threshold )); then
          hours=$(( elapsed/3600 )); mins=$(( (elapsed%3600)/60 ))
          fail=1
          ISSUES+=("$d: Self-test appears stuck (type=${prev_type:-$test_type}, running ${hours}h ${mins}m). Consider abort: smartctl -X $d")
        fi
      else
        printf 'type=%s\nstart=%s\n' "$test_type" "$now" > "$sf" 2>/dev/null || true
      fi
    else
      # není in-progress → smaž případný state
      sf="$STATE_DIR/selftest_$(basename "$d").state"
      rm -f "$sf" 2>/dev/null || true
    fi

      # Volitelné čekání na dokončení self-testu
      if $WAIT_FOR_COMPLETION && ( $RUN_LONG_TEST || $RUN_SHORT_TEST ); then
        log "Waiting for NVMe self-test to complete on $d ..."
        while :; do
          status_line="$(sudo smartctl -a "$d" 2>/dev/null | grep -i 'Self-test' | head -n1 || true)"
          echo "[$(date +%F\ %T)] $d status: $status_line" >> "$LOG"
          grep -qi 'in progress' <<<"$status_line" || break
          sleep 60
        done
        log "NVMe self-test finished on $d"
      fi
    fi

    # ŽIVOTNÍ ČÍTAČE – NVMe
    if $DRY_RUN; then
      LIFE+=("$d: DRY RUN – NVMe")
    else
      nvme_pcycles="$(grep -E 'Power Cycles' <<<"$out" | awk -F: '{gsub(/^[ \t]+/,"",$2); print $2}' | awk '{print $1}' | tail -1)"
      [[ -z "$nvme_pcycles" ]] && nvme_pcycles="N/A"
      LIFE+=("$d: Power Cycles=$nvme_pcycles; Load/Unload=N/A")
    fi

    # Hodnocení stavu
    disk_issues=()
    if ! $DRY_RUN; then
      (( (rc & 2) != 0 )) && disk_issues+=("SMART health: predictive failure (rc&2)")
      line="$(grep -E 'Media and Data Integrity Errors' <<<"$out" || true)"; [[ "$line" =~ ([1-9][0-9]*) ]] && disk_issues+=("$line")
      line="$(grep -E 'Percentage Used' <<<"$out" || true)";          [[ "$line" =~ ([8-9][0-9]|100)% ]] && disk_issues+=("$line")
    fi

  else
    log "SATA/USB: $d"
    if $DRY_RUN; then
      rc=0
      echo -e "==== $d ====\n[DRY RUN] would run: smartctl -d auto -H -A -l error; optional self-test: $( $RUN_LONG_TEST && echo long || $RUN_SHORT_TEST && echo short || echo none )\n" >> "$LOG"
    else
      if $RUN_LONG_TEST; then
        { set +e; sudo smartctl -d auto -t long "$d" >"$tmp.start" 2>&1; rc_test=$?; set -e; } || true
        if (( rc_test != 0 )); then
          { set +e; sudo smartctl -d sat -t long "$d" >"$tmp.start" 2>&1; set -e; } || true
        fi
        [[ -s "$tmp.start" ]] && cat "$tmp.start" >> "$LOG"
      elif $RUN_SHORT_TEST; then
        { set +e; sudo smartctl -d auto -t short "$d" >"$tmp.start" 2>&1; rc_test=$?; set -e; } || true
        if (( rc_test != 0 )); then
          { set +e; sudo smartctl -d sat -t short "$d" >"$tmp.start" 2>&1; set -e; } || true
        fi
        [[ -s "$tmp.start" ]] && cat "$tmp.start" >> "$LOG"
      fi
      set +e; sudo smartctl -d auto -H -A -l error "$d" >"$tmp" 2>&1; rc=$?
      if (( rc != 0 )); then
        sudo smartctl -d sat  -H -A -l error "$d" >"$tmp" 2>&1; rc=$?
      fi
      set -e
      out="$(cat "$tmp")"
      echo -e "==== $d ====\n$out\n" >> "$LOG"

      # Zapiš i self-test log (pokud je k dispozici)
      set +e; sudo smartctl -d auto -l selftest "$d" >"$tmp.st" 2>&1; rcst=$?
      if (( rcst != 0 )); then
        sudo smartctl -d sat -l selftest "$d" >"$tmp.st" 2>&1 || true
      fi
      set -e
      echo -e "---- SELF-TEST LOG ($d) ----\n$(cat "$tmp.st")\n" >> "$LOG"

      # Krátký status: pokud běží self-test, zaloguj přehledovou větu
      status_line="$(sudo smartctl -c -d auto "$d" 2>/dev/null | grep -i 'Self-test execution status' || true)"
      if [[ -z "$status_line" ]]; then
        status_line="$(sudo smartctl -c -d sat "$d" 2>/dev/null | grep -i 'Self-test execution status' || true)"
      fi
      if grep -qi 'in progress' <<<"$status_line"; then
        echo "[$(date +%F\ %T)] $d Self-test status: $status_line" >> "$LOG"
        # pokus o určení typu testu ze self-test logu
        test_type="unknown"
        if grep -qi 'Extended' "$tmp.st"; then test_type="long"; fi
        if grep -qi 'Short' "$tmp.st"; then test_type="short"; fi
        sf="$STATE_DIR/selftest_$(basename "$d").state"
        now=$(date +%s)
        if [[ -f "$sf" ]]; then
          start=$(awk -F= '/^start=/{print $2}' "$sf" 2>/dev/null || echo "$now")
          prev_type=$(awk -F= '/^type=/{print $2}' "$sf" 2>/dev/null || echo "$test_type")
          [[ -z "$start" ]] && start=$now
          elapsed=$(( now - start ))
          case "${prev_type:-$test_type}" in
            short) threshold=$((2*3600));;
            long)  threshold=$((24*3600));;
            *)     threshold=$((24*3600));;
          esac
          if (( elapsed > threshold )); then
            hours=$(( elapsed/3600 )); mins=$(( (elapsed%3600)/60 ))
            fail=1
            ISSUES+=("$d: Self-test appears stuck (type=${prev_type:-$test_type}, running ${hours}h ${mins}m). Consider abort: smartctl -X -d auto $d")
          fi
        else
          printf 'type=%s\nstart=%s\n' "$test_type" "$now" > "$sf" 2>/dev/null || true
        fi
      else
        sf="$STATE_DIR/selftest_$(basename "$d").state"
        rm -f "$sf" 2>/dev/null || true
      fi

      # Volitelné čekání na dokončení self-testu
      if $WAIT_FOR_COMPLETION && ( $RUN_LONG_TEST || $RUN_SHORT_TEST ); then
        log "Waiting for SATA/USB self-test to complete on $d ..."
        while :; do
          status_line="$(sudo smartctl -c -d auto "$d" 2>/dev/null | grep -i 'Self-test execution status' || true)"
          if [[ -z "$status_line" ]]; then
            status_line="$(sudo smartctl -c -d sat "$d" 2>/dev/null | grep -i 'Self-test execution status' || true)"
          fi
          echo "[$(date +%F\ %T)] $d status: $status_line" >> "$LOG"
          grep -qi 'in progress' <<<"$status_line" || break
          sleep 60
        done
        log "SATA/USB self-test finished on $d"
      fi
    fi

    # ŽIVOTNÍ ČÍTAČE – SATA
    if $DRY_RUN; then
      LIFE+=("$d: DRY RUN – SATA/USB")
    else
      # Power_Cycle_Count (ID 12) / fallback podle názvu
      pcycles="$(awk '$1==12 || $2=="Power_Cycle_Count"{print $NF}' <<<"$out" | tail -1)"
      [[ -z "$pcycles" ]] && pcycles="N/A"
      # Load_Cycle_Count (ID 193) / fallback
      lcc="$(awk '$1==193 || $2=="Load_Cycle_Count"{print $NF}' <<<"$out" | tail -1)"
      [[ -z "$lcc" ]] && lcc="N/A"
      # Start_Stop_Count (ID 4) – informativní
      ssc="$(awk '$1==4 || $2=="Start_Stop_Count"{print $NF}' <<<"$out" | tail -1)"
      [[ -n "$ssc" ]] && life_extra="; Start_Stop_Count=$ssc" || life_extra=""
      LIFE+=("$d: Power_Cycle_Count=$pcycles; Load_Cycle_Count=$lcc$life_extra")
    fi

    # Hodnocení stavu
    disk_issues=()
    if ! $DRY_RUN; then
      (( (rc & 2) != 0 )) && disk_issues+=("SMART health: predictive failure (rc&2)")
      line="$(grep -E 'Reallocated_Sector_Ct'    <<<"$out" | tail -1 || true)"; [[ "$line" =~ [^0-9]([1-9][0-9]*)$ ]] && disk_issues+=("$line")
      line="$(grep -E 'Current_Pending_Sector'   <<<"$out" | tail -1 || true)"; [[ "$line" =~ [^0-9]([1-9][0-9]*)$ ]] && disk_issues+=("$line")
      line="$(grep -E 'Offline_Uncorrectable'    <<<"$out" | tail -1 || true)"; [[ "$line" =~ [^0-9]([1-9][0-9]*)$ ]] && disk_issues+=("$line")
    fi
  fi

  if (( ${#disk_issues[@]} )); then
    fail=1
    ISSUES+=("$d: ${disk_issues[*]}")
  fi
  rm -f "$tmp"
done

# ŽIVOTNÍ ČÍTAČE – vždy před SUMMARY
echo "---- LIFE COUNTS ----" >> "$LOG"
for l in "${LIFE[@]}"; do echo "$l" >> "$LOG"; done
echo >> "$LOG"

# SUMMARY
echo "---- SUMMARY ----" >> "$LOG"
if (( fail )); then
  for i in "${ISSUES[@]}"; do echo "$i" >> "$LOG"; done
else
  echo "OK – žádné kritické indikátory." >> "$LOG"
fi
echo >> "$LOG"

# MAIL
sent_mail=false
if (( fail )); then
  log "STATUS: PROBLÉM – posílám e-mail"
  {
    echo "From: Vojta.Hamacek@seznam.cz"
    echo "To: $RECIPIENT"
    echo "Subject: [SMART ALERT] $HOST – problémy detekovány"
    echo "Content-Type: text/plain; charset=UTF-8"
    echo
    echo "---- LIFE COUNTS ----"
    for l in "${LIFE[@]}"; do echo "$l"; done
    echo
    echo "---- SUMMARY ----"
    for i in "${ISSUES[@]}"; do printf '%s\n' "$i"; done
    echo
    echo "---- FULL LOG ----"
    echo
    cat "$LOG"
  } | msmtp -C /home/vojrik/Scripts/Disck_checks/.msmtprc -a default "$RECIPIENT" && sent_mail=true || true
else
  log "STATUS: OK – e-mail se neposílá"
fi

# Vlastnictví logu a symlink na plochu – vždy ukazuj na aktuální zdroj
chown vojrik:vojrik "$LOG" 2>/dev/null || true
ln -sfn "$LOG" "/home/vojrik/Desktop/$LOG_NAME" 2>/dev/null || true
chown -h vojrik:vojrik "/home/vojrik/Desktop/$LOG_NAME" 2>/dev/null || true

# Jednotný závěrečný status
if (( fail )); then
  if $sent_mail; then
    echo "[$(date +%F\ %T)] STATUS: ALERT – e‑mail odeslán" >> "$LOG"
  else
    echo "[$(date +%F\ %T)] STATUS: ALERT – e‑mail se NEpodařilo odeslat" >> "$LOG"
  fi
else
  echo "[$(date +%F\ %T)] STATUS: OK – e‑mail se neposílá" >> "$LOG"
fi
