#!/usr/bin/env bash
set -euo pipefail

main() {
  local repo_root
  repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

  local install_dir="/home/vojrik/Scripts/rpi_cameras"
  local etc_dir="/etc/camera-streamer"
  local systemd_dir="/etc/systemd/system"

  sudo install -d -m 0755 "${install_dir}"
  sudo install -m 0755 "${repo_root}/soft-stream.py" "${install_dir}/soft-stream.py"
  sudo install -m 0755 "${repo_root}/measure_fps.py" "${install_dir}/measure_fps.py"
  sudo install -m 0644 "${repo_root}/README.md" "${install_dir}/README.md"

  sudo install -d -m 0755 "${etc_dir}"
  sudo install -m 0644 "${repo_root}/systemd/camera-soft-stream.env" "${etc_dir}/camera-soft-stream.env"

  for unit in camera-soft-cam0.service camera-soft-cam1.service; do
    sudo install -m 0644 "${repo_root}/systemd/${unit}" "${systemd_dir}/${unit}"
  done

  sudo systemctl daemon-reload
  sudo systemctl enable --now camera-soft-cam0.service camera-soft-cam1.service
}

main "$@"
