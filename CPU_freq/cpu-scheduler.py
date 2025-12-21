#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RPi CPU scheduler v2: day/night switching + load monitoring with hard enforcement of governor and min/max limits.
Works with overclocking (arm_freq=2800 in /boot/firmware/config.txt): uses 'schedutil' during the day, 'powersave' when idle.
"""

import time, datetime, pathlib, os, sys, argparse, json

# -------- default configuration --------
NIGHT_START = "22:00"
NIGHT_END   = "08:00"

IDLE_MIN_KHZ = 600_000
IDLE_MAX_KHZ = 1_200_000
IDLE_GOVERNOR = "powersave"

PERF_MIN_KHZ = 800_000
PERF_MAX_KHZ = 2_800_000
PERF_GOVERNOR = "schedutil"

LOW_LOAD_PCT         = 35
LOW_LOAD_DURATION_S  = 300
HIGH_LOAD_PCT        = 80
HIGH_LOAD_DURATION_S = 10

CHECK_INTERVAL_S = 1.0
FAN_MODE_PATH = "/run/fan_mode"
# -------------------------------------

CPUFREQ_BASE = pathlib.Path("/sys/devices/system/cpu")
CPUS = [p for p in CPUFREQ_BASE.glob("cpu[0-9]*") if (p/"cpufreq").exists()]

STATE_DIR = pathlib.Path("/var/lib/cpu-scheduler"); STATE_DIR.mkdir(parents=True, exist_ok=True)
CFG_FILE   = STATE_DIR/"config.json"
MODE_FILE  = STATE_DIR/"mode"
OVR_FILE   = STATE_DIR/"override_until"
LAST_WRITTEN = {"gov": None, "min": None, "max": None, "fan": None, "force_high_fallback": None}
_AVAILABLE_GOVS = None

def log(msg): print(time.strftime("%H:%M:%S"), msg, flush=True)

def _read_int(p: pathlib.Path):
    try: return int(p.read_text().strip())
    except: return None

def _write_str(p: pathlib.Path, s: str):
    with open(p, "w") as f: f.write(str(s))

def cpufreq_paths(name: str): return [cpu/"cpufreq"/name for cpu in CPUS]

def available_governors():
    global _AVAILABLE_GOVS
    if _AVAILABLE_GOVS is None:
        sample = CPUS[0]/"cpufreq"
        govs_path = sample/"scaling_available_governors"
        if govs_path.exists():
            _AVAILABLE_GOVS = govs_path.read_text().strip().split()
        else:
            _AVAILABLE_GOVS = []
    return _AVAILABLE_GOVS

def available_freqs():
    sample = CPUS[0]/"cpufreq"
    av = sample/"scaling_available_frequencies"
    if av.exists():
        vals = [int(x) for x in av.read_text().split()]
        return sorted(set(vals))
    mn = _read_int(sample/"cpuinfo_min_freq")
    mx = _read_int(sample/"cpuinfo_max_freq")
    return [v for v in (mn, mx) if v]

def clamp_freq(khz: int):
    av = available_freqs()
    if not av: return khz
    av_sorted = sorted(set(av))
    # choose the closest value <= requested, otherwise fall back to minimum
    candidates = [f for f in av_sorted if f <= khz]
    return candidates[-1] if candidates else av_sorted[0]

def set_governor(name: str):
    for p in cpufreq_paths("scaling_governor"):
        try: _write_str(p, name)
        except: pass

def ensure_governor(name: str):
    govs = available_governors()
    if name and govs and name not in govs:
        log(f"WARNING: requested governor '{name}' not supported, keeping current")
        return
    changed = False
    for p in cpufreq_paths("scaling_governor"):
        try:
            cur = p.read_text().strip()
            if cur != name:
                _write_str(p, name)
                changed = True
        except: pass
    if changed or LAST_WRITTEN["gov"] != name:
        log(f"GOVERNOR={name}")
        LAST_WRITTEN["gov"] = name

def pick_force_high_governor(cfg):
    gov = cfg["perf_governor"]
    if gov not in ("performance", "userspace"):
        return gov
    govs = available_governors()
    for cand in ("schedutil", "ondemand", "conservative"):
        if cand in govs:
            if LAST_WRITTEN.get("force_high_fallback") != cand:
                log(f"NOTICE: force-high requested with fixed governor '{gov}', using '{cand}' instead")
                LAST_WRITTEN["force_high_fallback"] = cand
            return cand
    if LAST_WRITTEN.get("force_high_fallback") != "none":
        log(f"WARNING: force-high requested with fixed governor '{gov}', but no scaling governor available; keeping current")
        LAST_WRITTEN["force_high_fallback"] = "none"
    return None

def enforce_min_max(min_khz: int, max_khz: int, tag: str):
    tmin = clamp_freq(min_khz)
    tmax = clamp_freq(max_khz)
    if tmin > tmax: tmin, tmax = tmax, tmin

    # the Pi occasionally overwrites max -> enforce every time but log only on change
    cur_min = _read_int(cpufreq_paths("scaling_min_freq")[0]) or 0
    cur_max = _read_int(cpufreq_paths("scaling_max_freq")[0]) or 0
    for p in cpufreq_paths("scaling_min_freq"): _write_str(p, tmin)
    for p in cpufreq_paths("scaling_max_freq"): _write_str(p, tmax)

    if LAST_WRITTEN["min"] != tmin or LAST_WRITTEN["max"] != tmax:
        log(f"PROFILE={tag} min={tmin} max={tmax} kHz")
        LAST_WRITTEN["min"], LAST_WRITTEN["max"] = tmin, tmax
    else:
        # if someone changed the limits externally, surface that information
        if cur_min != tmin or cur_max != tmax:
            log(f"NOTICE: external change detected (was min={cur_min} max={cur_max}), re-enforced to min={tmin} max={tmax}")

def set_fan_mode(mode: str):
    # Log only when the value changes; silently re-enforce or log NOTICE when altered externally
    prev = LAST_WRITTEN.get("fan")
    if prev != mode:
        try:
            with open(FAN_MODE_PATH, "w") as f: f.write(mode + "\n")
            log(f"FAN_MODE={mode}")
        except Exception as e:
            log(f"FAN_MODE write failed: {e}")
        LAST_WRITTEN["fan"] = mode
    else:
        # Same desired state - verify that nobody overwrote the backing file
        try:
            cur = pathlib.Path(FAN_MODE_PATH).read_text().strip()
            if cur != mode:
                try:
                    with open(FAN_MODE_PATH, "w") as f: f.write(mode + "\n")
                    log(f"NOTICE: FAN_MODE external change detected (was '{cur}'), re-enforced to '{mode}'")
                except Exception as e:
                    log(f"FAN_MODE re-enforce failed: {e}")
                LAST_WRITTEN["fan"] = mode
        except Exception:
            pass

def cpu_usage_pct(interval: float):
    """Return CPU busy percentage over the provided interval using /proc/stat."""
    def snap():
        with open("/proc/stat", "r", encoding="ascii") as f:
            for line in f:
                if line.startswith("cpu "):
                    parts = [int(x) for x in line.split()[1:]]
                    if len(parts) < 4:
                        raise RuntimeError("Unexpected /proc/stat format")
                    idle = parts[3]
                    if len(parts) > 4:
                        idle += parts[4]  # account for iowait
                    total = sum(parts)
                    return total, idle
        raise RuntimeError("Missing cpu line in /proc/stat")

    interval = max(0.05, float(interval))
    total_1, idle_1 = snap()
    time.sleep(interval)
    total_2, idle_2 = snap()

    total_delta = total_2 - total_1
    if total_delta <= 0:
        return 0.0
    idle_delta = idle_2 - idle_1
    usage = 100.0 * (1.0 - (idle_delta / total_delta))
    return max(0.0, min(100.0, usage))

def parse_hhmm(s: str): h,m=[int(x) for x in s.split(":")]; return h,m

def in_night(now, start_s, end_s):
    sh,sm=parse_hhmm(start_s); eh,em=parse_hhmm(end_s)
    start=now.replace(hour=sh,minute=sm,second=0,microsecond=0)
    end=now.replace(hour=eh,minute=em,second=0,microsecond=0)
    if end <= start: return now>=start or now<end
    return start<=now<end

DEFAULT_CFG = {
  "night_start": NIGHT_START, "night_end": NIGHT_END,
  "idle_min_khz": IDLE_MIN_KHZ, "idle_max_khz": IDLE_MAX_KHZ,
  "perf_min_khz": PERF_MIN_KHZ, "perf_max_khz": PERF_MAX_KHZ,
  "idle_governor": IDLE_GOVERNOR, "perf_governor": PERF_GOVERNOR,
  "low_load_pct": LOW_LOAD_PCT, "low_load_duration_s": LOW_LOAD_DURATION_S,
  "high_load_pct": HIGH_LOAD_PCT, "high_load_duration_s": HIGH_LOAD_DURATION_S,
  "check_interval_s": CHECK_INTERVAL_S, "fan_mode_path": FAN_MODE_PATH,
}

def load_cfg():
    if CFG_FILE.exists():
        try: 
            cfg = {**DEFAULT_CFG, **json.loads(CFG_FILE.read_text())}
            return cfg
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

def daemon_loop():
    cfg=load_cfg(); global FAN_MODE_PATH; FAN_MODE_PATH=cfg["fan_mode_path"]
    log("START daemon")

    # init: set profile based on day/night
    now0=datetime.datetime.now()
    if in_night(now0,cfg["night_start"],cfg["night_end"]):
        ensure_governor(cfg["idle_governor"])
        enforce_min_max(cfg["idle_min_khz"],cfg["idle_max_khz"],"IDLE(init)")
        set_fan_mode("silent"); in_idle=True
    else:
        ensure_governor(cfg["perf_governor"])
        enforce_min_max(cfg["perf_min_khz"],cfg["perf_max_khz"],"PERF(init)")
        set_fan_mode("normal"); in_idle=False

    low_acc=0; high_acc=0; last_is_night=None

    while True:
        mode=get_mode(); now=datetime.datetime.now()
        is_night=in_night(now,cfg["night_start"],cfg["night_end"])

        # Day/night switching
        if last_is_night is True and is_night is False:
            ensure_governor(cfg["perf_governor"])
            enforce_min_max(cfg["perf_min_khz"],cfg["perf_max_khz"],"PERF(day-start)")
            set_fan_mode("normal"); in_idle=False; low_acc=high_acc=0

        if is_night and not override_active() and mode=="auto":
            ensure_governor(cfg["idle_governor"])
            enforce_min_max(cfg["idle_min_khz"],cfg["idle_max_khz"],"IDLE(night)")
            set_fan_mode("silent"); in_idle=True; low_acc=high_acc=0; last_is_night=is_night
            time.sleep(cfg["check_interval_s"]); continue

        # Modes with explicit enforcement
        if mode=="force-low":
            ensure_governor(cfg["idle_governor"])
            enforce_min_max(cfg["idle_min_khz"],cfg["idle_max_khz"],"IDLE(force)")
            set_fan_mode("silent"); in_idle=True
            time.sleep(cfg["check_interval_s"]); last_is_night=is_night; continue
        if mode=="force-high":
            gov = pick_force_high_governor(cfg)
            if gov:
                ensure_governor(gov)
            # Use the widest safe range so max acts as a ceiling, not a fixed target.
            enforce_min_max(cfg["idle_min_khz"],cfg["perf_max_khz"],"PERF(force-limit)")
            set_fan_mode("normal"); in_idle=False
            time.sleep(cfg["check_interval_s"]); last_is_night=is_night; continue
        # day-auto = automatic switching during the day, force performance profile at night
        if mode=="day-auto" and is_night:
            ensure_governor(cfg["perf_governor"])
            enforce_min_max(cfg["perf_min_khz"],cfg["perf_max_khz"],"PERF(day-auto)")
            set_fan_mode("normal"); in_idle=False
            time.sleep(cfg["check_interval_s"]); last_is_night=is_night; continue

        # Guard and re-enforce limits in auto mode
        if in_idle:
            ensure_governor(cfg["idle_governor"])
            enforce_min_max(cfg["idle_min_khz"],cfg["idle_max_khz"],"IDLE(enforce)")
        else:
            ensure_governor(cfg["perf_governor"])
            enforce_min_max(cfg["perf_min_khz"],cfg["perf_max_khz"],"PERF(enforce)")

        # Load-based adaptation (daytime or when night auto mode is overridden)
        usage=cpu_usage_pct(cfg["check_interval_s"])

        if in_idle:
            if usage>=cfg["high_load_pct"]:
                high_acc+=cfg["check_interval_s"]
                if high_acc>=cfg["high_load_duration_s"]:
                    ensure_governor(cfg["perf_governor"])
                    enforce_min_max(cfg["perf_min_khz"],cfg["perf_max_khz"],"PERF(switch)")
                    set_fan_mode("normal"); in_idle=False; high_acc=low_acc=0
            else: high_acc=0
        else:
            if usage<=cfg["low_load_pct"]:
                low_acc+=cfg["check_interval_s"]
                if low_acc>=cfg["low_load_duration_s"]:
                    ensure_governor(cfg["idle_governor"])
                    enforce_min_max(cfg["idle_min_khz"],cfg["idle_max_khz"],"IDLE(switch)")
                    set_fan_mode("silent"); in_idle=True; low_acc=high_acc=0
            else: low_acc=0

        last_is_night=is_night

# ---------- CLI ----------
def cmd_status():
    cfg=load_cfg(); mode=get_mode(); ov=override_active()
    s=CPUS[0]/"cpufreq"
    st={"mode":mode,"override":ov,"cur":_read_int(s/"scaling_cur_freq"),
        "min":_read_int(s/"scaling_min_freq"),"max":_read_int(s/"scaling_max_freq"),
        "gov": (CPUS[0]/"cpufreq"/"scaling_governor").read_text().strip(),
        "avail":available_freqs(),"avail_governors":available_governors(),"cfg":cfg}
    print(json.dumps(st,indent=2,sort_keys=True))

def cmd_set(args):
    cfg=load_cfg()
    if args.night: s,e=args.night.split("-"); cfg["night_start"]=s; cfg["night_end"]=e
    govs=available_governors()
    if args.idle_governor is not None:
        if govs and args.idle_governor not in govs:
            print(f"Governor '{args.idle_governor}' is not available: {govs}",file=sys.stderr)
            sys.exit(1)
        cfg["idle_governor"]=args.idle_governor
    if args.perf_governor is not None:
        if govs and args.perf_governor not in govs:
            print(f"Governor '{args.perf_governor}' is not available: {govs}",file=sys.stderr)
            sys.exit(1)
        cfg["perf_governor"]=args.perf_governor
    for k in ["idle_min_khz","idle_max_khz","perf_min_khz","perf_max_khz",
              "idle_governor","perf_governor",
              "low_load_pct","low_load_duration_s","high_load_pct","high_load_duration_s",
              "check_interval_s"]:
        v=getattr(args,k,None); 
        if v is not None: cfg[k]=v
    if args.fan_path: cfg["fan_mode_path"]=args.fan_path
    CFG_FILE.write_text(json.dumps(cfg, indent=2,sort_keys=True)); print("OK")

def cmd_mode(args):
    set_mode(args.mode); set_override(args.override or 0); print("OK")

def main():
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest="cmd",required=True)
    sub.add_parser("start"); sub.add_parser("status")
    pset=sub.add_parser("set"); pset.add_argument("--night"); 
    pset.add_argument("--idle-min-khz",type=int); pset.add_argument("--idle-max-khz",type=int)
    pset.add_argument("--perf-min-khz",type=int); pset.add_argument("--perf-max-khz",type=int)
    pset.add_argument("--idle-governor",type=str); pset.add_argument("--perf-governor",type=str)
    pset.add_argument("--low-load-pct",type=float); pset.add_argument("--low-load-duration-s",type=int)
    pset.add_argument("--high-load-pct",type=float); pset.add_argument("--high-load-duration-s",type=int)
    pset.add_argument("--check-interval-s",type=float); pset.add_argument("--fan-path",type=str)
    pmode=sub.add_parser("mode"); pmode.add_argument("mode",choices=["auto","day-auto","force-low","force-high"])
    pmode.add_argument("--override",type=int,default=0)
    args=ap.parse_args()
    if args.cmd!="status" and os.geteuid()!=0:
        print("Run as root (except for 'status')",file=sys.stderr); sys.exit(1)
    if not CPUS: print("Nenalezeno cpufreq",file=sys.stderr); sys.exit(1)
    if args.cmd=="start": daemon_loop()
    elif args.cmd=="status": cmd_status()
    elif args.cmd=="set": cmd_set(args)
    elif args.cmd=="mode": cmd_mode(args)

if __name__=="__main__": main()
