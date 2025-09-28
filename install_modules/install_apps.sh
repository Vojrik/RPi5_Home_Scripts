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

ensure_stui_desktop_entry() {
  local desktop_file="/usr/share/applications/s-tui.desktop"
  local desktop_contents
  read -r -d '' desktop_contents <<'EOF'
[Desktop Entry]
Name=s-tui
Comment=Terminal-based system monitor
Exec=s-tui
Terminal=true
Type=Application
Categories=System;Utility;
Keywords=monitor;cpu;stress;
Icon=utilities-system-monitor
EOF

  if [[ ! -f "$desktop_file" ]] || ! cmp -s <(printf '%s\n' "$desktop_contents") "$desktop_file"; then
    log "Refreshing s-tui desktop entry at $desktop_file"
    printf '%s\n' "$desktop_contents" >"$desktop_file"
  else
    log "s-tui desktop entry already up to date"
  fi

  chmod 0644 "$desktop_file"
}

determine_primary_user() {
  local user="${TARGET_USER:-}" home="${TARGET_HOME:-}"

  if [[ -z "$user" ]]; then
    if [[ -n ${SUDO_USER:-} && ${SUDO_USER} != "root" ]]; then
      user="${SUDO_USER}"
    fi
  fi

  if [[ -z "$user" ]]; then
    user=$(awk -F: '$3 >= 1000 && $1 != "nobody" {print $1; exit}' /etc/passwd)
  fi

  if [[ -n "$user" && -z "$home" ]]; then
    home=$(getent passwd "$user" | cut -d: -f6)
  fi

  if [[ -n "$user" && -n "$home" ]]; then
    printf '%s\n%s\n' "$user" "$home"
  fi
}

deploy_stui_shortcut_to_desktop() {
  local user home
  mapfile -t user_home < <(determine_primary_user)

  if (( ${#user_home[@]} != 2 )); then
    warn "Unable to determine target user for s-tui desktop shortcut"
    return
  fi

  user="${user_home[0]}"
  home="${user_home[1]}"
  local desktop_dir="$home/Desktop"
  local desktop_link="$desktop_dir/s-tui.desktop"

  mkdir -p "$desktop_dir"
  if [[ ! -f "$desktop_link" ]]; then
    log "Placing s-tui desktop shortcut for user $user"
    cp /usr/share/applications/s-tui.desktop "$desktop_link"
  else
    log "s-tui desktop shortcut already exists at $desktop_link"
  fi

  chmod 0755 "$desktop_link"
  chown "$user":"$user" "$desktop_link" 2>/dev/null || true
}

ensure_stui_desktop_entry
deploy_stui_shortcut_to_desktop

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
nodesource_key_urls=(
  "https://deb.nodesource.com/gpgkey/nodesource.gpg.key"
  "https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key"
)

for key_url in "${nodesource_key_urls[@]}"; do
  if curl -fsSL "$key_url" -o "${nodesource_key_tmp}"; then
    if gpg --dearmor --batch --yes -o "${nodesource_key_path}" "${nodesource_key_tmp}"; then
      nodesource_key_ready=true
      log "Prepared NodeSource GPG key from $key_url"
      break
    else
      warn "Failed to process NodeSource GPG key from $key_url"
    fi
  else
    warn "Failed to download NodeSource GPG key from $key_url"
  fi
done

rm -f "${nodesource_key_tmp}"

if [[ -f /etc/os-release ]]; then
  # shellcheck disable=SC1091
  source /etc/os-release
fi

if [[ ${nodesource_key_ready} == true ]]; then
  distro_codename="$(get_nodesource_codename)"
  nodesource_channels=(node_20.x node_18.x)
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
    apt-get install -y nodejs
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
  if ! snap list snapd >/dev/null 2>&1; then
    if ! snap install snapd; then
      warn "Failed to install snapd management snap; snap installations may fail"
    fi
  fi
  if ! snap install gdu-disk-usage-analyzer; then
    warn "Failed to install gdu-disk-usage-analyzer via snap"
  fi
else
  warn "snap command not available; skipping installation of gdu-disk-usage-analyzer"
fi

pi_apps_installer="/tmp/pi-apps-installer.sh"
pi_apps_urls=(
  "https://pi-apps.io/install"
  "https://pi-apps.io/install/"
  "https://raw.githubusercontent.com/Botspot/pi-apps/master/install"
)
pi_apps_downloaded=false
for pi_apps_url in "${pi_apps_urls[@]}"; do
  if curl -fsSL "$pi_apps_url" -o "${pi_apps_installer}"; then
    if head -n1 "${pi_apps_installer}" | grep -q '^#!'; then
      pi_apps_downloaded=true
      log "Downloaded Pi-Apps installer from $pi_apps_url"
      break
    fi
  fi
done

if [[ ${pi_apps_downloaded} == true ]]; then
  pi_apps_user=""
  if [[ -n ${TARGET_USER:-} && ${TARGET_USER} != "root" ]]; then
    pi_apps_user="${TARGET_USER}"
  elif [[ -n ${SUDO_USER:-} && ${SUDO_USER} != "root" ]]; then
    pi_apps_user="${SUDO_USER}"
  fi

  if [[ -n ${pi_apps_user} ]]; then
    if sudo -u "${pi_apps_user}" bash "${pi_apps_installer}"; then
      log "Pi-Apps installer completed successfully for user ${pi_apps_user}"
    else
      warn "Pi-Apps installer returned a non-zero exit status for user ${pi_apps_user}"
    fi
  else
    warn "Pi-Apps installer requires a non-root user but none could be determined"
  fi
else
  warn "Failed to download a valid Pi-Apps installer script"
fi
rm -f "${pi_apps_installer}"

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
