#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
MODULES_DIR="$SCRIPT_DIR/install_modules"
REPO_ROOT="$SCRIPT_DIR"
export REPO_ROOT

if [[ ! -d "$MODULES_DIR" ]] || [[ ! -f "$MODULES_DIR/lib.sh" ]]; then
  cat <<'EOM' >&2
Error: Required installer modules were not found next to install_rpi5_home.sh.

Download the entire repository before running this script, for example:
  git clone https://github.com/Vojrik/RPi5_Home_Scripts.git
  cd RPi5_Home_Scripts
  sudo ./install_rpi5_home.sh

Alternatively, copy the install_modules directory so it sits beside this script.
EOM
  exit 1
fi

source "$MODULES_DIR/lib.sh"
require_root

cat <<'EOM'
==============================================
RPi Home Installer
This workflow can perform the following steps:
  1) Detect Raspberry Pi model and apply the recommended overclock.
  2) Update the operating system (apt update/upgrade/autoremove).
  3) Install desktop, monitoring and development tools plus PiShrink.
  4) Deploy the Backup, CPU_freq and Fan script directories to the target user.
  5) Optionally deploy a Docker stack with Zigbee2MQTT, Mosquitto and Home Assistant (ZBT-1).
  6) Optionally deploy the home-automation-backup scripts.
==============================================
EOM

if prompt_yes_no "Run the base installation (steps 1-4)?" "Y"; then

  log "Starting base installation"
  "$MODULES_DIR/overclock.sh"
  "$MODULES_DIR/os_update.sh"
  "$MODULES_DIR/install_apps.sh"
  "$MODULES_DIR/deploy_scripts.sh" Backup CPU_freq Disck_checks Fan
  log "Base installation complete"
else
  warn "Base installation skipped by user"
fi

if prompt_yes_no "Install the Zigbee2MQTT + Mosquitto + Home Assistant Docker stack?" "N"; then
  "$MODULES_DIR/home_automation_stack.sh"
else
  log "Docker home automation stack skipped"
fi

if prompt_yes_no "Deploy the home-automation-backup scripts?" "Y"; then
  "$MODULES_DIR/deploy_scripts.sh" home-automation-backup
else
  log "home-automation-backup deployment skipped"
fi

log "Installer run finished"
