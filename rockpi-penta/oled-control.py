#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
import re
import subprocess
from pathlib import Path
from configparser import ConfigParser

CONF_PATH = Path("/etc/rockpi-penta.conf")


def _read_white_test():
    cfg = ConfigParser()
    cfg.read(CONF_PATH)
    return cfg.getboolean("oled", "white-test", fallback=False)


def _set_white_test(enabled: bool):
    text = CONF_PATH.read_text(encoding="ascii", errors="ignore")
    lines = text.splitlines()
    section_re = re.compile(r"^\s*\[(?P<name>[^\]]+)\]\s*$")

    oled_idx = None
    for i, line in enumerate(lines):
        m = section_re.match(line)
        if m and m.group("name").strip().lower() == "oled":
            oled_idx = i
            break

    value = "true" if enabled else "false"
    if oled_idx is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(["[oled]", f"white-test = {value}"])
    else:
        end_idx = len(lines)
        for i in range(oled_idx + 1, len(lines)):
            if section_re.match(lines[i]):
                end_idx = i
                break

        key_re = re.compile(r"^\s*white-test\s*=")
        for i in range(oled_idx + 1, end_idx):
            if key_re.match(lines[i]):
                lines[i] = f"white-test = {value}"
                break
        else:
            lines.insert(oled_idx + 1, f"white-test = {value}")

    content = "\n".join(lines)
    if text.endswith("\n"):
        content += "\n"
    CONF_PATH.write_text(content, encoding="ascii")


def _maybe_restart(restart: bool):
    if not restart:
        return
    subprocess.run(["systemctl", "restart", "rockpi-penta.service"], check=False)


def _require_root():
    if os.geteuid() != 0:
        raise SystemExit("Run as root (sudo) to modify /etc/rockpi-penta.conf.")


def _cmd_status(_args):
    enabled = _read_white_test()
    print(f"white-test={str(enabled).lower()}")


def _cmd_full_white(args):
    _require_root()
    enabled = args.state == "on"
    _set_white_test(enabled)
    _maybe_restart(args.restart)
    print(f"white-test set to {str(enabled).lower()}")


def main():
    parser = argparse.ArgumentParser(description="OLED helper for rockpi-penta")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_status = sub.add_parser("status", help="Show OLED white-test state")
    p_status.set_defaults(func=_cmd_status)

    p_full = sub.add_parser("full-white", help="Toggle full white OLED test mode")
    p_full.add_argument("state", choices=["on", "off"])
    p_full.add_argument("--restart", action="store_true", help="Restart rockpi-penta.service")
    p_full.set_defaults(func=_cmd_full_white)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
