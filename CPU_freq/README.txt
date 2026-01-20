CPU Scheduler Quick Reference
=============================

Run in the foreground:
    sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py start

Status (sudo not required):
    /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py status

Available modes:
    sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py mode auto
    sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py mode day-auto
    sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py mode force-low
    sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py mode force-high
    sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py mode auto --override 7200

HA helper (maps Auto/High/Low to scheduler modes):
    sudo /home/vojrik/Scripts/CPU_freq/set_cpu_scheduler_mode.sh auto
    sudo /home/vojrik/Scripts/CPU_freq/set_cpu_scheduler_mode.sh high
    sudo /home/vojrik/Scripts/CPU_freq/set_cpu_scheduler_mode.sh low

MQTT state:
    topic: rpi/cpu_scheduler/mode
    payload: auto/high/low

Change configuration values (persisted by `set`; restart the service to apply):
    sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py set --night 22:00-07:00
    sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py set --idle-max-khz 1200000 --perf-max-khz 2800000
    sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py set --low-load-pct 30 --low-load-duration-s 600
    sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py set --high-load-pct 80 --high-load-duration-s 10
    sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py set --fan-path /run/fan_mode

Troubleshooting
---------------
- Service status and logs:
  - `systemctl status cpu-scheduler.service`
  - `journalctl -u cpu-scheduler.service -f`
- Service does not start on boot:
  - `systemctl is-enabled cpu-scheduler.service` should report `enabled`. If not, run `sudo systemctl enable --now cpu-scheduler.service`.
  - After modifying the script execute `sudo systemctl daemon-reload` followed by `sudo systemctl restart cpu-scheduler.service`.
- Night profile still runs at high frequency:
  - Check the mode: `cat /var/lib/cpu-scheduler/mode` (e.g. `day-auto` keeps the performance profile at night; `force-high` enforces performance).
  - Inspect overrides: `cat /var/lib/cpu-scheduler/override_until` and compare with `date +%s`. Clear with `sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py mode auto --override 0`.
  - External cpufreq changes trigger `NOTICE: external change detected …` in the log; the daemon re-applies min/max afterwards.
- `set` changes did not apply:
  - `set` writes to `/var/lib/cpu-scheduler/config.json`. Restart the service: `sudo systemctl restart cpu-scheduler.service`.
- cpufreq diagnostics:
  - Available frequencies: `/home/vojrik/Scripts/CPU_freq/cpu-scheduler.py status` (field `avail`).
  - Current governor/min/max: `status` shows `gov`, `min`, `max` (read from `/sys/devices/system/cpu/.../cpufreq`).
- Fan mode path:
  - If `/run/fan_mode` is not writable, set the correct path: `sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py set --fan-path /run/fan_mode` and restart the service.
