#!/usr/bin/env bash
set -euo pipefail

# Spin down all present SATA disks that match /dev/sd[a-z].
for dev in /dev/sd[a-z]; do
  if [ -b "$dev" ]; then
    /usr/sbin/hdparm -y "$dev" >/dev/null 2>&1 || true
  fi
done
