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
  xrdp
  rpi-imager
  gparted
  snapd
  gsmartcontrol
  gimp
  xpdf
)

apt-get install -y "${packages[@]}"

installed_node_version="not installed"

if command -v node >/dev/null 2>&1; then
  installed_node_version=$(node --version 2>/dev/null || echo "vunknown")
  log "Detected existing Node.js version ${installed_node_version}"
else
  log "Node.js not found; preparing to install the latest Node.js release from NodeSource"
fi

apt-get install -y ca-certificates curl gnupg
mkdir -p /etc/apt/keyrings
nodesource_key_tmp=$(mktemp)
nodesource_key_path="/etc/apt/keyrings/nodesource.gpg"
nodesource_key_ready=false

if curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key -o "${nodesource_key_tmp}"; then
  if gpg --dearmor --batch --yes -o "${nodesource_key_path}" "${nodesource_key_tmp}"; then
    nodesource_key_ready=true
  else
    warn "Failed to process NodeSource GPG key"
  fi
else
  warn "Failed to download NodeSource GPG key"
fi
rm -f "${nodesource_key_tmp}"

if [[ -f /etc/os-release ]]; then
  # shellcheck disable=SC1091
  source /etc/os-release
fi

if [[ ${nodesource_key_ready} == true ]]; then
  distro_codename=${VERSION_CODENAME:-${UBUNTU_CODENAME:-nodistro}}
  nodesource_channels=(node_current.x node_23.x node_22.x node_21.x node_20.x)
  nodesource_list="/etc/apt/sources.list.d/nodesource.list"
  nodesource_setup_success=false
  selected_channel=""

  for channel in "${nodesource_channels[@]}"; do
    log "Attempting to configure NodeSource repository channel ${channel}"
    cat <<EOF >"${nodesource_list}"
deb [signed-by=${nodesource_key_path}] https://deb.nodesource.com/${channel} ${distro_codename} main
EOF
    if apt-get update; then
      nodesource_setup_success=true
      selected_channel=${channel}
      break
    fi
    warn "Failed to refresh package lists from NodeSource channel ${channel}; trying next available channel"
    rm -f "${nodesource_list}"
  done

  if [[ ${nodesource_setup_success} == true ]]; then
    log "Using NodeSource channel ${selected_channel} to install the latest Node.js packages"
    apt-get install -y nodejs npm
    log "Node.js updated to $(node --version 2>/dev/null || echo 'unknown version')"
  else
    warn "Unable to configure any NodeSource repository; skipping Node.js upgrade"
  fi
else
  warn "Skipping Node.js upgrade because the NodeSource GPG key could not be prepared"
fi

if command -v npm >/dev/null 2>&1; then
  log "Installing optional @openai/codex via npm"
  if ! npm install -g @openai/codex; then
    warn "@openai/codex installation failed; continuing without optional package"
  fi
else
  warn "npm is not available; skipping installation of optional @openai/codex package"
fi

if command -v snap >/dev/null 2>&1; then
  if command -v systemctl >/dev/null 2>&1; then
    if ! systemctl is-active --quiet snapd; then
      if ! systemctl enable --now snapd; then
        warn "Unable to start snapd service automatically; snap installations may fail"
      fi
    fi
  fi
  if ! snap install gdu-disk-usage-analyzer; then
    warn "Failed to install gdu-disk-usage-analyzer via snap"
  fi
else
  warn "snap command not available; skipping installation of gdu-disk-usage-analyzer"
fi

pi_apps_installer="/tmp/pi-apps-installer.sh"
if curl -fsSL https://pi-apps.io/install -o "${pi_apps_installer}"; then
  if bash "${pi_apps_installer}"; then
    log "Pi-Apps installer completed successfully"
  else
    warn "Pi-Apps installer returned a non-zero exit status"
  fi
  rm -f "${pi_apps_installer}"
else
  warn "Failed to download Pi-Apps installer script"
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
