#!/usr/bin/python3
# -*- coding: utf-8 -*-

import time
import sys
import json
import pathlib
import fan_pwm  # must provide: init_pwm(freq_hz), set_fan_speed(duty_pct), stop_pwm(), gpio_low()

try:
    import paho.mqtt.client as mqtt
except Exception:  # pragma: no cover - optional dependency for status publish
    mqtt = None

# === Settings ===
WAIT_TIME = 2.0
PWM_FREQ = 20000            # Hz for 3-pin DC; 25000 for 4-pin
MODE_FILE = "/run/fan_mode" # "normal" / "silent"
OVERRIDE_FILE = "/run/fan_override" # "auto" / "normal" / "silent" / "duty:NN"
HYST = 1.0                  # degC

# Duty policy
FAN_MIN_DUTY = 23.0         # % that reliably keeps fan spinning (tune to your fan)
FAN_OFF_DUTY = 0.01         # % used instead of a raw zero (hardware keeps fan at max on 0)
FAN_KICK_DUTY = 24.0       # % kick-start
FAN_KICK_MS = 500           # ms

# Curves
tempSteps =             [40,    44.99,  45,     47,     49.99,  50,     54.99,  55,     58,     59.99,  60,     64,     67,     70,     73]
speedSteps_normal =     [0,     0,      0,      0,      0,      0,      0,      23,     25,     27,     27,     30,     40,     50,     100]
speedSteps_silent =     [0,     0,      0,      0,      0,      0,      0,      0,      0,      0,      23.5,   24,     25,     28,     35]
profiles = {"normal": speedSteps_normal, "silent": speedSteps_silent}

# === State ===
cpu_ref = None
last_mode = None
last_effective = None
last_override = None
last_mqtt = None
pwm_enabled = False
fanDutyOld = -1.0

def read_mode():
    try:
        with open(MODE_FILE, "r") as f:
            m = f.read().strip().lower()
            return m if m in profiles else "normal"
    except FileNotFoundError:
        return "normal"

def read_override():
    try:
        value = pathlib.Path(OVERRIDE_FILE).read_text().strip().lower()
    except FileNotFoundError:
        return ("auto", None)
    if not value or value == "auto":
        return ("auto", None)
    if value in profiles:
        return ("profile", value)
    if value.startswith("duty:"):
        value = value.split(":", 1)[1].strip()
    if value.endswith("%"):
        value = value[:-1].strip()
    if value.isdigit():
        duty = int(value)
        return ("duty", max(0, min(100, duty)))
    return ("auto", None)

def clamp(v, lo, hi):
    return hi if v > hi else lo if v < lo else v

def interp_speed(t, temps, speeds):
    if t < temps[0]:
        return float(speeds[0])
    if t >= temps[-1]:
        return float(speeds[-1])
    for i in range(len(temps)-1):
        a, b = temps[i], temps[i+1]
        if a <= t < b:
            sa, sb = float(speeds[i]), float(speeds[i+1])
            return round((sb-sa)/(b-a)*(t-a)+sa, 1)
    return float(speeds[-1])

def ensure_pwm_enabled():
    global pwm_enabled
    if not pwm_enabled:
        fan_pwm.init_pwm(freq_hz=PWM_FREQ)
        pwm_enabled = True

def disable_pwm():
    global pwm_enabled
    if pwm_enabled:
        # stop PWM clock and force pin low (fan completely off)
        try:
            fan_pwm.stop_pwm()
        finally:
            # optional: if your fan_pwm exposes gpio_low(), set the pin to 0
            if hasattr(fan_pwm, "gpio_low"):
                fan_pwm.gpio_low()
        pwm_enabled = False

def load_mqtt_config():
    config_path = pathlib.Path("/home/vojrik/homeassistant/.storage/core.config_entries")
    try:
        data = json.loads(config_path.read_text())
    except Exception:
        return None
    for entry in data.get("data", {}).get("entries", []):
        if entry.get("domain") == "mqtt":
            cfg = entry.get("data", {})
            return {
                "host": cfg.get("broker", "127.0.0.1"),
                "port": int(cfg.get("port", 1883)),
                "username": cfg.get("username"),
                "password": cfg.get("password"),
            }
    return None

def publish_state(percent):
    global last_mqtt
    payload = str(int(round(percent)))
    if payload == last_mqtt:
        return
    if mqtt is None:
        return
    cfg = load_mqtt_config()
    if not cfg:
        return
    try:
        client = mqtt.Client(client_id="fan_ctrl_cpu", clean_session=True)
        if cfg.get("username"):
            client.username_pw_set(cfg.get("username"), cfg.get("password"))
        client.connect(cfg["host"], cfg["port"], 10)
        client.publish("rpi/fan/state", payload, retain=True)
        client.disconnect()
        last_mqtt = payload
    except Exception:
        pass

# sanity checks
if len(speedSteps_normal) != len(tempSteps) or len(speedSteps_silent) != len(tempSteps):
    print("The number of temperature and speed steps does not match!", file=sys.stderr)
    sys.exit(1)
if not all(tempSteps[i] < tempSteps[i+1] for i in range(len(tempSteps)-1)):
    print("tempSteps must be strictly increasing!", file=sys.stderr)
    sys.exit(1)

try:
    # Lazy enable: only when needed (>0%)
    while True:
        override = read_override()
        override_changed = (override != last_override)
        last_override = override

        if override[0] == "duty":
            duty = float(override[1])
            if override_changed or duty != fanDutyOld:
                if duty <= 0.0:
                    ensure_pwm_enabled()
                    if FAN_OFF_DUTY != fanDutyOld:
                        fan_pwm.set_fan_speed(FAN_OFF_DUTY)
                        fanDutyOld = FAN_OFF_DUTY
                    publish_state(0)
                else:
                    was_off = not pwm_enabled
                    ensure_pwm_enabled()
                    if was_off:
                        fan_pwm.set_fan_speed(FAN_KICK_DUTY)
                        time.sleep(FAN_KICK_MS / 1000.0)
                    if duty != fanDutyOld:
                        fan_pwm.set_fan_speed(duty)
                        fanDutyOld = duty
                    publish_state(duty)
            cpu_ref = None
            last_mode = None
            time.sleep(WAIT_TIME)
            continue

        if override[0] == "profile":
            mode = override[1]
        else:
            mode = read_mode()

        speeds = profiles[mode]
        mode_changed = (mode != last_mode)
        if mode_changed:
            print(f"Mode: {mode}")
            last_mode = mode
            cpu_ref = None  # force recompute
            last_effective = None

        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            cpu = float(f.read().strip()) / 1000.0

        if cpu_ref is None or abs(cpu - cpu_ref) > HYST or mode_changed:
            target = clamp(interp_speed(cpu, tempSteps, speeds), 0.0, 100.0)

            if target <= 0.0:
                # keep PWM active and set a tiny duty so the fan is actually off
                ensure_pwm_enabled()
                if FAN_OFF_DUTY != fanDutyOld:
                    fan_pwm.set_fan_speed(FAN_OFF_DUTY)
                    fanDutyOld = FAN_OFF_DUTY
                publish_state(0)
            else:
                # enable PWM if needed, do kick-start if we were OFF
                was_off = not pwm_enabled
                ensure_pwm_enabled()

                duty = max(target, FAN_MIN_DUTY)
                if was_off:
                    fan_pwm.set_fan_speed(FAN_KICK_DUTY)
                    time.sleep(FAN_KICK_MS/1000.0)

                if duty != fanDutyOld:
                    fan_pwm.set_fan_speed(duty)
                    fanDutyOld = duty
                publish_state(duty)

            cpu_ref = cpu

        time.sleep(WAIT_TIME)

except KeyboardInterrupt:
    print("Fan ctrl interrupted by keyboard")
    try:
        disable_pwm()
    finally:
        sys.exit(0)
except Exception:
    try:
        disable_pwm()
    finally:
        raise
