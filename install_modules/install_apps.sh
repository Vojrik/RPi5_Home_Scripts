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

apt-get install -y "${packages[@]}"

if command -v node >/dev/null 2>&1; then
  log "Detected existing Node.js version $(node --version 2>/dev/null || echo 'unknown')"
else
  log "Node.js not found; installing latest release"
fi

log "Configuring NodeSource Node.js repository for the latest release"
apt-get install -y ca-certificates curl gnupg
mkdir -p /etc/apt/keyrings
curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
  | gpg --dearmor --batch --yes -o /etc/apt/keyrings/nodesource.gpg
if [[ -f /etc/os-release ]]; then
  # shellcheck disable=SC1091
  source /etc/os-release
fi
nodesource_channel="node_current.x"
distro_codename=${VERSION_CODENAME:-${UBUNTU_CODENAME:-nodistro}}
cat <<EOF >/etc/apt/sources.list.d/nodesource.list
deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/${nodesource_channel} ${distro_codename} main
EOF
apt-get update
apt-get install -y nodejs npm
log "Node.js updated to $(node --version 2>/dev/null || echo 'unknown version')"

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
