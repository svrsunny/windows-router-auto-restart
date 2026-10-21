# Shared helpers, dot-sourced by the other scripts. Compatible with Windows PowerShell 5.1 and PowerShell 7.
Set-StrictMode -Version 2
$ErrorActionPreference = 'Stop'

$script:RepoRoot    = Split-Path -Parent $PSScriptRoot
$script:RouterCtl   = Join-Path $RepoRoot 'src\routerctl.py'
$script:VenvDir     = Join-Path $RepoRoot '.venv'
$script:VenvPython  = Join-Path $VenvDir 'Scripts\python.exe'
$script:VenvPythonW = Join-Path $VenvDir 'Scripts\pythonw.exe'
$script:DataHome    = if ($env:ROUTER_AUTO_RESTART_HOME) { $env:ROUTER_AUTO_RESTART_HOME } else { $RepoRoot }
$script:ConfigPath  = Join-Path $DataHome 'config\config.json'
$script:CredentialTarget = 'RouterAutoRestart:router-admin'
$script:ShortcutName = 'Router Auto Restart'
$script:AppUserModelId = 'RouterAutoRestart.Dashboard'   # must match APP_ID in src\routerkit\ui\dashboard.py

function Write-Step([string]$Text) { Write-Host "`n==> $Text" -ForegroundColor Cyan }
function Write-Ok([string]$Text)   { Write-Host "    [ OK ] $Text" -ForegroundColor Green }
function Write-Warn2([string]$Text) { Write-Host "    [WARN] $Text" -ForegroundColor Yellow }
function Write-Fail([string]$Text) { Write-Host "    [FAIL] $Text" -ForegroundColor Red }

function Get-ProjectPython {
    # ROUTER_AUTO_RESTART_PYTHON lets tests or custom setups point at another interpreter.
    if ($env:ROUTER_AUTO_RESTART_PYTHON) { return $env:ROUTER_AUTO_RESTART_PYTHON }
    if (Test-Path -LiteralPath $VenvPython) { return $VenvPython }
    throw "The project's Python environment (.venv) is missing. Run .\scripts\Install.ps1 first."
}

function Invoke-RouterCtl {
    # Runs src\routerctl.py with the project's Python; check $LASTEXITCODE afterwards.
    # A simple function on purpose: $args passes '--flags' through untouched.
    $py = Get-ProjectPython
    & $py $RouterCtl @args
}

function Get-ConfigObject {
    if (-not (Test-Path -LiteralPath $ConfigPath)) { return $null }
    return (Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8) | ConvertFrom-Json
}

function Get-ConfigValue([string]$Name, $Default) {
    $cfg = Get-ConfigObject
    if ($cfg -and ($cfg.PSObject.Properties.Name -contains $Name) -and $null -ne $cfg.$Name -and "$($cfg.$Name)" -ne '') {
        return $cfg.$Name
    }
    return $Default
}

function Get-TaskName        { return [string](Get-ConfigValue 'task_name' 'RouterAutoRestart') }
function Get-WatchdogTaskName { return [string](Get-ConfigValue 'watchdog_task_name' 'RouterAutoRestart-Watchdog') }

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    $dir = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
    [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding $false))
}

function Get-ExitMeaning([int]$Code) {
    switch ($Code) {
        0 { 'OK' }
        1 { 'failed - see logs\router-auto-restart.log' }
        2 { 'no router password stored - run .\scripts\Configure.ps1' }
        3 { 'restart request sent, but recovery was not verified - check the router' }
        4 { 'refused: a restart is already running or one just happened (cooldown)' }
        5 { 'configuration problem - run .\scripts\Configure.ps1' }
        default { "exit code $Code" }
    }
}
