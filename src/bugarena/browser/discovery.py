"""Cross-platform discovery for Chrome, Brave, and Helium browsers."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class BrowserInstall(BaseModel):
    """Detected browser installation metadata."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    executable: str = ""
    version: str = ""
    found: bool = False
    notes: str = ""


def _windows_registry_path(exe_name: str) -> str | None:
    if os.name != "nt":
        return None
    try:
        import winreg
    except ImportError:
        return None
    subkey = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe_name}"
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, subkey) as key:
                val, _ = winreg.QueryValueEx(key, "")
                if val and Path(val).is_file():
                    return str(Path(val))
        except OSError:
            continue
    return None


def _probe_version(exe: str) -> str:
    try:
        res = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=4.0,
            check=False,
        )
        if res.returncode != 0:
            return "unknown"
        out = (res.stdout or "").strip()
        return out.splitlines()[0] if out else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _candidate_paths(browser_name: str) -> list[str]:
    local = os.environ.get("LOCALAPPDATA", "")
    pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    pf86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")

    if browser_name == "chrome":
        return [
            str(Path(pf) / "Google" / "Chrome" / "Application" / "chrome.exe"),
            str(Path(pf86) / "Google" / "Chrome" / "Application" / "chrome.exe"),
            str(Path(local) / "Google" / "Chrome" / "Application" / "chrome.exe"),
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/usr/bin/google-chrome",
            "/usr/bin/chromium",
        ]
    if browser_name == "brave":
        return [
            str(Path(pf) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe"),
            str(Path(pf86) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe"),
            str(Path(local) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe"),
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/usr/bin/brave-browser",
        ]
    if browser_name == "helium":
        return [
            str(Path(local) / "imput" / "Helium" / "Application" / "helium.exe"),
            str(Path(local) / "Helium" / "Application" / "helium.exe"),
            str(Path(pf) / "Helium" / "Application" / "helium.exe"),
            "/Applications/Helium.app/Contents/MacOS/Helium",
            "/usr/bin/helium",
        ]
    return []


def discover_browsers(
    overrides: dict[str, str] | None = None,
    *,
    probe_versions: bool = False,
) -> list[BrowserInstall]:
    """Detect Chrome, Brave, and Helium installations on the host machine."""
    custom = {k.lower(): v for k, v in (overrides or {}).items() if v}
    exe_names = {"chrome": "chrome.exe", "brave": "brave.exe", "helium": "helium.exe"}
    results: list[BrowserInstall] = []

    ordered_names = ["chrome", "brave", "helium", *(k for k in custom if k not in ("chrome", "brave", "helium"))]
    for name in ordered_names:
        resolved: str | None = None
        note = ""
        if name in custom and Path(custom[name]).is_file():
            resolved = str(Path(custom[name]).resolve())
            note = "User-supplied executable path."
        exe_name = exe_names.get(name, f"{name}.exe")
        if not resolved:
            which_hit = shutil.which(name) or shutil.which(exe_name)
            if which_hit and Path(which_hit).is_file():
                resolved = str(Path(which_hit).resolve())
        if not resolved and name in exe_names:
            resolved = _windows_registry_path(exe_names[name])
        if not resolved:
            for cand in _candidate_paths(name):
                if cand and Path(cand).is_file():
                    resolved = str(Path(cand).resolve())
                    break

        if resolved:
            version = _probe_version(resolved) if probe_versions else "chromium-compatible"
            results.append(
                BrowserInstall(name=name, executable=resolved, version=version, found=True, notes=note)
            )
        else:
            results.append(
                BrowserInstall(
                    name=name,
                    found=False,
                    notes=f"{name} not auto-detected; provide {name}_path if installed.",
                )
            )
    return results
