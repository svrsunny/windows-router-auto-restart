<#
.SYNOPSIS
    Reverses the setup. Asks before every step; the repository and its source files are never touched.
.DESCRIPTION
    Always offered (each asks for confirmation):
      - remove the scheduled restart task and the watchdog logon task
      - stop a running watchdog started from this folder
      - remove the Start menu / desktop shortcuts created by New-Shortcut.ps1
    Only when asked for:
      -RemovePassword   delete the stored password from Windows Credential Manager
      -RemoveLocalData  delete config\config.json, data\ and logs\
      -RemoveVenv       delete the .venv Python environment
    Use -WhatIf to see what would happen, or -Confirm:$false to skip the questions.
.EXAMPLE
    .\scripts\Uninstall.ps1
.EXAMPLE
    .\scripts\Uninstall.ps1 -RemovePassword -RemoveLocalData -RemoveVenv
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param([switch]$RemovePassword, [switch]$RemoveLocalData, [switch]$RemoveVenv)
. "$PSScriptRoot\_Common.ps1"

Write-Step 'Scheduled tasks'
foreach ($n in @((Get-TaskName), (Get-WatchdogTaskName))) {
    if (-not (Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue)) { Write-Ok "'$n' not registered"; continue }
    if ($PSCmdlet.ShouldProcess($n, 'Unregister scheduled task')) {
        Unregister-ScheduledTask -TaskName $n -Confirm:$false
        Write-Ok "removed '$n'"
    }
}

Write-Step 'Running watchdog'
$ctl = [regex]::Escape($RouterCtl)
$procs = @(Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match $ctl -and $_.CommandLine -match '\swatchdog\b' })
if (-not $procs) { Write-Ok 'none running' }
foreach ($p in $procs) {
    if ($PSCmdlet.ShouldProcess("PID $($p.ProcessId)", 'Stop watchdog process')) {
        Stop-Process -Id $p.ProcessId -Confirm:$false
        Write-Ok "stopped PID $($p.ProcessId)"
    }
}

Write-Step 'Shortcuts'
foreach ($path in @((Join-Path ([Environment]::GetFolderPath('Programs')) "$ShortcutName.lnk"),
                    (Join-Path ([Environment]::GetFolderPath('Desktop')) "$ShortcutName.lnk"))) {
    if (-not (Test-Path -LiteralPath $path)) { continue }
    if ($PSCmdlet.ShouldProcess($path, 'Delete shortcut')) { Remove-Item -LiteralPath $path -Confirm:$false; Write-Ok "deleted $path" }
}
Write-Host '    (A pinned taskbar icon is removed with right-click > Unpin from taskbar.)'

if ($RemovePassword) {
    Write-Step 'Stored password'
    $listed = (cmdkey /list:$CredentialTarget | Out-String) -match [regex]::Escape($CredentialTarget)
    if (-not $listed) { Write-Ok 'no stored password' }
    elseif ($PSCmdlet.ShouldProcess($CredentialTarget, 'Delete from Windows Credential Manager')) {
        $null = cmdkey /delete:$CredentialTarget
        Write-Ok 'deleted'
    }
}

if ($RemoveLocalData) {
    Write-Step 'Local configuration, state and logs'
    foreach ($path in @($ConfigPath, (Join-Path $DataHome 'data'), (Join-Path $DataHome 'logs'))) {
        if (-not (Test-Path -LiteralPath $path)) { continue }
        if ($PSCmdlet.ShouldProcess($path, 'Delete')) { Remove-Item -LiteralPath $path -Recurse -Confirm:$false; Write-Ok "deleted $path" }
    }
}

if ($RemoveVenv) {
    Write-Step 'Python environment'
    if ((Test-Path -LiteralPath $VenvDir) -and $PSCmdlet.ShouldProcess($VenvDir, 'Delete')) {
        Remove-Item -LiteralPath $VenvDir -Recurse -Confirm:$false
        Write-Ok "deleted $VenvDir"
    }
}

Write-Step 'Done. The repository folder and source files were left in place.'
exit 0
