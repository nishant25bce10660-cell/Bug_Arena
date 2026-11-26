"""Pre-start questionnaire, authorization confirmation, and live cursor tracking."""

from __future__ import annotations

import os
import re
import secrets
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bugarena.browser.cursor import AccessPolicy, BrowserCursor
from bugarena.browser.discovery import discover_browsers
from bugarena.sandbox.security import validate_safe_path

_VALID_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

QUESTIONNAIRE_ITEMS: tuple[dict[str, Any], ...] = (
    {"id": "site_url", "question": "Target site URL to audit (type or paste URL now)", "required": True},
    {"id": "authorization", "question": "Authorization level: own / written_permission / neither (neither forces passive mode)", "required": True},
    {
        "id": "browsers",
        "question": "Select which browser(s) to permit via IDE permission prompt or explicit list (none granted by default; supply <name>_path for custom installs)",
        "required": True,
        "default": [],
    },
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
        installed_names = [b["name"] for b in browsers if b["found"]]
        questions: list[dict[str, Any]] = []
        for item in QUESTIONNAIRE_ITEMS:
            q = dict(item)
            if q["id"] == "browsers":
                q["options"] = installed_names
            questions.append(q)
        return {
            "status": "AWAITING_CONFIRMATION",
            "user_hint": user_hint or "",
            "detected_browsers": browsers,
            "api_keys_present": keys_present,
            "questions": questions,
            "note": "No browser or network probe starts until IDE browser permission / session_confirm(answers) grants explicit access.",
        }

    def session_confirm(
        self,
        answers: dict[str, Any],
        *,
        all_tool_names: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """Validate answers, enforce passive mode on 'neither', write scope_and_authorization.md, issue token."""
        policy = AccessPolicy.from_answers(answers)
        raw_run_id = answers.get("run_id")
        if raw_run_id is not None and str(raw_run_id).strip():
            run_id = str(raw_run_id).strip()
            if not _VALID_RUN_ID_RE.match(run_id):
                raise ValueError(f"Invalid run_id {run_id!r}: must match ^[A-Za-z0-9][A-Za-z0-9_-]{{0,63}}$")
        else:
            run_id = f"run_{uuid.uuid4().hex[:8]}"
        if run_id in self._sessions:
            raise ValueError(f"Session run_id '{run_id}' already exists.")

        out_cfg = answers.get("output_config") if isinstance(answers.get("output_config"), dict) else {}
        out_root = Path(answers.get("output_dir") or out_cfg.get("output_dir") or self.default_output_root).resolve()
        out_root.mkdir(parents=True, exist_ok=True)
        run_dir = validate_safe_path(out_root, run_id)
        run_dir.mkdir(parents=True, exist_ok=True)

        profile_mode = str(answers.get("profile_mode", "fresh_isolated"))
        profile_warning = ""
        if profile_mode != "fresh_isolated":
            profile_warning = (
                "WARNING: dedicated_existing profile mode selected. Never point BugArena at a daily user profile; "
                "default fresh_isolated temporary profiles remain safer."
            )

        tool_filters = answers.get("tool_filters") if isinstance(answers.get("tool_filters"), dict) else {}
        tools_allowed = answers.get("tools_allowed", tool_filters.get("tools_allowed", "all"))
        raw_denied = answers.get("tools_denied", tool_filters.get("tools_denied", []))
        tools_denied = {raw_denied} if isinstance(raw_denied, str) else set(raw_denied or [])
        enforce_acl = bool(all_tool_names) or tools_allowed != "all" or bool(tools_denied)
        if tools_allowed == "all" or tools_allowed is None:
            active_tools = [t for t in all_tool_names if t not in tools_denied]
        elif isinstance(tools_allowed, str):
            active_tools = [tools_allowed] if (tools_allowed and tools_allowed not in tools_denied) else []
        else:
            active_tools = [t for t in tools_allowed if t not in tools_denied]

        token = secrets.token_urlsafe(24)
        raw_browsers = answers.get("browsers")
        if raw_browsers is None:
            requested_browsers: list[str] = []
        elif isinstance(raw_browsers, str):
            b_clean = raw_browsers.strip().lower()
            requested_browsers = [b_clean] if b_clean else []
        else:
            requested_browsers = [str(b).strip().lower() for b in raw_browsers if str(b).strip()]
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
            f"- **Requested Browsers:** `{', '.join(requested_browsers) if requested_browsers else 'None granted'}`",
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
            "enforce_tool_acl": enforce_acl,
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
            "browsers": requested_browsers,
            "browser_permission_granted": bool(requested_browsers),
            "max_rps": policy.max_rps,
            "scope_file": str(scope_file),
            "active_tools": active_tools,
            "profile_warning": profile_warning,
            "detected_browsers": session_rec["detected_browsers"],
        }

    def grant_browsers(
        self,
        run_id: str,
        browsers: list[str],
        *,
        overrides: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Update permitted browsers for an active session (e.g., via IDE elicitation)."""
        sess = self.get_session(run_id)
        cleaned = [str(b).strip().lower() for b in browsers if str(b).strip()]
        existing_overrides = {
            k.removesuffix("_path").lower(): str(v)
            for k, v in sess.get("answers", {}).items()
            if k.endswith("_path") and v and k != "project_path"
        }
        if overrides:
            existing_overrides.update({k.lower(): str(v) for k, v in overrides.items() if v})
            for k, v in overrides.items():
                if v:
                    sess["answers"][f"{k.lower()}_path"] = str(v)
        detected = {b.name: b for b in discover_browsers(overrides=existing_overrides)}
        sess["browsers"] = list(dict.fromkeys([*sess["browsers"], *cleaned]))
        sess["answers"]["browsers"] = list(sess["browsers"])
        sess["detected_browsers"] = {k: v.model_dump() for k, v in detected.items()}
        scope_file = Path(sess["scope_file"])
        if scope_file.is_file():
            txt = scope_file.read_text(encoding="utf-8")
            updated_line = f"- **Requested Browsers:** `{', '.join(sess['browsers']) if sess['browsers'] else 'None granted'}`"
            txt = re.sub(r"^- \*\*Requested Browsers:\*\* .*$", updated_line, txt, flags=re.MULTILINE)
            scope_file.write_text(txt, encoding="utf-8")
        return sess

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
