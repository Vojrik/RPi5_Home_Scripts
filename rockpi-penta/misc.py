#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import subprocess
import multiprocessing as mp
import traceback
from configparser import ConfigParser
from collections import defaultdict

# ------ Commands used for OLED info ------
cmds = {
    'blk': "lsblk | awk '{print $1}'",
    'up': "s=$(cut -d. -f1 /proc/uptime); d=$((s/86400)); h=$(((s%86400)/3600)); m=$(((s%3600)/60)); "
          "if [ $d -gt 0 ]; then val=$(printf '%dd%02dh' \"$d\" \"$h\"); "
          "elif [ $h -gt 0 ]; then val=$(printf '%02dh%02dm' \"$h\" \"$m\"); "
          "else val=$(printf '%dm' \"$m\"); fi; "
          "echo Uptime: $val",
    'temp': "cat /sys/class/thermal/thermal_zone0/temp",
    'ip': "hostname -I | awk '{printf \"IP %s\", $1}'",
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
    if key == 'cpu':
        return get_cpu_load()
    return check_output(cmds[key])

def get_cpu_temp():
    t = float(get_info('temp')) / 1000.0
    if conf['oled']['f-temp']:
        return "CPU Temp: {:.0f}°F".format(t * 1.8 + 32)
    return "CPU Temp: {:.1f}°C".format(t)

_cpu_cache = {'time': 0.0, 'text': 'CPU Load: -- %'}

def _read_cpu_times():
    with open('/proc/stat', 'r', encoding='ascii') as fh:
        line = fh.readline()
    parts = line.split()
    if not parts or parts[0] != 'cpu':
        raise RuntimeError("Unexpected /proc/stat format")
    values = [int(v) for v in parts[1:]]
    idle = values[3]
    if len(values) > 4:
        idle += values[4]  # include iowait in idle bucket
    total = sum(values)
    return total, idle

def get_cpu_load():
    now = time.time()
    if now - _cpu_cache['time'] < 1.0:
        return _cpu_cache['text']

    total_1, idle_1 = _read_cpu_times()
    time.sleep(0.1)
    total_2, idle_2 = _read_cpu_times()

    total_delta = total_2 - total_1
    idle_delta = idle_2 - idle_1
    if total_delta <= 0:
        usage = 0.0
    else:
        usage = max(0.0, min(100.0, 100.0 * (1.0 - (idle_delta / total_delta))))

    text = "CPU Load: {:.0f} %".format(usage)
    _cpu_cache['time'] = now
    _cpu_cache['text'] = text
    return text

# ------ Konfigurace ------
def read_conf():
    c = defaultdict(dict)
    try:
        cfg = ConfigParser()
        cfg.read('/etc/rockpi-penta.conf')

        # Only load the pieces needed by the OLED module
        c['slider']['auto'] = cfg.getboolean('slider', 'auto')
        c['slider']['time'] = cfg.getfloat('slider', 'time')
        c['oled']['rotate'] = cfg.getboolean('oled', 'rotate')
        c['oled']['f-temp'] = cfg.getboolean('oled', 'f-temp')
        c['oled']['white-test'] = cfg.getboolean('oled', 'white-test', fallback=False)
        c['oled']['invert'] = cfg.getboolean('oled', 'invert', fallback=False)
    except Exception:
        traceback.print_exc()
        c['slider']['auto'] = True
        c['slider']['time'] = 10.0
        c['oled']['rotate'] = False
        c['oled']['f-temp'] = False
        c['oled']['white-test'] = False
        c['oled']['invert'] = False
    return c

# ------ Disk info (optional, for alternate pages) ------
def get_disk_info(cache={}):
    if not cache.get('time') or time.time() - cache['time'] > 30:
        info = {}
        cmd = "df -h | awk '$NF==\"/\"{printf \"%s\", $5}'"
        info['root'] = check_output(cmd)
        # Add any additional devices here if you want more than the root filesystem:
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

# ------ Global config ------
conf = {'disk': [], 'idx': mp.Value('d', -1), 'run': mp.Value('d', 1)}
conf.update(read_conf())

def reload_conf():
    conf.update(read_conf())
    return conf
