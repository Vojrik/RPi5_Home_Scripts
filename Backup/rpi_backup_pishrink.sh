#!/usr/bin/env bash
# rpi_backup_pishrink.sh
set -Eeuo pipefail

# --- Nastavení ---
SRC_DEV="/dev/sda"   # výchozí; bude přepsáno autodetekcí, pokud neuvedeš --src
DEST_DIR="/mnt/md0/_RPi5_Home_OS"
NAME_PREFIX="RPi5_Home"
LOG_DIR="${DEST_DIR}/_logs"
ASK_CONFIRM=true
DRY_RUN=false

usage() {
  cat <<EOF
Použití: sudo $(basename "$0") [--src /dev/sdX] [--dest DIR] [--prefix NAME] [--yes] [--dry-run]
EOF
}

# označíme, zda uživatel zadal --src
SRC_SET=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --src) SRC_DEV="$2"; SRC_SET=true; shift 2;;
    --dest) DEST_DIR="$2"; shift 2;;
    --prefix) NAME_PREFIX="$2"; shift 2;;
    --yes) ASK_CONFIRM=false; shift;;
    --dry-run) DRY_RUN=true; shift;;
    -h|--help) usage; exit 0;;
    *) echo "Neznámý parametr: $1"; usage; exit 1;;
  esac
done

mkdir -p "$DEST_DIR" "$LOG_DIR"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"

require_tool() { command -v "$1" >/dev/null 2>&1 || { echo "Chybí $1"; exit 2; }; }
require_tool dd
require_tool lsblk
require_tool findmnt
require_tool awk
require_tool blockdev
require_tool pishrink.sh

# --- Autodetekce zdrojového zařízení (pokud uživatel nezadal --src) ---
detect_root_parent() {
  local src parent
  src="$(findmnt -no SOURCE /)"                        # /dev/sda2 | /dev/mmcblk0p2 | /dev/nvme0n1p2 | /dev/mapper/...
  parent="$(lsblk -no PKNAME "$src" 2>/dev/null)"      # sda | mmcblk0 | nvme0n1 | prázdné pokud mapper bez PKNAME
  if [[ -z "$parent" ]]; then
    # Pokusíme se najít nadřazený "disk" v řetězci
    parent="$(lsblk -no NAME,TYPE "$(readlink -f "$src")" | awk '$2=="disk"{print $1; exit}')"
  fi
  [[ -n "$parent" ]] || { echo "Nelze zjistit rodič root zařízení."; exit 8; }
  printf '/dev/%s\n' "$parent"
}

if [[ "$SRC_SET" == false ]]; then
  SRC_DEV="$(detect_root_parent)"
fi

[[ -b "$SRC_DEV" ]] || { echo "Zdroj není blokové zařízení: $SRC_DEV"; exit 3; }
[[ -w "$DEST_DIR" ]] || { echo "Cílový adresář není zapisovatelný: $DEST_DIR"; exit 4; }

# --- Zjištění poslední verze ---
shopt -s nullglob
existing=( "$DEST_DIR"/"${NAME_PREFIX}"_v*.img )
max_major=0; max_minor=0
for f in "${existing[@]}"; do
  bn="$(basename "$f")"
  if [[ "$bn" =~ ${NAME_PREFIX}_v([0-9]+)\.([0-9]+)\.img$ ]]; then
    M="${BASH_REMATCH[1]}"; m="${BASH_REMATCH[2]}"
    if (( M > max_major || (M == max_major && m > max_minor) )); then
      max_major=$M; max_minor=$m
    fi
  fi
done
next_major=$max_major; next_minor=$((max_minor + 1))
suggest="${next_major}.${next_minor}"
echo "Nalezeno poslední: v${max_major}.${max_minor}  → návrh další: v${suggest}"

# --- Volba verze (Enter / M/m / x.y) ---
echo
echo "Zvol verzi:"
echo "  [Enter]  malá verze v${suggest}"
echo "  M/m      velká verze v$((max_major+1)).0"
echo "  x.y      ručně, např. 3.0 nebo 2.2"
read -r -p "Volba: " choice || true
choice_lc="$(printf '%s' "${choice:-}" | tr '[:upper:]' '[:lower:]')"

case "${choice_lc:-}" in
  "" ) ver="$suggest" ;;
  m|major ) ver="$((max_major+1)).0" ;;
  *.* )
    [[ "$choice_lc" =~ ^([0-9]+)\.([0-9]+)$ ]] || { echo "Neplatný formát verze."; exit 5; }
    ver="$choice_lc"
    ;;
  * ) echo "Neplatná volba."; exit 5 ;;
esac

IMG_PATH="${DEST_DIR}/${NAME_PREFIX}_v${ver}.img"
LOG_PATH="${LOG_DIR}/${NAME_PREFIX}_v${ver}_${TIMESTAMP}.log"
[[ -e "$IMG_PATH" ]] && { echo "Cíl již existuje: $IMG_PATH"; exit 6; }

echo
echo "Souhrn:"
echo "  Zdroj:   $SRC_DEV  (detekováno z /, pokud nebylo zadáno --src)"
echo "  Cíl IMG: $IMG_PATH"
echo "  Log:     $LOG_PATH"
echo "  Verze:   v${ver}"
echo
lsblk -o NAME,MODEL,SIZE,MOUNTPOINT,FSTYPE "$SRC_DEV" || true
echo

if $ASK_CONFIRM; then
  read -r -p "Pokračovat? [y/N]: " ack || true
  [[ "$ack" =~ ^[Yy]$ ]] || { echo "Zrušeno."; exit 7; }
fi

# --- Nabídka promazání logů ---
read -r -p "Chceš pročistit logy před zálohou? [y/N]: " cleanlogs || true
if [[ "$cleanlogs" =~ ^[Yy]$ ]]; then
  echo "Mazání starých logů..."
  sudo rm -f /var/log/*.gz /var/log/*.[0-9] /var/log/*/*.gz /var/log/*/*.[0-9] 2>/dev/null || true
  sudo truncate -s 0 /var/log/*.log /var/log/*/*.log 2>/dev/null || true
  sudo journalctl --vacuum-size=200M || true
fi

# --- Odhad místa ---
src_size_bytes=$(blockdev --getsize64 "$SRC_DEV")
dest_free_bytes=$(
  LC_ALL=C df -B1 --output=avail "$DEST_DIR" | awk 'NR==2{printf "%d\n",$1}'
)
if (( dest_free_bytes < src_size_bytes )); then
  echo "Varování: může být málo místa pro RAW image."
fi

run() {
  echo "+ $*"
  if $DRY_RUN; then return 0; fi
  { "$@"; } 2>&1 | tee -a "$LOG_PATH"
}

echo "Log: $LOG_PATH"
echo "Start: $(date -Is)" | tee -a "$LOG_PATH"

# --- Krok 1: RAW image ---
run dd if="$SRC_DEV" of="$IMG_PATH" bs=4M conv=fsync status=progress

# --- Krok 2: PiShrink ---
run pishrink.sh -s "$IMG_PATH"

echo "Hotovo: $(date -Is)" | tee -a "$LOG_PATH"
echo "Výsledek: $IMG_PATH" | tee -a "$LOG_PATH"

# --- Dotaz na balení ---
read -r -p "Chceš image zabalit do 7z? [y/N]: " dozip || true
if [[ "$dozip" =~ ^[Yy]$ ]]; then
  if command -v 7z >/dev/null 2>&1; then
    SEV_PATH="${IMG_PATH%.img}.7z"
    echo "Balení do 7z: $SEV_PATH" | tee -a "$LOG_PATH"
    if ! $DRY_RUN; then
      7z a -mx=9 "$SEV_PATH" "$IMG_PATH" | tee -a "$LOG_PATH"
    fi
  else
    echo "7z není nainstalován. Přeskočeno." | tee -a "$LOG_PATH"
  fi
fi

echo "Konec. Log: $LOG_PATH"
