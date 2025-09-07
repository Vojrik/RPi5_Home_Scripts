#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import subprocess
import multiprocessing as mp
import traceback
from configparser import ConfigParser
from collections import defaultdict

# ------ Příkazy pro info na OLED ------
cmds = {
    'blk': "lsblk | awk '{print $1}'",
    'up': "s=$(cut -d. -f1 /proc/uptime); d=$((s/86400)); h=$(((s%86400)/3600)); m=$(((s%3600)/60)); "
          "if [ $d -gt 0 ]; then val=$(printf '%dd%02dh' \"$d\" \"$h\"); "
          "elif [ $h -gt 0 ]; then val=$(printf '%02dh%02dm' \"$h\" \"$m\"); "
          "else val=$(printf '%dm' \"$m\"); fi; "
          "echo Uptime: $val",
    'temp': "cat /sys/class/thermal/thermal_zone0/temp",
    'ip': "hostname -I | awk '{printf \"IP %s\", $1}'",
    'cpu': "uptime | awk '{printf \"CPU Load: %.2f %%\", $(NF-2)}'",
    'men': "free -m | awk 'NR==2{printf \"RAM: %s/%s MB\", $3,$2}'",

    'disk_root': "df -hP /        | awk 'NR==2{u=$3; t=$2; g=substr(t,length(t)); sub(/[A-Z]/,\"\",u); sub(/[A-Z]/,\"\",t); if(g==\"G\") g=\"GB\"; if(g==\"T\") g=\"TB\"; printf \"Root: %s/%s %s, %s\", u,t,g,$5}'",
    'disk_md0':  "df -hP /mnt/md0 | awk 'NR==2{u=$3; t=$2; g=substr(t,length(t)); sub(/[A-Z]/,\"\",u); sub(/[A-Z]/,\"\",t); if(g==\"G\") g=\"GB\"; if(g==\"T\") g=\"TB\"; printf \"md0: %s/%s %s, %s\", u,t,g,$5}'",
    'disk_md1':  "df -hP /mnt/md1 | awk 'NR==2{u=$3; t=$2; g=substr(t,length(t)); sub(/[A-Z]/,\"\",u); sub(/[A-Z]/,\"\",t); if(g==\"G\") g=\"GB\"; if(g==\"T\") g=\"TB\"; printf \"md1: %s/%s %s, %s\", u,t,g,$5}'",
}

# ------ Utility ------
def check_output(cmd):
    return subprocess.check_output(cmd, shell=True).decode().strip()

def check_call(cmd):
    return subprocess.check_call(cmd, shell=True)

def get_info(key):
    return check_output(cmds[key])

def get_cpu_temp():
    t = float(get_info('temp')) / 1000.0
    if conf['oled']['f-temp']:
        return "CPU Temp: {:.0f}°F".format(t * 1.8 + 32)
    return "CPU Temp: {:.1f}°C".format(t)

# ------ Konfigurace ------
def read_conf():
    c = defaultdict(dict)
    try:
        cfg = ConfigParser()
        cfg.read('/etc/rockpi-penta.conf')

        # pouze to, co používá OLED
        c['slider']['auto'] = cfg.getboolean('slider', 'auto')
        c['slider']['time'] = cfg.getfloat('slider', 'time')
        c['oled']['rotate'] = cfg.getboolean('oled', 'rotate')
        c['oled']['f-temp'] = cfg.getboolean('oled', 'f-temp')
    except Exception:
        traceback.print_exc()
        c['slider']['auto'] = True
        c['slider']['time'] = 10.0
        c['oled']['rotate'] = False
        c['oled']['f-temp'] = False
    return c

# ------ Disk info (volitelné, pro případ jiné stránky) ------
def get_disk_info(cache={}):
    if not cache.get('time') or time.time() - cache['time'] > 30:
        info = {}
        cmd = "df -h | awk '$NF==\"/\"{printf \"%s\", $5}'"
        info['root'] = check_output(cmd)
        # Přidat vlastní zařízení sem, pokud chceš víc než root:
        # for dev in ('md0','md1'): ...
        cache['info'] = list(zip(*info.items()))
        cache['time'] = time.time()
    return cache['info']

# ------ Slider helpers pro OLED ------
def slider_next(pages: dict):
    conf['idx'].value += 1
    return pages[int(conf['idx'].value) % len(pages)]

def slider_sleep():
    time.sleep(conf['slider']['time'])

# ------ Globální config ------
conf = {'disk': [], 'idx': mp.Value('d', -1), 'run': mp.Value('d', 1)}
conf.update(read_conf())
