#!/usr/bin/env bash
# /home/vojrik/Scripts/Disck_checks/smart_daily.sh
set -Eeuo pipefail

export MSMTP_CONFIG=/home/vojrik/Scripts/Disck_checks/.msmtprc

RECIPIENT="Vojta.Hamacek@seznam.cz"
DESKTOP_LOG="/home/vojrik/Desktop/smart_daily.log"
RUN_SHORT_TEST=false

HOST="$(hostname)"
DATE_ISO="$(date -Is)"

: > "$DESKTOP_LOG"
log(){ echo "[$(date +%F\ %T)] $*" | tee -a "$DESKTOP_LOG"; }

ROOT_PART="$(findmnt -n -o SOURCE /)"
ROOT_BLK="/dev/$(lsblk -no pkname "$ROOT_PART")"
[[ "$ROOT_BLK" == "/dev/" ]] && ROOT_BLK="$ROOT_PART"

mapfile -t DISKS < <(lsblk -dpno NAME,TYPE | awk '$2=="disk"{print $1}' | grep -vE 'loop|zram' || true)

wake_disk() {
  local dev="$1" tries=10 state
  if [[ "$dev" =~ ^/dev/sd ]]; then
    while (( tries-- > 0 )); do
      state="$(sudo hdparm -C "$dev" 2>/dev/null | awk '/drive state/ {print $4}')"
      [[ "$state" == "active/idle" ]] && return 0
      sudo dd if="$dev" of=/dev/null bs=512 count=1 status=none 2>/dev/null || true
      sleep 5
    done
  fi
  return 0
}

log "SMART kontrola | host: $HOST | $DATE_ISO"
echo >> "$DESKTOP_LOG"

fail=0
declare -a ISSUES
declare -a LIFE     # životní čítače k přehledu

for d in "${DISKS[@]}"; do
  if [[ "$d" == "$ROOT_BLK" ]]; then
    log "SKIP systémový disk: $d"
    echo -e "==== $d ====\n(Skipped: system disk)\n" >> "$DESKTOP_LOG"
    continue
  fi

  wake_disk "$d"
  tmp="$(mktemp)"

  if [[ "$d" == /dev/nvme* ]]; then
    log "NVMe: $d"
    $RUN_SHORT_TEST && { set +e; sudo smartctl -t short "$d" >/dev/null 2>&1; set -e; }
    set +e; sudo smartctl -H -A -l error "$d" >"$tmp" 2>&1; rc=$?; set -e
    out="$(cat "$tmp")"
    echo -e "==== $d ====\n$out\n" >> "$DESKTOP_LOG"

    # ŽIVOTNÍ ČÍTAČE – NVMe
    nvme_pcycles="$(grep -E 'Power Cycles' <<<"$out" | awk -F: '{gsub(/^[ \t]+/,"",$2); print $2}' | awk '{print $1}' | tail -1)"
    [[ -z "$nvme_pcycles" ]] && nvme_pcycles="N/A"
    LIFE+=("$d: Power Cycles=$nvme_pcycles; Load/Unload=N/A")

    # Hodnocení stavu
    disk_issues=()
    (( (rc & 2) != 0 )) && disk_issues+=("SMART health: predictive failure (rc&2)")
    line="$(grep -E 'Media and Data Integrity Errors' <<<"$out" || true)"; [[ "$line" =~ ([1-9][0-9]*) ]] && disk_issues+=("$line")
    line="$(grep -E 'Percentage Used' <<<"$out" || true)";          [[ "$line" =~ ([8-9][0-9]|100)% ]] && disk_issues+=("$line")

  else
    log "SATA/USB: $d"
    $RUN_SHORT_TEST && { set +e; sudo smartctl -d auto -t short "$d" >/devnull 2>&1; set -e; } || true
    set +e; sudo smartctl -d auto -H -A -l error "$d" >"$tmp" 2>&1; rc=$?
    if (( rc != 0 )); then
      sudo smartctl -d sat  -H -A -l error "$d" >"$tmp" 2>&1; rc=$?
    fi
    set -e
    out="$(cat "$tmp")"
    echo -e "==== $d ====\n$out\n" >> "$DESKTOP_LOG"

    # ŽIVOTNÍ ČÍTAČE – SATA
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

    # Hodnocení stavu
    disk_issues=()
    (( (rc & 2) != 0 )) && disk_issues+=("SMART health: predictive failure (rc&2)")
    line="$(grep -E 'Reallocated_Sector_Ct'    <<<"$out" | tail -1 || true)"; [[ "$line" =~ [^0-9]([1-9][0-9]*)$ ]] && disk_issues+=("$line")
    line="$(grep -E 'Current_Pending_Sector'   <<<"$out" | tail -1 || true)"; [[ "$line" =~ [^0-9]([1-9][0-9]*)$ ]] && disk_issues+=("$line")
    line="$(grep -E 'Offline_Uncorrectable'    <<<"$out" | tail -1 || true)"; [[ "$line" =~ [^0-9]([1-9][0-9]*)$ ]] && disk_issues+=("$line")
  fi

  if (( ${#disk_issues[@]} )); then
    fail=1
    ISSUES+=("$d: ${disk_issues[*]}")
  fi
  rm -f "$tmp"
done

# ŽIVOTNÍ ČÍTAČE – vždy před SUMMARY
echo "---- LIFE COUNTS ----" >> "$DESKTOP_LOG"
for l in "${LIFE[@]}"; do echo "$l" >> "$DESKTOP_LOG"; done
echo >> "$DESKTOP_LOG"

# SUMMARY
echo "---- SUMMARY ----" >> "$DESKTOP_LOG"
if (( fail )); then
  for i in "${ISSUES[@]}"; do echo "$i" >> "$DESKTOP_LOG"; done
else
  echo "OK – žádné kritické indikátory." >> "$DESKTOP_LOG"
fi
echo >> "$DESKTOP_LOG"

# MAIL
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
    cat "$DESKTOP_LOG"
  } | msmtp -C /home/vojrik/Scripts/Disck_checks/.msmtprc -a default "$RECIPIENT" || true
else
  log "STATUS: OK – e-mail se neposílá"
fi
