"""Cron helpers for the disk checks GUI."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

CRON_HEADER = "# BEGIN RPI5_DISK_CHECKS"
CRON_FOOTER = "# END RPI5_DISK_CHECKS"


def build_cron_entries(config: Dict[str, object]) -> List[str]:
    script_dir = Path(str(config.get("script_directory")))
    schedule = config.get("schedule", {})
    smart_options = config.get("smart_options", {})

    entries: List[str] = []
    smart_flags = _smart_flags(smart_options)

    if _is_enabled(schedule, "smart_daily"):
        minute, hour = _split_time(schedule["smart_daily"].get("time", "00:00"))
        command = _format_command(
            script_dir / "smart_daily.sh",
            smart_flags,
            "smart_daily",
        )
        entries.extend(
            _with_comment(
                "Denní SMART kontrola",
                _format_cron_line(minute, hour, "*", "*", "*", command),
            )
        )

    if _is_enabled(schedule, "raid_watch"):
        minute, hour = _split_time(schedule["raid_watch"].get("time", "00:00"))
        command = _format_command(script_dir / "raid_watch.sh", [], "raid_watch")
        entries.extend(
            _with_comment(
                "Denní RAID watch",
                _format_cron_line(minute, hour, "*", "*", "*", command),
            )
        )

    if smart_options.get("enable_short", True) and _is_enabled(schedule, "smart_short_weekly"):
        sched = schedule["smart_short_weekly"]
        minute, hour = _split_time(sched.get("time", "17:50"))
        dow = _weekday_to_cron(sched.get("weekday", "Tue"))
        command = _format_command(
            script_dir / "smart_daily.sh",
            ["--short", *smart_flags],
            "smart_short",
        )
        entries.extend(
            _with_comment(
                "Týdenní krátký SMART test",
                _format_cron_line(minute, hour, "*", "*", dow, command),
            )
        )

    if smart_options.get("enable_long", True) and _is_enabled(schedule, "smart_long_monthly"):
        sched = schedule["smart_long_monthly"]
        minute, hour = _split_time(sched.get("time", "18:30"))
        dow = _weekday_to_cron(sched.get("weekday", "Tue"))
        command = _wrap_first_week(
            _format_command(
                script_dir / "smart_daily.sh",
                ["--long", *smart_flags],
                "smart_long",
            ),
            sched.get("day_constraint"),
        )
        entries.extend(
            _with_comment(
                "Měsíční dlouhý SMART test",
                _format_cron_line(minute, hour, "*", "*", dow, command),
            )
        )

    if _is_enabled(schedule, "raid_check"):
        sched = schedule["raid_check"]
        minute, hour = _split_time(sched.get("time", "08:00"))
        dow = _weekday_to_cron(sched.get("weekday", "Tue"))
        raid_flags: List[str] = []
        if sched.get("dry_run"):
            raid_flags.append("--dry-run")
        command = _wrap_first_week(
            _format_command(
                script_dir / "raid_check.sh",
                raid_flags,
                "raid_check",
            ),
            sched.get("day_constraint"),
        )
        entries.extend(
            _with_comment(
                "Měsíční RAID kontrola",
                _format_cron_line(minute, hour, "*", "*", dow, command),
            )
        )

    return entries


def apply_cron(entries: Iterable[str]) -> subprocess.CompletedProcess[str]:
    entries = list(entries)
    block = "\n".join([CRON_HEADER, *entries, CRON_FOOTER, ""]) if entries else ""
    current = _read_crontab()
    updated = _replace_block(current, CRON_HEADER, CRON_FOOTER, block)
    return subprocess.run([_crontab_bin(), "-"], input=updated, text=True, capture_output=True, check=False)


def _crontab_bin() -> str:
    binary = shutil.which("crontab")
    if binary is None:
        raise FileNotFoundError("crontab binary not found")
    return binary


def _read_crontab() -> str:
    binary = _crontab_bin()
    result = subprocess.run([binary, "-l"], capture_output=True, text=True, check=False)
    if result.returncode != 0 and "no crontab for" in result.stderr:
        return ""
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Failed to read crontab")
    return result.stdout


def _replace_block(source: str, header: str, footer: str, block: str) -> str:
    lines = source.splitlines()
    new_lines: List[str] = []
    skip = False
    for line in lines:
        if line.strip() == header:
            skip = True
            continue
        if skip and line.strip() == footer:
            skip = False
            continue
        if not skip:
            new_lines.append(line)
    if block:
        new_lines.append(block.rstrip("\n"))
    return "\n".join(new_lines).rstrip("\n") + "\n"


def _is_enabled(schedule: Dict[str, object], key: str) -> bool:
    entry = schedule.get(key)
    return bool(entry and entry.get("enabled", False))


def _split_time(value: str) -> Tuple[str, str]:
    try:
        hour_str, minute_str = value.split(":", 1)
        hour = max(0, min(23, int(hour_str)))
        minute = max(0, min(59, int(minute_str)))
    except (ValueError, TypeError):
        return "0", "0"
    return str(minute), str(hour)


def _weekday_to_cron(value: str) -> str:
    mapping = {
        "sun": "0",
        "mon": "1",
        "tue": "2",
        "wed": "3",
        "thu": "4",
        "fri": "5",
        "sat": "6",
    }
    return mapping.get(value.lower(), "*")


def _smart_flags(options: Dict[str, object]) -> List[str]:
    flags: List[str] = []
    if options.get("wait_for_completion"):
        flags.append("--wait")
    if options.get("dry_run"):
        flags.append("--dry-run")
    return flags


def _format_command(script: Path, flags: List[str], log_stub: str) -> str:
    args = " ".join(flags)
    if args:
        args = " " + args
    return (
        f"nice -n 10 ionice -c3 \"{script}\"{args} >"
        f"/tmp/{log_stub}.cron.log 2>&1"
    )


def _wrap_first_week(command: str, constraint: str | None) -> str:
    if constraint != "first_week":
        return command
    return f"[ $(date +\\%d) -le 7 ] && {command}"


def _format_cron_line(minute: str, hour: str, dom: str, month: str, dow: str, command: str) -> str:
    return f"{minute} {hour} {dom} {month} {dow} {command}".strip()


def _with_comment(comment: str, line: str) -> List[str]:
    return [f"# {comment}", line]


__all__ = [
    "CRON_HEADER",
    "CRON_FOOTER",
    "build_cron_entries",
    "apply_cron",
]
