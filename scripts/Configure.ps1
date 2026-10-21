<#
.SYNOPSIS
    Creates or updates config\config.json and stores the router password in Windows Credential Manager.
.DESCRIPTION
    Asks for the router address, model, username, restart time and interval. Values you leave
    blank keep their current (or default) value. Settings not asked about are preserved.

    The password is read with Read-Host -AsSecureString and handed to Python over standard input,
    so it never appears in a file, a command line, a log or the console history. Python then
    stores it in Credential Manager for the current Windows user (encrypted with DPAPI). The
    scheduled task must therefore run as this same user - which is how Register-ScheduledTask.ps1
    sets it up.
.EXAMPLE
    .\scripts\Configure.ps1
.EXAMPLE
    .\scripts\Configure.ps1 -RouterUrl http://192.0.2.1 -Model gx-gpon-e4222 -RestartTime 04:00 -IntervalDays 3 -NonInteractive -SkipPassword
#>
[CmdletBinding()]
param(
    [string]$RouterUrl,
    [string]$Model,
    [string]$Username,
    [string]$RestartTime,
    [int]$IntervalDays = 0,
    [double]$WarnMinutes = -1,
    [switch]$SkipPassword,
    [switch]$NonInteractive
)
. "$PSScriptRoot\_Common.ps1"
# Windows PowerShell 5.1 can serialise nested arrays as {"value":[...],"Count":n}; this avoids it (this session only)
if ($PSVersionTable.PSVersion.Major -lt 6) { Remove-TypeData System.Array -ErrorAction SilentlyContinue }

$timeRe = '^([01]?\d|2[0-3]):[0-5]\d$'

function Read-Value([string]$Prompt, [string]$Default, [scriptblock]$Valid, [string]$Hint) {
    if ($NonInteractive) {
        if (& $Valid $Default) { return $Default }
        throw "$Prompt`: '$Default' is not valid ($Hint)"
    }
    while ($true) {
        $shown = if ($Default) { " [$Default]" } else { '' }
        $v = Read-Host "$Prompt$shown"
        if ([string]::IsNullOrWhiteSpace($v)) { $v = $Default }
        if ($v -and (& $Valid $v)) { return $v.Trim() }
        Write-Warn2 "Not valid: $Hint"
    }
}

Write-Step 'Router settings'
$existing = Get-ConfigObject
$cfg = [ordered]@{}
if ($existing) { foreach ($p in $existing.PSObject.Properties) { $cfg[$p.Name] = $p.Value } }
function Current([string]$Name, $Default) { if ($cfg.Contains($Name) -and "$($cfg[$Name])" -ne '') { return $cfg[$Name] } return $Default }

# supported models come from the Python adapters, so this list never goes stale
$models = @(Invoke-RouterCtl models | Where-Object { $_ -match "`t" } | ForEach-Object {
    $id, $desc = $_ -split "`t", 2; [pscustomobject]@{ Id = $id; Description = $desc } })
if (-not $models) { throw 'Could not list supported router models (is .venv installed?)' }
if (-not $NonInteractive -and -not $Model) {
    Write-Host '    Supported router models (verified on real devices):'
    $models | ForEach-Object { Write-Host "      $($_.Id)  -  $($_.Description)" }
    Write-Host '    Not listed? See docs\router-compatibility.md - other routers need their own adapter.'
}
$defModel = if ($Model) { $Model } else { Current 'router_model' $(if ($models.Count -eq 1) { $models[0].Id } else { '' }) }
$cfg['router_model'] = Read-Value 'Router model' $defModel { param($v) $models.Id -contains $v } 'one of the ids listed above'

if ($RouterUrl) {
    $url = $RouterUrl.TrimEnd('/')
} else {
    $u = $null
    $cur = Current 'router_url' ''
    if ($cur) { try { $u = [uri]$cur } catch { } }
    $hostDefault = if ($u) { $u.Host } else { '' }
    $schemeDefault = if ($u) { $u.Scheme } else { 'http' }
    $portDefault = if ($u -and -not $u.IsDefaultPort) { [string]$u.Port } else { '' }
    $h = Read-Value 'Router address (IP or hostname, e.g. 192.168.1.1)' $hostDefault {
        param($v) $v -match '^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$' } 'an IP address or hostname, without http://'
    $scheme = Read-Value 'Protocol (http or https)' $schemeDefault { param($v) $v -in @('http', 'https') } 'http or https'
    $port = if ($NonInteractive) { $portDefault } else { Read-Host "Port (blank for the default $(if ($scheme -eq 'https') {443} else {80}))$(if ($portDefault) {" [$portDefault]"})" }
    if ([string]::IsNullOrWhiteSpace($port)) { $port = $portDefault }
    if ($port -and ($port -notmatch '^\d{1,5}$' -or [int]$port -lt 1 -or [int]$port -gt 65535)) { throw "Invalid port '$port'" }
    $url = "${scheme}://$h" + $(if ($port) { ":$port" } else { '' })
}
if ($url -notmatch '^https?://[^/@\s]+$') { throw "Router URL '$url' must look like http://192.0.2.1 (no path, no user:password@)." }
$cfg['router_url'] = $url

$cfg['username'] = Read-Value 'Router admin username' $(if ($Username) { $Username } else { Current 'username' 'admin' }) {
    param($v) -not [string]::IsNullOrWhiteSpace($v) } 'must not be empty'

Write-Step 'Schedule (used by Register-ScheduledTask.ps1)'
$t = Read-Value 'Restart time, 24-hour HH:MM (local time)' $(if ($RestartTime) { $RestartTime } else { Current 'restart_time' '04:00' }) {
    param($v) $v -match $timeRe } 'e.g. 04:00 or 14:50'
$hh, $mm = $t -split ':'
$cfg['restart_time'] = '{0:00}:{1}' -f [int]$hh, $mm
$d = Read-Value 'Restart every how many days' $(if ($IntervalDays -gt 0) { "$IntervalDays" } else { "$(Current 'interval_days' 3)" }) {
    param($v) $v -match '^\d+$' -and [int]$v -ge 1 -and [int]$v -le 365 } 'a whole number from 1 to 365'
$cfg['interval_days'] = [int]$d
$w = Read-Value 'Countdown window before each restart, minutes (0 = none)' $(if ($WarnMinutes -ge 0) { "$WarnMinutes" } else { "$(Current 'warn_minutes' 10)" }) {
    param($v) $v -match '^\d+(\.\d+)?$' -and [double]$v -le 120 } 'a number from 0 to 120'
$cfg['warn_minutes'] = [double]$w

Write-Step "Writing $ConfigPath"
Write-Utf8NoBom $ConfigPath (($cfg | ConvertTo-Json -Depth 5) + "`n")
Invoke-RouterCtl check-config
if ($LASTEXITCODE -ne 0) { Write-Fail 'The configuration is not valid (see above).'; exit 5 }
Write-Ok 'configuration saved (contains no password)'

if ($SkipPassword) {
    Write-Warn2 'Password step skipped (-SkipPassword).'
} else {
    Write-Step "Router password for '$($cfg['username'])'"
    Write-Host '    Typed characters are hidden. The password goes to Windows Credential Manager, not to a file.'
    $s1 = Read-Host 'Password' -AsSecureString
    $s2 = Read-Host 'Again' -AsSecureString
    $b1 = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s1)
    $b2 = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s2)
    $oldEnc = $OutputEncoding
    try {
        $p1 = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b1)
        $p2 = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b2)
        if ($p1 -ne $p2) { Write-Fail 'The two entries differ; password not changed.'; exit 1 }
        if (-not $p1) { Write-Fail 'Empty password; not changed.'; exit 1 }
        # UTF-8 so non-ASCII characters survive the pipe (Windows PowerShell defaults to ASCII here)
        $OutputEncoding = New-Object System.Text.UTF8Encoding $false
        $p1 | & (Get-ProjectPython) $RouterCtl set-password --stdin   # piped: never on the command line
        if ($LASTEXITCODE -ne 0) { Write-Fail 'Could not store the password.'; exit 1 }
    } finally {
        $OutputEncoding = $oldEnc
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b1)
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b2)
        Remove-Variable p1, p2, s1, s2 -ErrorAction SilentlyContinue
    }
    Write-Host '    Note: .NET strings cannot be wiped from memory reliably; the plain copy lives only in this'
    Write-Host '    PowerShell process until it exits. Close this window when you are done if that matters to you.'
}

Write-Step 'Next: .\scripts\Test-Connection.ps1'
exit 0
