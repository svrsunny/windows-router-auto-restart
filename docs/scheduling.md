# Scheduling

The automatic restart is a normal Windows **Task Scheduler** task. Nothing stays running in the
background for it.

## Register

```powershell
.\scripts\Register-ScheduledTask.ps1 -WhatIf     # print exactly what would be registered; change nothing
.\scripts\Register-ScheduledTask.ps1             # restart_time / interval_days / warn_minutes from config
.\scripts\Register-ScheduledTask.ps1 -Time 04:00 -IntervalDays 3 -WarnMinutes 10
.\scripts\Register-ScheduledTask.ps1 -WithWatchdog   # also start the internet watchdog at logon
```

Running it again with other values replaces the existing task, which is how you change the time or interval.

## How the task is set up

| Setting | Value | Why |
|---|---|---|
| Trigger | Daily, every *N* days, at *HH:MM* local time | Default every 3 days |
| Runs as | You, **only when you're logged on**, without admin rights | The countdown window must appear on your desktop, and the password is in your own Credential Manager |
| Program | `.venv\Scripts\pythonw.exe` (no console window) | Stable path, no flashing console |
| Arguments | `"…\src\routerctl.py" reboot --prompt --warn-minutes N` | No password or other secret, ever |
| Working directory | the repository folder | |
| Missed run | Runs as soon as possible after the scheduled time (*StartWhenAvailable*) | PC was off or asleep |
| Retries on failure | **None** | A retry could restart the router twice |
| Overlap | A new instance is ignored while one is running | |
| Time limit | 3 hours | Countdown plus postponements |
| Power | Runs on battery too | |

**Daylight saving and time zones:** the trigger uses local wall-clock time, so a 04:00 task stays at
04:00 when the clocks change. On the day the clocks go forward, a time inside the skipped hour runs
when that hour would have been. If you travel to another time zone, the task follows the PC's
current clock.

**Logged off or asleep:** the task doesn't wake the PC and doesn't run while nobody is logged on.
It catches up at the next opportunity, which may be at an unexpected time, and the countdown window
still gives you the chance to postpone or skip.

**Another Windows account:** a task registered by one user can't read another user's Credential
Manager. Register the task and store the password while logged on as the same user.

## What happens at the scheduled time

1. If **Skip next run** was set in the dashboard, the flag is cleared and nothing else happens.
2. The countdown window appears. Choose *Restart now*, *Postpone 30 min*, *Postpone 1 h* or *Skip
   this time*. Closing the window counts as skip. Ignoring it restarts when the countdown ends.
3. The router is logged in to and the restart request is sent once.
4. The router is watched going offline and coming back, then the internet. The result goes to the
   log and the task's *Last Run Result*: 0 = recovered, 3 = request sent but recovery not verified.

## Inspect and manage

```powershell
Get-ScheduledTask -TaskName RouterAutoRestart | Get-ScheduledTaskInfo   # LastRunTime, LastTaskResult, NextRunTime
Get-ScheduledTask -TaskName RouterAutoRestart | Select-Object -ExpandProperty Triggers
Start-ScheduledTask   -TaskName RouterAutoRestart     # test now (countdown appears first)
Disable-ScheduledTask -TaskName RouterAutoRestart     # pause
Enable-ScheduledTask  -TaskName RouterAutoRestart     # resume
.\scripts\Remove-ScheduledTask.ps1                     # remove (add -IncludeWatchdog for the watchdog task)
```

You can also use the dashboard (*Pause schedule*, *Skip next run*, *Edit schedule*) or Task
Scheduler itself (`taskschd.msc`, *Task Scheduler Library*).

`LastTaskResult` values: 0 OK · 1 failed · 2 no password · 3 sent, recovery not verified ·
4 refused (cooldown or already running) · 5 configuration problem · 267011 not run yet.

## Watchdog task

`-WithWatchdog` registers `RouterAutoRestart-Watchdog`, which starts the watchdog when you log on.
On some PCs creating a logon-triggered task needs an elevated PowerShell. If it fails with
"Access is denied", run that one command in PowerShell opened with *Run as administrator*. You can
also start the watchdog from the dashboard when needed.
