"""Standard-library unit tests for the optional Windows windowless launcher."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
import subprocess

FILE = Path(__file__).resolve().parents[1] / "background_proxy.py"
SPEC = importlib.util.spec_from_file_location("background_proxy", FILE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BackgroundProxyTests(unittest.TestCase):
    def test_start_when_healthy_is_idempotent(self):
        with patch.object(MODULE, "healthy", return_value=True), \
             patch.object(MODULE, "call_existing_script") as called, \
             patch.object(MODULE, "log_event"):
            self.assertIn("已运行", MODULE.start())
            called.assert_not_called()

    def test_start_when_stopped_checks_identity(self):
        with patch.object(MODULE, "healthy", side_effect=[False, True]), \
             patch.object(MODULE, "call_existing_script") as called, \
             patch.object(MODULE, "log_event"):
            self.assertIn("已静默启动", MODULE.start())
            called.assert_called_once_with("start")

    def test_start_never_claims_success_when_health_fails(self):
        with patch.object(MODULE, "healthy", side_effect=[False, False]), \
             patch.object(MODULE, "call_existing_script") as called:
            with self.assertRaisesRegex(RuntimeError, "health"):
                MODULE.start()
            called.assert_called_once_with("start")

    def test_stop_uses_verified_powershell_guard(self):
        with patch.object(MODULE, "healthy", return_value=False), \
             patch.object(MODULE, "call_existing_script") as called, \
             patch.object(MODULE, "log_event"):
            self.assertIn("已安全停止", MODULE.stop())
            called.assert_called_once_with("stop")

    def test_stop_never_kills_by_port_or_pid_without_record(self):
        with patch.object(MODULE, "healthy", return_value=True), \
             patch.object(MODULE, "call_existing_script") as called:
            with self.assertRaisesRegex(RuntimeError, "still healthy"):
                MODULE.stop()
            called.assert_called_once_with("stop")

    @unittest.skipUnless(__import__("os").name == "nt", "Windows process flags")
    def test_powershell_invocation_suppresses_console(self):
        with patch.object(MODULE.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as process:
            MODULE.call_existing_script("start")
            arguments, kwargs = process.call_args
            self.assertIn("-NonInteractive", arguments[0])
            self.assertIn("start-proxy.ps1", arguments[0][-1])
            self.assertEqual(kwargs["creationflags"], subprocess.CREATE_NO_WINDOW)
            self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
            self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)

    def test_pythonw_entrypoint_is_present(self):
        self.assertTrue((FILE.parent / "background_proxy.pyw").is_file())


if __name__ == "__main__":
    unittest.main()
