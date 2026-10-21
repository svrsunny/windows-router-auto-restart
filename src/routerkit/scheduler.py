"""Windows Task Scheduler wrapper (through PowerShell's ScheduledTasks module).

The restart task runs as the current user, only while that user is logged on (Interactive),
with normal (non-elevated) rights. That is required for two reasons: the countdown window has
to appear on that user's desktop, and the router password lives in that user's Credential
Manager. Nothing secret is placed in the task's arguments.

Times are local wall-clock times; Task Scheduler keeps them across daylight-saving changes.
If the PC is off or asleep at the scheduled time, StartWhenAvailable runs the task at the next
opportunity. The task is never retried automatically on failure, so a failure can't cause a
second restart.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .config import CLI, ROOT, TIME_RE

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def q(value) -> str:
    """Quote a value as a PowerShell single-quoted string literal."""
    return "'" + str(value).replace("'", "''") + "'"


def ps(command: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW,
    )


def _err(p: subprocess.CompletedProcess) -> str:
    text = (p.stderr or p.stdout or "").strip()
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return first[:240] or f"PowerShell exit code {p.returncode}"


def pythonw() -> str:
    """pythonw.exe next to the running interpreter (no console window), else the interpreter itself."""
    exe = Path(sys.executable)
    cand = exe.with_name("pythonw.exe")
    return str(cand if cand.exists() else exe)


def _execute() -> str:
    return f'"{pythonw()}"'          # quoted: the path may contain spaces


# ---------- query ----------

def _query_script(name: str) -> str:
    return f"""
$ErrorActionPreference = 'Stop'
$t = Get-ScheduledTask -TaskName {q(name)} -ErrorAction SilentlyContinue
if (-not $t) {{ '{{"missing":true}}'; exit 0 }}
$i = $t | Get-ScheduledTaskInfo
$last = $null; if ($i.LastRunTime -and $i.LastRunTime.Year -gt 2000) {{ $last = $i.LastRunTime.ToString('s') }}
$next = $null; if ($i.NextRunTime -and $i.NextRunTime.Year -gt 2000) {{ $next = $i.NextRunTime.ToString('s') }}
$days = $null; $at = $null; $argline = $null
$tr = @($t.Triggers) | Select-Object -First 1
if ($tr) {{ if ($tr.DaysInterval) {{ $days = [int]$tr.DaysInterval }}; if ($tr.StartBoundary) {{ $at = [string]$tr.StartBoundary }} }}
$ac = @($t.Actions) | Select-Object -First 1
if ($ac -and $ac.Arguments) {{ $argline = [string]$ac.Arguments }}
[pscustomobject]@{{ state = [string]$t.State; last = $last; result = [int64]$i.LastTaskResult; next = $next;
  missed = [int]$i.NumberOfMissedRuns; days = $days; at = $at; args = $argline }} | ConvertTo-Json -Compress
"""


def parse_query(stdout: str) -> dict:
    d = json.loads(stdout.strip().splitlines()[-1])
    if d.get("missing"):
        return {"missing": True}
    for k in ("last", "next"):
        d[k] = datetime.fromisoformat(d[k]) if d.get(k) else None
    m = re.search(r"T(\d{2}):(\d{2})", d.get("at") or "")
    d["at"] = f"{m.group(1)}:{m.group(2)}" if m else None
    m = re.search(r"--warn-minutes\s+([\d.]+)", d.get("args") or "")
    try:
        d["warn"] = float(m.group(1)) if m else None
    except ValueError:
        d["warn"] = None
    return d


def query_task(name: str) -> dict:
    """{'state','last','result','next','missed','days','at','warn'} | {'missing': True} | {'error': str}."""
    try:
        p = ps(_query_script(name))
        if p.returncode != 0:
            return {"error": _err(p)}
        return parse_query(p.stdout)
    except Exception as e:  # noqa: BLE001  (timeouts, bad JSON, missing powershell)
        return {"error": str(e)[:240]}


def result_text(code: int) -> str:
    known = {0: "OK", 1: "Failed - see the log", 2: "No router password", 3: "Sent, recovery not verified",
             4: "Refused (cooldown or already running)", 267009: "Running", 267011: "Not run yet",
             267014: "Stopped by user", 2147750687: "Already running"}
    return known.get(code, f"Error 0x{code & 0xFFFFFFFF:X}")


# ---------- changes ----------

def set_enabled(name: str, enabled: bool) -> tuple[bool, str]:
    cmd = "Enable-ScheduledTask" if enabled else "Disable-ScheduledTask"
    p = ps(f"$ErrorActionPreference = 'Stop'; {cmd} -TaskName {q(name)} | Out-Null")
    return (p.returncode == 0, "" if p.returncode == 0 else _err(p))


_PRINCIPAL = ('$p = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\\$env:USERNAME" '
              '-LogonType Interactive -RunLevel Limited\n')


def reboot_task_script(name: str, at: str, every_days: int, warn_minutes: float, register: bool = True) -> str:
    if not TIME_RE.match(at):
        raise ValueError("time must be HH:MM (24-hour, two digits each, e.g. 04:00)")
    if not 1 <= int(every_days) <= 365:
        raise ValueError("every_days must be 1-365")
    if not 0 <= float(warn_minutes) <= 120:
        raise ValueError("warn_minutes must be 0-120")
    args = f'"{CLI}" reboot --prompt --warn-minutes {float(warn_minutes):g}'
    script = f"""
$ErrorActionPreference = 'Stop'
$a = New-ScheduledTaskAction -Execute {q(_execute())} -Argument {q(args)} -WorkingDirectory {q(ROOT)}
$t = New-ScheduledTaskTrigger -Daily -DaysInterval {int(every_days)} -At {q(at)}
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
     -ExecutionTimeLimit (New-TimeSpan -Hours 3) -MultipleInstances IgnoreNew
{_PRINCIPAL}"""
    if register:
        script += (f"Register-ScheduledTask -TaskName {q(name)} -Action $a -Trigger $t -Settings $s -Principal $p "
                   f"-Description {q('router-auto-restart: scheduled router restart with a countdown window')} "
                   f"-Force | Out-Null\n")
    else:
        script += "if ($a -and $t -and $s -and $p) { 'ok' }\n"
    return script


def watchdog_task_script(name: str, register: bool = True) -> str:
    args = f'"{CLI}" watchdog'
    script = f"""
$ErrorActionPreference = 'Stop'
$a = New-ScheduledTaskAction -Execute {q(_execute())} -Argument {q(args)} -WorkingDirectory {q(ROOT)}
$t = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\\$env:USERNAME"
$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
     -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
{_PRINCIPAL}"""
    if register:
        script += (f"Register-ScheduledTask -TaskName {q(name)} -Action $a -Trigger $t -Settings $s -Principal $p "
                   f"-Description {q('router-auto-restart: internet watchdog')} -Force | Out-Null\n")
    else:
        script += "if ($a -and $t -and $s -and $p) { 'ok' }\n"
    return script


def install_reboot_task(name: str, at: str, every_days: int, warn_minutes: float) -> tuple[bool, str]:
    p = ps(reboot_task_script(name, at, every_days, warn_minutes))
    return (p.returncode == 0, "" if p.returncode == 0 else _err(p))


def install_watchdog_task(name: str) -> tuple[bool, str]:
    p = ps(watchdog_task_script(name))
    return (p.returncode == 0, "" if p.returncode == 0 else _err(p))


def uninstall(name: str) -> tuple[bool, str]:
    p = ps(f"$ErrorActionPreference = 'Stop'; "
           f"if (Get-ScheduledTask -TaskName {q(name)} -ErrorAction SilentlyContinue) "
           f"{{ Unregister-ScheduledTask -TaskName {q(name)} -Confirm:$false }}")
    return (p.returncode == 0, "" if p.returncode == 0 else _err(p))
