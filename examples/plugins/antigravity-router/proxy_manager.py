#!/usr/bin/env python3
"""Cross-platform Codey Antigravity proxy manager (stdlib-only).

One command-line contract for Windows, macOS, and Linux. Keep the native Rust
proxy and platform-native process supervisor. Never bundle OAuth secrets.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
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

ROOT = Path(__file__).resolve().parent
HOME = Path.home()
URL = "http://127.0.0.1:28787/health"
HEALTH = URL
LABEL = "com.chuyua.codey-antigravity.proxy"
SERVICE_ID = "com.chuyua.codey-antigravity.oauth-client-id"
SERVICE_SECRET = "com.chuyua.codey-antigravity.oauth-client-secret"
AUTH = HOME / ".pi" / "agent" / "auth.json"
EXE = ROOT / "bin" / "antigravity-proxy"
PLIST = HOME / "Library" / "LaunchAgents" / (LABEL + ".plist")
STATE = HOME / "Library" / "Application Support" / "CodeyAntigravity" / "runtime"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "CodeyAntigravityProxy28787"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def healthy() -> bool:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(URL, timeout=2) as response:
            raw = response.read(2049)
            if response.status != 200 or len(raw) > 2048:
                return False
            data = json.loads(raw)
            return isinstance(data, dict) and data.get("ok") is True and data.get("service") == "codey-antigravity-proxy"
    except (ValueError, OSError, urllib.error.URLError):
        return False


def mac_only() -> None:
    if sys.platform != "darwin" or os.geteuid() == 0:
        raise RuntimeError("Run as a normal logged-in macOS user, not root")


def mac_launch_domain() -> str:
    return f"gui/{os.getuid()}"


def mac_target() -> str:
    return mac_launch_domain() + "/" + LABEL


def mac_command(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        list(args), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, check=False, timeout=15, text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"System service command failed: {args[0]} {args[1]}")
    return result


def mac_loaded() -> bool:
    return mac_command("/bin/launchctl", "print", mac_target(), check=False).returncode == 0


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


def mac_keychain_value(service: str) -> str:
    if sys.platform == "darwin":
        import pwd
        user = pwd.getpwuid(os.getuid()).pw_name
    else:
        user = getpass.getuser()  # Unit-test fallback on non-macOS.
    result = mac_command(
        "/usr/bin/security", "find-generic-password",
        "-a", user, "-s", service, "-w", check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError("Missing authorized OAuth client entry in macOS Keychain: " + service)
    value = result.stdout.rstrip("\r\n")
    if not value or any(ord(ch) < 32 for ch in value):
        raise RuntimeError("Invalid OAuth client entry in macOS Keychain: " + service)
    return value


def mac_authorized_credentials() -> tuple[str, str]:
    return mac_keychain_value(SERVICE_ID), mac_keychain_value(SERVICE_SECRET)


def mac_expected_plist() -> dict:
    return {
        "Label": LABEL,
        "ProgramArguments": [str(Path(sys.executable).resolve()), str(ROOT / "proxy_manager.py"), "serve"],
        "WorkingDirectory": str(ROOT),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 30,
        "ProcessType": "Background",
        "Umask": 0o077,
        "StandardOutPath": str(STATE / "launchd.stdout.log"),
        "StandardErrorPath": str(STATE / "launchd.stderr.log"),
    }


def mac_check_plist() -> bool:
    if not PLIST.exists() and not PLIST.is_symlink():
        return False
    if PLIST.is_symlink() or not PLIST.is_file() or PLIST.stat().st_uid != os.getuid():
        raise RuntimeError("LaunchAgent path is not a regular file owned by this user")
    try:
        content = plistlib.loads(PLIST.read_bytes())
    except (ValueError, OSError, TypeError) as exc:
        raise RuntimeError("Cannot read existing LaunchAgent") from exc
    if content != mac_expected_plist():
        raise RuntimeError("Existing LaunchAgent differs; refusing to overwrite or manage")
    return True


def mac_prepare_runtime() -> None:
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


def mac_preflight() -> None:
    mac_only()
    if not EXE.is_file() or not os.access(EXE, os.X_OK):
        raise RuntimeError("Install the macOS arm64 portable bundle with the Rust executable first")
    if not AUTH.is_file():
        raise RuntimeError("Google OAuth auth.json is missing; login manually first")
    if mac_command(str(EXE), "--version").stdout.strip() != "antigravity-proxy 0.10.0":
        raise RuntimeError("Unexpected Rust proxy version")
    mac_authorized_credentials()  # Never stores or prints the secrets.


def mac_write_plist() -> bool:
    if mac_check_plist():
        return False
    if PLIST.parent.is_symlink():
        raise RuntimeError("Unsafe symlink LaunchAgents directory")
    PLIST.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    data = plistlib.dumps(mac_expected_plist(), fmt=plistlib.FMT_XML, sort_keys=True)
    fd = os.open(PLIST, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
    except BaseException:
        PLIST.unlink(missing_ok=True)
        raise
    return True


def mac_wait_ready() -> bool:
    for _ in range(30):
        if healthy():
            return True
        time.sleep(0.25)
    return False


def mac_enable() -> str:
    mac_preflight()
    if healthy() and not mac_loaded():
        raise RuntimeError("Port 28787 is already in use by a service not managed by this LaunchAgent")
    mac_prepare_runtime()
    new_file = mac_write_plist()
    if mac_loaded():
        if not healthy():
            raise RuntimeError("LaunchAgent is loaded but unhealthy; inspect the private stderr log")
        return "macOS LaunchAgent 已运行"
    try:
        mac_command("/bin/launchctl", "bootstrap", mac_launch_domain(), str(PLIST))
    except RuntimeError:
        if new_file:
            PLIST.unlink(missing_ok=True)
        raise
    if not mac_wait_ready():
        raise RuntimeError("LaunchAgent loaded but proxy is not healthy; inspect launchd.stderr.log")
    return "macOS 后台代理已启动，并启用登录后自动运行"


def mac_start() -> str:
    mac_only()
    if not mac_check_plist():
        raise RuntimeError("Run autorun-on first to install the user's LaunchAgent")
    mac_preflight()
    if mac_loaded():
        if not healthy():
            raise RuntimeError("LaunchAgent is loaded but proxy is not healthy")
        return "macOS 后台代理已运行"
    if healthy():
        raise RuntimeError("Port 28787 belongs to another running instance; refusing takeover")
    mac_command("/bin/launchctl", "bootstrap", mac_launch_domain(), str(PLIST))
    if not mac_wait_ready():
        raise RuntimeError("LaunchAgent started but proxy health failed")
    return "macOS 后台代理已启动"


def mac_stop() -> str:
    mac_only()
    if not mac_check_plist():
        raise RuntimeError("LaunchAgent has not been installed")
    if mac_loaded():
        mac_command("/bin/launchctl", "bootout", mac_target())
    for _ in range(24):
        if not healthy():
            return "macOS 后台代理已停止；下次登录仍会自动启动"
        time.sleep(0.25)
    raise RuntimeError("Port 28787 is still occupied, possibly by a different instance")


def mac_disable() -> str:
    mac_only()
    if not mac_check_plist():
        return "没有本工具安装的 LaunchAgent"
    if mac_loaded():
        mac_command("/bin/launchctl", "bootout", mac_target())
    PLIST.unlink()
    return "已关闭并移除本用户的 LaunchAgent，账号与模型数据未更改"


def mac_restart() -> str:
    mac_only()
    if not mac_check_plist():
        raise RuntimeError("LaunchAgent has not been installed")
    mac_preflight()
    if healthy() and not mac_loaded():
        raise RuntimeError("Port 28787 belongs to an unmanaged service")
    if mac_loaded():
        mac_command("/bin/launchctl", "kickstart", "-k", mac_target())
    else:
        mac_command("/bin/launchctl", "bootstrap", mac_launch_domain(), str(PLIST))
    if not mac_wait_ready():
        raise RuntimeError("LaunchAgent restarted but proxy health failed")
    return "macOS 后台代理重启成功"


def mac_serve() -> None:
    # This Python process is *replaced* by Rust, so launchd supervises the
    # native proxy directly, without any additional resident Python service.
    mac_only()
    mac_preflight()
    mac_prepare_runtime()
    client_id, client_secret = mac_authorized_credentials()
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



def win_log_event(event: str) -> None:
    state = ROOT / ".runtime"
    state.mkdir(exist_ok=True)
    log = state / "background-proxy.log"
    # Never log OAuth credentials, request bodies, environment values or subprocess output.
    if log.exists() and log.stat().st_size > 256 * 1024:
        log.write_text("", encoding="utf-8")
    with log.open("a", encoding="utf-8") as stream:
        stream.write(datetime.now(timezone.utc).isoformat() + " " + event + "\n")


def win_call_existing_script(action: str) -> None:
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


def win_start() -> str:
    if healthy():
        win_log_event("already-running")
        return "后台代理已运行，127.0.0.1:28787"
    win_call_existing_script("start")
    if not healthy():
        raise RuntimeError("Started but failed proxy health identity validation")
    win_log_event("started-hidden")
    return "后台代理已静默启动，127.0.0.1:28787"


def win_stop() -> str:
    # The existing PowerShell stop script validates PID, creation time and port identity.
    win_call_existing_script("stop")
    if healthy():
        raise RuntimeError("Proxy is still healthy after stopping; refusing further action")
    win_log_event("stopped")
    return "后台代理已安全停止"


def win_startup_command() -> str:
    exe = Path(sys.executable)
    if exe.name.lower() == "python.exe":
        exe = exe.with_name("pythonw.exe")
    elif exe.name.lower() not in ("pythonw.exe",):
        raise RuntimeError("Expected a CPython python.exe or pythonw.exe interpreter")
    if not exe.is_file():
        raise RuntimeError("pythonw.exe is not installed next to Python")
    script = ROOT / "proxy_manager.py"
    if not script.is_file():
        raise RuntimeError("Missing unified Python manager entrypoint")
    return f'"{exe}" "{script}" start'


def win_autorun(action: str) -> str:
    if os.name != "nt":
        raise RuntimeError("Login startup is Windows only")
    import winreg
    expected = win_startup_command()
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        try:
            current, kind = winreg.QueryValueEx(key, RUN_NAME)
        except FileNotFoundError:
            current, kind = None, None
        if current is not None and (kind != winreg.REG_SZ or current != expected):
            raise RuntimeError("Existing startup entry differs; refusing to overwrite")
        if action == "on":
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, expected)
            win_log_event("autorun-enabled")
            return "已启用当前用户登录后无窗口启动（HKCU Run，不使用计划任务）"
        if action == "off":
            if current == expected:
                winreg.DeleteValue(key, RUN_NAME)
                win_log_event("autorun-disabled")
            return "已关闭本工具的登录自动启动项"
        if action == "status":
            return "登录自动启动：已启用" if current == expected else "登录自动启动：未启用"
    raise ValueError("Unknown autorun command")



# Linux stays on the existing verified POSIX process scripts. systemd
# setup is optional, and requires desktop secret-service support.
LINUX_LABEL = "codey-antigravity-proxy.service"
LINUX_SERVICE = HOME / ".config" / "systemd" / "user" / LINUX_LABEL

def linux_command(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(list(args), cwd=ROOT, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True, timeout=35, check=False)
    if check and result.returncode:
        raise RuntimeError("Linux service command failed: " + args[0])
    return result


def linux_read_secret(service: str) -> str:
    result = linux_command("secret-tool", "lookup", "service", service, check=False)
    if result.returncode or not result.stdout.strip():
        raise RuntimeError("Missing authorized OAuth client entry in Linux Secret Service: " + service)
    value = result.stdout.rstrip("\r\n")
    if any(ord(c) < 32 for c in value):
        raise RuntimeError("Invalid OAuth client credential")
    return value


def linux_serve() -> None:
    if sys.platform != "linux" or os.geteuid() == 0:
        raise RuntimeError("Linux service requires a non-root user session")
    if not EXE.is_file() or not os.access(EXE, os.X_OK) or not AUTH.is_file():
        raise RuntimeError("Install the Linux portable proxy and login first")
    creds = (linux_read_secret(SERVICE_ID), linux_read_secret(SERVICE_SECRET))
    env = os.environ.copy()
    env["ANTIGRAVITY_CLIENT_ID"], env["ANTIGRAVITY_CLIENT_SECRET"] = creds
    env["PI_CODING_AGENT_DIR"] = str(AUTH.parent)
    env["NO_PROXY"] = ",".join(dict.fromkeys(
        [x for x in env.get("NO_PROXY", "").split(",") if x] + ["localhost", "127.0.0.1", "::1"]))
    os.execve(str(EXE), [str(EXE), "serve", "--port", "28787", "--auth", str(AUTH)], env)


def linux_expected_unit() -> str:
    exe = str(Path(sys.executable).resolve())
    script = str(ROOT / "proxy_manager.py")
    # systemd unit escape for % and literal argument representation.
    for val in (exe, script, str(ROOT)):
        if "\n" in val or "\r" in val or '"' in val or "%" in val:
            raise RuntimeError("Unsupported characters in systemd service paths")
    return ("[Unit]\nDescription=Codey Antigravity Rust Proxy\nAfter=network-online.target\n\n"
            f'[Service]\nType=exec\nExecStart="{exe}" "{script}" serve\n'
            f'WorkingDirectory="{ROOT}"\n'
            "Restart=on-failure\nRestartSec=10\nNoNewPrivileges=true\n"
            "UMask=0077\n\n[Install]\nWantedBy=default.target\n")


def linux_unit_installed() -> bool:
    if not LINUX_SERVICE.exists() and not LINUX_SERVICE.is_symlink():
        return False
    if LINUX_SERVICE.is_symlink() or not LINUX_SERVICE.is_file():
        raise RuntimeError("Unsafe systemd unit file")
    if LINUX_SERVICE.read_text(encoding="utf8") != linux_expected_unit():
        raise RuntimeError("Foreign systemd user unit differs; refusing change")
    return True


def linux_wait_ready() -> bool:
    for _ in range(30):
        if healthy():
            return True
        time.sleep(0.25)
    return False


def linux_managed(action: str) -> str:
    if sys.platform != "linux" or os.geteuid() == 0:
        raise RuntimeError("Linux user service requires non-root session")
    service = ("systemctl", "--user")
    if action == "autorun-status":
        return "Linux 登录自启动：" + ("已配置" if linux_unit_installed() else "未配置")
    if action == "autorun-on":
        if healthy() and not linux_unit_installed():
            raise RuntimeError("Existing proxy occupies 28787; stop it safely before enabling")
        if not EXE.is_file() or not AUTH.is_file():
            raise RuntimeError("Linux proxy or auth.json not installed")
        linux_read_secret(SERVICE_ID)
        linux_read_secret(SERVICE_SECRET)
        if not linux_unit_installed():
            if LINUX_SERVICE.parent.is_symlink():
                raise RuntimeError("Unsafe symlink systemd unit directory")
            LINUX_SERVICE.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            with LINUX_SERVICE.open("x",encoding="utf8") as f:
                f.write(linux_expected_unit())
            LINUX_SERVICE.chmod(0o600)
        linux_command(*service,"daemon-reload")
        linux_command(*service,"enable","--now",LINUX_LABEL)
        if not linux_wait_ready():
            raise RuntimeError("systemd enabled but proxy health is not ready")
        return "Linux systemd 用户后台代理已配置"
    if action == "autorun-off":
        if not linux_unit_installed():
            return "Linux 没有本工具的登录启动项"
        linux_command(*service,"disable","--now",LINUX_LABEL)
        LINUX_SERVICE.unlink()
        linux_command(*service,"daemon-reload")
        return "Linux systemd 用户后台代理已移除，OAuth 数据保留"
    if action == "status":
        try:
            active = linux_command(*service, "is-active", "--quiet", LINUX_LABEL, check=False).returncode == 0
        except OSError:
            active = False  # Minimal/headless Linux may not have systemd.
        return f"systemd 用户服务激活={active} 代理健康={healthy()}"
    if action == "start":
        if linux_unit_installed():
            linux_command(*service,"start",LINUX_LABEL)
        else:
            linux_command("bash",str(ROOT/"start-proxy.sh"))
        if not linux_wait_ready():
            raise RuntimeError("Linux proxy health failed after start")
        return "Linux 后台代理已启动"
    if action == "stop":
        if linux_unit_installed():
            linux_command(*service,"stop",LINUX_LABEL)
        else:
            linux_command("bash",str(ROOT/"stop-proxy.sh"))
        for _ in range(24):
            if not healthy():
                return "Linux 后台代理已停止"
            time.sleep(0.25)
        raise RuntimeError("Proxy still healthy; refusing foreign process manipulation")
        return "Linux 后台代理已停止"
    if action == "restart":
        if linux_unit_installed():
            linux_command(*service,"restart",LINUX_LABEL)
            if not linux_wait_ready():
                raise RuntimeError("Linux systemd proxy unhealthy after restart")
            return "Linux 后台代理已重启"
        linux_managed("stop")
        return linux_managed("start")
    raise RuntimeError("Unknown Linux command")




ACTIONS = ("start", "stop", "restart", "status", "autorun-on", "autorun-off", "autorun-status", "serve")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Codey Antigravity 跨平台后台管理器")
    parser.add_argument("action", nargs="?", default="status", choices=ACTIONS)
    options = parser.parse_args(argv)
    try:
        if sys.platform == "darwin":
            mac_only()
            if options.action == "serve":
                mac_serve()
                return 0
            if options.action == "autorun-on":
                message = mac_enable()
            elif options.action == "autorun-off":
                message = mac_disable()
            elif options.action == "autorun-status":
                message = "macOS LaunchAgent 登录自启动：" + ("已配置" if mac_check_plist() else "未配置")
            elif options.action == "start":
                message = mac_start()
            elif options.action == "stop":
                message = mac_stop()
            elif options.action == "restart":
                message = mac_restart()
            else:
                active = mac_loaded()
                live = healthy()
                message = f"macOS LaunchAgent 已加载={active} 代理健康={live}"
                print(message)
                return 0 if active and live else 3
        elif sys.platform == "win32":
            if options.action == "serve":
                raise RuntimeError("Windows uses a detached native proxy, not a resident Python service")
            if options.action == "autorun-on":
                message = win_autorun("on")
            elif options.action == "autorun-off":
                message = win_autorun("off")
            elif options.action == "autorun-status":
                message = win_autorun("status")
            elif options.action == "start":
                message = win_start()
            elif options.action == "stop":
                message = win_stop()
            elif options.action == "restart":
                win_stop()
                message = win_start()
            else:
                live = healthy()
                print("Windows 后台代理健康：" + str(live))
                return 0 if live else 3
        elif sys.platform == "linux":
            if options.action == "serve":
                linux_serve()
                return 0
            message = linux_managed(options.action)
            if options.action == "status":
                print(message)
                return 0 if healthy() else 3
        else:
            raise RuntimeError("Unsupported operating system: " + sys.platform)
        if sys.stdout is not None:
            print(message)
        return 0
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        if sys.stderr is not None:
            print("后台管理失败：" + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
