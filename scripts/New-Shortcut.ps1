<#
.SYNOPSIS
    Creates a Start menu and/or desktop shortcut for the dashboard that can be pinned to the taskbar.
.DESCRIPTION
    Windows only offers "Pin to taskbar" for shortcuts whose target is a program (.exe). A shortcut
    to a .py or .pyw file points at a script, so the option is missing. This script makes a
    shortcut whose target is the project's .venv\Scripts\pythonw.exe (no console window), with
    the dashboard as its argument and the project icon.

    It also stamps the shortcut with an AppUserModelID that the dashboard sets on its own window,
    so the pinned icon and the running window share one taskbar button instead of two.

    To pin: open Start, find "Router Auto Restart", right-click > Pin to taskbar.
    (or open the dashboard from the shortcut, right-click its taskbar button > Pin to taskbar)
.PARAMETER Desktop
    Create only the desktop shortcut.
.PARAMETER StartMenu
    Create only the Start menu shortcut. With neither switch, both are created.
.PARAMETER Directory
    Create the shortcut in this folder instead (used by the tests).
.EXAMPLE
    .\scripts\New-Shortcut.ps1
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param([switch]$Desktop, [switch]$StartMenu, [string]$Directory)
. "$PSScriptRoot\_Common.ps1"

if (-not (Test-Path -LiteralPath $VenvPythonW)) { throw "Missing $VenvPythonW - run .\scripts\Install.ps1 first." }
if (-not $Desktop -and -not $StartMenu -and -not $Directory) { $Desktop = $true; $StartMenu = $true }

if (-not ('RouterAutoRestart.ShortcutAppId' -as [type])) {
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace RouterAutoRestart {
    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    public struct PropertyKey { public Guid FormatId; public uint PropertyId;
        public PropertyKey(Guid f, uint p) { FormatId = f; PropertyId = p; } }
    [StructLayout(LayoutKind.Explicit)]
    public struct PropVariant {
        [FieldOffset(0)] public ushort vt;
        [FieldOffset(8)] public IntPtr pointer;
        [FieldOffset(16)] public IntPtr padding;      // PROPVARIANT is 24 bytes on x64
    }
    [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IPropertyStore {
        [PreserveSig] int GetCount(out uint count);
        [PreserveSig] int GetAt(uint index, out PropertyKey key);
        [PreserveSig] int GetValue(ref PropertyKey key, out PropVariant value);
        [PreserveSig] int SetValue(ref PropertyKey key, ref PropVariant value);
        [PreserveSig] int Commit();
    }
    [ComImport, Guid("0000010b-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IPersistFile {
        [PreserveSig] int GetClassID(out Guid id);
        [PreserveSig] int IsDirty();
        [PreserveSig] int Load([MarshalAs(UnmanagedType.LPWStr)] string file, uint mode);
        [PreserveSig] int Save([MarshalAs(UnmanagedType.LPWStr)] string file, [MarshalAs(UnmanagedType.Bool)] bool remember);
        [PreserveSig] int SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string file);
        [PreserveSig] int GetCurFile([MarshalAs(UnmanagedType.LPWStr)] out string file);
    }
    [ComImport, Guid("00021401-0000-0000-C000-000000000046")]
    class CShellLink { }
    public static class ShortcutAppId {
        // PKEY_AppUserModel_ID
        static readonly PropertyKey Key = new PropertyKey(new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), 5);
        public static void Set(string lnkPath, string appId) {
            object link = new CShellLink();
            try {
                IPersistFile file = (IPersistFile)link;
                Marshal.ThrowExceptionForHR(file.Load(lnkPath, 2));          // STGM_READWRITE
                IPropertyStore store = (IPropertyStore)link;
                PropVariant pv = new PropVariant();
                pv.vt = 31;                                                   // VT_LPWSTR
                pv.pointer = Marshal.StringToCoTaskMemUni(appId);
                try {
                    PropertyKey key = Key;
                    Marshal.ThrowExceptionForHR(store.SetValue(ref key, ref pv));
                    Marshal.ThrowExceptionForHR(store.Commit());
                } finally { Marshal.FreeCoTaskMem(pv.pointer); }
                Marshal.ThrowExceptionForHR(file.Save(lnkPath, true));
            } finally { Marshal.ReleaseComObject(link); }
        }
    }
}
'@
}

$icon = Join-Path $RepoRoot 'assets\router-auto-restart.ico'
$targets = @()
if ($StartMenu) { $targets += Join-Path ([Environment]::GetFolderPath('Programs')) "$ShortcutName.lnk" }
if ($Desktop)   { $targets += Join-Path ([Environment]::GetFolderPath('Desktop')) "$ShortcutName.lnk" }
if ($Directory) { $targets += Join-Path (Resolve-Path -LiteralPath $Directory) "$ShortcutName.lnk" }

$shell = New-Object -ComObject WScript.Shell
foreach ($path in $targets) {
    if (-not $PSCmdlet.ShouldProcess($path, 'Create shortcut')) { continue }
    $lnk = $shell.CreateShortcut($path)
    $lnk.TargetPath = $VenvPythonW
    $lnk.Arguments = "`"$RouterCtl`" dashboard"
    $lnk.WorkingDirectory = $RepoRoot
    $lnk.Description = 'Router Auto Restart dashboard'
    if (Test-Path -LiteralPath $icon) { $lnk.IconLocation = "$icon,0" }
    $lnk.Save()
    [RouterAutoRestart.ShortcutAppId]::Set($path, $AppUserModelId)
    Write-Ok "created $path"
}
[void][Runtime.InteropServices.Marshal]::ReleaseComObject($shell)

Write-Host @"

To pin it: open Start, search "$ShortcutName", right-click it > Pin to taskbar.
(Windows doesn't let scripts pin items to the taskbar themselves.)
"@
exit 0
