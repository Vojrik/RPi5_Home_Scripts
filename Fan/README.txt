Možno přepínat za běhu pomocí:
		# spustit v popředí
sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py start

# stav
sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py status

# režimy
sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py mode auto
sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py mode day-auto
sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py mode force-low
sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py mode force-high
sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py mode auto --override 7200

# změny konfigurace (set … uloží config, projeví se až po restartu služby:)
sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py set --night 22:00-07:00
sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py set --idle-max-khz 1200000 --perf-max-khz 2800000
sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py set --low-load-pct 30 --low-load-duration-s 600
sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py set --high-load-pct 80 --high-load-duration-s 10
sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py set --fan-path /run/fan_mode
