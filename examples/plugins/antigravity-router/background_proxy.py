#!/usr/bin/env python3
"""Windowless Windows proxy control. Delegates ownership checks to PowerShell scripts."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent
HEALTH = "http://127.0.0.1:28787/health"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "CodeyAntigravityProxy28787"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def healthy() -> bool:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(HEALTH, timeout=2) as response:
            if response.status != 200:
                return False
            raw = response.read(2049)
            if len(raw) > 2048:
                return False
            data = json.loads(raw)
            return isinstance(data, dict) and data.get("ok") is True and data.get("service") == "codey-antigravity-proxy"
    except (ValueError, OSError, urllib.error.URLError):
        return False


def log_event(event: str) -> None:
    state = ROOT / ".runtime"
    state.mkdir(exist_ok=True)
    log = state / "background-proxy.log"
    # Never log OAuth credentials, request bodies, environment values or subprocess output.
    if log.exists() and log.stat().st_size > 256 * 1024:
        log.write_text("", encoding="utf-8")
    with log.open("a", encoding="utf-8") as stream:
        stream.write(datetime.now(timezone.utc).isoformat() + " " + event + "\n")


def call_existing_script(action: str) -> None:
    if os.name != "nt":
        raise RuntimeError("Only Windows is supported")
    script = ROOT / ("start-proxy.ps1" if action == "start" else "stop-proxy.ps1")
    if not script.is_file():
        raise RuntimeError("Missing bundled PowerShell startup/shutdown script")
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(script)],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        timeout=35,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("Proxy script returned a failure; use the original script for diagnostics")


def start() -> str:
    if healthy():
        log_event("already-running")
        return "后台代理已运行，127.0.0.1:28787"
    call_existing_script("start")
    if not healthy():
        raise RuntimeError("Started but failed proxy health identity validation")
    log_event("started-hidden")
    return "后台代理已静默启动，127.0.0.1:28787"


def stop() -> str:
    # The existing PowerShell stop script validates PID, creation time and port identity.
    call_existing_script("stop")
    if healthy():
        raise RuntimeError("Proxy is still healthy after stopping; refusing further action")
    log_event("stopped")
    return "后台代理已安全停止"


def startup_command() -> str:
    exe = Path(sys.executable)
    if exe.name.lower() == "python.exe":
        exe = exe.with_name("pythonw.exe")
    elif exe.name.lower() not in ("pythonw.exe",):
        raise RuntimeError("Expected a CPython python.exe or pythonw.exe interpreter")
    if not exe.is_file():
        raise RuntimeError("pythonw.exe is not installed next to Python")
    script = ROOT / "background_proxy.pyw"
    if not script.is_file():
        raise RuntimeError("Missing Python windowless entrypoint")
    return f'"{exe}" "{script}"'


def autorun(action: str) -> str:
    if os.name != "nt":
        raise RuntimeError("Login startup is Windows only")
    import winreg
    expected = startup_command()
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        try:
            current, kind = winreg.QueryValueEx(key, RUN_NAME)
        except FileNotFoundError:
            current, kind = None, None
        if current is not None and (kind != winreg.REG_SZ or current != expected):
            raise RuntimeError("Existing startup entry differs; refusing to overwrite")
        if action == "on":
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, expected)
            log_event("autorun-enabled")
            return "已启用当前用户登录后无窗口启动（HKCU Run，不使用计划任务）"
        if action == "off":
            if current == expected:
                winreg.DeleteValue(key, RUN_NAME)
                log_event("autorun-disabled")
            return "已关闭本工具的登录自动启动项"
        if action == "status":
            return "登录自动启动：已启用" if current == expected else "登录自动启动：未启用"
    raise ValueError("Unknown autorun command")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Antigravity 无窗口后台管理器 (Windows)")
    parser.add_argument("command", nargs="?", default="start",
                        choices=("start", "stop", "restart", "status",
                                 "autorun-on", "autorun-off", "autorun-status"))
    options = parser.parse_args(argv)
    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if sys.stderr is not None and hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    try:
        command = options.command
        status_code = 0
        if command == "status":
            live = healthy()
            message = "后台代理运行正常，127.0.0.1:28787" if live else "后台代理未响应，127.0.0.1:28787"
            status_code = 0 if live else 3
        elif command.startswith("autorun-"):
            message = autorun(command.removeprefix("autorun-"))
        elif command == "start":
            message = start()
        elif command == "stop":
            message = stop()
        else:
            stop()
            message = start()
        if sys.stdout is not None:
            print(message)
        return status_code
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        try:
            log_event("failed-" + options.command + "-" + type(error).__name__)
        except OSError:
            pass
        if sys.stderr is not None:
            print("操作失败：" + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
