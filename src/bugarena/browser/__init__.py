"""Isolated browser discovery, RFC 6455 CDP client, [mcp_<browser>] cursors, and access gate."""

from bugarena.browser.cdp import CDPClient, CDPError
from bugarena.browser.cursor import (
    AccessPolicy,
    AuthorizationError,
    BrowserCursor,
    CursorIsolationError,
)
from bugarena.browser.discovery import BrowserInstall, discover_browsers
from bugarena.browser.questionnaire import QUESTIONNAIRE_ITEMS, SessionManager

__all__ = [
    "QUESTIONNAIRE_ITEMS",
    "AccessPolicy",
    "AuthorizationError",
    "BrowserCursor",
    "BrowserInstall",
    "CDPClient",
    "CDPError",
    "CursorIsolationError",
    "SessionManager",
    "discover_browsers",
]
