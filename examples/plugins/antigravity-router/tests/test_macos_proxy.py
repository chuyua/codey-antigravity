"""Portable tests for macOS LaunchAgent wiring; no live Mac login is modified."""
import importlib.util
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "macos_proxy.py"
SPEC = importlib.util.spec_from_file_location("macos_proxy", SOURCE)
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
            patch.object(M.os, "getuid", create=True, return_value=0),
        ]
        for pt in self.patches:
            pt.start()
            self.addCleanup(pt.stop)

    def test_plist_is_native_user_agent_not_terminal_or_windows_task(self):
        value = M.expected_plist()
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
        self.assertTrue(M.write_plist())
        self.assertTrue(M.check_plist())
        self.assertFalse(M.write_plist())
        if os.name != "nt":
            self.assertEqual(M.PLIST.stat().st_mode & 0o777, 0o600)
        value = plistlib.loads(M.PLIST.read_bytes())
        value["Label"] = "com.somebody.else"
        M.PLIST.write_bytes(plistlib.dumps(value))
        with self.assertRaisesRegex(RuntimeError, "differs"):
            M.check_plist()

    def test_launchagent_bootstrap_only_when_port_is_not_foreign(self):
        with patch.object(M, "healthy", return_value=True), patch.object(M, "loaded", return_value=False), \
             patch.object(M, "preflight"), patch.object(M, "command") as call:
            with self.assertRaisesRegex(RuntimeError, "not managed"):
                M.enable()
            call.assert_not_called()
            self.assertFalse(M.PLIST.exists())

    def test_bootstrap_with_identity_and_readiness(self):
        with patch.object(M, "healthy", return_value=False), patch.object(M, "loaded", return_value=False), \
             patch.object(M, "preflight"), patch.object(M, "command") as call, \
             patch.object(M, "wait_ready", return_value=True):
            self.assertIn("已启动", M.enable())
            self.assertTrue(M.check_plist())
            call.assert_called_once_with("/bin/launchctl", "bootstrap", M.launch_domain(), str(M.PLIST))

    def test_failed_bootstrap_rolls_back_only_new_plist(self):
        with patch.object(M, "healthy", return_value=False), patch.object(M, "loaded", return_value=False), \
             patch.object(M, "preflight"), patch.object(M, "command", side_effect=RuntimeError("failed")):
            with self.assertRaises(RuntimeError):
                M.enable()
            self.assertFalse(M.PLIST.exists())

    def test_stop_uses_only_own_launchctl_domain_and_keeps_autostart(self):
        M.write_plist()
        with patch.object(M, "loaded", return_value=True), patch.object(M, "healthy", return_value=False), \
             patch.object(M, "command") as call:
            self.assertIn("已停止", M.stop())
            call.assert_called_once_with("/bin/launchctl", "bootout", M.target())
            self.assertTrue(M.PLIST.exists())

    def test_autostart_off_does_not_remove_unknown_plist(self):
        M.write_plist()
        with patch.object(M, "loaded", return_value=False):
            self.assertIn("移除", M.disable())
        self.assertFalse(M.PLIST.exists())
        M.write_plist()
        value = plistlib.loads(M.PLIST.read_bytes())
        value["ProgramArguments"] = ["/usr/bin/false"]
        M.PLIST.write_bytes(plistlib.dumps(value))
        with self.assertRaisesRegex(RuntimeError, "differs"):
            M.disable()

    def test_keychain_read_returns_value_without_command_line_secret(self):
        with patch.object(M, "command", return_value=subprocess.CompletedProcess([], 0, "example-secret")) as run:
            self.assertEqual(M.keychain_value(M.SERVICE_SECRET), "example-secret")
            arguments = run.call_args.args
            self.assertEqual(arguments[:2], ("/usr/bin/security", "find-generic-password"))
            self.assertNotIn("example-secret", str(arguments))

    def test_exec_replaces_python_with_rust_and_injects_only_memory_env(self):
        with patch.object(M, "preflight"), patch.object(M, "authorized_credentials", return_value=("cid", "csecret")), \
             patch.object(M.os, "execve", side_effect=RuntimeError("mock exec")) as execute:
            with self.assertRaisesRegex(RuntimeError, "mock exec"):
                M.serve()
            exe, args, env = execute.call_args.args
            self.assertEqual(exe, str(M.EXE))
            self.assertEqual(args[1:4], ["serve", "--port", "28787"])
            self.assertEqual(env["ANTIGRAVITY_CLIENT_ID"], "cid")
            self.assertEqual(env["ANTIGRAVITY_CLIENT_SECRET"], "csecret")
            self.assertNotIn("csecret", str(M.expected_plist()))

    def test_missing_keychain_entry_blocks_enabling(self):
        with patch.object(M, "command", return_value=subprocess.CompletedProcess([], 44, "")):
            with self.assertRaisesRegex(RuntimeError, "Missing authorized OAuth client"):
                M.keychain_value(M.SERVICE_ID)


if __name__ == "__main__":
    unittest.main()
