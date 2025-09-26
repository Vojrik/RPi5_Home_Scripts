#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/lib.sh"

log "Preparing Docker-based home automation stack"
export DEBIAN_FRONTEND=noninteractive

log "Installing prerequisite packages for the home automation stack"
if ! apt-get update; then
  warn "apt-get update failed; continuing with existing package indexes"
fi
apt-get install -y ca-certificates curl gnupg mosquitto-clients

install_docker_from_distro() {
  log "Attempting to install Docker from distribution packages (docker.io)"
  if apt-get install -y docker.io docker-compose-plugin; then
    log "Docker installed from distribution repositories"
    return 0
  fi
  warn "Failed to install docker.io package from distribution repositories"
  return 1
}

setup_docker_repository() {
  log "Configuring Docker APT repository"
  install -m 0755 -d /etc/apt/keyrings
  if ! curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg; then
    warn "Failed to download Docker GPG key"
    return 1
  fi
  chmod a+r /etc/apt/keyrings/docker.gpg
  local codename architecture repo_file
  architecture=$(dpkg --print-architecture)
  codename=$(awk -F= '$1=="VERSION_CODENAME"{print $2}' /etc/os-release)
  if [[ -z "$codename" ]]; then
    warn "Unable to detect Debian codename; skipping Docker repository configuration"
    return 1
  fi
  repo_file="/etc/apt/sources.list.d/docker.list"
  echo "deb [arch=${architecture} signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian ${codename} stable" > "$repo_file"
  if ! apt-get update; then
    warn "apt-get update failed after adding Docker repository"
    rm -f "$repo_file" /etc/apt/keyrings/docker.gpg
    return 1
  fi
  return 0
}

install_docker_from_official_repo() {
  log "Attempting to install Docker from Docker's official APT repository"
  if setup_docker_repository && apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin; then
    log "Docker installed from Docker's official repository"
    return 0
  fi
  warn "Failed to install Docker from Docker's official repository"
  return 1
}

install_docker_offline() {
  local offline_dir="$SCRIPT_DIR/offline"
  log "Looking for offline Docker installer in ${offline_dir}"
  local installer="${offline_dir}/docker-install.sh"
  if [[ -x "$installer" ]]; then
    "$installer"
    log "Docker installed using offline installer"
    return 0
  fi
  warn "Offline installer script not found at ${installer}"
  return 1
}

if ! command -v docker >/dev/null 2>&1; then
  install_docker_from_distro || install_docker_from_official_repo || install_docker_offline || {
    err "Docker engine installation failed; please install Docker manually and re-run the installer"
    exit 1
  }
else
  log "Docker binary already present; skipping engine installation"
fi

ensure_command docker docker.io
systemctl enable --now docker

COMPOSE_CMD="docker compose"
if ! docker compose version >/dev/null 2>&1; then
  warn "docker compose plugin not found; attempting to install docker-compose-plugin package"
  if apt-get install -y docker-compose-plugin; then
    COMPOSE_CMD="docker compose"
  else
    warn "docker-compose-plugin package unavailable; falling back to docker-compose"
    apt-get install -y docker-compose
    if command -v docker-compose >/dev/null 2>&1; then
      COMPOSE_CMD="docker-compose"
    else
      err "Neither docker compose plugin nor docker-compose binary is available."
    fi
  fi
fi

STACK_DIR_DEFAULT="/opt/home-automation"
prompt_default STACK_DIR "Installation directory for the Docker stack" "$STACK_DIR_DEFAULT"
mkdir -p "$STACK_DIR"
cd "$STACK_DIR"

prompt_default ZIGBEE_ADAPTER "Path to Zigbee adapter (ZBT-1) device" "/dev/ttyACM0"
prompt_required MQTT_USERNAME "MQTT username"
prompt_secret MQTT_PASSWORD "MQTT password"
prompt_default HA_TIMEZONE "System timezone" "$(cat /etc/timezone 2>/dev/null || echo 'Europe/Prague')"

MOSQUITTO_CONFIG_DIR="$STACK_DIR/mosquitto/config"
MOSQUITTO_DATA_DIR="$STACK_DIR/mosquitto/data"
Z2M_DATA_DIR="$STACK_DIR/zigbee2mqtt"
HA_CONFIG_DIR="$STACK_DIR/homeassistant"

mkdir -p "$MOSQUITTO_CONFIG_DIR" "$MOSQUITTO_DATA_DIR" "$Z2M_DATA_DIR" "$HA_CONFIG_DIR"

cat > "$MOSQUITTO_CONFIG_DIR/mosquitto.conf" <<EOC
persistence true
persistence_location /mosquitto/data/
log_timestamp true
allow_anonymous false
password_file /mosquitto/config/passwordfile
listener 1883 0.0.0.0
listener 9001 0.0.0.0
protocol websockets
EOC

ensure_command mosquitto_passwd mosquitto-clients
mosquitto_passwd -b -c "$MOSQUITTO_CONFIG_DIR/passwordfile" "$MQTT_USERNAME" "$MQTT_PASSWORD"

cat > "$Z2M_DATA_DIR/configuration.yaml" <<EOC
homeassistant: true
permit_join: false
mqtt:
  base_topic: zigbee2mqtt
  server: mqtt://mosquitto:1883
  user: $MQTT_USERNAME
  password: $MQTT_PASSWORD
serial:
  port: $ZIGBEE_ADAPTER
advanced:
  log_level: info
frontend:
  port: 8080
EOC

cat > "$STACK_DIR/docker-compose.yml" <<EOC
version: "3.9"
services:
  mosquitto:
    image: eclipse-mosquitto:2
    restart: unless-stopped
    ports:
      - "1883:1883"
      - "9001:9001"
    volumes:
      - ./mosquitto/config:/mosquitto/config
      - ./mosquitto/data:/mosquitto/data
  zigbee2mqtt:
    image: koenkk/zigbee2mqtt:latest
    restart: unless-stopped
    depends_on:
      - mosquitto
    environment:
      - TZ=$HA_TIMEZONE
    volumes:
      - ./zigbee2mqtt:/app/data
    devices:
      - $ZIGBEE_ADAPTER:$ZIGBEE_ADAPTER
  homeassistant:
    image: ghcr.io/home-assistant/home-assistant:stable
    restart: unless-stopped
    network_mode: host
    privileged: true
    depends_on:
      - mosquitto
    volumes:
      - ./homeassistant:/config
    environment:
      - TZ=$HA_TIMEZONE
EOC

log "Starting containers with $COMPOSE_CMD"
$COMPOSE_CMD up -d
