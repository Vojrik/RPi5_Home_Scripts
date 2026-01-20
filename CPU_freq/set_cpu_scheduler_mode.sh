#!/bin/sh
set -eu

if [ $# -lt 1 ]; then
  echo "Usage: $0 {auto|high|low}" >&2
  exit 2
fi

mode=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')

case "$mode" in
  auto) target="auto" ;;
  high) target="force-high" ;;
  low) target="force-low" ;;
  *)
    echo "Invalid scheduler mode: $1" >&2
    exit 2
    ;;
esac

exec /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py mode "$target"
