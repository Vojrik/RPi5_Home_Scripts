"""Configuration helpers for the disk checks GUI."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Dict

CONFIG_DIR = Path.home() / ".config" / "rpi5-home"
CONFIG_PATH = CONFIG_DIR / "disk_checks.json"

WEEKDAYS = [
    "Mon",
    "Tue",
    "Wed",
    "Thu",
    "Fri",
    "Sat",
    "Sun",
]


def _default_script_dir() -> str:
    return str(Path.home() / "Scripts" / "Disck_checks")


DEFAULT_CONFIG: Dict[str, Any] = {
    "script_directory": _default_script_dir(),
    "services": [
        {
            "key": "smart_daily",
            "display_name": "SMART denní kontrola",
            "service": "smart-daily.service",
            "description": "Spouští hlavní skript smart_daily.sh se sledováním SMART parametrů.",
            "category": "disk",
        },
        {
            "key": "raid_watch",
            "display_name": "RAID watch",
            "service": "raid-watch.service",
            "description": "Monitoruje stav RAID polí prostřednictvím raid_watch.sh.",
            "category": "disk",
        },
        {
            "key": "raid_check",
            "display_name": "RAID parity check",
            "service": "raid-check.service",
            "description": "Spouští měsíční kontrolu parity skriptem raid_check.sh.",
            "category": "disk",
        },
        {
            "key": "daily_bundle",
            "display_name": "Denní bundle",
            "service": "disk-daily-bundle.service",
            "description": "Wrapper pro daily_checks.sh kombinující SMART a RAID watch.",
            "category": "disk",
        },
        {
            "key": "cpu_scheduler",
            "display_name": "CPU Scheduler",
            "service": "cpu-scheduler.service",
            "description": "Služba instalovaná skriptem install_rpi5_home.sh pro řízení frekvencí CPU.",
            "category": "system",
        },
        {
            "key": "fanctrl",
            "display_name": "Fan Control",
            "service": "fanctrl.service",
            "description": "Řízení ventilátoru z modulu Fan/.",
            "category": "system",
        },
        {
            "key": "rockpi_penta",
            "display_name": "RockPi Penta",
            "service": "rockpi-penta.service",
            "description": "Řízení LED a ventilátoru pro RockPi Penta case.",
            "category": "system",
        },
    ],
    "log_settings": {
        "primary": "/var/log/Disck_checks",
        "fallback": str(Path.home() / "Disck_checks" / "logs"),
        "desktop_symlinks": True,
    },
    "email": {
        "recipient": "",
        "send_success": False,
        "subject_template": "[RPi] Disk check alert",
    },
    "smart_options": {
        "enable_short": True,
        "enable_long": True,
        "wait_for_completion": False,
        "dry_run": False,
    },
    "schedule": {
        "smart_daily": {
            "enabled": True,
            "time": "19:00",
        },
        "smart_short_weekly": {
            "enabled": True,
            "weekday": "Tue",
            "time": "17:50",
        },
        "smart_long_monthly": {
            "enabled": True,
            "weekday": "Tue",
            "time": "18:30",
            "day_constraint": "first_week",
        },
        "raid_watch": {
            "enabled": True,
            "time": "19:00",
        },
        "raid_check": {
            "enabled": True,
            "weekday": "Tue",
            "time": "08:00",
            "day_constraint": "first_week",
            "dry_run": False,
        },
    },
}


def load_config() -> Dict[str, Any]:
    """Load configuration from disk, returning defaults when missing."""
    if not CONFIG_PATH.exists():
        return deepcopy(DEFAULT_CONFIG)

    try:
        data = json.loads(CONFIG_PATH.read_text())
    except json.JSONDecodeError:
        backup = CONFIG_PATH.with_suffix(".invalid.json")
        backup.write_text(CONFIG_PATH.read_text())
        return deepcopy(DEFAULT_CONFIG)

    merged = deepcopy(DEFAULT_CONFIG)
    merged = _deep_merge(merged, data)
    return merged


def save_config(config: Dict[str, Any]) -> None:
    """Persist configuration to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False))


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


__all__ = [
    "CONFIG_PATH",
    "CONFIG_DIR",
    "DEFAULT_CONFIG",
    "WEEKDAYS",
    "load_config",
    "save_config",
]
