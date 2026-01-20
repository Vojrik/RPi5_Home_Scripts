Runtime fan control commands
============================

Manual fan override (writes /run/fan_override):
    sudo /home/vojrik/Scripts/Fan/set_fan_override.sh auto
    sudo /home/vojrik/Scripts/Fan/set_fan_override.sh normal
    sudo /home/vojrik/Scripts/Fan/set_fan_override.sh silent
    sudo /home/vojrik/Scripts/Fan/set_fan_override.sh 40

Start the scheduler in the foreground:
    sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py start

Query current status:
    sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py status

Available modes:
    sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py mode auto
    sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py mode day-auto
    sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py mode force-low
    sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py mode force-high
    sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py mode auto --override 7200

Changing configuration values (the new Settings are applied after restarting the service):
    sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py set --night 22:00-07:00
    sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py set --idle-max-khz 1200000 --perf-max-khz 2800000
    sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py set --low-load-pct 30 --low-load-duration-s 600
    sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py set --high-load-pct 80 --high-load-duration-s 10
    sudo /home/vojrik/Scripts/CPU_freq/cpu-scheduler.py set --fan-path /run/fan_mode
