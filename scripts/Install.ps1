<#
.SYNOPSIS
    Checks prerequisites and creates the project's Python environment (.venv).
.DESCRIPTION
    Safe to run more than once. Changes nothing outside the repository folder: no scheduled
    tasks, no shortcuts, no system settings. Next steps are printed at the end.
.PARAMETER Python
    Path to a specific python.exe to build the environment from (default: the py launcher, then python).
.EXAMPLE
    .\scripts\Install.ps1
#>
[CmdletBinding()]
param([string]$Python)
. "$PSScriptRoot\_Common.ps1"

Write-Step 'Checking prerequisites'
$os = [Environment]::OSVersion.Version
if ($os.Major -lt 10) { Write-Fail "Windows 10 or 11 is required (found $os)."; exit 1 }
Write-Ok "Windows $($os.Major).$($os.Minor) build $($os.Build)"
if ($PSVersionTable.PSVersion -lt [version]'5.1') { Write-Fail 'PowerShell 5.1 or later is required.'; exit 1 }
Write-Ok "PowerShell $($PSVersionTable.PSVersion)"

function Test-PythonCandidate([string]$Exe, [string[]]$Prefix) {
    try {
        # no quotes inside the code: Windows PowerShell 5.1 strips them from native arguments
        $out = & $Exe @Prefix -c 'import sys; print(*sys.version_info[:2], sep=chr(46))' 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $out) { return $null }
        $v = [version]("$out".Trim())
        if ($v -ge [version]'3.9') { return @{ Exe = $Exe; Prefix = $Prefix; Version = $v } }
    } catch { }
    return $null
}

$found = $null
if ($Python) { $found = Test-PythonCandidate $Python @() }
else {
    foreach ($c in @(@{ E = 'py'; P = @('-3') }, @{ E = 'python'; P = @() })) {
        if (Get-Command $c.E -ErrorAction SilentlyContinue) {
            $found = Test-PythonCandidate $c.E $c.P
            if ($found) { break }
        }
    }
}
if (-not $found) {
    Write-Fail 'Python 3.9 or later was not found.'
    Write-Host  '    Install it with:  winget install Python.Python.3.12   (or from https://www.python.org)'
    Write-Host  '    then open a new PowerShell window and run this script again.'
    exit 1
}
Write-Ok "Python $($found.Version) ($($found.Exe) $($found.Prefix -join ' '))"

if (Get-Command git -ErrorAction SilentlyContinue) { Write-Ok "$(git --version)" }
else { Write-Warn2 'Git not found (only needed to clone or update the repository).' }

Write-Step 'Creating the Python environment (.venv)'
if (Test-Path -LiteralPath $VenvPython) {
    Write-Ok '.venv already exists'
} else {
    & $found.Exe @($found.Prefix) -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { Write-Fail 'Could not create .venv'; exit 1 }
    Write-Ok "created $VenvDir"
}

Write-Step 'Installing dependencies (requests)'
& $VenvPython -m pip install --disable-pip-version-check --quiet -r (Join-Path $RepoRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { Write-Fail 'pip install failed (internet connection?)'; exit 1 }
Write-Ok 'dependencies installed'

Write-Step 'Done. Next steps:'
Write-Host '    .\scripts\Configure.ps1               # enter your router address, model, password and schedule'
Write-Host '    .\scripts\Test-Connection.ps1         # check everything without restarting'
Write-Host '    .\scripts\Register-ScheduledTask.ps1  # turn on the automatic restart'
Write-Host '    .\scripts\New-Shortcut.ps1            # Start menu / desktop shortcut you can pin to the taskbar'
exit 0
