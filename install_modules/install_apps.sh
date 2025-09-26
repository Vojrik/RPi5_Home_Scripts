#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/lib.sh"

log "Installing desktop and monitoring applications"
export DEBIAN_FRONTEND=noninteractive

packages=(
  gnome-system-monitor
  git
  git-cola
  python3
  idle3
  s-tui
  htop
  stress
  terminator
  rsync
  mosquitto-clients
)

if command -v node >/dev/null 2>&1; then
  log "Node.js already present; skipping apt install"
else
  packages+=(nodejs)
fi

if command -v npm >/dev/null 2>&1; then
  log "npm already present; skipping apt install"
elif dpkg-query -W -f='${Version}\n' nodejs 2>/dev/null | grep -q 'nodesource'; then
  warn "NodeSource-provided nodejs detected; Debian npm package conflicts, skipping npm install"
else
  packages+=(npm)
fi

apt-get install -y "${packages[@]}"

if command -v npm >/dev/null 2>&1; then
  log "Installing optional @openai/codex via npm"
  if ! npm install -g @openai/codex; then
    warn "@openai/codex installation failed; continuing without optional package"
  fi
else
  warn "npm is not available; skipping installation of optional @openai/codex package"
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
