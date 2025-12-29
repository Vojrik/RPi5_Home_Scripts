#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH=""

detect_config_path() {
  if [[ -f /boot/firmware/config.txt ]]; then
    CONFIG_PATH="/boot/firmware/config.txt"
    return
  fi
  if [[ -f /boot/config.txt ]]; then
    CONFIG_PATH="/boot/config.txt"
    return
  fi
  echo "Could not find /boot/firmware/config.txt or /boot/config.txt" >&2
  exit 1
}

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "Please run as root (sudo)." >&2
    exit 1
  fi
}

line_present() {
  local line="$1"
  grep -q -E "^[[:space:]]*${line//\//\\/}[[:space:]]*$" "$CONFIG_PATH"
}

get_last_value() {
  local key="$1"
  awk -v k="$key" '
    $0 ~ "^[[:space:]]*#" { next }
    $0 ~ "^[[:space:]]*" k { val=$0 }
    END { if (val != "") print val }
  ' "$CONFIG_PATH"
}

get_last_value_suffix() {
  local key="$1"
  local line
  line="$(get_last_value "$key")"
  if [[ -z "$line" ]]; then
    echo ""
    return
  fi
  echo "${line#*=}"
}

remove_lines_starting_with() {
  local prefix="$1"
  local tmp
  tmp="$(mktemp)"
  awk -v p="$prefix" '
    $0 ~ "^[[:space:]]*#" { print; next }
    $0 ~ "^[[:space:]]*" p { next }
    { print }
  ' "$CONFIG_PATH" > "$tmp"
  mv "$tmp" "$CONFIG_PATH"
}

replace_or_append() {
  local key="$1"
  local value="$2"
  local tmp
  tmp="$(mktemp)"
  awk -v k="$key" -v v="$value" '
    BEGIN { done=0 }
    $0 ~ "^[[:space:]]*#" { print; next }
    $0 ~ "^[[:space:]]*" k {
      if (!done) { print v; done=1 }
      next
    }
    { print }
    END { if (!done) print v }
  ' "$CONFIG_PATH" > "$tmp"
  mv "$tmp" "$CONFIG_PATH"
}

toggle_dtoverlay() {
  local overlay="$1"
  if line_present "dtoverlay=${overlay}"; then
    remove_lines_starting_with "dtoverlay=${overlay}"
    echo "Enabled ${overlay#disable-}."
  else
    printf '\n%s\n' "dtoverlay=${overlay}" >> "$CONFIG_PATH"
    echo "Disabled ${overlay#disable-}."
  fi
}

set_hdmi() {
  local mode="$1"
  if [[ "$mode" == "off" ]]; then
    replace_or_append "hdmi_blanking=" "hdmi_blanking=2"
    echo "HDMI disabled."
  else
    replace_or_append "hdmi_blanking=" "hdmi_blanking=0"
    echo "HDMI enabled."
  fi
}

set_led() {
  local mode="$1"
  if [[ "$mode" == "off" ]]; then
    replace_or_append "dtparam=act_led_trigger=" "dtparam=act_led_trigger=none"
    replace_or_append "dtparam=act_led_activelow=" "dtparam=act_led_activelow=on"
    echo "Activity LED disabled."
  else
    replace_or_append "dtparam=act_led_trigger=" "dtparam=act_led_trigger=mmc0"
    replace_or_append "dtparam=act_led_activelow=" "dtparam=act_led_activelow=off"
    echo "Activity LED enabled."
  fi
}

set_power_led() {
  local mode="$1"
  if [[ "$mode" == "off" ]]; then
    replace_or_append "dtparam=pwr_led_trigger=" "dtparam=pwr_led_trigger=none"
    replace_or_append "dtparam=pwr_led_activelow=" "dtparam=pwr_led_activelow=on"
    echo "Power LED disabled."
  else
    replace_or_append "dtparam=pwr_led_trigger=" "dtparam=pwr_led_trigger=default-on"
    replace_or_append "dtparam=pwr_led_activelow=" "dtparam=pwr_led_activelow=off"
    echo "Power LED enabled."
  fi
}

get_state_hdmi() {
  local v
  v="$(get_last_value_suffix "hdmi_blanking=")"
  if [[ "$v" == "2" ]]; then
    echo "off"
  elif [[ "$v" == "0" ]]; then
    echo "on"
  else
    echo "unknown"
  fi
}

get_state_overlay() {
  local overlay="$1"
  if line_present "dtoverlay=${overlay}"; then
    echo "off"
  else
    echo "on"
  fi
}

get_state_activity_led() {
  local v
  v="$(get_last_value_suffix "dtparam=act_led_trigger=")"
  if [[ "$v" == "none" ]]; then
    echo "off"
  elif [[ -n "$v" ]]; then
    echo "on"
  else
    echo "unknown"
  fi
}

get_state_power_led() {
  local v
  v="$(get_last_value_suffix "dtparam=pwr_led_trigger=")"
  if [[ "$v" == "none" ]]; then
    echo "off"
  elif [[ -n "$v" ]]; then
    echo "on"
  else
    echo "unknown"
  fi
}

prompt_restart() {
  echo
  read -r -p "Restart now to apply changes? [y/N] " answer
  case "${answer:-}" in
    y|Y|yes|YES)
      reboot
      ;;
    *)
      echo "Restart later to apply changes."
      ;;
  esac
}

show_menu() {
  local hdmi_state
  local bt_state
  local wifi_state
  local act_led_state
  local pwr_led_state
  hdmi_state="$(get_state_hdmi)"
  bt_state="$(get_state_overlay "disable-bt")"
  wifi_state="$(get_state_overlay "disable-wifi")"
  act_led_state="$(get_state_activity_led)"
  pwr_led_state="$(get_state_power_led)"
  cat <<EOF
Power saving menu
1) Toggle HDMI on/off (current: ${hdmi_state})
2) Toggle Bluetooth on/off (current: ${bt_state})
3) Toggle Wi-Fi on/off (current: ${wifi_state})
4) Toggle Activity LED on/off (current: ${act_led_state})
5) Toggle Power LED on/off (current: ${pwr_led_state})
6) Exit
EOF
}

main() {
  require_root
  detect_config_path
  echo "Using config: $CONFIG_PATH"
  while true; do
    show_menu
    read -r -p "Choose an option: " choice
    case "$choice" in
      1)
        if line_present "hdmi_blanking=2"; then
          set_hdmi on
        else
          set_hdmi off
        fi
        prompt_restart
        ;;
      2)
        toggle_dtoverlay "disable-bt"
        prompt_restart
        ;;
      3)
        toggle_dtoverlay "disable-wifi"
        prompt_restart
        ;;
      4)
        if line_present "dtparam=act_led_trigger=none"; then
          set_led on
        else
          set_led off
        fi
        prompt_restart
        ;;
      5)
        if line_present "dtparam=pwr_led_trigger=none"; then
          set_power_led on
        else
          set_power_led off
        fi
        prompt_restart
        ;;
      6)
        exit 0
        ;;
      *)
        echo "Invalid choice."
        ;;
    esac
  done
}

main "$@"
