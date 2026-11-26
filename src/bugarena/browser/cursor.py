"""Isolated per-browser cursors ([mcp_<browser>]) and Session Authorization Gate."""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

from bugarena.browser.cdp import CDPClient


def _parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("true", "yes", "y", "1", "on"):
        return True
    if text in ("false", "no", "n", "0", "off", ""):
        return False
    return default


class AuthorizationError(PermissionError):
    """Raised when an action violates session authorization or passive-mode limits."""


class CursorIsolationError(PermissionError):
    """Raised when a cursor attempts unauthorized port or capability access."""


_PASSIVE_ALLOWED_ACTIONS = frozenset({
    "navigate",
    "read_dom",
    "read_console",
    "read_network",
    "read_storage",
    "read_security",
    "screenshot",
    "print_pdf",
    "robots_check",
})

_ACTIVE_ACTIONS = frozenset({
    "form_submit",
    "click_interaction",
    "type_input",
    "fuzz",
    "auth_probe",
})

_CURSOR_COLORS = {
    "chrome": "#1a73e8",
    "brave": "#fb542b",
    "helium": "#10b981",
}


class AccessPolicy(BaseModel):
    """Immutable authorization and safety policy derived from questionnaire answers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    site_url: str
    allowed_origin: str
    authorization: str = "neither"  # own | written_permission | neither
    access_level: str = "passive"  # full_access | passive
    max_rps: float = Field(default=2.0, gt=0.0)
    respect_robots_txt: bool = True
    allow_subdomains: bool = False
    max_pages: int = Field(default=10, ge=1, le=200)

    @classmethod
    def from_answers(cls, answers: dict[str, Any]) -> AccessPolicy:
        site_url = str(answers.get("site_url", "")).strip()
        parsed = urlparse(site_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or not parsed.hostname:
            raise ValueError(f"Valid http/https site_url required, got {site_url!r}")
        auth = str(answers.get("authorization", "neither")).lower().strip()
        if auth not in ("own", "written_permission", "neither"):
            auth = "neither"
        requested_access = str(answers.get("access_level", "passive")).lower().strip()
        # Non-negotiable Section 4 gate: without own/permission, force passive mode
        effective_access = (
            "full_access"
            if (auth in ("own", "written_permission") and requested_access == "full_access")
            else "passive"
        )
        max_rps = float(answers.get("max_rps", 2.0))
        if effective_access == "passive":
            max_rps = min(max_rps, 2.0)
        scope_cfg = answers.get("scope") if isinstance(answers.get("scope"), dict) else {}
        respect_robots = True if effective_access == "passive" else _parse_bool(answers.get("respect_robots_txt"), True)
        allow_subdomains = _parse_bool(scope_cfg.get("allow_subdomains", answers.get("allow_subdomains")), False)
        max_pages = min(max(1, int(scope_cfg.get("max_pages", answers.get("max_pages", 10)))), 200)
        return cls(
            site_url=site_url,
            allowed_origin=f"{parsed.scheme}://{parsed.netloc}",
            authorization=auth,
            access_level=effective_access,
            max_rps=max_rps,
            respect_robots_txt=respect_robots,
            allow_subdomains=allow_subdomains,
            max_pages=max_pages,
        )

    @staticmethod
    def parse_robots_disallow(robots_text: str) -> tuple[str, ...]:
        """Extract Disallow path prefixes under User-agent: * from robots.txt."""
        disallows: list[str] = []
        in_wildcard = False
        for raw_line in (robots_text or "").splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            key, val = (p.strip() for p in line.split(":", 1))
            k_low = key.lower()
            if k_low == "user-agent":
                in_wildcard = val == "*"
            elif k_low == "disallow" and in_wildcard and val:
                disallows.append(val)
        return tuple(disallows)

    @staticmethod
    def is_path_allowed(target_url: str, robots_disallow: Sequence[str] | None = None) -> bool:
        if not robots_disallow:
            return True
        path = urlparse(target_url).path or "/"
        return not any(path.startswith(prefix) for prefix in robots_disallow)

    def assert_action_allowed(
        self,
        action: str,
        target_url: str | None = None,
        *,
        robots_disallow: Sequence[str] | None = None,
    ) -> None:
        if target_url:
            p = urlparse(target_url)
            allowed = urlparse(self.allowed_origin)
            p_host = (p.hostname or "").lower()
            a_host = (allowed.hostname or "").lower()
            scheme_ok = p.scheme in ("http", "https") and p.scheme == allowed.scheme
            cred_ok = not p.username and not p.password
            port_ok = p.port == allowed.port
            exact_host = p_host == a_host
            sub_host = self.allow_subdomains and bool(a_host) and p_host.endswith(f".{a_host}")
            if not (scheme_ok and cred_ok and port_ok and (exact_host or sub_host)):
                raise AuthorizationError(f"Target {target_url!r} outside authorized origin {self.allowed_origin!r}")
            if self.respect_robots_txt and robots_disallow and not self.is_path_allowed(target_url, robots_disallow):
                raise AuthorizationError(f"Target {target_url!r} disallowed by robots.txt policy.")
        if self.access_level == "passive" and action in _ACTIVE_ACTIONS:
            raise AuthorizationError(
                f"Action {action!r} blocked: session is in passive mode (requires own/written_permission)."
            )
        if action not in _PASSIVE_ALLOWED_ACTIONS and action not in _ACTIVE_ACTIONS:
            raise AuthorizationError(f"Unknown browser action {action!r}")


def _spawn_browser_proc(args: list[str], kwargs: dict[str, Any]) -> subprocess.Popen[str]:
    return subprocess.Popen(args, **kwargs)


def _kill_proc_tree(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=5.0,
                check=False,
            )
    else:
        with contextlib.suppress(OSError):
            os.killpg(proc.pid, signal.SIGKILL)
        with contextlib.suppress(OSError):
            proc.kill()
    with contextlib.suppress(OSError, subprocess.TimeoutExpired):
        proc.wait(timeout=3.0)


def _remove_tree(path: Path) -> None:
    if not path.exists():
        return

    def _on_err(func, p, _exc):
        with contextlib.suppress(OSError):
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
            func(p)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_on_err)
    else:
        shutil.rmtree(path, onerror=_on_err)


@dataclass
class BrowserCursor:
    """Isolated worker owning one Chromium instance ([mcp_<browser>]) over loopback CDP."""

    browser_name: str
    port: int
    profile_dir: Path
    capability_token: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    pid: int | None = None
    headless: bool = True
    cdp: CDPClient | None = None
    _proc: subprocess.Popen[str] | None = None
    _cleanup_profile: bool = True
    _last_nav_ts: float = 0.0

    @property
    def cursor_name(self) -> str:
        return f"[mcp_{self.browser_name.lower()}]"

    def verify_target(self, *, port: int, capability_token: str) -> None:
        """Reject any connection or command unless port AND capability_token match this cursor."""
        if port != self.port:
            raise CursorIsolationError(
                f"{self.cursor_name} blocked from accessing foreign port {port} (owns {self.port})."
            )
        if not secrets.compare_digest(capability_token, self.capability_token):
            raise CursorIsolationError(f"{self.cursor_name} capability token mismatch.")

    @staticmethod
    def snapshot_browser_pids() -> set[int]:
        """Return PIDs of running Chrome/Brave/Helium processes for before/after isolation checks."""
        targets = {"chrome.exe", "brave.exe", "helium.exe", "chrome", "brave", "helium"}
        pids: set[int] = set()
        if os.name == "nt":
            res = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5.0,
                check=False,
            )
            if res.returncode != 0:
                raise RuntimeError(f"tasklist failed ({res.returncode}): {res.stderr[:200]}")
            for row in res.stdout.splitlines():
                parts = [c.strip().strip('"') for c in row.split(",")]
                if len(parts) >= 2 and parts[0].lower() in targets and parts[1].isdigit():
                    pids.add(int(parts[1]))
        else:
            res = subprocess.run(["ps", "-eo", "pid,comm"], capture_output=True, text=True, timeout=5.0, check=False)
            if res.returncode != 0:
                raise RuntimeError(f"ps failed ({res.returncode}): {res.stderr[:200]}")
            for row in res.stdout.splitlines()[1:]:
                cols = row.strip().split(None, 1)
                if len(cols) == 2 and cols[0].isdigit() and any(t in cols[1].lower() for t in targets):
                    pids.add(int(cols[0]))
        return pids

    @classmethod
    async def launch(
        cls,
        *,
        browser_name: str,
        executable: str,
        headless: bool = True,
        dedicated_profile: Path | None = None,
        timeout_seconds: float = 12.0,
    ) -> BrowserCursor:
        """Launch Chromium on 127.0.0.1 ephemeral port with isolated temp --user-data-dir."""
        if not Path(executable).is_file():
            raise FileNotFoundError(f"Browser executable not found: {executable}")

        if dedicated_profile is not None:
            profile_dir = Path(dedicated_profile).resolve()
            profile_dir.mkdir(parents=True, exist_ok=True)
            cleanup_profile = False
        else:
            profile_dir = Path(tempfile.mkdtemp(prefix=f"bugarena_{browser_name}_")).resolve()
            cleanup_profile = True

        args = [
            executable,
            f"--user-data-dir={profile_dir}",
            "--remote-debugging-port=0",
            "--remote-debugging-address=127.0.0.1",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-extensions",
            "--disable-sync",
            "--disable-gpu",
        ]
        if headless:
            args.append("--headless=new")
        args.append("about:blank")

        stderr_log = profile_dir / "browser_stderr.log"
        stderr_fh = stderr_log.open("w", encoding="utf-8", errors="replace")
        kwargs: dict[str, Any] = {
            "stdout": subprocess.DEVNULL,
            "stderr": stderr_fh,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "shell": False,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kwargs["start_new_session"] = True

        try:
            proc = await asyncio.to_thread(_spawn_browser_proc, args, kwargs)
        finally:
            stderr_fh.close()
        port: int | None = None
        cdp: CDPClient | None = None
        deadline = time.monotonic() + timeout_seconds

        try:
            active_port_file = profile_dir / "DevToolsActivePort"
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    err = stderr_log.read_text(encoding="utf-8", errors="replace") if stderr_log.is_file() else ""
                    raise RuntimeError(f"{browser_name} exited early ({proc.returncode}): {err[:400]}")
                if active_port_file.is_file():
                    first_line = active_port_file.read_text(encoding="utf-8", errors="ignore").splitlines()
                    if first_line and first_line[0].strip().isdigit():
                        port = int(first_line[0].strip())
                        break
                await asyncio.sleep(0.15)

            if port is None and stderr_log.is_file():
                err_txt = stderr_log.read_text(encoding="utf-8", errors="replace")
                m = re.search(r"ws://127\.0\.0\.1:(\d+)/", err_txt)
                if m:
                    port = int(m.group(1))
            if port is None:
                raise TimeoutError(f"Timed out waiting for DevToolsActivePort from {browser_name}.")

            cdp = await CDPClient.from_port(port, prefer_page_target=True)
            cursor = cls(
                browser_name=browser_name,
                port=port,
                profile_dir=profile_dir,
                pid=proc.pid,
                headless=headless,
                cdp=cdp,
                _proc=proc,
                _cleanup_profile=cleanup_profile,
            )
            await cdp.send("Page.enable")
            await cdp.send("Runtime.enable")
            if not headless:
                await cursor.inject_visual_badge()
            return cursor
        except BaseException:
            if cdp is not None:
                with contextlib.suppress(Exception):
                    await cdp.close()
            _kill_proc_tree(proc)
            if cleanup_profile:
                with contextlib.suppress(OSError):
                    _remove_tree(profile_dir)
            raise

    async def inject_visual_badge(self) -> None:
        """Render non-intrusive [mcp_<browser>] cursor overlay in headed mode only."""
        if self.cdp is None:
            return
        color = _CURSOR_COLORS.get(self.browser_name.lower(), "#7c3aed")
        js = (
            "(() => { let el = document.getElementById('__bugarena_cursor_badge');"
            "if (!el) { el = document.createElement('div'); el.id = '__bugarena_cursor_badge';"
            "el.style.cssText = 'position:fixed;bottom:10px;right:10px;z-index:2147483647;"
            f"padding:4px 8px;border-radius:6px;background:{color};color:#fff;font:12px monospace;"
            "pointer-events:none;box-shadow:0 2px 6px rgba(0,0,0,0.3)';"
            f"el.textContent = {self.cursor_name!r}; document.documentElement.appendChild(el); }} }})();"
        )
        with contextlib.suppress(Exception):
            await self.cdp.send("Runtime.evaluate", {"expression": js})

    async def remove_visual_badge(self) -> None:
        if self.cdp is None:
            return
        with contextlib.suppress(Exception):
            await self.cdp.send(
                "Runtime.evaluate",
                {"expression": "document.getElementById('__bugarena_cursor_badge')?.remove();"},
            )

    async def navigate(
        self,
        url: str,
        *,
        policy: AccessPolicy,
        robots_disallow: Sequence[str] | None = None,
        readiness_timeout: float = 8.0,
    ) -> dict[str, Any]:
        policy.assert_action_allowed("navigate", target_url=url, robots_disallow=robots_disallow)
        min_gap = 1.0 / max(policy.max_rps, 0.1)
        elapsed = time.monotonic() - self._last_nav_ts
        if elapsed < min_gap:
            await asyncio.sleep(min_gap - elapsed)
        self._last_nav_ts = time.monotonic()
        assert self.cdp is not None
        load_before = len(self.cdp.events.get("Page.loadEventFired", []))
        res: dict[str, Any] = {}
        for attempt in range(2):
            res = await self.cdp.send("Page.navigate", {"url": url})
            err_txt = res.get("errorText") if isinstance(res, dict) else None
            if not err_txt:
                break
            if err_txt == "net::ERR_ABORTED" and attempt == 0:
                # Fresh Chromium renderer can abort an immediate first navigation while initializing
                await asyncio.sleep(0.25)
                continue
            raise RuntimeError(f"Page.navigate failed for {url}: {err_txt}")
        loaded = False
        deadline = time.monotonic() + readiness_timeout
        while time.monotonic() < deadline:
            if len(self.cdp.events.get("Page.loadEventFired", [])) > load_before:
                loaded = True
                break
            with contextlib.suppress(Exception):
                st = await self.cdp.send(
                    "Runtime.evaluate",
                    {
                        "expression": "({state: document.readyState, href: window.location.href})",
                        "returnByValue": True,
                    },
                )
                val = st.get("result", {}).get("value") or {}
                if (
                    isinstance(val, dict)
                    and val.get("state") == "complete"
                    and str(val.get("href", "")).startswith(("http://", "https://"))
                ):
                    loaded = True
                    break
            await asyncio.sleep(0.1)
        if not loaded:
            raise TimeoutError(f"Timed out waiting for page load readiness on {url}")
        await asyncio.sleep(0.15)
        if not self.headless:
            await self.inject_visual_badge()
        return res

    async def close(self) -> None:
        try:
            if not self.headless:
                await self.remove_visual_badge()
        finally:
            try:
                if self.cdp is not None:
                    with contextlib.suppress(Exception):
                        await self.cdp.close()
                    self.cdp = None
            finally:
                if self._proc is not None:
                    _kill_proc_tree(self._proc)
                    self._proc = None
                if self._cleanup_profile:
                    with contextlib.suppress(OSError):
                        _remove_tree(self.profile_dir)
