"""The command line and the PowerShell scripts, run as real processes in a throw-away home folder.
Restart commands are only run in modes that cannot restart anything (-WhatIf / no confirmation),
and the configured router address is a documentation address (192.0.2.1) that is never routed."""
import _setup  # noqa: F401  (must come first)

import json
import os
import subprocess
import sys
import unittest

from routerkit import scheduler

CLI = str(_setup.SRC / "routerctl.py")
SCRIPTS = _setup.REPO / "scripts"
CONFIG = _setup.HOME / "config" / "config.json"
ENV = {**os.environ, "ROUTER_AUTO_RESTART_HOME": str(_setup.HOME), "ROUTER_AUTO_RESTART_PYTHON": sys.executable}


def cli(*args, stdin=subprocess.DEVNULL, timeout=60):
    return subprocess.run([sys.executable, CLI, *args], capture_output=True, text=True, env=ENV,
                          stdin=stdin, timeout=timeout)


def ps1(name, *args, timeout=120):
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                           "-File", str(SCRIPTS / name), *args],
                          capture_output=True, text=True, env=ENV, stdin=subprocess.DEVNULL, timeout=timeout)


def write_config(extra=None):
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps({**_setup.TEST_CONFIG, **(extra or {})}), encoding="utf-8")


class Cli(unittest.TestCase):
    def setUp(self):
        write_config()

    def test_models(self):
        r = cli("models")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("gx-gpon-e4222", r.stdout)

    def test_missing_config_exit_code(self):
        CONFIG.unlink()
        r = cli("status")
        self.assertEqual(r.returncode, 5)
        self.assertIn("Configure.ps1", r.stderr)

    def test_check_config(self):
        self.assertEqual(cli("check-config").returncode, 0)
        write_config({"interval_days": 0})
        r = cli("check-config")
        self.assertEqual(r.returncode, 5)
        self.assertIn("interval_days", r.stderr)

    def test_restart_refused_without_confirmation(self):
        r = cli("reboot")                         # stdin is not a terminal and there is no --yes
        self.assertEqual(r.returncode, 1)
        self.assertIn("--yes", r.stderr)

    def test_install_print_only_changes_nothing(self):
        r = cli("install", "--print-only", "--time", "05:30", "--every-days", "2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Register-ScheduledTask -TaskName 'RouterAutoRestart-SelfTest'", r.stdout)
        self.assertIn("-DaysInterval 2 -At '05:30'", r.stdout)
        self.assertEqual(scheduler.query_task("RouterAutoRestart-SelfTest"), {"missing": True})

    def test_bad_time_rejected(self):
        r = cli("install", "--print-only", "--time", "25:00")
        self.assertEqual(r.returncode, 1)


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class PowerShellScripts(unittest.TestCase):
    def setUp(self):
        write_config()

    def test_all_scripts_parse(self):
        files = sorted(str(p) for p in SCRIPTS.glob("*.ps1"))
        self.assertGreaterEqual(len(files), 8)
        cmd = ("$bad = 0; foreach ($f in $args) { $e = $null; "
               "[void][System.Management.Automation.Language.Parser]::ParseFile($f, [ref]$null, [ref]$e); "
               "if ($e) { $bad++; Write-Output \"$f`: $($e[0].Message)\" } }; exit $bad")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", "& {" + cmd + "}", *files],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_configure_noninteractive(self):
        write_config({"probe_targets": [["192.0.2.53", 443]], "theme": "dark"})
        r = ps1("Configure.ps1", "-RouterUrl", "http://192.0.2.1:8080", "-Model", "gx-gpon-e4222",
                "-Username", "YOUR_ROUTER_USERNAME", "-RestartTime", "4:30", "-IntervalDays", "2",
                "-WarnMinutes", "5", "-NonInteractive", "-SkipPassword")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        raw = CONFIG.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), "config must be written without a BOM")
        d = json.loads(raw)
        self.assertEqual((d["router_url"], d["restart_time"], d["interval_days"], d["warn_minutes"]),
                         ("http://192.0.2.1:8080", "04:30", 2, 5))
        self.assertEqual(d["probe_targets"], [["192.0.2.53", 443]])    # untouched settings survive
        self.assertEqual(d["theme"], "dark")
        self.assertNotIn("password", raw.decode().lower())

    def test_configure_rejects_url_with_credentials(self):
        r = ps1("Configure.ps1", "-RouterUrl", "http://user:pw@192.0.2.1", "-Model", "gx-gpon-e4222",
                "-NonInteractive", "-SkipPassword")
        self.assertNotEqual(r.returncode, 0)

    def test_register_whatif_registers_nothing(self):
        r = ps1("Register-ScheduledTask.ps1", "-Time", "04:00", "-IntervalDays", "3", "-WhatIf")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("-DaysInterval 3 -At '04:00'", r.stdout)
        self.assertEqual(scheduler.query_task("RouterAutoRestart-SelfTest"), {"missing": True})

    def test_restart_whatif_does_not_restart(self):
        r = ps1("Restart-Router.ps1", "-WhatIf")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("What if", r.stdout)
        self.assertNotIn("logged in", r.stdout + r.stderr)

    def test_restart_whatif_wins_over_force(self):
        r = ps1("Restart-Router.ps1", "-Force", "-WhatIf")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("What if", r.stdout)

    def test_remove_and_uninstall_whatif_keep_files(self):
        (_setup.HOME / "logs").mkdir(exist_ok=True)
        (_setup.HOME / "logs" / "keep.log").write_text("x")
        for name, extra in (("Remove-ScheduledTask.ps1", ["-IncludeWatchdog"]),
                            ("Uninstall.ps1", ["-RemoveLocalData"])):
            r = ps1(name, *extra, "-WhatIf")
            self.assertEqual(r.returncode, 0, name + r.stdout + r.stderr)
        self.assertTrue(CONFIG.exists())
        self.assertTrue((_setup.HOME / "logs" / "keep.log").exists())

    def test_uninstall_removes_local_data_when_confirmed(self):
        (_setup.HOME / "data").mkdir(exist_ok=True)
        # -Confirm:$false needs PowerShell's own parser, so use -Command (as a user typing it would)
        script = str(SCRIPTS / "Uninstall.ps1").replace("'", "''")
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
                            f"& '{script}' -RemoveLocalData -Confirm:$false; exit $LASTEXITCODE"],
                           capture_output=True, text=True, env=ENV, stdin=subprocess.DEVNULL, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(CONFIG.exists())
        self.assertFalse((_setup.HOME / "data").exists())
        self.assertTrue((_setup.REPO / "src" / "routerctl.py").exists())     # source untouched

    def test_connection_test_reports_unreachable(self):
        r = ps1("Test-Connection.ps1", "-SkipLogin")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("[FAIL] Router reachable", r.stdout)


if __name__ == "__main__":
    unittest.main()
