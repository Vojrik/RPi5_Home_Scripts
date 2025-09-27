#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/lib.sh"

if [[ $# -lt 1 ]]; then
  err "No directories specified for deployment"
  exit 1
fi

ensure_target_context

sync_tree() {
  local src="$1" dest="$2"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete "$src/" "$dest/"
  else
    local dest_parent backup tmp
    dest_parent=$(dirname "$dest")
    mkdir -p "$dest_parent"

    tmp=$(mktemp -d "${dest_parent}/.sync_tree_tmp.XXXXXX")
    if ! cp -a "$src/." "$tmp/"; then
      rm -rf "$tmp"
      return 1
    fi

    if [[ -e "$dest" ]]; then
      backup="${dest}.backup.$(date +%s).$$"
      if ! mv "$dest" "$backup"; then
        rm -rf "$tmp"
        return 1
      fi

      if mv "$tmp" "$dest"; then
        rm -rf "$backup"
      else
        mv "$backup" "$dest"
        rm -rf "$tmp"
        return 1
      fi
    else
      if ! mv "$tmp" "$dest"; then
        rm -rf "$tmp"
        return 1
      fi
    fi
  fi
}

deploy_directories() {
  local local_src dest

  for dir in "$@"; do
    local_src="$REPO_ROOT/$dir"
    if [[ ! -d "$local_src" ]]; then
      warn "Source directory $local_src not found; skipping"
      continue
    fi
    dest="$TARGET_SCRIPTS_DIR/$dir"
    log "Deploying $dir to $dest"
    mkdir -p "$dest"
    sync_tree "$local_src" "$dest"
    chown -R "$TARGET_USER":"$TARGET_USER" "$dest"
    find "$dest" -type f -name '*.sh' -exec chmod +x {} +
  done
}

deploy_directories "$@"
