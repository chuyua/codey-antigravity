#!/usr/bin/env python3
"""macOS LaunchAgent manager for the existing native Rust Antigravity proxy.

The LaunchAgent supervises the Rust process (via execve), without a terminal.
Authorized OAuth client values are read from the user's macOS Keychain at runtime;
they never appear in the launchd plist, on the command line or in our logs.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import time
import urllib.error
import urllib.request

LABEL = "com.chuyua.codey-antigravity.proxy"
SERVICE_ID = "com.chuyua.codey-antigravity.oauth-client-id"
SERVICE_SECRET = "com.chuyua.codey-antigravity.oauth-client-secret"
ROOT = Path(__file__).resolve().parent
HOME = Path.home()
AUTH = HOME / ".pi" / "agent" / "auth.json"
EXE = ROOT / "bin" / "antigravity-proxy"
PLIST = HOME / "Library" / "LaunchAgents" / (LABEL + ".plist")
STATE = HOME / "Library" / "Application Support" / "CodeyAntigravity" / "runtime"
URL = "http://127.0.0.1:28787/health"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def mac_only() -> None:
    if sys.platform != "darwin" or os.geteuid() == 0:
        raise RuntimeError("Run as a normal logged-in macOS user, not root")


def launch_domain() -> str:
    return f"gui/{os.getuid()}"


def target() -> str:
    return launch_domain() + "/" + LABEL


def command(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        list(args), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, check=False, timeout=15, text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"System service command failed: {args[0]} {args[1]}")
    return result


def loaded() -> bool:
    return command("/bin/launchctl", "print", target(), check=False).returncode == 0


def healthy() -> bool:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(URL, timeout=2) as response:
            raw = response.read(2049)
            if len(raw) > 2048 or response.status != 200:
                return False
            obj = json.loads(raw)
            return isinstance(obj, dict) and obj.get("ok") is True and obj.get("service") == "codey-antigravity-proxy"
    except (ValueError, OSError, urllib.error.URLError):
        return False


def keychain_value(service: str) -> str:
    if sys.platform == "darwin":
        import pwd
        user = pwd.getpwuid(os.getuid()).pw_name
    else:
        user = getpass.getuser()  # Unit-test fallback on non-macOS.
    result = command(
        "/usr/bin/security", "find-generic-password",
        "-a", user, "-s", service, "-w", check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError("Missing authorized OAuth client entry in macOS Keychain: " + service)
    value = result.stdout.rstrip("\r\n")
    if not value or any(ord(ch) < 32 for ch in value):
        raise RuntimeError("Invalid OAuth client entry in macOS Keychain: " + service)
    return value


def authorized_credentials() -> tuple[str, str]:
    return keychain_value(SERVICE_ID), keychain_value(SERVICE_SECRET)


def expected_plist() -> dict:
    return {
        "Label": LABEL,
        "ProgramArguments": [str(Path(sys.executable).resolve()), str(ROOT / "macos_proxy.py"), "serve"],
        "WorkingDirectory": str(ROOT),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 30,
        "ProcessType": "Background",
        "Umask": 0o077,
        "StandardOutPath": str(STATE / "launchd.stdout.log"),
        "StandardErrorPath": str(STATE / "launchd.stderr.log"),
    }


def check_plist() -> bool:
    if not PLIST.exists() and not PLIST.is_symlink():
        return False
    if PLIST.is_symlink() or not PLIST.is_file() or PLIST.stat().st_uid != os.getuid():
        raise RuntimeError("LaunchAgent path is not a regular file owned by this user")
    try:
        content = plistlib.loads(PLIST.read_bytes())
    except (ValueError, OSError, TypeError) as exc:
        raise RuntimeError("Cannot read existing LaunchAgent") from exc
    if content != expected_plist():
        raise RuntimeError("Existing LaunchAgent differs; refusing to overwrite or manage")
    return True


def prepare_runtime() -> None:
    if STATE.is_symlink():
        raise RuntimeError("Refusing symlink runtime directory")
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not STATE.is_dir() or STATE.stat().st_uid != os.getuid():
        raise RuntimeError("Runtime directory is not owned by the current user")
    os.chmod(STATE, 0o700)
    for name in ("launchd.stdout.log", "launchd.stderr.log"):
        path = STATE / name
        if path.is_symlink():
            raise RuntimeError("Unsafe symlink log path: " + name)
        if path.exists():
            if not path.is_file() or path.stat().st_uid != os.getuid():
                raise RuntimeError("Unsafe existing log file: " + name)
            os.chmod(path, 0o600)
        else:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)


def preflight() -> None:
    mac_only()
    if not EXE.is_file() or not os.access(EXE, os.X_OK):
        raise RuntimeError("Install the macOS arm64 portable bundle with the Rust executable first")
    if not AUTH.is_file():
        raise RuntimeError("Google OAuth auth.json is missing; login manually first")
    if command(str(EXE), "--version").stdout.strip() != "antigravity-proxy 0.10.0":
        raise RuntimeError("Unexpected Rust proxy version")
    authorized_credentials()  # Never stores or prints the secrets.


def write_plist() -> bool:
    if check_plist():
        return False
    if PLIST.parent.is_symlink():
        raise RuntimeError("Unsafe symlink LaunchAgents directory")
    PLIST.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    data = plistlib.dumps(expected_plist(), fmt=plistlib.FMT_XML, sort_keys=True)
    fd = os.open(PLIST, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
    except BaseException:
        PLIST.unlink(missing_ok=True)
        raise
    return True


def wait_ready() -> bool:
    for _ in range(30):
        if healthy():
            return True
        time.sleep(0.25)
    return False


def enable() -> str:
    preflight()
    if healthy() and not loaded():
        raise RuntimeError("Port 28787 is already in use by a service not managed by this LaunchAgent")
    prepare_runtime()
    new_file = write_plist()
    if loaded():
        if not healthy():
            raise RuntimeError("LaunchAgent is loaded but unhealthy; inspect the private stderr log")
        return "macOS LaunchAgent 已运行"
    try:
        command("/bin/launchctl", "bootstrap", launch_domain(), str(PLIST))
    except RuntimeError:
        if new_file:
            PLIST.unlink(missing_ok=True)
        raise
    if not wait_ready():
        raise RuntimeError("LaunchAgent loaded but proxy is not healthy; inspect launchd.stderr.log")
    return "macOS 后台代理已启动，并启用登录后自动运行"


def start() -> str:
    mac_only()
    if not check_plist():
        raise RuntimeError("Run autorun-on first to install the user's LaunchAgent")
    preflight()
    if loaded():
        if not healthy():
            raise RuntimeError("LaunchAgent is loaded but proxy is not healthy")
        return "macOS 后台代理已运行"
    if healthy():
        raise RuntimeError("Port 28787 belongs to another running instance; refusing takeover")
    command("/bin/launchctl", "bootstrap", launch_domain(), str(PLIST))
    if not wait_ready():
        raise RuntimeError("LaunchAgent started but proxy health failed")
    return "macOS 后台代理已启动"


def stop() -> str:
    mac_only()
    if not check_plist():
        raise RuntimeError("LaunchAgent has not been installed")
    if loaded():
        command("/bin/launchctl", "bootout", target())
    for _ in range(24):
        if not healthy():
            return "macOS 后台代理已停止；下次登录仍会自动启动"
        time.sleep(0.25)
    raise RuntimeError("Port 28787 is still occupied, possibly by a different instance")


def disable() -> str:
    mac_only()
    if not check_plist():
        return "没有本工具安装的 LaunchAgent"
    if loaded():
        command("/bin/launchctl", "bootout", target())
    PLIST.unlink()
    return "已关闭并移除本用户的 LaunchAgent，账号与模型数据未更改"


def restart() -> str:
    mac_only()
    if not check_plist():
        raise RuntimeError("LaunchAgent has not been installed")
    preflight()
    if healthy() and not loaded():
        raise RuntimeError("Port 28787 belongs to an unmanaged service")
    if loaded():
        command("/bin/launchctl", "kickstart", "-k", target())
    else:
        command("/bin/launchctl", "bootstrap", launch_domain(), str(PLIST))
    if not wait_ready():
        raise RuntimeError("LaunchAgent restarted but proxy health failed")
    return "macOS 后台代理重启成功"


def serve() -> None:
    # This Python process is *replaced* by Rust, so launchd supervises the
    # native proxy directly, without any additional resident Python service.
    mac_only()
    preflight()
    prepare_runtime()
    client_id, client_secret = authorized_credentials()
    env = os.environ.copy()
    env["ANTIGRAVITY_CLIENT_ID"] = client_id
    env["ANTIGRAVITY_CLIENT_SECRET"] = client_secret
    env["PI_CODING_AGENT_DIR"] = str(AUTH.parent)
    env["AG_IMAGE_DIR"] = str(STATE / "images")
    env["NO_PROXY"] = ",".join(dict.fromkeys(
        [value for value in env.get("NO_PROXY", "").split(",") if value]
        + ["127.0.0.1", "localhost", "::1"]))
    (STATE / "images").mkdir(mode=0o700, parents=True, exist_ok=True)
    os.execve(str(EXE), [str(EXE), "serve", "--port", "28787", "--auth", str(AUTH)], env)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="macOS LaunchAgent 管理 Codey Antigravity Rust 代理")
    parser.add_argument("action", choices=("serve", "start", "stop", "restart", "status",
                                          "autorun-on", "autorun-off", "autorun-status"))
    args = parser.parse_args(argv)
    try:
        if args.action == "serve":
            serve()
            return 0
        mac_only()
        if args.action == "autorun-on":
            result = enable()
        elif args.action == "autorun-off":
            result = disable()
        elif args.action == "autorun-status":
            result = "登录自启动：已配置" if check_plist() else "登录自启动：未配置"
        elif args.action == "start":
            result = start()
        elif args.action == "stop":
            result = stop()
        elif args.action == "restart":
            result = restart()
        else:
            configured = check_plist()
            running = loaded()
            live = healthy()
            result = f"LaunchAgent 已配置={configured} 已加载={running} 代理健康={live}"
            print(result)
            return 0 if running and live else 3
        print(result)
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        # Do not include OAuth secrets in error text.
        print(f"macOS 代理操作失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
