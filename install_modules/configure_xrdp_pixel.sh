#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/lib.sh"

log "Ensuring PIXEL desktop packages for XRDP"
export DEBIAN_FRONTEND=${DEBIAN_FRONTEND:-noninteractive}

PACKAGES=(
  raspberrypi-ui-mods
  lxde
  lxde-common
  lxde-core
  lxsession
)

apt-get update
apt-get install -y "${PACKAGES[@]}"

if ! command -v startlxde-pi >/dev/null 2>&1; then
  err "startlxde-pi is not available after package installation; PIXEL configuration cannot continue"
  exit 1
fi

target_user="${TARGET_USER:-}"
if [[ -z "$target_user" || "$target_user" == "root" ]]; then
  if [[ -n ${SUDO_USER:-} && ${SUDO_USER} != "root" ]]; then
    target_user="${SUDO_USER}"
  else
    target_user=$(awk -F: '$3 >= 1000 && $1 != "nobody" {print $1; exit}' /etc/passwd || true)
  fi
fi

if [[ -z "$target_user" || "$target_user" == "root" ]]; then
  warn "Unable to determine a non-root target user; skipping XRDP PIXEL configuration"
  exit 0
fi

target_home=$(getent passwd "$target_user" | cut -d: -f6)
if [[ -z "$target_home" || ! -d "$target_home" ]]; then
  warn "Home directory for user '$target_user' not found; skipping XRDP PIXEL configuration"
  exit 0
fi

xsession_file="$target_home/.xsession"
backup_suffix="backup-$(date +%Y%m%d-%H%M%S)"

if [[ -f "$xsession_file" ]]; then
  cp "$xsession_file" "$xsession_file.$backup_suffix"
  log "Existing .xsession backed up to $xsession_file.$backup_suffix"
fi

cat <<'XEOF' > "$xsession_file"
#!/bin/sh
export XDG_SESSION_TYPE=x11
export GDK_BACKEND=x11
export SDL_VIDEODRIVER=x11
exec /usr/bin/startlxde-pi
XEOF

chmod +x "$xsession_file"
chown "$target_user:$target_user" "$xsession_file"

log "Restarting xrdp service to apply PIXEL session configuration"
if systemctl list-unit-files xrdp.service >/dev/null 2>&1; then
  systemctl restart xrdp
else
  warn "xrdp.service not found; restart skipped"
fi

log "PIXEL desktop for XRDP configured for user $target_user"
