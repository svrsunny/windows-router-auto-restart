"""Router password storage.

Lookup order:
  1. ROUTER_PASS in this process's environment (for one-off testing only)
  2. Windows Credential Manager, generic credential "RouterAutoRestart:router-admin"
     (written by scripts/Configure.ps1; encrypted with DPAPI for the current Windows user)
  3. Legacy: ROUTER_PASS saved with `setx` (HKCU\\Environment). This is plain text in the
     registry and is supported only for older setups; Configure.ps1 never uses it.

The password is never written to config files, logs, task arguments or command lines.
Credential Manager entries belong to one Windows account: a scheduled task must run as the
same user that stored the password.
"""
from __future__ import annotations

import ctypes
import os
import sys

TARGET = "RouterAutoRestart:router-admin"
_ERROR_NOT_FOUND = 1168

if sys.platform == "win32":
    from ctypes import wintypes

    class _CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    _PCRED = ctypes.POINTER(_CREDENTIAL)
    _adv = ctypes.WinDLL("advapi32", use_last_error=True)
    _adv.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_PCRED)]
    _adv.CredReadW.restype = wintypes.BOOL
    _adv.CredWriteW.argtypes = [_PCRED, wintypes.DWORD]
    _adv.CredWriteW.restype = wintypes.BOOL
    _adv.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    _adv.CredDeleteW.restype = wintypes.BOOL
    _adv.CredFree.argtypes = [ctypes.c_void_p]
    _adv.CredFree.restype = None
    _CRED_TYPE_GENERIC = 1
    _CRED_PERSIST_LOCAL_MACHINE = 2


def vault_read(target: str = TARGET) -> str | None:
    if sys.platform != "win32":
        return None
    p = _PCRED()
    if not _adv.CredReadW(target, _CRED_TYPE_GENERIC, 0, ctypes.byref(p)):
        err = ctypes.get_last_error()
        if err == _ERROR_NOT_FOUND:
            return None
        raise ctypes.WinError(err)
    try:
        c = p.contents
        return ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize).decode("utf-16-le")
    finally:
        _adv.CredFree(p)


def vault_write(password: str, username: str = "admin", target: str = TARGET) -> None:
    if sys.platform != "win32":
        raise OSError("Credential Manager is only available on Windows")
    if not password:
        raise ValueError("password is empty")
    blob = password.encode("utf-16-le")
    buf = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    cred = _CREDENTIAL()
    cred.Type = _CRED_TYPE_GENERIC
    cred.TargetName = target
    cred.CredentialBlobSize = len(blob)
    cred.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))
    cred.Persist = _CRED_PERSIST_LOCAL_MACHINE
    cred.UserName = username
    if not _adv.CredWriteW(ctypes.byref(cred), 0):
        raise ctypes.WinError(ctypes.get_last_error())


def vault_delete(target: str = TARGET) -> bool:
    """Remove the stored credential; returns False if there was none."""
    if sys.platform != "win32":
        return False
    if not _adv.CredDeleteW(target, _CRED_TYPE_GENERIC, 0):
        err = ctypes.get_last_error()
        if err == _ERROR_NOT_FOUND:
            return False
        raise ctypes.WinError(err)
    return True


def _setx_password() -> str | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            value = winreg.QueryValueEx(k, "ROUTER_PASS")[0]
            return value if isinstance(value, str) and value else None
    except OSError:
        return None


def get_password() -> tuple[str | None, str]:
    """Return (password or None, where it came from)."""
    if os.environ.get("ROUTER_PASS"):
        return os.environ["ROUTER_PASS"], "environment"
    try:
        pw = vault_read()
    except OSError:
        pw = None
    if pw:
        return pw, "Credential Manager"
    pw = _setx_password()
    if pw:
        return pw, "setx (registry)"
    return None, "not set"
