"""SHA-256 hash-chained EvidenceVault with automatic PII, cookie, and secret redaction."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from bugarena.sandbox.security import (
    SecurityViolationError,
    scrub_sensitive_data,
    validate_safe_path,
)

_COOKIE_HEADER_RE = re.compile(
    r'("(?:cookie|set-cookie)"\s*:\s*")([^"\r\n]+)'
    r'|(^(?:cookie|set-cookie)\s*:\s*)([^\r\n]+)',
    re.IGNORECASE | re.MULTILINE,
)
_COOKIE_KV_RE = re.compile(
    r"(?i)\b(cookie|set-cookie|sessionid|phpsessid|asp\.net_sessionid|csrftoken|jsessionid|connect\.sid|sid|jwt|auth_token|id_token|access_token)\s*[:=]\s*([^\r\n\"',;}]+)"
)
_AUTH_HEADER_RE = re.compile(
    r'(?:^|(?<=[\s{,`]))("?(?:authorization|proxy-authorization|x-api-key|x-goog-api-key|x-auth-token)"?\s*:\s*"?)(?!\*\*|\s*\[REDACTED)([^\r\n",}]+)',
    re.IGNORECASE | re.MULTILINE,
)
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d{1,3}[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]\d{3}[-.\s]\d{4}(?!\w)")


def _canonical_entry_hash(payload_without_hash: dict[str, Any]) -> str:
    encoded = json.dumps(payload_without_hash, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def scrub_evidence_text(text: str, *, base_dir: Path | str | None = None) -> tuple[str, list[dict[str, str]]]:
    """Scrub secrets, cookies, authorization headers, emails, and phones, returning redaction records."""
    redactions: list[dict[str, str]] = []
    scrubbed = scrub_sensitive_data(text, base_dir=base_dir)
    if scrubbed != text:
        redactions.append({"kind": "token_or_path", "count": "1+"})

    rules: tuple[tuple[str, re.Pattern[str], Any], ...] = (
        ("auth_header", _AUTH_HEADER_RE, r"\1[REDACTED_AUTH]"),
        (
            "cookie_header",
            _COOKIE_HEADER_RE,
            lambda m: f"{m.group(1) or m.group(3)}[REDACTED_COOKIE]",
        ),
        ("cookie_or_session", _COOKIE_KV_RE, r"\1=[REDACTED_COOKIE]"),
        ("email", _EMAIL_RE, "[REDACTED_EMAIL]"),
        ("phone", _PHONE_RE, "[REDACTED_PHONE]"),
    )
    for kind, pattern, repl in rules:
        new_text, n = pattern.subn(repl, scrubbed)
        if n:
            redactions.append({"kind": kind, "count": str(n)})
            scrubbed = new_text

    return scrubbed, redactions


class EvidenceEntry(BaseModel):
    """Immutable hash-chained entry stored in evidence/manifest.jsonl."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: str
    sha256: str
    tool_name: str
    args_summary: str
    timestamp: str
    prev_hash: str
    entry_hash: str
    rel_path: str
    byte_size: int
    mime_type: str = "text/plain"


class EvidenceVault:
    """Append-only artifact vault enforcing SHA-256 hash chaining and evidence scrubbing."""

    def __init__(self, run_dir: Path | str):
        self.run_dir = Path(run_dir).resolve()
        self.evidence_dir = self.run_dir / "evidence"
        self.raw_dir = self.evidence_dir / "raw"
        self.manifest_path = self.evidence_dir / "manifest.jsonl"
        self.redactions_path = self.evidence_dir / "redactions.json"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        if not self.redactions_path.exists():
            self.redactions_path.write_text("[]", encoding="utf-8")

    def entries(self) -> list[EvidenceEntry]:
        """Load all recorded manifest entries in chronological order."""
        if not self.manifest_path.is_file():
            return []
        lines = [ln for ln in self.manifest_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        return [EvidenceEntry.model_validate_json(ln) for ln in lines]

    def get(self, evidence_id: str) -> EvidenceEntry | None:
        """Lookup one evidence entry by ID."""
        for entry in self.entries():
            if entry.evidence_id == evidence_id:
                return entry
        return None

    def record_artifact(
        self,
        data: bytes | str,
        *,
        ext: str = ".txt",
        tool_name: str,
        args_summary: str = "",
        mime_type: str = "text/plain",
        is_binary: bool = False,
        base_dir: Path | str | None = None,
    ) -> EvidenceEntry:
        """Scrub text artifacts if non-binary, write under evidence/raw/, and append manifest entry."""
        existing = self.entries()
        next_num = len(existing) + 1
        ev_id = f"EV-{next_num:04d}"
        safe_ext = ext if ext.startswith(".") else f".{ext}"
        rel_path = f"evidence/raw/{ev_id}{safe_ext}"
        target = validate_safe_path(self.run_dir, rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        if is_binary or safe_ext.lower() in (".png", ".jpg", ".jpeg", ".webp", ".pdf"):
            raw_bytes = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        else:
            raw_text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
            scrubbed_text, redactions = scrub_evidence_text(raw_text, base_dir=base_dir)
            if redactions:
                self._append_redactions(ev_id, redactions)
            raw_bytes = scrubbed_text.encode("utf-8")

        target.write_bytes(raw_bytes)
        file_sha = hashlib.sha256(raw_bytes).hexdigest()
        prev_hash = existing[-1].entry_hash if existing else "GENESIS"
        ts = datetime.now(UTC).isoformat(timespec="seconds")

        body: dict[str, Any] = {
            "evidence_id": ev_id,
            "sha256": file_sha,
            "tool_name": tool_name,
            "args_summary": scrub_evidence_text(args_summary, base_dir=base_dir)[0][:240],
            "timestamp": ts,
            "prev_hash": prev_hash,
            "rel_path": rel_path,
            "byte_size": len(raw_bytes),
            "mime_type": mime_type,
        }
        entry_hash = _canonical_entry_hash(body)
        entry = EvidenceEntry(**body, entry_hash=entry_hash)

        with self.manifest_path.open("a", encoding="utf-8") as fh:
            fh.write(entry.model_dump_json() + "\n")
        return entry

    def _append_redactions(self, evidence_id: str, redactions: list[dict[str, str]]) -> None:
        current = json.loads(self.redactions_path.read_text(encoding="utf-8"))
        ts = datetime.now(UTC).isoformat(timespec="seconds")
        for r in redactions:
            current.append({"evidence_id": evidence_id, "timestamp": ts, **r})
        self.redactions_path.write_text(json.dumps(current, indent=2), encoding="utf-8")

    def read_artifact_text(self, evidence_id: str) -> str | None:
        """Read UTF-8 text of a non-binary artifact stored in the vault."""
        entry = self.get(evidence_id)
        if entry is None:
            return None
        path = validate_safe_path(self.run_dir, entry.rel_path)
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8", errors="replace")

    def verify_chain(self) -> dict[str, Any]:
        """Verify prev_hash linkage, entry_hash integrity, and on-disk SHA-256 of every artifact."""
        errors: list[str] = []
        if not self.manifest_path.is_file():
            return {"valid": True, "entries_checked": 0, "errors": []}

        raw_lines = self.manifest_path.read_text(encoding="utf-8").splitlines()
        expected_prev = "GENESIS"
        checked = 0
        for idx, line in enumerate(raw_lines, 1):
            if not line.strip():
                continue
            try:
                entry = EvidenceEntry.model_validate_json(line)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"Line {idx}: invalid manifest JSON ({exc})")
                continue
            checked += 1
            if entry.prev_hash != expected_prev:
                errors.append(
                    f"{entry.evidence_id}: prev_hash mismatch (expected {expected_prev}, got {entry.prev_hash})"
                )
            body = entry.model_dump()
            recorded_entry_hash = body.pop("entry_hash")
            if _canonical_entry_hash(body) != recorded_entry_hash:
                errors.append(f"{entry.evidence_id}: entry_hash mismatch (manifest row edited)")

            try:
                artifact_path = validate_safe_path(self.run_dir, entry.rel_path)
            except (SecurityViolationError, ValueError) as exc:
                errors.append(f"{entry.evidence_id}: unsafe artifact path {entry.rel_path!r} ({exc})")
                expected_prev = entry.entry_hash
                continue
            if not artifact_path.is_file():
                errors.append(f"{entry.evidence_id}: missing artifact {entry.rel_path}")
            else:
                actual_sha = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
                if actual_sha != entry.sha256:
                    errors.append(
                        f"{entry.evidence_id}: artifact SHA-256 mismatch (expected {entry.sha256}, got {actual_sha})"
                    )
            expected_prev = entry.entry_hash

        return {"valid": len(errors) == 0, "entries_checked": checked, "errors": errors}
