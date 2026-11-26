"""TDD tests for IDE-gated per-browser permission (no predefined default browser)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from bugarena.browser import AuthorizationError, SessionManager
from bugarena.inspect.site_audit import SiteAuditCoordinator
from bugarena.server import inspect_panel, session_confirm, site_audit_round, site_audit_start


def test_questionnaire_has_no_predefined_default_browser(tmp_path: Path):
    mgr = SessionManager(default_output_root=tmp_path)
    prep = mgr.session_prepare(user_hint="check site")
    browsers_q = next(q for q in prep["questions"] if q["id"] == "browsers")
    assert browsers_q["required"] is True
    assert browsers_q["default"] == []
    assert "options" in browsers_q

    # Omitting 'browsers' grants ZERO browsers (no silent Chrome default)
    conf = mgr.session_confirm({"site_url": "https://example.com", "authorization": "own"})
    assert conf["browsers"] == []
    assert conf["browser_permission_granted"] is False
    scope_txt = Path(conf["scope_file"]).read_text(encoding="utf-8")
    assert "None granted" in scope_txt


@pytest.mark.asyncio
async def test_site_audit_and_inspect_panel_reject_ungranted_or_empty_browsers(tmp_path: Path):
    conf_empty = await session_confirm({
        "site_url": "http://127.0.0.1:8000",
        "authorization": "own",
        "output_dir": str(tmp_path / "r1"),
    })
    assert conf_empty["browsers"] == []
    with pytest.raises(AuthorizationError, match="No browser access granted"):
        await site_audit_start("http://127.0.0.1:8000", conf_empty["run_id"], conf_empty["session_token"])
    with pytest.raises(AuthorizationError, match="No browser access granted"):
        await site_audit_round(conf_empty["run_id"], session_token=conf_empty["session_token"])

    # Granting only brave must reject inspect_panel(browser="chrome")
    conf_brave = await session_confirm({
        "site_url": "http://127.0.0.1:8000",
        "authorization": "own",
        "browsers": ["brave"],
        "output_dir": str(tmp_path / "r2"),
    })
    with pytest.raises(AuthorizationError, match="not permitted"):
        await inspect_panel(
            conf_brave["run_id"],
            "chrome",
            "Elements",
            session_token=conf_brave["session_token"],
        )

    coord = SiteAuditCoordinator(output_root=tmp_path / "c")
    c_empty = coord.sessions.session_confirm({"site_url": "http://127.0.0.1:8000", "authorization": "own"})
    with pytest.raises(AuthorizationError):
        await coord.start_and_run_round(c_empty["run_id"])


@pytest.mark.asyncio
async def test_ide_elicit_prompt_starts_unchecked_and_grants_only_user_selection(tmp_path: Path):
    captured: dict = {}

    class _FakeCtx:
        request_context = object()

        async def elicit(self, message: str, schema):
            captured["message"] = message
            captured["schema"] = schema
            # Every discovered browser boolean field MUST start False (nothing predefined)
            defaults = schema()
            for fname, finfo in schema.model_fields.items():
                if finfo.annotation is bool:
                    assert getattr(defaults, fname) is False, f"{fname} must default to False"
            # Simulate user choosing only brave (or first available boolean) in IDE popup
            kwargs = {}
            if "allow_brave" in schema.model_fields:
                kwargs["allow_brave"] = True
            elif any(f.annotation is bool for f in schema.model_fields.values()):
                first_bool = next(n for n, f in schema.model_fields.items() if f.annotation is bool)
                kwargs[first_bool] = True
            return SimpleNamespace(action="accept", data=schema(**kwargs))

    conf = await session_confirm(
        {
            "site_url": "https://example.com",
            "authorization": "own",
            "output_dir": str(tmp_path / "ide_r1"),
        },
        ctx=_FakeCtx(),  # type: ignore[arg-type]
    )
    assert "allow_" in "".join(captured["schema"].model_fields)
    if "allow_brave" in captured["schema"].model_fields:
        assert conf["browsers"] == ["brave"]
        assert "chrome" not in conf["browsers"]
    assert conf["browser_permission_granted"] is True

    class _DeclineCtx:
        request_context = object()

        async def elicit(self, message: str, schema):
            return SimpleNamespace(action="decline", data=None)

    conf_declined = await session_confirm(
        {
            "site_url": "https://example.com",
            "authorization": "own",
            "output_dir": str(tmp_path / "ide_r2"),
        },
        ctx=_DeclineCtx(),  # type: ignore[arg-type]
    )
    assert conf_declined["browsers"] == []
    assert conf_declined["browser_permission_granted"] is False
