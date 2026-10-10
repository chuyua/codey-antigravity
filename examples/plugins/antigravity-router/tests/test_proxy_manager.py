"""Unified proxy manager tests across Windows, macOS and Linux."""
import importlib.util
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "proxy_manager.py"
SPEC = importlib.util.spec_from_file_location("proxy_manager", SOURCE)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class MacLaunchAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="launch-agent-tests-")
        self.addCleanup(self.temp.cleanup)
        home = Path(self.temp.name)
        self.patches = [
            patch.object(M, "ROOT", home),
            patch.object(M, "STATE", home / "Library/Application Support/CodeyAntigravity/runtime"),
            patch.object(M, "PLIST", home / "Library/LaunchAgents" / (M.LABEL + ".plist")),
            patch.object(M, "AUTH", home / ".pi/agent/auth.json"),
            patch.object(M, "EXE", home / "bin/antigravity-proxy"),
            patch.object(M, "mac_only"),
        ]
        # Windows has no getuid and reports a synthetic st_uid; on actual
        # macOS preserve the real UID so file ownership checks are exercised.
        if os.name == "nt":
            self.patches.append(patch.object(M.os, "getuid", create=True, return_value=0))
        for pt in self.patches:
            pt.start()
            self.addCleanup(pt.stop)

    def test_plist_is_native_user_agent_not_terminal_or_windows_task(self):
        value = M.mac_expected_plist()
        self.assertTrue(value["RunAtLoad"])
        self.assertEqual(value["KeepAlive"], {"SuccessfulExit": False})
        self.assertEqual(value["ProcessType"], "Background")
        self.assertEqual(value["Umask"], 0o077)
        self.assertEqual(value["ProgramArguments"][-1], "serve")
        self.assertNotIn("ANTIGRAVITY_CLIENT_SECRET", str(value))
        self.assertNotIn("auth.json", str(value))
        self.assertNotIn("/bin/sh", str(value))
        self.assertEqual(value["Label"], M.LABEL)

    def test_writes_private_user_owned_plist_and_detects_changes(self):
        self.assertTrue(M.mac_write_plist())
        self.assertTrue(M.mac_check_plist())
        self.assertFalse(M.mac_write_plist())
        if os.name != "nt":
            self.assertEqual(M.PLIST.stat().st_mode & 0o777, 0o600)
        value = plistlib.loads(M.PLIST.read_bytes())
        value["Label"] = "com.somebody.else"
        M.PLIST.write_bytes(plistlib.dumps(value))
        with self.assertRaisesRegex(RuntimeError, "differs"):
            M.mac_check_plist()

    def test_launchagent_bootstrap_only_when_port_is_not_foreign(self):
        with patch.object(M, "healthy", return_value=True), patch.object(M, "mac_loaded", return_value=False), \
             patch.object(M, "mac_preflight"), patch.object(M, "mac_command") as call:
            with self.assertRaisesRegex(RuntimeError, "not managed"):
                M.mac_enable()
            call.assert_not_called()
            self.assertFalse(M.PLIST.exists())

    def test_bootstrap_with_identity_and_readiness(self):
        with patch.object(M, "healthy", return_value=False), patch.object(M, "mac_loaded", return_value=False), \
             patch.object(M, "mac_preflight"), patch.object(M, "mac_command") as call, \
             patch.object(M, "mac_wait_ready", return_value=True):
            self.assertIn("已启动", M.mac_enable())
            self.assertTrue(M.mac_check_plist())
            call.assert_called_once_with("/bin/launchctl", "bootstrap", M.mac_launch_domain(), str(M.PLIST))

    def test_failed_bootstrap_rolls_back_only_new_plist(self):
        with patch.object(M, "healthy", return_value=False), patch.object(M, "mac_loaded", return_value=False), \
             patch.object(M, "mac_preflight"), patch.object(M, "mac_command", side_effect=RuntimeError("failed")):
            with self.assertRaises(RuntimeError):
                M.mac_enable()
            self.assertFalse(M.PLIST.exists())

    def test_stop_uses_only_own_launchctl_domain_and_keeps_autostart(self):
        M.mac_write_plist()
        with patch.object(M, "mac_loaded", return_value=True), patch.object(M, "healthy", return_value=False), \
             patch.object(M, "mac_command") as call:
            self.assertIn("已停止", M.mac_stop())
            call.assert_called_once_with("/bin/launchctl", "bootout", M.mac_target())
            self.assertTrue(M.PLIST.exists())

    def test_autostart_off_does_not_remove_unknown_plist(self):
        M.mac_write_plist()
        with patch.object(M, "mac_loaded", return_value=False):
            self.assertIn("移除", M.mac_disable())
        self.assertFalse(M.PLIST.exists())
        M.mac_write_plist()
        value = plistlib.loads(M.PLIST.read_bytes())
        value["ProgramArguments"] = ["/usr/bin/false"]
        M.PLIST.write_bytes(plistlib.dumps(value))
        with self.assertRaisesRegex(RuntimeError, "differs"):
            M.mac_disable()

    def test_keychain_read_returns_value_without_command_line_secret(self):
        with patch.object(M, "mac_command", return_value=subprocess.CompletedProcess([], 0, "example-secret")) as run:
            self.assertEqual(M.mac_keychain_value(M.SERVICE_SECRET), "example-secret")
            arguments = run.call_args.args
            self.assertEqual(arguments[:2], ("/usr/bin/security", "find-generic-password"))
            self.assertNotIn("example-secret", str(arguments))

    def test_exec_replaces_python_with_rust_and_injects_only_memory_env(self):
        with patch.object(M, "mac_preflight"), patch.object(M, "mac_authorized_credentials", return_value=("cid", "csecret")), \
             patch.object(M.os, "execve", side_effect=RuntimeError("mock exec")) as execute:
            with self.assertRaisesRegex(RuntimeError, "mock exec"):
                M.mac_serve()
            exe, args, env = execute.call_args.args
            self.assertEqual(exe, str(M.EXE))
            self.assertEqual(args[1:4], ["serve", "--port", "28787"])
            self.assertEqual(env["ANTIGRAVITY_CLIENT_ID"], "cid")
            self.assertEqual(env["ANTIGRAVITY_CLIENT_SECRET"], "csecret")
            self.assertNotIn("csecret", str(M.mac_expected_plist()))

    def test_missing_keychain_entry_blocks_enabling(self):
        with patch.object(M, "mac_command", return_value=subprocess.CompletedProcess([], 44, "")):
            with self.assertRaisesRegex(RuntimeError, "Missing authorized OAuth client"):
                M.mac_keychain_value(M.SERVICE_ID)


class BackgroundProxyTests(unittest.TestCase):
    def test_start_when_healthy_is_idempotent(self):
        with patch.object(M, "healthy", return_value=True), \
             patch.object(M, "win_call_existing_script") as called, \
             patch.object(M, "win_log_event"):
            self.assertIn("已运行", M.win_start())
            called.assert_not_called()

    def test_start_when_stopped_checks_identity(self):
        with patch.object(M, "healthy", side_effect=[False, True]), \
             patch.object(M, "win_call_existing_script") as called, \
             patch.object(M, "win_log_event"):
            self.assertIn("已静默启动", M.win_start())
            called.assert_called_once_with("start")

    def test_start_never_claims_success_when_health_fails(self):
        with patch.object(M, "healthy", side_effect=[False, False]), \
             patch.object(M, "win_call_existing_script") as called:
            with self.assertRaisesRegex(RuntimeError, "health"):
                M.win_start()
            called.assert_called_once_with("start")

    def test_stop_uses_verified_powershell_guard(self):
        with patch.object(M, "healthy", return_value=False), \
             patch.object(M, "win_call_existing_script") as called, \
             patch.object(M, "win_log_event"):
            self.assertIn("已安全停止", M.win_stop())
            called.assert_called_once_with("stop")

    def test_stop_never_kills_by_port_or_pid_without_record(self):
        with patch.object(M, "healthy", return_value=True), \
             patch.object(M, "win_call_existing_script") as called:
            with self.assertRaisesRegex(RuntimeError, "still healthy"):
                M.win_stop()
            called.assert_called_once_with("stop")

    @unittest.skipUnless(__import__("os").name == "nt", "Windows process flags")
    def test_powershell_invocation_suppresses_console(self):
        with patch.object(M.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as process:
            M.win_call_existing_script("start")
            arguments, kwargs = process.call_args
            self.assertIn("-NonInteractive", arguments[0])
            self.assertIn("start-proxy.ps1", arguments[0][-1])
            self.assertEqual(kwargs["creationflags"], subprocess.CREATE_NO_WINDOW)
            self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
            self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)

    def test_pythonw_entrypoint_is_present(self):
        self.assertTrue(SOURCE.is_file())
        self.assertEqual(SOURCE.name, "proxy_manager.py")


class LinuxManagerTests(unittest.TestCase):
    def test_systemd_unit_is_user_owned_no_secrets(self):
        unit = M.linux_expected_unit()
        self.assertIn("WantedBy=default.target", unit)
        self.assertIn("Type=exec", unit)
        self.assertIn("serve", unit)
        self.assertNotIn("ANTIGRAVITY_CLIENT_SECRET", unit)
        self.assertNotIn("auth.json", unit)

    def test_linux_server_exec_replaces_python_with_rust(self):
        with patch.object(M.sys, "platform", "linux"), patch.object(M.os, "geteuid", return_value=1000, create=True), \
             patch.object(M, "linux_read_secret", side_effect=["cid", "ssecret"]), \
             patch.object(M.os, "execve", side_effect=RuntimeError("mock-exec"), create=True) as execve, \
             patch.object(M.Path, "is_file", return_value=True), \
             patch.object(M.os, "access", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "mock-exec"):
                M.linux_serve()
            args = execve.call_args.args
            self.assertEqual(args[1][1:4], ["serve", "--port", "28787"])
            self.assertEqual(args[2]["ANTIGRAVITY_CLIENT_ID"], "cid")
            self.assertEqual(args[2]["ANTIGRAVITY_CLIENT_SECRET"], "ssecret")
            self.assertNotIn("ssecret", M.linux_expected_unit())

    def test_linux_foreign_service_never_overwritten(self):
        with tempfile.TemporaryDirectory() as d, patch.object(M, "LINUX_SERVICE", Path(d) / "proxy.service"):
            M.LINUX_SERVICE.write_text("[Unit]\\nUnknown=true\\n", encoding="utf8")
            with self.assertRaisesRegex(RuntimeError, "Foreign"):
                M.linux_unit_installed()

    def test_windows_and_macos_select_correct_backends(self):
        with patch.object(M.sys, "platform", "win32"), patch.object(M, "win_start", return_value="windows"), \
             patch.object(M, "mac_start") as mac:
            self.assertEqual(M.main(["start"]), 0)
            mac.assert_not_called()
        with patch.object(M.sys, "platform", "darwin"), patch.object(M, "mac_only"), \
             patch.object(M, "mac_start", return_value="mac"), patch.object(M, "win_start") as win:
            self.assertEqual(M.main(["start"]), 0)
            win.assert_not_called()


if __name__ == "__main__":
    unittest.main()
