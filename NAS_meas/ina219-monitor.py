#!/usr/bin/env python3
import argparse
import json
import os
import socket
import sys
import time

try:
    from smbus2 import SMBus
except ImportError:
    try:
        from smbus import SMBus
    except ImportError:
        SMBus = None

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

# INA219 register addresses
REG_CONFIG = 0x00
REG_SHUNT_VOLTAGE = 0x01
REG_BUS_VOLTAGE = 0x02
REG_POWER = 0x03
REG_CURRENT = 0x04
REG_CALIBRATION = 0x05

# INA219 config: 32V bus range, 80mV shunt range, 12-bit ADCs, 128 samples averaging, continuous shunt+bus
CONFIG_32V_80MV_CONT = 0x3BFF

# Hardware configuration
MAX_CURRENT_A = 4.0

# Rshunt = parallel of one 0.1 Ohm and six 0.11 Ohm resistors
RSHUNT_OHM = 1.0 / (1.0 / 0.1 + 6.0 / 0.11)

# INA219 calibration
CURRENT_LSB_A = MAX_CURRENT_A / 32767.0
POWER_LSB_W = 20.0 * CURRENT_LSB_A
CALIBRATION_VALUE = int(0.04096 / (CURRENT_LSB_A * RSHUNT_OHM))

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


def swap_bytes(value):
    return ((value & 0xFF) << 8) | (value >> 8)


def read_register(bus, addr, reg):
    value = bus.read_word_data(addr, reg)
    return swap_bytes(value)


def write_register(bus, addr, reg, value):
    bus.write_word_data(addr, reg, swap_bytes(value))


def find_ina219_address(bus, start=0x40, end=0x4F):
    for addr in range(start, end + 1):
        try:
            read_register(bus, addr, REG_CONFIG)
            return addr
        except OSError:
            continue
    return None


def to_signed_16(value):
    if value & 0x8000:
        return value - 0x10000
    return value


def build_mqtt_config(env):
    host = get_env(env, "MQTT_HOST", "127.0.0.1")
    if not host:
        return None
    return {
        "host": host,
        "port": int(get_env(env, "MQTT_PORT", "1883")),
        "user": get_env(env, "MQTT_USER", ""),
        "password": get_env(env, "MQTT_PASSWORD", ""),
        "client_id": get_env(env, "MQTT_CLIENT_ID", f"nas-ina219-{socket.gethostname()}"),
        "base_topic": get_env(env, "MQTT_BASE_TOPIC", "nas/ina219"),
        "discovery_prefix": get_env(env, "MQTT_DISCOVERY_PREFIX", "homeassistant"),
        "device_id": get_env(env, "MQTT_DEVICE_ID", "nas_ina219"),
        "device_name": get_env(env, "MQTT_DEVICE_NAME", "NAS INA219"),
    }


def publish_discovery(client, cfg):
    availability_topic = f"{cfg['base_topic']}/status"
    device_info = {
        "identifiers": [cfg["device_id"]],
        "name": cfg["device_name"],
        "manufacturer": "Texas Instruments",
        "model": "INA219",
    }
    sensors = [
        {
            "suffix": "voltage",
            "name": "Voltage",
            "unit": "V",
            "device_class": "voltage",
        },
        {
            "suffix": "current",
            "name": "Current",
            "unit": "A",
            "device_class": "current",
        },
        {
            "suffix": "power",
            "name": "Power",
            "unit": "W",
            "device_class": "power",
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
    parser = argparse.ArgumentParser(description="Read INA219 and publish measurements to MQTT.")
    parser.add_argument("--no-mqtt", action="store_true", help="Disable MQTT publishing.")
    parser.add_argument(
        "--i2c-bus",
        type=int,
        default=int(get_env(env, "I2C_BUS", "1")),
        help="I2C bus number (default: 1).",
    )
    parser.add_argument(
        "--i2c-address",
        type=lambda value: int(value, 0),
        default=get_env(env, "I2C_ADDRESS"),
        help="INA219 I2C address (default: auto-scan 0x40-0x4F).",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=float(get_env(env, "PUBLISH_INTERVAL_SEC", "1")),
        help="Publish interval in seconds.",
    )
    return parser.parse_args()


def main():
    if SMBus is None:
        print("Missing smbus/smbus2. Install python3-smbus or smbus2.")
        return 1

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

    try:
        bus = SMBus(args.i2c_bus)
    except FileNotFoundError:
        print(f"I2C bus /dev/i2c-{args.i2c_bus} not found. Enable I2C in system config.")
        return 1

    with bus:
        if args.i2c_address is None:
            addr = find_ina219_address(bus)
        else:
            addr = int(args.i2c_address)
        if addr is None:
            print("INA219 not found on I2C addresses 0x40-0x4F.")
            return 1

        write_register(bus, addr, REG_CONFIG, CONFIG_32V_80MV_CONT)
        write_register(bus, addr, REG_CALIBRATION, CALIBRATION_VALUE)

        print(f"INA219 detected at 0x{addr:02X}")
        print(f"Rshunt={RSHUNT_OHM:.6f} Ohm, current_lsb={CURRENT_LSB_A:.9f} A")
        print("Press Ctrl+C to stop.")

        try:
            while True:
                shunt_raw = to_signed_16(read_register(bus, addr, REG_SHUNT_VOLTAGE))
                bus_raw = read_register(bus, addr, REG_BUS_VOLTAGE)
                current_raw = to_signed_16(read_register(bus, addr, REG_CURRENT))
                power_raw = read_register(bus, addr, REG_POWER)

                shunt_voltage_v = shunt_raw * 10e-6
                bus_voltage_v = ((bus_raw >> 3) * 4e-3)
                # Force positive display if sensor is wired with reversed polarity.
                current_a = abs(current_raw * CURRENT_LSB_A)
                power_w = power_raw * POWER_LSB_W

                # Total voltage is bus voltage plus shunt drop.
                total_voltage_v = bus_voltage_v + shunt_voltage_v

                print(
                    f"U={total_voltage_v:6.3f} V | "
                    f"I={current_a:6.3f} A | "
                    f"P={power_w:7.3f} W"
                )

                if mqtt_client and mqtt_cfg:
                    mqtt_client.publish(f"{mqtt_cfg['base_topic']}/voltage", f"{total_voltage_v:.6f}")
                    mqtt_client.publish(f"{mqtt_cfg['base_topic']}/current", f"{current_a:.6f}")
                    mqtt_client.publish(f"{mqtt_cfg['base_topic']}/power", f"{power_w:.6f}")

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
