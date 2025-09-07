#!/usr/bin/python3
# -*- coding: utf-8 -*-

import time
import sys
import os
import fan_pwm  # náš modul s init_pwm, set_fan_speed, stop_pwm

# === Nastavení ===
WAIT_TIME = 2
FAN_MIN = 0
PWM_FREQ = 20000  # Hz pro 3pin DC fan; pro 4pin PC fan dej 25000
MODE_FILE = "/run/fan_mode"  # obsah: "normal" nebo "silent"
hyst = 1

tempSteps = [40, 44.99, 45, 47, 50, 54.99, 55, 58, 61, 64, 67, 70]
speedSteps_normal = [0.1, 0.1, 22, 25, 30, 35, 35, 40, 50, 60, 70, 100]
speedSteps_silent = [0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 22, 25, 28, 30, 33, 35]

profiles = {
    "normal": speedSteps_normal,
    "silent": speedSteps_silent,
}

# === Stav ===
cpuTempOld = 0.0
fanSpeedOld = 0.0
firstRun = True
last_mode = None

def read_mode():
    try:
        with open(MODE_FILE, "r") as f:
            m = f.read().strip().lower()
            return m if m in profiles else "normal"
    except FileNotFoundError:
        return "normal"

def interp_speed(t, temps, speeds):
    if t < temps[0]:
        return speeds[0]
    if t >= temps[-1]:
        return speeds[-1]
    # lineární interpolace mezi body
    for i in range(len(temps) - 1):
        if temps[i] <= t < temps[i + 1]:
            return round(
                (speeds[i + 1] - speeds[i])
                / (temps[i + 1] - temps[i])
                * (t - temps[i])
                + speeds[i],
                1,
            )
    return speeds[-1]

# sanity check
if len(speedSteps_normal) != len(tempSteps) or len(speedSteps_silent) != len(tempSteps):
    print("Počet teplotních a rychlostních kroků se neshoduje!")
    sys.exit(1)

try:
    fan_pwm.init_pwm(freq_hz=PWM_FREQ)

    while True:
        # režim zvenku
        mode = read_mode()
        speeds = profiles[mode]

        if mode != last_mode:
            print(f"Režim: {mode}")
            last_mode = mode

        # teplota CPU
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            cpuTemp = float(f.read()) / 1000.0

        # výpočet rychlosti s hysterezí
        if firstRun or abs(cpuTemp - cpuTempOld) > hyst:
            fanSpeed = interp_speed(cpuTemp, tempSteps, speeds)

            if fanSpeed != fanSpeedOld and (fanSpeed >= FAN_MIN or fanSpeed == 0):
                fan_pwm.set_fan_speed(fanSpeed)
                fanSpeedOld = fanSpeed

            cpuTempOld = cpuTemp
            firstRun = False

        # print(f"{mode} | CPU: {cpuTemp:.1f} °C | Duty: {fanSpeedOld:.1f} %")

        time.sleep(WAIT_TIME)

except KeyboardInterrupt:
    print("Fan ctrl interrupted by keyboard")
    fan_pwm.stop_pwm()
    sys.exit(0)
except Exception as e:
    # tvrdě ukončit PWM i při chybě
    try:
        fan_pwm.stop_pwm()
    finally:
        raise
