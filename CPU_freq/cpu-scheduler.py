#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Raspberry Pi CPU scheduler: čas + zátěž + fan_mode, s CLI (start/status/set/mode/override).
Obsahuje fix: po startu nastaví správný profil (PERF/IDLE) a během běhu opravuje,
pokud je max frekvence rozhozená.
"""

# ------------------------ KONFIGURACE VÝCHOZÍ ------------------------

NIGHT_START = "22:00"
NIGHT_END   = "07:00"

IDLE_MIN_KHZ = 600_000
IDLE_MAX_KHZ = 1_200_000

PERF_MIN_KHZ = 800_000
PERF_MAX_KHZ = 2_800_000

LOW_LOAD_PCT         = 30
LOW_LOAD_DURATION_S  = 600
HIGH_LOAD_PCT        = 80
HIGH_LOAD_DURATION_S = 10

CHECK_INTERVAL_S = 1.0
FAN_MODE_PATH = "/run/fan_mode"

# -------------------------------------------------------------

import time, datetime, pathlib, os, sys, argparse, json

CPUFREQ_BASE = pathlib.Path("/sys/devices/system/cpu")
CPUS = [p for p in CPUFREQ_BASE.glob("cpu[0-9]*") if (p/"cpufreq").exists()]

STATE_DIR = pathlib.Path("/var/lib/cpu-scheduler")
STATE_DIR.mkdir(parents=True, exist_ok=True)
CFG_FILE   = STATE_DIR/"config.json"
MODE_FILE  = STATE_DIR/"mode"
OVR_FILE   = STATE_DIR/"override_until"

def log(msg): print(time.strftime("%H:%M:%S"), msg, flush=True)

def _read_int(p: pathlib.Path):
    try: return int(p.read_text().strip())
    except Exception: return None

def _write_str(p: pathlib.Path, s: str):
    with open(p, "w") as f: f.write(str(s))

def cpufreq_paths(name: str): return [cpu/"cpufreq"/name for cpu in CPUS]

def available_freqs():
    sample = CPUS[0]/"cpufreq"
    av = sample/"scaling_available_frequencies"
    if av.exists():
        vals = [int(x) for x in av.read_text().split()]
        return sorted(set(vals))
    mn = _read_int(sample/"cpuinfo_min_freq")
    mx = _read_int(sample/"cpuinfo_max_freq")
    return sorted([v for v in (mn, mx) if v])

def clamp_freq(khz: int):
    av = available_freqs()
    if av: return max([f for f in av if f <= khz] or [min(av)])
    sample = CPUS[0]/"cpufreq"
    mn = _read_int(sample/"cpuinfo_min_freq") or khz
    mx = _read_int(sample/"cpuinfo_max_freq") or khz
    return min(max(khz, mn), mx)

def set_governor(name="schedutil"):
    for p in cpufreq_paths("scaling_governor"): _write_str(p, name)

def apply_profile(min_khz: int, max_khz: int, tag: str):
    tmin = clamp_freq(min_khz); tmax = clamp_freq(max_khz)
    if tmin > tmax: tmin, tmax = tmax, tmin
    for p in cpufreq_paths("scaling_min_freq"): _write_str(p, tmin)
    for p in cpufreq_paths("scaling_max_freq"): _write_str(p, tmax)
    log(f"PROFILE={tag} min={tmin} max={tmax} kHz")

def set_fan_mode(mode: str):
    try:
        with open(FAN_MODE_PATH, "w") as f: f.write(mode + "\n")
        log(f"FAN_MODE={mode}")
    except Exception as e:
        log(f"FAN_MODE write failed: {e}")

def cpu_usage_pct(interval: float):
    def snap():
        with open("/proc/stat") as f:
            for line in f:
                if line.startswith("cpu "):
                    parts = [int(x) for x in line.split()[1:]]
                    idle = parts[3] + parts[4]; total = sum(parts)
                    return idle, total
    i1, t1 = snap(); time.sleep(interval); i2, t2 = snap()
    dtotal = t2 - t1
    if dtotal <= 0: return 0.0
    didle = i2 - i1
    return 100.0 * (1.0 - didle / dtotal)

def parse_hhmm(s: str): h,m=[int(x) for x in s.split(":")]; return h,m

def in_night(now, start_s, end_s):
    sh,sm=parse_hhmm(start_s); eh,em=parse_hhmm(end_s)
    start=now.replace(hour=sh,minute=sm,second=0,microsecond=0)
    end=now.replace(hour=eh,minute=em,second=0,microsecond=0)
    if end <= start: return now>=start or now<end
    return start<=now<end

# ---------- config ----------
DEFAULT_CFG = {
  "night_start": NIGHT_START, "night_end": NIGHT_END,
  "idle_min_khz": IDLE_MIN_KHZ, "idle_max_khz": IDLE_MAX_KHZ,
  "perf_min_khz": PERF_MIN_KHZ, "perf_max_khz": PERF_MAX_KHZ,
  "low_load_pct": LOW_LOAD_PCT, "low_load_duration_s": LOW_LOAD_DURATION_S,
  "high_load_pct": HIGH_LOAD_PCT, "high_load_duration_s": HIGH_LOAD_DURATION_S,
  "check_interval_s": CHECK_INTERVAL_S, "fan_mode_path": FAN_MODE_PATH,
}

def load_cfg():
    if CFG_FILE.exists():
        try: return {**DEFAULT_CFG, **json.loads(CFG_FILE.read_text())}
        except: pass
    return DEFAULT_CFG.copy()

def save_cfg(cfg): CFG_FILE.write_text(json.dumps(cfg, indent=2,sort_keys=True))
def get_mode(): return MODE_FILE.read_text().strip() if MODE_FILE.exists() else "auto"
def set_mode(m): MODE_FILE.write_text(m+"\n")
def set_override(sec): 
    if sec<=0: OVR_FILE.unlink(missing_ok=True)
    else: OVR_FILE.write_text(str(int(time.time()+sec)))
def override_active():
    try: return time.time()<int(OVR_FILE.read_text().strip())
    except: return False

# ---------- DAEMON LOOP ----------
def daemon_loop():
    cfg=load_cfg(); global FAN_MODE_PATH; FAN_MODE_PATH=cfg["fan_mode_path"]
    try: set_governor("schedutil")
    except: pass

    in_idle=False; low_acc=0; high_acc=0; last_is_night=None
    log("START daemon")

    # INIT profil
    now0=datetime.datetime.now()
    if in_night(now0,cfg["night_start"],cfg["night_end"]):
        apply_profile(cfg["idle_min_khz"],cfg["idle_max_khz"],"IDLE(init)")
        set_fan_mode("silent"); in_idle=True
    else:
        apply_profile(cfg["perf_min_khz"],cfg["perf_max_khz"],"PERF(init)")
        set_fan_mode("normal"); in_idle=False

    while True:
        mode=get_mode(); now=datetime.datetime.now()
        is_night=in_night(now,cfg["night_start"],cfg["night_end"])
        sample=CPUS[0]/"cpufreq"; cur_max=_read_int(sample/"scaling_max_freq")

        if mode=="force-low":
            apply_profile(cfg["idle_min_khz"],cfg["idle_max_khz"],"IDLE(force)")
            set_fan_mode("silent"); time.sleep(cfg["check_interval_s"]); continue
        if mode=="force-high":
            apply_profile(cfg["perf_min_khz"],cfg["perf_max_khz"],"PERF(force)")
            set_fan_mode("normal"); time.sleep(cfg["check_interval_s"]); continue

        if last_is_night is True and is_night is False:
            apply_profile(cfg["perf_min_khz"],cfg["perf_max_khz"],"PERF(day-start)")
            set_fan_mode("normal"); in_idle=False; low_acc=high_acc=0

        if is_night and not override_active() and mode=="auto":
            if cur_max!=clamp_freq(cfg["idle_max_khz"]):
                apply_profile(cfg["idle_min_khz"],cfg["idle_max_khz"],"IDLE(night-fix)")
                set_fan_mode("silent")
            in_idle=True; low_acc=high_acc=0; last_is_night=is_night
            time.sleep(cfg["check_interval_s"]); continue

        # denní logika
        usage=cpu_usage_pct(cfg["check_interval_s"])
        log(f"usage={usage:.1f}% in_idle={in_idle} mode={mode}")

        want=clamp_freq(cfg["perf_max_khz"]) if not in_idle else clamp_freq(cfg["idle_max_khz"])
        if cur_max!=want:
            tag="PERF(fix)" if not in_idle else "IDLE(fix)"
            apply_profile(cfg["perf_min_khz"],cfg["perf_max_khz"],tag) if not in_idle else apply_profile(cfg["idle_min_khz"],cfg["idle_max_khz"],tag)

        if in_idle:
            if usage>=cfg["high_load_pct"]:
                high_acc+=cfg["check_interval_s"]
                if high_acc>=cfg["high_load_duration_s"]:
                    apply_profile(cfg["perf_min_khz"],cfg["perf_max_khz"],"PERF")
                    set_fan_mode("normal"); in_idle=False; high_acc=low_acc=0
            else: high_acc=0
        else:
            if usage<=cfg["low_load_pct"]:
                low_acc+=cfg["check_interval_s"]
                if low_acc>=cfg["low_load_duration_s"]:
                    apply_profile(cfg["idle_min_khz"],cfg["idle_max_khz"],"IDLE")
                    set_fan_mode("silent"); in_idle=True; low_acc=high_acc=0
            else: low_acc=0

        last_is_night=is_night

# ---------- CLI ----------
def cmd_status():
    cfg=load_cfg(); mode=get_mode(); ov=override_active()
    s=CPUS[0]/"cpufreq"
    st={"mode":mode,"override":ov,"cur":_read_int(s/"scaling_cur_freq"),
        "min":_read_int(s/"scaling_min_freq"),"max":_read_int(s/"scaling_max_freq"),
        "avail":available_freqs(),"cfg":cfg}
    print(json.dumps(st,indent=2,sort_keys=True))

def cmd_set(args):
    cfg=load_cfg()
    if args.night: s,e=args.night.split("-"); cfg["night_start"]=s; cfg["night_end"]=e
    for k in ["idle_min_khz","idle_max_khz","perf_min_khz","perf_max_khz",
              "low_load_pct","low_load_duration_s","high_load_pct","high_load_duration_s",
              "check_interval_s"]:
        v=getattr(args,k,None); 
        if v is not None: cfg[k]=v
    if args.fan_path: cfg["fan_mode_path"]=args.fan_path
    save_cfg(cfg); print("OK")

def cmd_mode(args):
    set_mode(args.mode); set_override(args.override or 0); print("OK")

def main():
    if os.geteuid()!=0: print("Spusť jako root",file=sys.stderr); sys.exit(1)
    if not CPUS: print("Nenalezeno cpufreq",file=sys.stderr); sys.exit(1)
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest="cmd",required=True)
    sub.add_parser("start"); sub.add_parser("status")
    pset=sub.add_parser("set"); pset.add_argument("--night"); 
    pset.add_argument("--idle-min-khz",type=int); pset.add_argument("--idle-max-khz",type=int)
    pset.add_argument("--perf-min-khz",type=int); pset.add_argument("--perf-max-khz",type=int)
    pset.add_argument("--low-load-pct",type=float); pset.add_argument("--low-load-duration-s",type=int)
    pset.add_argument("--high-load-pct",type=float); pset.add_argument("--high-load-duration-s",type=int)
    pset.add_argument("--check-interval-s",type=float); pset.add_argument("--fan-path",type=str)
    pmode=sub.add_parser("mode"); pmode.add_argument("mode",choices=["auto","day-auto","force-low","force-high"])
    pmode.add_argument("--override",type=int,default=0)
    args=ap.parse_args()
    if args.cmd=="start": daemon_loop()
    elif args.cmd=="status": cmd_status()
    elif args.cmd=="set": cmd_set(args)
    elif args.cmd=="mode": cmd_mode(args)

if __name__=="__main__": main()
