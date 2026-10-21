<#
.SYNOPSIS
    Removes the scheduled restart task (and optionally the watchdog's logon task).
.DESCRIPTION
    Uses only built-in cmdlets, so it works even if .venv has been deleted. Leaves configuration,
    password, logs and source files alone.
.EXAMPLE
    .\scripts\Remove-ScheduledTask.ps1
.EXAMPLE
    .\scripts\Remove-ScheduledTask.ps1 -IncludeWatchdog -WhatIf
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param([switch]$IncludeWatchdog)
. "$PSScriptRoot\_Common.ps1"

$names = @(Get-TaskName)
if ($IncludeWatchdog) { $names += Get-WatchdogTaskName }
foreach ($n in $names) {
    $task = Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
    if (-not $task) { Write-Ok "'$n' is not registered"; continue }
    if ($PSCmdlet.ShouldProcess($n, 'Unregister scheduled task')) {
        Unregister-ScheduledTask -TaskName $n -Confirm:$false
        Write-Ok "removed '$n'"
    }
}
exit 0
