#!/usr/bin/python3
# -*- coding: utf-8 -*-

import os
import sys

# Settings for your PWM channel
PWM_CHIP = 0   # controller 0
PWM_CH   = 3   # channel 3
FREQ_HZ  = 25000 # Hz for 2-pin DC fan; use 25000 for a 4-pin PC fan

base = f"/sys/class/pwm/pwmchip{PWM_CHIP}"
pwm  = f"{base}/pwm{PWM_CH}"

def write(path, value):
    with open(path, "w") as f:
        f.write(str(value))

def ensure_exported():
    if os.path.exists(pwm):
        write(f"{base}/unexport", PWM_CH)
    write(f"{base}/export", PWM_CH)


def setup(freq_hz):
    period_ns = round(1e9 / freq_hz)
    # Round to integer multiples (e.g. 10 ns)
    quantum = 20
    period_ns = (period_ns // quantum) * quantum
    try:
        write(f"{pwm}/enable", 0)
    except FileNotFoundError:
        pass
    write(f"{pwm}/period", period_ns)
    write(f"{pwm}/duty_cycle", 0)
    write(f"{pwm}/enable", 1)
    return period_ns

def set_duty_percent(period_ns, pct):
    pct = max(0.0, min(100.0, float(pct)))
    pct = 100.0 - pct  # invert duty cycle
    duty_ns = int(period_ns * (pct / 100.0))
    write(f"{pwm}/duty_cycle", duty_ns)

def cleanup():
    try:
        write(f"{pwm}/enable", 0)
    except FileNotFoundError:
        pass

if __name__ == "__main__":
    try:
        ensure_exported()
        period_ns = setup(FREQ_HZ)
        print("Enter fan speed in % (0-100), 'q' to quit.")
        while True:
            s = input("Fan Speed [%]: ").strip()
            if s.lower() in ("q", "quit", "exit"):
                break
            if not s:
                continue
            set_duty_percent(period_ns, s)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print("Error:", e, file=sys.stderr)
    finally:
        cleanup()
