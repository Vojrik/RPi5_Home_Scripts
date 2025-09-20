#!/usr/bin/env bash
# rpi_backup_pishrink.sh
set -Eeuo pipefail

# --- Settings ---
SRC_DEV="/dev/sda"   # default; overwritten by auto-detection unless --src is provided
DEST_DIR="/mnt/md0/_RPi5_Home_OS"
NAME_PREFIX="RPi5_Home"
LOG_DIR="${DEST_DIR}/_logs"
ASK_CONFIRM=true
DRY_RUN=false

usage() {
  cat <<EOF
Usage: sudo $(basename "$0") [--src /dev/sdX] [--dest DIR] [--prefix NAME] [--yes] [--dry-run]
EOF
}

# Track whether the user provided --src
SRC_SET=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --src) SRC_DEV="$2"; SRC_SET=true; shift 2;;
    --dest) DEST_DIR="$2"; shift 2;;
    --prefix) NAME_PREFIX="$2"; shift 2;;
    --yes) ASK_CONFIRM=false; shift;;
    --dry-run) DRY_RUN=true; shift;;
    -h|--help) usage; exit 0;;
    *) echo "Unknown parameter: $1"; usage; exit 1;;
  esac
done

mkdir -p "$DEST_DIR" "$LOG_DIR"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"

require_tool() { command -v "$1" >/dev/null 2>&1 || { echo "$1 is missing"; exit 2; }; }
require_tool dd
require_tool lsblk
require_tool findmnt
require_tool awk
require_tool blockdev
require_tool pishrink.sh

# --- Auto-detect source device (when --src is not provided) ---
detect_root_parent() {
  local src parent
  src="$(findmnt -no SOURCE /)"                        # /dev/sda2 | /dev/mmcblk0p2 | /dev/nvme0n1p2 | /dev/mapper/...
  parent="$(lsblk -no PKNAME "$src" 2>/dev/null)"      # sda | mmcblk0 | nvme0n1 | empty if the mapper has no PKNAME
  if [[ -z "$parent" ]]; then
    # Try to find the parent "disk" higher in the chain
    parent="$(lsblk -no NAME,TYPE "$(readlink -f "$src")" | awk '$2=="disk"{print $1; exit}')"
  fi
  [[ -n "$parent" ]] || { echo "Unable to identify the parent device for root."; exit 8; }
  printf '/dev/%s\n' "$parent"
}

if [[ "$SRC_SET" == false ]]; then
  SRC_DEV="$(detect_root_parent)"
fi

[[ -b "$SRC_DEV" ]] || { echo "Source is not a block device: $SRC_DEV"; exit 3; }
[[ -w "$DEST_DIR" ]] || { echo "Destination directory is not writable: $DEST_DIR"; exit 4; }

# --- Determine the most recent version ---
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
echo "Last found: v${max_major}.${max_minor}  → suggested next: v${suggest}"

# --- Volba verze (Enter / M/m / x.y) ---
echo
echo "Select the version number:"
echo "  [Enter]  minor release v${suggest}"
echo "  M/m      bump major version to v$((max_major+1)).0"
echo "  x.y      manual entry, e.g. 3.0 or 2.2"
read -r -p "Choice: " choice || true
choice_lc="$(printf '%s' "${choice:-}" | tr '[:upper:]' '[:lower:]')"

case "${choice_lc:-}" in
  "" ) ver="$suggest" ;;
  m|major ) ver="$((max_major+1)).0" ;;
  *.* )
    [[ "$choice_lc" =~ ^([0-9]+)\.([0-9]+)$ ]] || { echo "Invalid version format."; exit 5; }
    ver="$choice_lc"
    ;;
  * ) echo "Invalid choice."; exit 5 ;;
esac

IMG_PATH="${DEST_DIR}/${NAME_PREFIX}_v${ver}.img"
LOG_PATH="${LOG_DIR}/${NAME_PREFIX}_v${ver}_${TIMESTAMP}.log"
[[ -e "$IMG_PATH" ]] && { echo "Destination already exists: $IMG_PATH"; exit 6; }

echo
echo "Summary:"
echo "  Source:  $SRC_DEV  (auto-detected from / unless --src was provided)"
echo "  Target:  $IMG_PATH"
echo "  Log:     $LOG_PATH"
echo "  Version: v${ver}"
echo
lsblk -o NAME,MODEL,SIZE,MOUNTPOINT,FSTYPE "$SRC_DEV" || true
echo

if $ASK_CONFIRM; then
  read -r -p "Continue? [y/N]: " ack || true
  [[ "$ack" =~ ^[Yy]$ ]] || { echo "Cancelled."; exit 7; }
fi

# --- Optional log cleanup ---
read -r -p "Purge logs before the backup? [y/N]: " cleanlogs || true
if [[ "$cleanlogs" =~ ^[Yy]$ ]]; then
  echo "Removing old logs..."
  sudo rm -f /var/log/*.gz /var/log/*.[0-9] /var/log/*/*.gz /var/log/*/*.[0-9] 2>/dev/null || true
  sudo truncate -s 0 /var/log/*.log /var/log/*/*.log 2>/dev/null || true
  sudo journalctl --vacuum-size=200M || true
fi

# --- Space estimation ---
src_size_bytes=$(blockdev --getsize64 "$SRC_DEV")
dest_free_bytes=$(
  LC_ALL=C df -B1 --output=avail "$DEST_DIR" | awk 'NR==2{printf "%d\n",$1}'
)
if (( dest_free_bytes < src_size_bytes )); then
  echo "Warning: there may not be enough space for the raw image."
fi

run() {
  echo "+ $*"
  if $DRY_RUN; then return 0; fi
  { "$@"; } 2>&1 | tee -a "$LOG_PATH"
}

echo "Log: $LOG_PATH"
echo "Start: $(date -Is)" | tee -a "$LOG_PATH"

# --- Step 1: raw image ---
run dd if="$SRC_DEV" of="$IMG_PATH" bs=4M conv=fsync status=progress

# --- Step 2: PiShrink ---
run pishrink.sh -s "$IMG_PATH"

echo "Done: $(date -Is)" | tee -a "$LOG_PATH"
echo "Result: $IMG_PATH" | tee -a "$LOG_PATH"

# --- Optional archive step ---
read -r -p "Compress the image into 7z? [y/N]: " dozip || true
if [[ "$dozip" =~ ^[Yy]$ ]]; then
  if command -v 7z >/dev/null 2>&1; then
    SEV_PATH="${IMG_PATH%.img}.7z"
    echo "Creating 7z archive: $SEV_PATH" | tee -a "$LOG_PATH"
    if ! $DRY_RUN; then
      7z a -mx=9 "$SEV_PATH" "$IMG_PATH" | tee -a "$LOG_PATH"
    fi
  else
    echo "7z is not installed. Skipping." | tee -a "$LOG_PATH"
  fi
fi

echo "Finished. Log: $LOG_PATH"
