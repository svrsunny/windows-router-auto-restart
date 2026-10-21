"""Imported first by every test module: points the app at a throw-away home folder so tests
never touch the real config, logs, password or router."""
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
if "ROUTER_AUTO_RESTART_TEST_HOME" not in os.environ:
    _home = tempfile.mkdtemp(prefix="rar-test-")
    os.environ["ROUTER_AUTO_RESTART_TEST_HOME"] = _home
    atexit.register(shutil.rmtree, _home, True)
HOME = Path(os.environ["ROUTER_AUTO_RESTART_TEST_HOME"])
os.environ["ROUTER_AUTO_RESTART_HOME"] = str(HOME)
for var in ("ROUTER_URL", "ROUTER_USER", "ROUTER_PASS"):
    os.environ.pop(var, None)
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

TEST_CONFIG = {
    "router_url": "http://192.0.2.1",           # TEST-NET-1: documentation address, never routed
    "router_model": "gx-gpon-e4222",
    "username": "YOUR_ROUTER_USERNAME",
    "task_name": "RouterAutoRestart-SelfTest",
    "watchdog_task_name": "RouterAutoRestart-SelfTest-Watchdog",
    "retry_delay": 0,
}
