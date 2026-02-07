#!/usr/bin/env python3
import argparse
import contextlib
import fcntl
import json
import os
import signal
import socket
import sys
import threading
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
I2C_LOCK_PATH = "/home/vojrik/.i2c-1.lock"
I2C_REOPEN_AFTER_ERRORS = 3
I2C_REOPEN_MIN_INTERVAL_SEC = 5.0
I2C_OP_TIMEOUT_SEC = float(os.environ.get("I2C_OP_TIMEOUT_SEC", "1.5"))
WATCHDOG_TIMEOUT_SEC = float(os.environ.get("WATCHDOG_TIMEOUT_SEC", "20"))
I2C_INIT_RETRY_SEC = float(os.environ.get("I2C_INIT_RETRY_SEC", "5"))
_LAST_PROGRESS_AT = time.monotonic()


def touch_progress():
    global _LAST_PROGRESS_AT
    _LAST_PROGRESS_AT = time.monotonic()


def start_watchdog():
    if WATCHDOG_TIMEOUT_SEC <= 0:
        return

    def _watchdog_loop():
        while True:
            time.sleep(2.0)
            if time.monotonic() - _LAST_PROGRESS_AT > WATCHDOG_TIMEOUT_SEC:
                print(
                    f"Watchdog: no progress for >{WATCHDOG_TIMEOUT_SEC:.0f}s, exiting for systemd restart.",
                    file=sys.stderr,
                )
                os._exit(1)

    thread = threading.Thread(target=_watchdog_loop, daemon=True, name="ina219-watchdog")
    thread.start()


@contextlib.contextmanager
def i2c_op_timeout(timeout_sec):
    if timeout_sec <= 0:
        yield
        return
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def _handle_timeout(_signum, _frame):
        raise TimeoutError("I2C operation timeout")

    old_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, _handle_timeout)
    old_timer = signal.setitimer(signal.ITIMER_REAL, timeout_sec)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, old_timer[0], old_timer[1])
        signal.signal(signal.SIGALRM, old_handler)


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
    with i2c_op_timeout(I2C_OP_TIMEOUT_SEC):
        value = bus.read_word_data(addr, reg)
    return swap_bytes(value)


def write_register(bus, addr, reg, value):
    with i2c_op_timeout(I2C_OP_TIMEOUT_SEC):
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


@contextlib.contextmanager
def i2c_lock(timeout=1.0):
    start = time.time()
    fd = os.open(I2C_LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o666)
    try:
        os.chmod(I2C_LOCK_PATH, 0o666)
    except OSError:
        pass
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.time() - start > timeout:
                    raise TimeoutError("I2C lock timeout")
                time.sleep(0.01)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

def open_bus(bus_num):
    return SMBus(bus_num)

def reopen_bus(bus, bus_num):
    try:
        bus.close()
    except Exception:
        pass
    return open_bus(bus_num)


def list_i2c_buses():
    buses = []
    try:
        for name in os.listdir("/dev"):
            if not name.startswith("i2c-"):
                continue
            try:
                buses.append(int(name.split("-", 1)[1]))
            except ValueError:
                continue
    except OSError:
        return []
    return sorted(set(buses))


def pick_i2c_bus(preferred_bus):
    device = f"/dev/i2c-{preferred_bus}"
    if os.path.exists(device):
        return preferred_bus
    buses = list_i2c_buses()
    if not buses:
        return None
    print(
        f"Preferred I2C bus {preferred_bus} missing; trying available bus {buses[0]} ({', '.join(str(b) for b in buses)})."
    )
    return buses[0]

def init_ina219(bus, addr, allow_scan=True):
    delay = 0.05
    for _ in range(3):
        try:
            with i2c_lock(timeout=3.0):
                if addr is None:
                    if not allow_scan:
                        raise RuntimeError("INA219 address missing.")
                    addr = find_ina219_address(bus)
                if addr is None:
                    raise RuntimeError("INA219 not found on I2C addresses 0x40-0x4F.")

                write_register(bus, addr, REG_CONFIG, CONFIG_32V_80MV_CONT)
                write_register(bus, addr, REG_CALIBRATION, CALIBRATION_VALUE)
            return addr
        except TimeoutError:
            time.sleep(delay)
            delay *= 2
            continue
    raise RuntimeError("I2C lock timeout during INA219 init.")


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

    # Use the new callback API when available to avoid deprecation warnings.
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


def read_measurements(bus, addr, retries=3):
    delay = 0.05
    for _ in range(retries):
        try:
            with i2c_lock():
                shunt_raw = to_signed_16(read_register(bus, addr, REG_SHUNT_VOLTAGE))
                bus_raw = read_register(bus, addr, REG_BUS_VOLTAGE)
                current_raw = to_signed_16(read_register(bus, addr, REG_CURRENT))
                power_raw = read_register(bus, addr, REG_POWER)
            return shunt_raw, bus_raw, current_raw, power_raw
        except (OSError, TimeoutError):
            time.sleep(delay)
            delay *= 2
            continue
    raise OSError("I2C read failed after retries")


def main():
    if SMBus is None:
        print("Missing smbus/smbus2. Install python3-smbus or smbus2.")
        return 1

    env = load_env_file(ENV_FILE)
    args = parse_args(env)
    start_watchdog()

    mqtt_cfg = None if args.no_mqtt else build_mqtt_config(env)
    mqtt_client = None
    if mqtt_cfg:
        try:
            mqtt_client = setup_mqtt(mqtt_cfg)
        except Exception as exc:
            print(f"MQTT setup failed: {exc}")
            return 1

    bus = None
    addr = None
    active_bus = None
    last_init_error_at = 0.0
    while bus is None or addr is None:
        touch_progress()
        active_bus = pick_i2c_bus(args.i2c_bus)
        if active_bus is None:
            now = time.time()
            if now - last_init_error_at > 5:
                print("No /dev/i2c-* devices found; waiting for I2C bus.")
                last_init_error_at = now
            time.sleep(I2C_INIT_RETRY_SEC)
            continue
        try:
            bus = open_bus(active_bus)
            addr = init_ina219(bus, args.i2c_address, allow_scan=args.i2c_address is None)
        except (FileNotFoundError, RuntimeError, OSError) as exc:
            now = time.time()
            if now - last_init_error_at > 5:
                print(f"I2C init failed on bus {active_bus}: {exc}")
                last_init_error_at = now
            try:
                if bus is not None:
                    bus.close()
            except Exception:
                pass
            bus = None
            addr = None
            time.sleep(I2C_INIT_RETRY_SEC)
            continue

    print(f"INA219 detected at 0x{addr:02X}")
    print(f"Using I2C bus {active_bus}")
    print(f"Rshunt={RSHUNT_OHM:.6f} Ohm, current_lsb={CURRENT_LSB_A:.9f} A")
    print("Press Ctrl+C to stop.")

    last_error_at = 0.0
    last_availability_at = 0.0
    last_reopen_at = 0.0
    consecutive_errors = 0
    try:
        while True:
            touch_progress()
            try:
                shunt_raw, bus_raw, current_raw, power_raw = read_measurements(bus, addr)
                consecutive_errors = 0
            except (OSError, TimeoutError) as exc:
                now = time.time()
                consecutive_errors += 1
                if now - last_error_at > 5:
                    print(f"I2C read failed: {exc}")
                    last_error_at = now
                if (
                    consecutive_errors >= I2C_REOPEN_AFTER_ERRORS
                    and now - last_reopen_at >= I2C_REOPEN_MIN_INTERVAL_SEC
                ):
                    try:
                        selected_bus = pick_i2c_bus(active_bus if active_bus is not None else args.i2c_bus)
                        if selected_bus is None:
                            raise RuntimeError("No /dev/i2c-* devices found.")
                        active_bus = selected_bus
                        bus = reopen_bus(bus, active_bus)
                        addr = init_ina219(
                            bus,
                            args.i2c_address,
                            allow_scan=args.i2c_address is None,
                        )
                        consecutive_errors = 0
                        last_reopen_at = now
                    except Exception as reopen_exc:
                        print(f"I2C reopen failed: {reopen_exc}")
                        last_reopen_at = now
                time.sleep(args.interval)
                touch_progress()
                continue

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
                now = time.time()
                if now - last_availability_at > 30:
                    mqtt_client.publish(
                        f"{mqtt_cfg['base_topic']}/status",
                        "online",
                        retain=True,
                    )
                    last_availability_at = now

            time.sleep(args.interval)
            touch_progress()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            bus.close()
        except Exception:
            pass
        if mqtt_client and mqtt_cfg:
            availability_topic = f"{mqtt_cfg['base_topic']}/status"
            mqtt_client.publish(availability_topic, "offline", retain=True)
            mqtt_client.loop_stop()
            mqtt_client.disconnect()

    return 0


if __name__ == "__main__":
    sys.exit(main())
