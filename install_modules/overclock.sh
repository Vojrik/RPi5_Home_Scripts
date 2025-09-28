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

PROMPT_PI4=false

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
    PROMPT_PI4=true
    OC_BLOCK=$(cat <<'EOT'
# --- RPi Home Installer Overclock (RPi 4) ---
over_voltage=5
arm_freq=2000
gpu_freq=650
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

if [[ "$PROMPT_PI4" == true ]]; then
  if [[ -n ${RPi_HOME_PI4_OC:-} ]]; then
    if [[ ${RPi_HOME_PI4_OC} =~ ^([Yy][Ee]?[Ss]?|1|true|TRUE)$ ]]; then
      log "Applying Raspberry Pi 4 overclock as requested via RPi_HOME_PI4_OC"
    else
      warn "Skipping Raspberry Pi 4 overclock (RPi_HOME_PI4_OC=${RPi_HOME_PI4_OC})"
      exit 0
    fi
  elif [[ ! -t 0 ]]; then
    warn "Skipping Raspberry Pi 4 overclock (non-interactive session, defaulting to No)"
    exit 0
  else
    prompt_message=$'Apply the Raspberry Pi 4 overclock profile?\nCPU: 2000 MHz    GPU: 650 MHz    over_voltage: 5'
    if ! prompt_yes_no "$prompt_message" "N"; then
      warn "Skipping Raspberry Pi 4 overclock per user choice"
      exit 0
    fi
    unset prompt_message
  fi
fi

if grep -q "RPi Home Installer Overclock" "$CONFIG_FILE"; then
  log "Removing existing RPi Home Installer overclock block from $CONFIG_FILE"
  perl -0pi -e 's/\n?# --- RPi Home Installer Overclock.*?# --- End RPi Home Installer Overclock ---\n?/\n/sg' "$CONFIG_FILE"
fi

log "Appending overclock configuration to $CONFIG_FILE"
printf '\n%s\n' "$OC_BLOCK" >> "$CONFIG_FILE"

if [[ "$PROMPT_PI4" == true ]]; then
  if [[ -x "$SCRIPT_DIR/configure_xrdp_pixel.sh" ]]; then
    log "Configuring XRDP PIXEL desktop for Raspberry Pi 4"
    ensure_target_context
    TARGET_USER="${TARGET_USER:-}" "$SCRIPT_DIR/configure_xrdp_pixel.sh"
  else
    warn "configure_xrdp_pixel.sh is missing; skipping XRDP PIXEL setup"
  fi
fi
