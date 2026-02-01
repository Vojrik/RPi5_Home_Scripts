# GPIO_control

Tento adresar obsahuje jediny podporovany skript pro rizeni serv na Raspberry Pi 5.
Pouziva se PIO-asistovane PWM (overlay `pwm-pio`), ktere je nezavisle na
standardnim HW PWM bloku RP1 (PWM0/PWM1). Diky tomu muze bezet ventilator na
20 kHz pres PWM0 (GPIO19) a serva mohou mit stabilni 50 Hz na libovolnych GPIO
0-27.

## Jak to funguje
- Overlay `dtoverlay=pwm-pio,gpio=XX` zapne PIO PWM na zvolenem GPIO.
- Kernel vystavi novy PWM controller v `/sys/class/pwm/pwmchipX` s kompatibilitou
  `raspberrypi,pwm-pio-rp1`.
- Skript zapisuje `period`, `duty_cycle`, `enable` do sysfs PWM a generuje tak
  presny signal bez jitteru z userspace.
- `pwm-pio` umi az 4 nezavisle PWM vystupy (GPIO 0-27), pokud nic jineho
  nepouziva PIO.

## Konfigurace (boot)
V `/boot/firmware/config.txt` musi byt:

```
dtoverlay=pwm,pwmchip=0,pwmchannel=3,pin=19
dtoverlay=pwm-pio,gpio=24
dtoverlay=pwm-pio,gpio=25
```

Po zmene je nutny reboot.

## Spusteni
Pan/Tilt na GPIO24/25:

```
sudo python3 /home/vojrik/Scripts/GPIO_control/camera_servo_control.py \
  --pan 0 --tilt 0 --backend pwm-pio --hold-seconds 5
```

Relativni krok (napr. pro tlacitka vlevo/vpravo) se stavem v souboru:

```
sudo python3 /home/vojrik/Scripts/GPIO_control/camera_servo_control.py \
  --pan-step -5 --state-file /tmp/camera_servo_state.json \
  --backend pwm-pio --hold-seconds 0.2
```

Vypnuti PWM vystupu:

```
sudo python3 /home/vojrik/Scripts/GPIO_control/camera_servo_control.py \
  --disable --backend pwm-pio
```

## Volitelne parametry
- `--pwmchip` vynuti konkretni pwmchip (napr. `2` nebo `/sys/class/pwm/pwmchip2`).
- `--pan-channel` a `--tilt-channel` urci index kanalu v pwmchipu.
- `--pan-step` / `--tilt-step` provadi relativni kroky a uklada stav do JSON souboru.
- `--state-file` urcuje kam se uklada posledni poloha (default `/tmp/camera_servo_state.json`).
- `--pan-min-percent`, `--pan-max-percent`, `--tilt-min-percent`, `--tilt-max-percent` osetruji krajni dorazy.
- `--disable` vypne PWM vystupy bez pohybu.

## Poznamky
- Defaultni frekvence je 50 Hz.
- Stabilita je dana HW/PIO PWM, ne schedulerem Linuxu.
