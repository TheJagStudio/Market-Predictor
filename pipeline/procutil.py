from __future__ import annotations

import os
import signal
import time
from pathlib import Path

from django.conf import settings


def pid_path(name: str) -> Path:
    return Path(settings.PID_DIR) / f"{name}.pid"


def read_pid(name: str) -> int | None:
    path = pid_path(name)
    if not path.exists():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def write_pid(name: str, pid: int) -> None:
    pid_path(name).write_text(str(pid), encoding="utf-8")


def clear_pid(name: str) -> None:
    path = pid_path(name)
    if path.exists():
        path.unlink()


def is_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def running_pid(name: str) -> int | None:
    pid = read_pid(name)
    if is_alive(pid):
        return pid
    if pid:
        clear_pid(name)
    return None


def stop_pid(name: str, timeout: float = 8.0) -> bool:
    pid = running_pid(name)
    if not pid:
        return True
    os.kill(pid, signal.SIGTERM)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not is_alive(pid):
            clear_pid(name)
            return True
        time.sleep(0.2)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass
    clear_pid(name)
    return not is_alive(pid)
