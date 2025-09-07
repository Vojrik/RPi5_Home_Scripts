# -*- coding: utf-8 -*-
import os

PWM_CHIP = 0   # řadič 0
PWM_CH   = 3   # kanál 3
FREQ_HZ  = 20000  # Hz

base = f"/sys/class/pwm/pwmchip{PWM_CHIP}"
pwm  = f"{base}/pwm{PWM_CH}"
_period_ns = None  # uložíme si periodu pro další výpočty

def _write(path, value):
    with open(path, "w") as f:
        f.write(str(value))

def init_pwm(freq_hz=FREQ_HZ):
    """Exportuje kanál a nastaví frekvenci."""
    global _period_ns
    # reset kanálu
    if os.path.exists(pwm):
        _write(f"{base}/unexport", PWM_CH)
    _write(f"{base}/export", PWM_CH)

    # výpočet periody a zarovnání na 20 ns krok
    period_ns = round(1e9 / freq_hz)
    quantum = 20
    period_ns = (period_ns // quantum) * quantum

    _write(f"{pwm}/period", period_ns)
    _write(f"{pwm}/duty_cycle", 0)
    _write(f"{pwm}/enable", 1)
    _period_ns = period_ns

def set_fan_speed(percent):
    """Nastaví střídu v procentech (0–100)."""
    if _period_ns is None:
        raise RuntimeError("PWM není inicializováno – zavolej init_pwm()")
    pct = max(0.0, min(100.0, float(percent)))
    pct = 100.0 - pct  # inverze duty cycle
    duty_ns = int(_period_ns * (pct / 100.0))
    _write(f"{pwm}/duty_cycle", duty_ns)

def stop_pwm():
    """Vypne PWM kanál."""
    try:
        _write(f"{pwm}/enable", 0)
    except FileNotFoundError:
        pass
