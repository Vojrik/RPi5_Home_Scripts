"""Helpers for querying and toggling systemd services."""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class ServiceState:
    name: str
    enabled: Optional[bool]
    active: Optional[bool]
    description: str = ""
    error: Optional[str] = None


SYSTEMCTL = shutil.which("systemctl")


def systemctl_available() -> bool:
    return SYSTEMCTL is not None


def _run_systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    if not systemctl_available():
        raise FileNotFoundError("systemctl binary not found")
    return subprocess.run(
        [SYSTEMCTL, *args],
        check=False,
        capture_output=True,
        text=True,
    )


def get_service_state(service: str) -> ServiceState:
    if not systemctl_available():
        return ServiceState(service, None, None, error="systemctl is not available")

    enabled = None
    active = None
    error_messages = []

    result = _run_systemctl("is-enabled", service)
    if result.returncode == 0:
        enabled = True
    elif result.returncode == 1 and result.stdout.strip() == "disabled":
        enabled = False
    else:
        enabled = None
        output = result.stderr.strip() or result.stdout.strip()
        if output:
            error_messages.append(output)

    result = _run_systemctl("is-active", service)
    if result.returncode == 0:
        active = True
    elif result.returncode == 3 and result.stdout.strip() == "inactive":
        active = False
    else:
        active = None
        output = result.stderr.strip() or result.stdout.strip()
        if output:
            error_messages.append(output)

    error = "\n".join(error_messages) if error_messages else None
    return ServiceState(service, enabled, active, error=error)


def set_service_enabled(service: str, enabled: bool) -> subprocess.CompletedProcess[str]:
    if enabled:
        return _run_systemctl("enable", "--now", service)
    return _run_systemctl("disable", "--now", service)


__all__ = [
    "ServiceState",
    "systemctl_available",
    "get_service_state",
    "set_service_enabled",
]
