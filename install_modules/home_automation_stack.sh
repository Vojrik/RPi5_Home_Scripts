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
if ! apt-get install -y ca-certificates curl gnupg mosquitto-clients; then
  warn "Failed to install some prerequisite packages (ca-certificates, curl, gnupg, mosquitto-clients)"
fi

docker_install_method=""

install_docker_from_distribution() {
  log "Attempting to install Docker from distribution packages (docker.io)"
  if apt-get install -y docker.io docker-compose-plugin; then
    if command -v docker >/dev/null 2>&1; then
      docker_install_method="debian-docker.io"
      return 0
    fi
    warn "docker.io package installed but docker binary still missing"
  else
    warn "Failed to install docker.io package from distribution repositories"
  fi
  return 1
}

install_docker_from_docker_repo() {
  log "Attempting to install Docker from Docker's official APT repository"
  if ! command -v curl >/dev/null 2>&1; then
    warn "curl command unavailable; skipping Docker repository installation path"
    return 1
  fi
  if ! command -v gpg >/dev/null 2>&1; then
    if ! apt-get install -y gnupg >/dev/null; then
      warn "Failed to install gnupg package required for Docker repository trust"
      return 1
    fi
  fi

  local keyring_dir="/etc/apt/keyrings"
  local keyring_file="$keyring_dir/docker.gpg"
  local repo_file="/etc/apt/sources.list.d/docker.list"

  install -m 0755 -d "$keyring_dir"
  if ! curl -fsSL https://download.docker.com/linux/debian/gpg -o "$keyring_file"; then
    warn "Failed to download Docker GPG key"
    return 1
  fi
  chmod a+r "$keyring_file"

  local codename="$(. /etc/os-release && echo "$VERSION_CODENAME")"
  local arch="$(dpkg --print-architecture)"

  cat > "$repo_file" <<-EOF
deb [arch=$arch signed-by=$keyring_file] https://download.docker.com/linux/debian $codename stable
EOF

  if ! apt-get update; then
    warn "apt-get update failed after adding Docker repository"
    rm -f "$repo_file" "$keyring_file"
    return 1
  fi

  if apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin; then
    if command -v docker >/dev/null 2>&1; then
      docker_install_method="docker-official-repo"
      return 0
    fi
    warn "Docker official packages installed but docker binary still missing"
  else
    warn "Failed to install Docker packages from Docker repository"
  fi
  return 1
}

run_offline_docker_installer() {
  local offline_dir="${OFFLINE_DOCKER_INSTALLER_DIR:-$SCRIPT_DIR/offline}"
  local installer="$offline_dir/docker-install.sh"
  local checksum_file="$installer.sha256"

  log "Looking for offline Docker installer in $offline_dir"

  if ! command -v sha256sum >/dev/null 2>&1; then
    warn "sha256sum command unavailable; cannot verify offline installer integrity"
    return 1
  fi

  if [[ ! -f "$installer" ]]; then
    warn "Offline installer script not found at $installer"
    return 1
  fi
  if [[ ! -f "$checksum_file" ]]; then
    warn "Checksum file not found for offline installer ($checksum_file)"
    return 1
  fi
  if ! sha256sum --status -c "$checksum_file"; then
    warn "Checksum verification failed for offline installer"
    return 1
  fi

  log "Running verified offline Docker installer"
  if bash "$installer"; then
    if command -v docker >/dev/null 2>&1; then
      docker_install_method="offline-installer"
      return 0
    fi
    warn "Offline installer completed but docker binary still missing"
  else
    warn "Offline Docker installer failed"
  fi
  return 1
}

if command -v docker >/dev/null 2>&1; then
  docker_install_method="preinstalled"
  log "Docker already present at $(command -v docker); skipping installation"
else
  install_docker_from_distribution || true

  if [[ -z "$docker_install_method" ]]; then
    install_docker_from_docker_repo || true
  fi

  if [[ -z "$docker_install_method" ]]; then
    run_offline_docker_installer || true
  fi
fi

if [[ -z "$docker_install_method" ]]; then
  err "Docker engine installation failed; please install Docker manually and re-run the installer"
  exit 1
fi

log "Docker installation path selected: $docker_install_method"

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

DOCKER_AVAILABLE=true
if ! docker info >/dev/null 2>&1; then
  DOCKER_AVAILABLE=false
fi

STACK_WAS_RUNNING=false
if [[ -f docker-compose.yml ]]; then
  if [[ "$DOCKER_AVAILABLE" == true ]]; then
    EXISTING_SERVICES="$($COMPOSE_CMD ps --services 2>/dev/null || true)"
    if [[ -n "$EXISTING_SERVICES" ]]; then
      STACK_WAS_RUNNING=true
    fi
  fi
fi

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

if [[ "$DOCKER_AVAILABLE" == false ]]; then
  warn "Docker daemon is not available; start it and run '$COMPOSE_CMD up -d' in $STACK_DIR to launch or restart the home automation stack."
elif [[ "$STACK_WAS_RUNNING" == true ]]; then
  log "Restarting existing containers with $COMPOSE_CMD"
  $COMPOSE_CMD down
  $COMPOSE_CMD up -d --force-recreate
else
  log "Starting containers with $COMPOSE_CMD"
  $COMPOSE_CMD up -d
fi
