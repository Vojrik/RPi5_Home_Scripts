#!/usr/bin/env bash
set -euo pipefail

LOG_TAG="i2c-guard"
WINDOW_MINUTES="${WINDOW_MINUTES:-2}"
TIMEOUT_THRESHOLD="${TIMEOUT_THRESHOLD:-8}"
I2C_DEVICE="${I2C_DEVICE:-1f00074000.i2c}"
REBOOT_ON_FAIL="${REBOOT_ON_FAIL:-0}"

count=$(journalctl -k --since "-${WINDOW_MINUTES} min" --no-pager \
  | grep -c "i2c_designware ${I2C_DEVICE}: controller timed out" || true)

if [ "$count" -lt "$TIMEOUT_THRESHOLD" ]; then
  exit 0
fi

logger -t "$LOG_TAG" "Detected ${count} i2c timeout events in ${WINDOW_MINUTES} min, starting recovery."

systemctl stop nas-ina219.service || true
systemctl stop rockpi-penta.service || true
sleep 1

if [ -w /sys/bus/platform/drivers/i2c_designware/unbind ] && [ -w /sys/bus/platform/drivers/i2c_designware/bind ]; then
  echo "${I2C_DEVICE}" > /sys/bus/platform/drivers/i2c_designware/unbind || true
  sleep 0.2
  echo "${I2C_DEVICE}" > /sys/bus/platform/drivers/i2c_designware/bind || true
fi

sleep 1
systemctl start rockpi-penta.service || true
systemctl start nas-ina219.service || true
sleep 5

if ! systemctl is-active --quiet rockpi-penta.service || ! systemctl is-active --quiet nas-ina219.service; then
  logger -t "$LOG_TAG" "Recovery failed (services not active)."
  if [ "$REBOOT_ON_FAIL" = "1" ]; then
    logger -t "$LOG_TAG" "Rebooting host due to persistent i2c failure."
    systemctl reboot
  fi
fi

