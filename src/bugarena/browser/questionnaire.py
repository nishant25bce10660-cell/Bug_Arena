"""Pre-start questionnaire, authorization confirmation, and live cursor tracking."""

from __future__ import annotations

import os
import secrets
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bugarena.browser.cursor import AccessPolicy, BrowserCursor
from bugarena.browser.discovery import discover_browsers

QUESTIONNAIRE_ITEMS: tuple[dict[str, Any], ...] = (
    {"id": "site_url", "question": "Target site URL to audit (type or paste URL now)", "required": True},
    {"id": "authorization", "question": "Authorization level: own / written_permission / neither (neither forces passive mode)", "required": True},
    {"id": "browsers", "question": "Browsers to grant (chrome, brave, helium — supply helium_path if not auto-detected)", "required": False, "default": ["chrome"]},
    {"id": "access_level", "question": "Access level: full_access (requires own/written_permission) or passive", "required": False, "default": "full_access"},
    {"id": "profile_mode", "question": "Profile mode: fresh_isolated (default) or dedicated_existing (warning: never daily profile)", "required": False, "default": "fresh_isolated"},
    {"id": "authenticated_areas", "question": "Does the site have authenticated areas you will log into manually in a headed window? (yes/no)", "required": False, "default": False},
    {"id": "scope", "question": "Scope: single_page / crawl / url_list, max_pages, allow_subdomains (yes/no)", "required": False, "default": {"mode": "single_page", "max_pages": 10, "allow_subdomains": False}},
    {"id": "inspect_panels", "question": "DevTools panels to inspect: all (default) or subset list", "required": False, "default": "all"},
    {"id": "project_path", "question": "Optional local project path to audit and source-map link to site findings", "required": False, "default": ""},
    {"id": "analysis_models", "question": "Analysis models: gemini, grok, or both (default)", "required": False, "default": ["gemini", "grok"]},
    {"id": "output_config", "question": "Output folder (default bugarena_reports/) and formats (md, pdf)", "required": False, "default": {"output_dir": "bugarena_reports", "formats": ["md", "pdf"]}},
    {"id": "merge_skill", "question": "Optional third-party skill source to inspect with merge_both_skills", "required": False, "default": ""},
    {"id": "tool_filters", "question": "Focus areas, exclusions, tools_allowed / tools_denied (default: all tools enabled)", "required": False, "default": {"tools_allowed": "all", "tools_denied": []}},
)


class SessionManager:
    """Manages session_prepare -> questionnaire -> session_confirm -> active browser cursors."""

    def __init__(self, default_output_root: Path | str = "bugarena_reports"):
        self.default_output_root = Path(default_output_root)
        self._sessions: dict[str, dict[str, Any]] = {}

    def session_prepare(
        self,
        user_hint: str | None = None,
        *,
        browser_overrides: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Detect installed browsers and API keys, and return the 13-question batch. Launches nothing."""
        browsers = [b.model_dump() for b in discover_browsers(overrides=browser_overrides)]
        keys_present = {
            "GEMINI_API_KEY": bool(os.environ.get("GEMINI_API_KEY")),
            "XAI_API_KEY": bool(os.environ.get("XAI_API_KEY")),
            "GROQ_API_KEY": bool(os.environ.get("GROQ_API_KEY")),
            "OPENAI_API_KEY": bool(os.environ.get("OPENAI_API_KEY")),
            "DEEPSEEK_API_KEY": bool(os.environ.get("DEEPSEEK_API_KEY")),
        }
        return {
            "status": "AWAITING_CONFIRMATION",
            "user_hint": user_hint or "",
            "detected_browsers": browsers,
            "api_keys_present": keys_present,
            "questions": list(QUESTIONNAIRE_ITEMS),
            "note": "No browser or network probe starts until session_confirm(answers) is called.",
        }

    def session_confirm(
        self,
        answers: dict[str, Any],
        *,
        all_tool_names: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """Validate answers, enforce passive mode on 'neither', write scope_and_authorization.md, issue token."""
        policy = AccessPolicy.from_answers(answers)
        run_id = str(answers.get("run_id") or f"run_{uuid.uuid4().hex[:8]}")
        out_root = Path(answers.get("output_dir") or self.default_output_root)
        run_dir = (out_root / run_id).resolve()
        run_dir.mkdir(parents=True, exist_ok=True)

        profile_mode = str(answers.get("profile_mode", "fresh_isolated"))
        profile_warning = ""
        if profile_mode != "fresh_isolated":
            profile_warning = (
                "WARNING: dedicated_existing profile mode selected. Never point BugArena at a daily user profile; "
                "default fresh_isolated temporary profiles remain safer."
            )

        tools_allowed = answers.get("tools_allowed", "all")
        tools_denied = set(answers.get("tools_denied") or [])
        if tools_allowed == "all" or not tools_allowed:
            active_tools = [t for t in all_tool_names if t not in tools_denied]
        else:
            active_tools = [t for t in tools_allowed if t not in tools_denied]

        token = secrets.token_urlsafe(24)
        requested_browsers = [str(b).lower() for b in (answers.get("browsers") or ["chrome"])]
        overrides = {
            k.removesuffix("_path").lower(): str(v)
            for k, v in answers.items()
            if k.endswith("_path") and v and k != "project_path"
        }
        detected = {b.name: b for b in discover_browsers(overrides=overrides)}

        scope_lines = [
            "# Scope & Authorization",
            "",
            f"- **Run ID:** `{run_id}`",
            f"- **Timestamp (UTC):** `{datetime.now(UTC).isoformat(timespec='seconds')}`",
            f"- **Target URL:** `{policy.site_url}`",
            f"- **Authorized Origin:** `{policy.allowed_origin}`",
            f"- **Authorization:** `{policy.authorization}`",
            f"- **Effective Access Level:** `{policy.access_level}`",
            f"- **Rate Limit:** `<= {policy.max_rps} req/s` | **robots.txt honored:** `{policy.respect_robots_txt}`",
            f"- **Requested Browsers:** `{', '.join(requested_browsers)}`",
            f"- **Profile Mode:** `{profile_mode}`",
        ]
        if profile_warning:
            scope_lines.append(f"- **Profile Warning:** {profile_warning}")
        scope_file = run_dir / "scope_and_authorization.md"
        scope_file.write_text("\n".join(scope_lines) + "\n", encoding="utf-8")

        session_rec = {
            "run_id": run_id,
            "run_dir": str(run_dir),
            "session_token": token,
            "policy": policy,
            "browsers": requested_browsers,
            "detected_browsers": {k: v.model_dump() for k, v in detected.items()},
            "answers": dict(answers),
            "active_tools": active_tools,
            "cursors": {},
            "scope_file": str(scope_file),
            "profile_warning": profile_warning,
        }
        self._sessions[run_id] = session_rec
        return {
            "status": "CONFIRMED",
            "run_id": run_id,
            "run_dir": str(run_dir),
            "session_token": token,
            "access_level": policy.access_level,
            "authorization": policy.authorization,
            "max_rps": policy.max_rps,
            "scope_file": str(scope_file),
            "active_tools": active_tools,
            "profile_warning": profile_warning,
            "detected_browsers": session_rec["detected_browsers"],
        }

    def get_session(self, run_id: str) -> dict[str, Any]:
        if run_id not in self._sessions:
            raise KeyError(f"Unknown session run_id '{run_id}'; run session_confirm first.")
        return self._sessions[run_id]

    def register_cursor(self, run_id: str, cursor: BrowserCursor) -> None:
        sess = self.get_session(run_id)
        sess["cursors"][cursor.cursor_name] = cursor

    def browser_cursor_list(self, run_id: str) -> dict[str, Any]:
        sess = self.get_session(run_id)
        items = []
        for cname, c in sess["cursors"].items():
            items.append({
                "cursor": cname,
                "browser": c.browser_name,
                "pid": c.pid,
                "port": c.port,
                "headless": c.headless,
                "state": "connected" if c.cdp is not None else "closed",
            })
        return {"run_id": run_id, "cursors": items}
