#!/bin/sh
set -eu

if [ $# -lt 1 ]; then
  echo "Usage: $0 {auto|normal|silent|0..100|0..100%|duty:NN}" >&2
  exit 2
fi

value=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')
override_file="/run/fan_override"

case "$value" in
  auto)
    rm -f "$override_file"
    exit 0
    ;;
  normal|silent)
    printf '%s\n' "$value" > "$override_file"
    exit 0
    ;;
esac

value=${value#duty:}
value=${value%\%}

case "$value" in
  ''|*[!0-9]*)
    echo "Invalid fan override value: $1" >&2
    exit 2
    ;;
esac

if [ "$value" -gt 100 ]; then
  value=100
fi

printf 'duty:%s\n' "$value" > "$override_file"
