#!/usr/bin/env bash
set -Eeuo pipefail

# --- Helpers ---------------------------------------------------------------
log()  { printf "\033[1;32m[INFO]\033[0m %s\n" "$1"; }
warn() { printf "\033[1;33m[WARN]\033[0m %s\n" "$1"; }
err()  { printf "\033[1;31m[ERR ]\033[0m %s\n" "$1"; }

require_root() {
  if [[ $EUID -ne 0 ]]; then
    err "This installer must be run as root (sudo)."
    exit 1
  fi
}

prompt_default() {
  local __var="$1" __prompt="$2" __default="$3" __input
  read -r -p "${__prompt} [${__default}]: " __input
  printf -v "$__var" '%s' "${__input:-$__default}"
}

prompt_required() {
  local __var="$1" __prompt="$2" __input
  while true; do
    read -r -p "${__prompt}: " __input
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
    read -r -s -p "${__prompt}: " __input
    echo
    if [[ -n "$__input" ]]; then
      printf -v "$__var" '%s' "$__input"
      return
    fi
    warn "Value cannot be empty."
  done
}

ensure_line_in_file() {
  local file="$1" line="$2"
  grep -qxF "$line" "$file" 2>/dev/null && return 0
  printf '\n%s\n' "$line" >> "$file"
}

replace_in_files() {
  local search="$1" replace="$2" dir="$3"
  local -a patterns=("*.sh" "*.py" "*.service" "*.txt" "*.md" "*.conf" "*.template" "*.ini")
  find "$dir" -type f \( $(printf -- '-name %q -o ' "${patterns[@]}") -false \) -print0 \
    | xargs -0 -r perl -pi -e "s|\Q${search}\E|${replace}|g"
}

replace_literal_in_files() {
  local search="$1" replace="$2" dir="$3"
  local -a patterns=("*.sh" "*.py" "*.service" "*.txt" "*.md" "*.conf" "*.template" "*.ini")
  find "$dir" -type f \( $(printf -- '-name %q -o ' "${patterns[@]}") -false \) -print0 \
    | xargs -0 -r perl -pi -e "s|\Q${search}\E|${replace}|g"
}

systemd_enable() {
  local unit="$1"; shift || true
  systemctl daemon-reload
  if systemctl enable --now "$unit"; then
    log "Enabled service $unit"
  else
    warn "Failed to enable $unit (check logs)."
  fi
}

sync_tree() {
  local src="$1" dest="$2"; shift 2 || true
  mkdir -p "$dest"
  rsync -a --exclude '__pycache__' "$@" "$src/" "$dest/"
}

# --- Main -----------------------------------------------------------------
require_root

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DEFAULT_USER=${SUDO_USER:-}
if [[ -z "$DEFAULT_USER" || "$DEFAULT_USER" == "root" ]]; then
  DEFAULT_USER=$(awk -F: '$3 >= 1000 && $1 != "nobody" {print $1; exit}' /etc/passwd)
fi
prompt_default TARGET_USER "Target username" "$DEFAULT_USER"

if ! getent passwd "$TARGET_USER" >/dev/null; then
  err "User '$TARGET_USER' does not exist."
  exit 1
fi

TARGET_HOME=$(getent passwd "$TARGET_USER" | cut -d: -f6)
TARGET_SCRIPTS_DIR="$TARGET_HOME/Scripts"
mkdir -p "$TARGET_SCRIPTS_DIR"

prompt_default BACKUP_DEST "Backup destination for home-automation backups" "$TARGET_HOME/Desktop/md0/_RPi5_Home_OS/Apps_Backups"
prompt_default HA_CONFIG_DIR "Home Assistant configuration directory" "$TARGET_HOME/homeassistant"
prompt_default OCTOPRINT_BIN "OctoPrint CLI path" "$TARGET_HOME/OctoPrint/venv/bin/octoprint"
prompt_default Z2M_DATA_DIR "Zigbee2MQTT data directory" "/opt/home-automation/zigbee2mqtt/data"
prompt_default MQTT_PASS_FILE "MQTT password file" "/opt/home-automation/credentials/mqtt_password.txt"
prompt_default HA_TOKEN_FILE "Home Assistant long-lived token file" "/opt/home-automation/credentials/ha_long_lived_token.txt"

log "Configure email for disk health alerts"
prompt_default SMTP_HOST "SMTP host" "smtp.example.com"
prompt_default SMTP_PORT "SMTP port" "465"
prompt_default SMTP_FROM "Sender e-mail" "alerts@example.com"
prompt_default SMTP_USER "SMTP username" "$SMTP_FROM"
prompt_default SMTP_USE_TLS "Use TLS (on/off)" "on"
prompt_default SMTP_STARTTLS "Use STARTTLS (on/off)" "off"
prompt_required SMTP_RECIPIENT "Recipient e-mail"
prompt_secret SMTP_PASSWORD "SMTP password"

APT_PACKAGES=(
  smartmontools
  mdadm
  hdparm
  msmtp
  msmtp-mta
  rsync
  python3
  python3-pip
  python3-venv
  python3-dev
  python3-setuptools
  python3-smbus
  python3-rpi.gpio
  i2c-tools
  git
  curl
  docker.io
  libatlas-base-dev
  libjpeg-dev
  libfreetype6-dev
  libtiff5
  libopenjp2-7
  zlib1g-dev
)

log "Installing apt packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y "${APT_PACKAGES[@]}"

# --- Copy directories -----------------------------------------------------
log "Syncing script directories to $TARGET_SCRIPTS_DIR"

sync_tree "$REPO_ROOT/Backup" "$TARGET_SCRIPTS_DIR/Backup"
sync_tree "$REPO_ROOT/CPU_freq" "$TARGET_SCRIPTS_DIR/CPU_freq"
sync_tree "$REPO_ROOT/Fan" "$TARGET_SCRIPTS_DIR/Fan"
sync_tree "$REPO_ROOT/home-automation-backup" "$TARGET_SCRIPTS_DIR/home-automation-backup"
sync_tree "$REPO_ROOT/rockpi-penta" "$TARGET_SCRIPTS_DIR/rockpi-penta"
sync_tree "$REPO_ROOT/Disck_checks" "$TARGET_SCRIPTS_DIR/Disck_checks" --exclude '.msmtprc' --exclude '.msmtp.pass' --exclude '.msmtp.log'

# Replace hard-coded paths and usernames
replace_in_files "/home/vojrik" "$TARGET_HOME" "$TARGET_SCRIPTS_DIR"
replace_literal_in_files "vojrik" "$TARGET_USER" "$TARGET_SCRIPTS_DIR"

# Ensure scripts executable
find "$TARGET_SCRIPTS_DIR" -type f -name '*.sh' -exec chmod +x {} +
find "$TARGET_SCRIPTS_DIR" -type f -name '*.py' -exec chmod +x {} +

chown -R "$TARGET_USER:$TARGET_USER" "$TARGET_SCRIPTS_DIR"

# --- Backup module --------------------------------------------------------
log "Configuring Backup module"
ln -sf "$TARGET_SCRIPTS_DIR/Backup/rpi_backup_pishrink.sh" /usr/local/bin/rpi_backup_pishrink
if ! command -v pishrink.sh >/dev/null; then
  log "Downloading pishrink.sh"
  curl -fsSL https://raw.githubusercontent.com/Drewsif/PiShrink/master/pishrink.sh -o /usr/local/bin/pishrink.sh
  chmod +x /usr/local/bin/pishrink.sh
fi

# --- CPU scheduler --------------------------------------------------------
log "Setting up cpu-scheduler service"
cat >/etc/systemd/system/cpu-scheduler.service <<EOF
[Unit]
Description=Raspberry Pi CPU scheduler
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 $TARGET_SCRIPTS_DIR/CPU_freq/cpu-scheduler.py start
User=root
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

systemd_enable cpu-scheduler.service

# --- Disk checks ----------------------------------------------------------
log "Configuring disk health monitoring"
DISCK_DIR="$TARGET_SCRIPTS_DIR/Disck_checks"

cat >"$DISCK_DIR/.msmtprc" <<EOF
defaults
auth on
tls $SMTP_USE_TLS
tls_starttls $SMTP_STARTTLS
tls_trust_file /etc/ssl/certs/ca-certificates.crt
logfile $DISCK_DIR/.msmtp.log

account primary
host $SMTP_HOST
port $SMTP_PORT
from $SMTP_FROM
user $SMTP_USER
passwordeval "cat $DISCK_DIR/.msmtp.pass"

account default : primary
EOF

printf '%s\n' "$SMTP_PASSWORD" >"$DISCK_DIR/.msmtp.pass"
chmod 600 "$DISCK_DIR/.msmtp.pass" "$DISCK_DIR/.msmtprc"
chown "$TARGET_USER:$TARGET_USER" "$DISCK_DIR/.msmtp.pass" "$DISCK_DIR/.msmtprc"
touch "$DISCK_DIR/.msmtp.log"
chown "$TARGET_USER:$TARGET_USER" "$DISCK_DIR/.msmtp.log"

for f in smart_daily.sh raid_watch.sh raid_check.sh daily_checks.sh; do
  perl -pi -e "s/RECIPIENT=\".*?\"/RECIPIENT=\"$SMTP_RECIPIENT\"/" "$DISCK_DIR/$f" 2>/dev/null || true
  perl -pi -e "s|MSMTP_CONFIG=.*|MSMTP_CONFIG=$DISCK_DIR/.msmtprc|" "$DISCK_DIR/$f" 2>/dev/null || true
done

mkdir -p /var/log/Disck_checks
chown "$TARGET_USER:$TARGET_USER" /var/log/Disck_checks

cat >/etc/cron.d/disck_checks <<EOF
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

0 19 * * * root nice -n 10 ionice -c3 $DISCK_DIR/smart_daily.sh >/tmp/smart_daily.cron.log 2>&1; nice -n 10 ionice -c3 $DISCK_DIR/raid_watch.sh >/tmp/raid_watch.cron.log 2>&1
50 17 * * 2 root nice -n 10 ionice -c3 $DISCK_DIR/smart_daily.sh --short >/tmp/smart_short.cron.log 2>&1
30 18 * * 2 root [ \$(date +\%d) -le 7 ] && nice -n 10 ionice -c3 $DISCK_DIR/smart_daily.sh --long >/tmp/smart_long.cron.log 2>&1
0 8 * * 2 root [ \$(date +\%d) -le 7 ] && nice -n 10 ionice -c3 $DISCK_DIR/raid_check.sh >/tmp/raid_check.cron.log 2>&1
EOF
chmod 644 /etc/cron.d/disck_checks
chown root:root /etc/cron.d/disck_checks

# --- Fan control ----------------------------------------------------------
log "Configuring PWM fan control"
cat >/etc/systemd/system/fanctrl.service <<EOF
[Unit]
Description=PWM Fan Control
After=multi-user.target

[Service]
Type=simple
User=root
ExecStart=/usr/bin/python3 $TARGET_SCRIPTS_DIR/Fan/fan_ctrl_CPU.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

BOOT_CONFIG=/boot/firmware/config.txt
if [[ ! -f "$BOOT_CONFIG" ]]; then
  BOOT_CONFIG=/boot/config.txt
fi
if [[ -f "$BOOT_CONFIG" ]]; then
  ensure_line_in_file "$BOOT_CONFIG" "dtoverlay=pwm,pwmchip=0,pwmchannel=3,pin=19"
else
  warn "Unable to find /boot config file; add dtoverlay manually."
fi

systemd_enable fanctrl.service

# --- Home automation backup ----------------------------------------------
log "Configuring home automation backup"
AUTO_BACKUP_DIR="$TARGET_SCRIPTS_DIR/home-automation-backup"
perl -pi -e "s|^BACKUP_DIR=.*|BACKUP_DIR=\"$BACKUP_DEST\"|" "$AUTO_BACKUP_DIR/backup_home_automation.sh"
perl -pi -e "s|^HA_SRC=.*|HA_SRC=\"$HA_CONFIG_DIR\"|" "$AUTO_BACKUP_DIR/backup_home_automation.sh"
perl -pi -e "s|^Z2M_SRC=.*|Z2M_SRC=\"$Z2M_DATA_DIR\"|" "$AUTO_BACKUP_DIR/backup_home_automation.sh"
perl -pi -e "s|^MQTT_PASS_FILE=.*|MQTT_PASS_FILE=\"$MQTT_PASS_FILE\"|" "$AUTO_BACKUP_DIR/backup_home_automation.sh"
perl -pi -e "s|^OCTOPRINT_BIN=.*|OCTOPRINT_BIN=\"$OCTOPRINT_BIN\"|" "$AUTO_BACKUP_DIR/backup_home_automation.sh"
perl -pi -e "s|^HA_TOKEN_FILE=.*|HA_TOKEN_FILE=\"$HA_TOKEN_FILE\"|" "$AUTO_BACKUP_DIR/backup_home_automation.sh"

mkdir -p "$BACKUP_DEST" "$BACKUP_DEST/homeassistant" "$BACKUP_DEST/zigbee2mqtt" "$BACKUP_DEST/octoprint"
chown -R "$TARGET_USER:$TARGET_USER" "$BACKUP_DEST"

touch /var/log/home_automation_backup.log
chown "$TARGET_USER:$TARGET_USER" /var/log/home_automation_backup.log

cat >/etc/cron.d/home_automation_backup <<EOF
# Daily backup of Home Assistant stack
1 19 * * * root $AUTO_BACKUP_DIR/backup_home_automation.sh >/var/log/home_automation_backup.log 2>&1
EOF
chmod 644 /etc/cron.d/home_automation_backup
chown root:root /etc/cron.d/home_automation_backup

# --- RockPi Penta ---------------------------------------------------------
log "Installing RockPi Penta OLED service"
ROCKPI_DIR="$TARGET_SCRIPTS_DIR/rockpi-penta"
python3 -m venv "$ROCKPI_DIR/.venv"
"$ROCKPI_DIR/.venv/bin/python" -m pip install --upgrade pip wheel
"$ROCKPI_DIR/.venv/bin/pip" install --upgrade -r "$ROCKPI_DIR/requirements.txt"

cat >/etc/systemd/system/rockpi-penta.service <<EOF
[Unit]
Description=Rockpi SATA HAT
After=local-fs.target
Wants=local-fs.target

[Service]
Type=simple
ExecStartPre=/usr/sbin/modprobe i2c_bcm2835
ExecStartPre=/usr/sbin/modprobe i2c-dev
ExecStartPre=/bin/sleep 0.2
ExecStart=$ROCKPI_DIR/.venv/bin/python $ROCKPI_DIR/main.py
WorkingDirectory=$ROCKPI_DIR
Restart=always
RestartSec=2
StartLimitIntervalSec=30
StartLimitBurst=10
StandardOutput=journal
StandardError=journal
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF

cat >/etc/rockpi-penta.conf <<'EOF'
[fan]
lv0 = 35
lv1 = 40
lv2 = 45
lv3 = 50

[key]
click = slider
twice = switch
press = none

[time]
twice = 0.7
press = 1.8

[slider]
auto = true
time = 10

[oled]
rotate = false
f-temp = false
EOF

cat >/etc/rockpi-penta.env <<'EOF'
SDA=SDA
SCL=SCL
OLED_RESET=D23
BUTTON_CHIP=4
BUTTON_LINE=17
FAN_CHIP=4
FAN_LINE=27
HARDWARE_PWM=0
EOF

systemd_enable rockpi-penta.service

# --- Ownership cleanup ----------------------------------------------------
chown -R "$TARGET_USER:$TARGET_USER" "$TARGET_SCRIPTS_DIR"

log "Installation complete. Review systemctl statuses and cron jobs as needed."
