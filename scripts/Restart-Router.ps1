<#
.SYNOPSIS
    Restarts the router NOW. Your internet connection drops while it restarts.
.DESCRIPTION
    Asks for confirmation unless -Force is given. After sending the restart request it watches the
    router go offline and come back, then waits for the internet, and reports the timings.
    Recovery usually takes one to three minutes but depends on the router and the ISP.

    The restart request is sent once and never retried. A second restart within the cooldown
    (reboot_cooldown_minutes, default 10) is refused unless -IgnoreCooldown is given.
.PARAMETER Force
    Don't ask for confirmation (for unattended use).
.PARAMETER NoWait
    Return right after sending the request instead of following the router's recovery.
.PARAMETER IgnoreCooldown
    Allow a restart even though one succeeded within the last few minutes.
.EXAMPLE
    .\scripts\Restart-Router.ps1
.EXAMPLE
    .\scripts\Restart-Router.ps1 -WhatIf
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param([switch]$Force, [switch]$NoWait, [switch]$IgnoreCooldown)
. "$PSScriptRoot\_Common.ps1"

$target = [string](Get-ConfigValue 'router_url' 'the router in config\config.json')
if ($Force -and -not $WhatIfPreference) { $ConfirmPreference = 'None' }
if (-not $PSCmdlet.ShouldProcess($target, 'Restart the router now (internet drops for a few minutes)')) {
    exit 0
}
$cliArgs = @('reboot', '--yes')
if ($NoWait) { $cliArgs += '--no-wait' }
if ($IgnoreCooldown) { $cliArgs += '--force' }
Invoke-RouterCtl @cliArgs
$code = $LASTEXITCODE
$color = if ($code -eq 0) { 'Green' } else { 'Yellow' }
Write-Host "`nResult: $(Get-ExitMeaning $code)" -ForegroundColor $color
exit $code
