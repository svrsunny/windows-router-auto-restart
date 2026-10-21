<#
.SYNOPSIS
    Registers (or updates) the Windows scheduled task that restarts the router every N days.
.DESCRIPTION
    Defaults come from config\config.json (restart_time, interval_days, warn_minutes). Running it
    again with other values updates the existing task.

    The task runs as YOU, only while you are logged on, without admin rights. That is deliberate:
    the countdown window must appear on your desktop and the password is in your Credential
    Manager. No password is put in the task. If the PC is off or asleep at that time, the task
    runs as soon as possible afterwards. It is never retried automatically after a failure.

    Use -WhatIf to see exactly what would be registered without changing anything.
.EXAMPLE
    .\scripts\Register-ScheduledTask.ps1
.EXAMPLE
    .\scripts\Register-ScheduledTask.ps1 -Time 04:00 -IntervalDays 3 -WithWatchdog
.EXAMPLE
    .\scripts\Register-ScheduledTask.ps1 -WhatIf
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')][string]$Time,
    [ValidateRange(0, 365)][int]$IntervalDays = 0,
    [double]$WarnMinutes = -1,
    [switch]$WithWatchdog
)
. "$PSScriptRoot\_Common.ps1"

$cliArgs = @('install')
if ($Time) { $cliArgs += @('--time', $Time) }
if ($IntervalDays -gt 0) { $cliArgs += @('--every-days', "$IntervalDays") }
if ($WarnMinutes -ge 0) { $cliArgs += @('--warn-minutes', "$WarnMinutes") }
if ($WithWatchdog) { $cliArgs += '--with-watchdog' }

$name = Get-TaskName
if ($WhatIfPreference) {
    Write-Host "What if: would register scheduled task '$name' with this PowerShell:" -ForegroundColor Cyan
    $previewArgs = $cliArgs + '--print-only'
    Invoke-RouterCtl @previewArgs
    exit $LASTEXITCODE
}
if (-not $PSCmdlet.ShouldProcess($name, 'Register scheduled router restart')) { exit 0 }
Invoke-RouterCtl @cliArgs
$code = $LASTEXITCODE
if ($code -ne 0) { Write-Fail (Get-ExitMeaning $code); exit $code }

$task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
if ($task) {
    $info = $task | Get-ScheduledTaskInfo
    Write-Ok "State: $($task.State)   Next run: $($info.NextRunTime)"
}
Write-Host @"

Useful commands:
  Get-ScheduledTask -TaskName '$name' | Get-ScheduledTaskInfo     # last/next run, last result
  Start-ScheduledTask -TaskName '$name'                            # run it now (countdown window first)
  Disable-ScheduledTask -TaskName '$name'                          # pause
  Enable-ScheduledTask -TaskName '$name'                           # resume
  .\scripts\Register-ScheduledTask.ps1 -Time 05:30 -IntervalDays 2   # change time / interval
  .\scripts\Remove-ScheduledTask.ps1                               # remove
"@
exit 0
