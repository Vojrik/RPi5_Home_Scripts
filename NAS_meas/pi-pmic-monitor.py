#!/usr/bin/env python3
import argparse
import json
import math
import os
import re
import socket
import subprocess
import sys
import time

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

ENV_FILE = os.path.join(os.path.dirname(__file__), ".env")


def load_env_file(path):
    env = {}
    if not os.path.exists(path):
        return env
    with open(path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip("\"").strip("'")
    return env


def get_env(env, key, default=None):
    return os.environ.get(key, env.get(key, default))


def build_mqtt_config(env):
    host = get_env(env, "MQTT_HOST", "127.0.0.1")
    if not host:
        return None
    base_topic = get_env(env, "PMIC_MQTT_BASE_TOPIC", get_env(env, "MQTT_BASE_TOPIC", "rpi_supply"))
    device_id = get_env(env, "PMIC_MQTT_DEVICE_ID", "rpi_supply")
    device_name = get_env(env, "PMIC_MQTT_DEVICE_NAME", "RPi Supply")
    return {
        "host": host,
        "port": int(get_env(env, "MQTT_PORT", "1883")),
        "user": get_env(env, "MQTT_USER", ""),
        "password": get_env(env, "MQTT_PASSWORD", ""),
        "client_id": get_env(env, "PMIC_MQTT_CLIENT_ID", f"rpi-supply-{socket.gethostname()}"),
        "base_topic": base_topic,
        "discovery_prefix": get_env(env, "MQTT_DISCOVERY_PREFIX", "homeassistant"),
        "device_id": device_id,
        "device_name": device_name,
    }


def publish_discovery(client, cfg):
    availability_topic = f"{cfg['base_topic']}/status"
    device_info = {
        "identifiers": [cfg["device_id"]],
        "name": cfg["device_name"],
        "manufacturer": "Raspberry Pi",
        "model": "RPi5 PMIC",
    }
    sensors = [
        {
            "suffix": "pi_ext5v_v",
            "name": "Pi EXT5V Voltage",
            "unit": "V",
            "device_class": "voltage",
        },
        {
            "suffix": "pi_3v3_sys_v",
            "name": "Pi 3V3 Voltage",
            "unit": "V",
            "device_class": "voltage",
        },
        {
            "suffix": "pi_3v3_sys_a",
            "name": "Pi 3V3 Current",
            "unit": "A",
            "device_class": "current",
        },
    ]

    for sensor in sensors:
        object_id = f"{cfg['device_id']}_{sensor['suffix']}"
        topic = f"{cfg['discovery_prefix']}/sensor/{object_id}/config"
        payload = {
            "name": f"{cfg['device_name']} {sensor['name']}",
            "state_topic": f"{cfg['base_topic']}/{sensor['suffix']}",
            "availability_topic": availability_topic,
            "unique_id": object_id,
            "device_class": sensor["device_class"],
            "state_class": "measurement",
            "unit_of_measurement": sensor["unit"],
            "device": device_info,
        }
        client.publish(topic, json.dumps(payload), retain=True)

    client.publish(availability_topic, "online", retain=True)


def setup_mqtt(cfg):
    if mqtt is None:
        raise RuntimeError("Missing paho-mqtt. Install python3-paho-mqtt or paho-mqtt.")

    try:
        client = mqtt.Client(
            client_id=cfg["client_id"],
            clean_session=True,
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        )
    except (AttributeError, TypeError):
        client = mqtt.Client(client_id=cfg["client_id"], clean_session=True)

    if cfg["user"] or cfg["password"]:
        client.username_pw_set(cfg["user"], cfg["password"])

    availability_topic = f"{cfg['base_topic']}/status"
    client.will_set(availability_topic, "offline", retain=True)
    client.connect(cfg["host"], cfg["port"], keepalive=60)
    client.loop_start()
    publish_discovery(client, cfg)
    return client


def parse_args(env):
    parser = argparse.ArgumentParser(description="Read Pi PMIC ADC values and publish to MQTT.")
    parser.add_argument("--no-mqtt", action="store_true", help="Disable MQTT publishing.")
    parser.add_argument(
        "--interval",
        type=float,
        default=float(get_env(env, "PUBLISH_INTERVAL_SEC", "1")),
        help="Publish interval in seconds.",
    )
    return parser.parse_args()


def parse_adc_value(text):
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        raise ValueError("No numeric value found")
    return float(match.group(0))


def read_pmic_adc():
    try:
        output = subprocess.check_output(
            ["vcgencmd", "pmic_read_adc"],
            stderr=subprocess.STDOUT,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"vcgencmd failed: {exc}") from exc

    readings = {}
    for line in output.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        try:
            readings[key] = parse_adc_value(raw_value)
        except ValueError:
            continue
    return readings


def is_finite(value):
    return isinstance(value, (int, float)) and math.isfinite(value)


def main():
    env = load_env_file(ENV_FILE)
    args = parse_args(env)

    mqtt_cfg = None if args.no_mqtt else build_mqtt_config(env)
    mqtt_client = None
    if mqtt_cfg:
        try:
            mqtt_client = setup_mqtt(mqtt_cfg)
        except Exception as exc:
            print(f"MQTT setup failed: {exc}")
            return 1

    last_error_at = 0.0
    try:
        while True:
            try:
                adc = read_pmic_adc()
            except RuntimeError as exc:
                now = time.time()
                if now - last_error_at > 5:
                    print(f"PMIC read failed: {exc}")
                    last_error_at = now
                time.sleep(args.interval)
                continue

            ext5v_v = adc.get("EXT5V_V")
            sys_3v3_v = adc.get("3V3_SYS_V")
            sys_3v3_a = adc.get("3V3_SYS_A")

            if not (is_finite(ext5v_v) and is_finite(sys_3v3_v) and is_finite(sys_3v3_a)):
                print("PMIC read missing expected values")
                time.sleep(args.interval)
                continue

            print(
                f"EXT5V_V={ext5v_v:6.3f} V | "
                f"3V3_SYS_V={sys_3v3_v:6.3f} V | "
                f"3V3_SYS_A={sys_3v3_a:6.3f} A"
            )

            if mqtt_client and mqtt_cfg:
                mqtt_client.publish(
                    f"{mqtt_cfg['base_topic']}/pi_ext5v_v",
                    f"{ext5v_v:.6f}",
                )
                mqtt_client.publish(
                    f"{mqtt_cfg['base_topic']}/pi_3v3_sys_v",
                    f"{sys_3v3_v:.6f}",
                )
                mqtt_client.publish(
                    f"{mqtt_cfg['base_topic']}/pi_3v3_sys_a",
                    f"{sys_3v3_a:.6f}",
                )

            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        if mqtt_client and mqtt_cfg:
            availability_topic = f"{mqtt_cfg['base_topic']}/status"
            mqtt_client.publish(availability_topic, "offline", retain=True)
            mqtt_client.loop_stop()
            mqtt_client.disconnect()

    return 0


if __name__ == "__main__":
    sys.exit(main())
