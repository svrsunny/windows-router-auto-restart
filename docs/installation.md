# Installation

Everything below is typed into a **PowerShell** window (Start → type *PowerShell* → Enter). No
administrator rights are needed.

## 1. Prerequisites

```powershell
[Environment]::OSVersion.Version      # 10.0.x = Windows 10 or 11
$PSVersionTable.PSVersion             # 5.1 or later
py -3 --version                       # Python 3.9 or later
git --version                         # only needed to clone
```

Install anything missing:

```powershell
winget install Python.Python.3.12
winget install Git.Git
```

Open a **new** PowerShell window afterwards so the new commands are found.

`curl` isn't needed. If you use `curl` for your own experiments, note that in Windows PowerShell 5.1
`curl` is an alias for `Invoke-WebRequest`. Type `curl.exe` to get the real curl.

## 2. Get the code

```powershell
git clone https://github.com/svrsunny/windows-router-auto-restart.git
Set-Location .\windows-router-auto-restart
```

If you downloaded a ZIP instead, Windows marks its files as "from the internet". Unblock them once:

```powershell
Get-ChildItem -Recurse | Unblock-File
```

## 3. Allow the scripts to run in this window

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

This only affects the current PowerShell window and changes nothing permanently.

## 4. Install

```powershell
.\scripts\Install.ps1
```

This checks the prerequisites, creates `.venv` (a private Python environment inside the folder) and
installs `requests` into it. Running it again is harmless. To use a specific Python:
`.\scripts\Install.ps1 -Python C:\Path\To\python.exe`.

Using a `.venv` matters on PCs with Python from the Microsoft Store. The venv gives a stable
`pythonw.exe` path that scheduled tasks and taskbar shortcuts can rely on, even after Store updates.

## 5. Next

1. [Configure](configuration.md): `.\scripts\Configure.ps1`
2. Test: `.\scripts\Test-Connection.ps1`
3. [Schedule](scheduling.md): `.\scripts\Register-ScheduledTask.ps1`
4. Optional: `.\scripts\New-Shortcut.ps1` for a dashboard shortcut you can pin to the taskbar

## Updating

```powershell
git pull
.\scripts\Install.ps1        # picks up any dependency changes
```

The scheduled task points at this folder, so it uses the updated code automatically. If you move
the folder, run `Register-ScheduledTask.ps1` and `New-Shortcut.ps1` again.
