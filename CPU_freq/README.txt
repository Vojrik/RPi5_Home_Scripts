# spustit v popředí
sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py start

# stav (lze i bez sudo)
/home/vojrik/Scripts/CPU_freq/cpu-scheduler.py status

# režimy
sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py mode auto
sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py mode day-auto
sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py mode force-low
sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py mode force-high
sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py mode auto --override 7200

# změny konfigurace (set … uloží config, projeví se až po restartu služby)
sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py set --night 22:00-07:00
sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py set --idle-max-khz 1200000 --perf-max-khz 2800000
sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py set --low-load-pct 30 --low-load-duration-s 600
sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py set --high-load-pct 80 --high-load-duration-s 10
sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py set --fan-path /run/fan_mode

**Troubleshooting**
- Stav a logy služby:
  - `systemctl status cpu-scheduler.service`
  - `journalctl -u cpu-scheduler.service -f`
- Služba neběží po bootu:
  - `systemctl is-enabled cpu-scheduler.service` musí vrátit `enabled`. Pokud ne: `sudo systemctl enable --now cpu-scheduler.service`.
  - Po úpravě skriptu spustit `sudo systemctl daemon-reload` a `sudo systemctl restart cpu-scheduler.service`.
- V noci je frekvence vysoko:
  - Zkontroluj režim: `cat /var/lib/cpu-scheduler/mode` (např. `day-auto` v noci drží výkon; `force-high` vynucuje výkon).
  - Ověř override: `cat /var/lib/cpu-scheduler/override_until` a čas porovnat s `date +%s`. Zrušení: `sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py mode auto --override 0`.
  - Externí změny (jiný proces mění cpufreq): v logu uvidíš `NOTICE: external change detected …`, démon pak min/max znovu vynutí.
- `set` změny se neprojevily:
  - `set` jen uloží konfiguraci do `/var/lib/cpu-scheduler/config.json`. Je potřeba restart služby: `sudo systemctl restart cpu-scheduler.service`.
- Kontrola cpufreq:
  - Dostupné frekvence: `/home/vojrik/Scripts/CPU_freq/cpu-scheduler.py status` (pole `avail`).
  - Aktuální guvernér/min/max: `status` ukazuje `gov`, `min`, `max` (čteno z `/sys/devices/system/cpu/.../cpufreq`).
- Fan mode cesta:
  - Pokud není `/run/fan_mode` zapisovatelné, nastav správnou cestu: `sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py set --fan-path /run/fan_mode` a restartuj službu.
