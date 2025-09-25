#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/lib.sh"

CONFIG_FILE=/boot/firmware/config.txt
MODEL=$(tr -d '\0' </proc/device-tree/model || true)

if [[ -z "$MODEL" ]]; then
  warn "Unable to determine Raspberry Pi model; skipping overclock configuration"
  exit 0
fi

log "Detected model: $MODEL"

case "$MODEL" in
  *"Raspberry Pi 5"*)
    OC_BLOCK=$(cat <<'EOT'
# --- RPi Home Installer Overclock (RPi 5) ---
arm_freq=2800
arm_freq_min=600
arm_boost=0
force_turbo=0
gpu_freq=970
# --- End RPi Home Installer Overclock ---
EOT
)
    ;;
  *"Raspberry Pi 4"*)
    OC_BLOCK=$(cat <<'EOT'
# --- RPi Home Installer Overclock (RPi 4) ---
over_voltage=4
arm_freq=2000
gpu_freq=600
# --- End RPi Home Installer Overclock ---
EOT
)
    ;;
  *)
    warn "Model is not RPi 4 or RPi 5; no overclock changes applied"
    exit 0
    ;;
esac

if [[ ! -f "$CONFIG_FILE" ]]; then
  err "Configuration file $CONFIG_FILE not found"
  exit 1
fi

if grep -q "RPi Home Installer Overclock" "$CONFIG_FILE"; then
  warn "An RPi Home Installer overclock block already exists; leaving unchanged"
  exit 0
fi

log "Appending overclock configuration to $CONFIG_FILE"
printf '\n%s\n' "$OC_BLOCK" >> "$CONFIG_FILE"
