# Double-click to open the dashboard without a console window.
# For a taskbar/Start-menu entry use scripts\New-Shortcut.ps1 instead (a .pyw file can't be pinned).
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from routerctl import main  # noqa: E402

sys.exit(main(["dashboard"]))
