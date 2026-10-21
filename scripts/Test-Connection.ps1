<#
.SYNOPSIS
    Diagnostics. Never restarts the router.
.DESCRIPTION
    Checks, in order: the router answers on its address and port; its web interface looks like the
    configured model; the stored password logs in (and logs straight out again); the internet is
    reachable; DNS works.

    Passing every check does not prove a restart will succeed - only a real restart can show that.
.PARAMETER SkipLogin
    Don't log in (useful while someone is logged in to the router's web page: the router allows only
    one admin session).
.EXAMPLE
    .\scripts\Test-Connection.ps1
#>
[CmdletBinding()]
param([switch]$SkipLogin)
. "$PSScriptRoot\_Common.ps1"

$cliArgs = @('test')
if ($SkipLogin) { $cliArgs += '--no-login' }
Invoke-RouterCtl @cliArgs
$code = $LASTEXITCODE
if ($code -ne 0) { Write-Host "`nResult: $(Get-ExitMeaning $code)" -ForegroundColor Yellow }
exit $code
