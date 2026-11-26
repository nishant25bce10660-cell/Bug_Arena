"""Append-only scrubbed transcript logger per agent and per [mcp_<browser>] cursor."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bugarena.truth.vault import scrub_evidence_text

_SENSITIVE_ARG_KEYS = ("token", "secret", "password", "passwd", "api_key", "apikey", "authorization", "cookie")


def _redact_args_obj(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            k: ("[REDACTED]" if any(s in str(k).lower() for s in _SENSITIVE_ARG_KEYS) else _redact_args_obj(v))
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [_redact_args_obj(item) for item in obj]
    return obj


class TranscriptLogger:
    """Records every tool invocation and result SHA-256 to transcripts/transcript.jsonl."""

    def __init__(self, run_dir: Path | str):
        self.run_dir = Path(run_dir).resolve()
        self.transcript_path = self.run_dir / "transcripts" / "transcript.jsonl"
        self.transcript_path.parent.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        *,
        agent: str,
        tool: str,
        args: Any,
        result_bytes: bytes | str,
        status: str = "ok",
        cursor: str = "",
    ) -> dict[str, Any]:
        raw_bytes = result_bytes.encode("utf-8") if isinstance(result_bytes, str) else bytes(result_bytes)
        result_sha = hashlib.sha256(raw_bytes).hexdigest()
        redacted_obj = _redact_args_obj(args)
        scrubbed_args, _ = scrub_evidence_text(json.dumps(redacted_obj, default=str), base_dir=self.run_dir)
        record = {
            "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
            "agent": agent,
            "cursor": cursor,
            "tool": tool,
            "args": scrubbed_args,
            "result_sha256": result_sha,
            "result_bytes": len(raw_bytes),
            "status": status,
        }
        with self.transcript_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        return record
