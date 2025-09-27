#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/lib.sh"

log "Updating and upgrading the operating system"
export DEBIAN_FRONTEND=noninteractive

if [[ -f /etc/os-release ]]; then
  # shellcheck disable=SC1091
  source /etc/os-release
fi

nodesource_codename="$(get_nodesource_codename)"

normalize_nodesource_distribution() {
  local codename="$1" file updated_any=false
  local -a repo_files=(/etc/apt/sources.list /etc/apt/sources.list.d/*.list)

  for file in "${repo_files[@]}"; do
    [[ -f "$file" ]] || continue
    if grep -qE '^[[:space:]]*deb(-src)?\s+(\[[^]]*\]\s*)?https://deb\.nodesource\.com/' "$file"; then
      if sed -E -i "s|(deb(-src)?\s+(\[[^]]*\]\s*)?https://deb\\.nodesource\\.com/[^[:space:]]+\s+)[^[:space:]]+|\\1${codename}|g" "$file"; then
        updated_any=true
      else
        warn "Failed to update NodeSource distribution in $file"
      fi
    fi
  done

  if [[ ${updated_any} == true ]]; then
    log "Ensured NodeSource repositories target distribution '${codename}'"
  fi
}

normalize_nodesource_distribution "${nodesource_codename}"

repair_docker_apt_key() {
  local repo_search_paths=(/etc/apt/sources.list /etc/apt/sources.list.d/*.list)
  local repo_files=()

  for path in "${repo_search_paths[@]}"; do
    for file in $path; do
      [[ -f "$file" ]] || continue
      if grep -q "download\.docker\.com" "$file"; then
        repo_files+=("$file")
      fi
    done
  done

  if [[ ${#repo_files[@]} -eq 0 ]]; then
    return 1
  fi

  if ! command -v curl >/dev/null 2>&1; then
    warn "curl command is required to repair Docker repository key but is not available"
    return 1
  fi
  if ! command -v gpg >/dev/null 2>&1; then
    warn "gpg command is required to repair Docker repository key but is not available"
    return 1
  fi

  local key_download_url="https://download.docker.com/linux/debian/gpg"
  local repaired_any=false

  for repo in "${repo_files[@]}"; do
    while IFS= read -r line; do
      [[ "$line" =~ download\.docker\.com ]] || continue

      local key_path=""
      if [[ "$line" =~ signed-by=([^][]+) ]]; then
        key_path="${BASH_REMATCH[1]}"
        key_path="${key_path%%]*}"
      else
        key_path="/etc/apt/keyrings/docker.gpg"
      fi

      local key_dir
      key_dir="$(dirname "$key_path")"
      install -m 0755 -d "$key_dir"

      local tmp_file
      tmp_file="${key_path}.tmp"
      rm -f "$tmp_file"
      if curl -fsSL "$key_download_url" | gpg --dearmor --batch --yes -o "$tmp_file"; then
        mv "$tmp_file" "$key_path"
        chmod a+r "$key_path"
        repaired_any=true
      else
        rm -f "$tmp_file"
        warn "Failed to refresh Docker repository key at $key_path"
      fi
    done <"$repo"
  done

  if [[ "$repaired_any" == true ]]; then
    log "Refreshed Docker repository GPG key"
    return 0
  fi

  return 1
}

if ! apt-get update; then
  warn "apt-get update failed; attempting to refresh Docker repository signing key"
  if repair_docker_apt_key; then
    log "Retrying apt-get update after repairing repository key"
    apt-get update
  else
    err "apt-get update failed and Docker repository key could not be refreshed automatically"
    exit 1
  fi
fi

apt-get -y upgrade
apt-get -y autoremove
log "System packages updated"
