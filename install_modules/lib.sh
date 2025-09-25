#!/usr/bin/env bash
set -Eeuo pipefail

log()  { printf "\033[1;32m[INFO]\033[0m %s\n" "$1"; }
warn() { printf "\033[1;33m[WARN]\033[0m %s\n" "$1"; }
err()  { printf "\033[1;31m[ERR ]\033[0m %s\n" "$1"; }

require_root() {
  if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
    err "This installer must be run with sudo/root privileges."
    exit 1
  fi
}

prompt_yes_no() {
  local prompt="$1" default="${2:-Y}" answer
  local default_hint
  if [[ "$default" =~ ^[Yy]$ ]]; then
    default_hint="Y/n"
  else
    default_hint="y/N"
  fi
  read -r -p "${prompt} [${default_hint}]: " answer || true
  answer=${answer:-$default}
  [[ "$answer" =~ ^[Yy]$ ]]
}

prompt_default() {
  local __var="$1" __prompt="$2" __default="$3" __input
  read -r -p "${__prompt} [${__default}]: " __input || true
  printf -v "$__var" '%s' "${__input:-$__default}"
}

prompt_required() {
  local __var="$1" __prompt="$2" __input
  while true; do
    read -r -p "${__prompt}: " __input || true
    if [[ -n "$__input" ]]; then
      printf -v "$__var" '%s' "$__input"
      return
    fi
    warn "Value cannot be empty."
  done
}

prompt_secret() {
  local __var="$1" __prompt="$2" __input
  while true; do
    read -r -s -p "${__prompt}: " __input || true
    echo
    if [[ -n "$__input" ]]; then
      printf -v "$__var" '%s' "$__input"
      return
    fi
    warn "Value cannot be empty."
  done
}

ensure_command() {
  local cmd="$1" package_hint="${2:-}";
  if ! command -v "$cmd" >/dev/null 2>&1; then
    if [[ -n "$package_hint" ]]; then
      err "Required command '$cmd' not found. Install package '$package_hint' and retry."
    else
      err "Required command '$cmd' not found on PATH."
    fi
    exit 1
  fi
}

ensure_target_context() {
  if [[ -n ${TARGET_USER:-} && -n ${TARGET_HOME:-} && -n ${TARGET_SCRIPTS_DIR:-} ]]; then
    return
  fi

  local default_user="${SUDO_USER:-}" passwd_entry
  if [[ -z "$default_user" || "$default_user" == "root" ]]; then
    passwd_entry=$(awk -F: '$3 >= 1000 && $1 != "nobody" {print $1; exit}' /etc/passwd)
    default_user=${passwd_entry:-pi}
  fi

  prompt_default TARGET_USER "Target username" "$default_user"

  if ! getent passwd "$TARGET_USER" >/dev/null; then
    err "User '$TARGET_USER' does not exist."
    exit 1
  fi

  TARGET_HOME=$(getent passwd "$TARGET_USER" | cut -d: -f6)
  local default_scripts_dir="$TARGET_HOME/Scripts"

  prompt_default TARGET_SCRIPTS_DIR "Which directory should store the repository scripts?" "$default_scripts_dir"

  mkdir -p "$TARGET_SCRIPTS_DIR"
  export TARGET_USER TARGET_HOME TARGET_SCRIPTS_DIR
}

