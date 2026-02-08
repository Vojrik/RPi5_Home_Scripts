#!/usr/bin/env bash
set -euo pipefail

LOG_TAG="i2c-guard"
WINDOW_MINUTES="${WINDOW_MINUTES:-2}"
TIMEOUT_THRESHOLD="${TIMEOUT_THRESHOLD:-8}"
I2C_DEVICE="${I2C_DEVICE:-1f00074000.i2c}"
COOLDOWN_SEC="${COOLDOWN_SEC:-1800}"
STATE_DIR="/run/i2c-guard"
COOLDOWN_FILE="${STATE_DIR}/nas_ina219_cooldown_until"

mkdir -p "${STATE_DIR}"

now_epoch="$(date +%s)"
cooldown_until=0
if [ -f "${COOLDOWN_FILE}" ]; then
  cooldown_until="$(cat "${COOLDOWN_FILE}" 2>/dev/null || echo 0)"
fi

count=$(journalctl -k --since "-${WINDOW_MINUTES} min" --no-pager \
  | grep -c "i2c_designware ${I2C_DEVICE}: controller timed out" || true)

if [ "${count}" -ge "${TIMEOUT_THRESHOLD}" ]; then
  logger -t "$LOG_TAG" "Detected ${count} i2c timeouts in ${WINDOW_MINUTES} min; disabling nas-ina219 for ${COOLDOWN_SEC}s cooldown."
  timeout 8 systemctl stop nas-ina219.service || true
  echo $((now_epoch + COOLDOWN_SEC)) > "${COOLDOWN_FILE}"
  exit 0
fi

if [ "${now_epoch}" -lt "${cooldown_until}" ]; then
  timeout 8 systemctl stop nas-ina219.service || true
  exit 0
fi

if [ "${cooldown_until}" -gt 0 ] && systemctl is-active --quiet rockpi-penta.service; then
  logger -t "$LOG_TAG" "Cooldown finished and OLED is active; starting nas-ina219 again."
  timeout 8 systemctl start nas-ina219.service || true
  rm -f "${COOLDOWN_FILE}"
fi
