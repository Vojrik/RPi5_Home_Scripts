#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/lib.sh"

log "Installing desktop and monitoring applications"
export DEBIAN_FRONTEND=noninteractive
apt-get install -y \
  gnome-system-monitor \
  git \
  git-cola \
  python3 \
  idle3 \
  s-tui \
  htop \
  stress \
  terminator \
  nodejs \
  npm \
  rsync \
  mosquitto-clients

if command -v npm >/dev/null 2>&1; then
  log "Installing @openai/codex via npm"
  npm install -g @openai/codex
else
  warn "npm is not available; skipping installation of @openai/codex"
fi

if [[ ! -d /opt/pishrink ]]; then
  log "Cloning PiShrink into /opt/pishrink"
  git clone https://github.com/Drewsif/PiShrink /opt/pishrink
else
  log "Updating existing PiShrink repository"
  git -C /opt/pishrink pull --ff-only
fi

if [[ ! -L /usr/local/bin/pishrink ]]; then
  ln -sf /opt/pishrink/pishrink.sh /usr/local/bin/pishrink
fi
log "Application installation complete"
