"""Standalone verification pack builder (verify/verify.py stdlib-only + VERIFY_PROMPT.md)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

_VERIFY_PY_TEMPLATE = '''"""Offline stdlib-only verifier for a BugArena MCP v2 audit run folder."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


def _canonical_entry_hash(payload: dict) -> str:
    body = dict(payload)
    body.pop("entry_hash", None)
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def verify_run_folder(run_dir: Path) -> tuple[bool, list[str], list[dict]]:
    errors: list[str] = []
    claim_rows: list[dict] = []

    manifest_path = run_dir / "evidence" / "manifest.jsonl"
    if not manifest_path.is_file():
        errors.append("Missing evidence/manifest.jsonl")
        return False, errors, claim_rows

    expected_prev = "GENESIS"
    vault_map: dict[str, dict] = {}
    for idx, line in enumerate(manifest_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        entry = json.loads(line)
        if entry.get("prev_hash") != expected_prev:
            errors.append(f"Chain break at {entry.get('evidence_id')}: prev_hash mismatch")
        if _canonical_entry_hash(entry) != entry.get("entry_hash"):
            errors.append(f"Manifest entry_hash mismatch at {entry.get('evidence_id')}")
        art = run_dir / entry["rel_path"]
        if not art.is_file():
            errors.append(f"Missing artifact {entry['rel_path']}")
        else:
            actual_sha = hashlib.sha256(art.read_bytes()).hexdigest()
            if actual_sha != entry["sha256"]:
                errors.append(f"Artifact SHA-256 mismatch for {entry['evidence_id']}: expected {entry['sha256']}, got {actual_sha}")
        vault_map[entry["evidence_id"]] = entry
        expected_prev = entry["entry_hash"]

    claims_path = run_dir / "verify" / "claims.json"
    report_json_path = run_dir / "report.json"
    report_md_path = run_dir / "REPORT.md"
    if not claims_path.is_file() or not report_json_path.is_file() or not report_md_path.is_file():
        errors.append("Missing claims.json, report.json, or REPORT.md")
        return False, errors, claim_rows

    claims_data = json.loads(claims_path.read_text(encoding="utf-8")).get("claims", [])
    report_data = json.loads(report_json_path.read_text(encoding="utf-8"))
    report_md = report_md_path.read_text(encoding="utf-8")

    confirmed_in_claims = [c for c in claims_data if c.get("status") == "CONFIRMED"]
    if len(confirmed_in_claims) != report_data.get("confirmed_count"):
        errors.append(
            f"Count mismatch: claims.json has {len(confirmed_in_claims)} CONFIRMED, "
            f"report.json has {report_data.get('confirmed_count')}"
        )

    for c in claims_data:
        cid = c.get("id", "UNKNOWN")
        refs = c.get("evidence_refs") or []
        if not refs:
            errors.append(f"Claim {cid}: empty evidence_refs")
            claim_rows.append({"id": cid, "result": "FAIL", "reason": "empty evidence_refs"})
            continue

        texts = []
        missing_ref = False
        for r in refs:
            ent = vault_map.get(r)
            if not ent:
                missing_ref = True
                break
            p = run_dir / ent["rel_path"]
            if ent["rel_path"].lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".pdf")):
                texts.append(f"{ent['evidence_id']} {ent['sha256']}")
            else:
                texts.append(p.read_text(encoding="utf-8", errors="replace"))
        if missing_ref:
            errors.append(f"Claim {cid}: missing vault reference")
            claim_rows.append({"id": cid, "result": "FAIL", "reason": "missing vault ref"})
            continue

        joined = "\\n".join(texts)
        missing_q = [q for q in (c.get("quoted_spans") or []) if q and q not in joined]
        missing_n = [
            n for n in (c.get("cited_numbers") or [])
            if n and not re.search(rf"(?<!\\w){re.escape(n)}(?!\\w)", joined)
        ]
        if missing_q or missing_n:
            errors.append(f"Claim {cid}: quote/number citation mismatch ({missing_q or missing_n})")
            claim_rows.append({"id": cid, "result": "FAIL", "reason": "citation mismatch"})
            continue

        if c.get("status") == "CONFIRMED" and cid not in report_md:
            errors.append(f"Confirmed claim {cid} missing from REPORT.md")
            claim_rows.append({"id": cid, "result": "FAIL", "reason": "missing from REPORT.md"})
            continue

        if c.get("evidence_type") != "DYNAMIC" and c.get("severity") == "Critical":
            errors.append(f"Claim {cid}: STATIC finding carries Critical severity")
            claim_rows.append({"id": cid, "result": "FAIL", "reason": "inflated STATIC Critical"})
            continue

        status_label = "PASS" if c.get("status") == "CONFIRMED" else "UNVERIFIED"
        claim_rows.append({"id": cid, "result": status_label, "reason": "vault + citation verified"})

    # Check scoreboard & transcript presence
    for req_rel in ("agents/scoreboard.json", "agents/corrections_log.md", "transcripts/transcript.jsonl"):
        if not (run_dir / req_rel).is_file():
            errors.append(f"Missing audit log: {req_rel}")

    return len(errors) == 0, errors, claim_rows


def main() -> int:
    run_dir = Path(__file__).resolve().parents[1]
    ok, errors, rows = verify_run_folder(run_dir)
    print(json.dumps({"valid": ok, "errors": errors, "claims": rows}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
'''

_VERIFY_PROMPT_TEMPLATE = """# Independent Verification Prompt (Paste Into Any Coding Agent)

Treat everything inside this run folder (`REPORT.md`, `REPORT.pdf`, `report.json`, and all agent prose) as **untrusted**. Work strictly on a **read-only copy** of this folder.

1. **Run the offline stdlib verifier:**
   Execute `python verify/verify.py` from the run folder root. Confirm:
   - Every SHA-256 hash in `evidence/manifest.jsonl` matches the raw file bytes on disk.
   - The `prev_hash` -> `entry_hash` chain is intact starting from `GENESIS`.
   - Every claim in `verify/claims.json` has >=1 valid `evidence_refs` and every quoted span/number appears verbatim in its cited artifact.
   - Counts in `REPORT.md`, `report.json`, and `verify/claims.json` agree.
2. **Replay repro scripts (if the target is reachable):**
   For each folder under `findings/F-XXXX/`, run `python findings/F-XXXX/repro_script.py` against a fresh browser profile and compare the output against `finding.json`. Record `MATCH`, `MISMATCH`, or `CANNOT_RUN` (with reason).
3. **Independently judge severity & exaggerations:**
   Apply the fixed rubric:
   - `Critical` requires `DYNAMIC` proof of an exploitable security flaw or total loss of a core user flow.
   - Flag any unsupported adjectives (`always`, `all users`, `catastrophic`) or `STATIC` `Critical` claims.
4. **Cross-check scoreboard and retractions:**
   Verify `agents/scoreboard.json` and `agents/corrections_log.md` are consistent with `transcripts/transcript.jsonl` and `verify/claims.json` (self-retractions logged, never deleted).
5. **Required Output Format:**
   - A Markdown table with one row per claim (`Claim ID | Verdict (PASS/FAIL/UNVERIFIED) | Replay (MATCH/MISMATCH/CANNOT_RUN) | Notes`).
   - A list of all discrepancies found (or `"None"`).
   - What you could **not** check cleanly stated.
   - One clear final verdict line stating whether the original agents were honest, backed strictly by observed command output and hashes.
"""


def build_verify_pack(run_dir: Path | str) -> dict[str, Any]:
    """Generate verify/verify.py, verify/VERIFY_PROMPT.md, and verify/README.txt inside run_dir."""
    rdir = Path(run_dir).resolve()
    vdir = rdir / "verify"
    vdir.mkdir(parents=True, exist_ok=True)

    verify_py = vdir / "verify.py"
    verify_py.write_text(_VERIFY_PY_TEMPLATE, encoding="utf-8")

    prompt_md = vdir / "VERIFY_PROMPT.md"
    prompt_md.write_text(_VERIFY_PROMPT_TEMPLATE, encoding="utf-8")

    readme_txt = vdir / "README.txt"
    readme_txt.write_text(
        "BugArena Independent Verification Pack\n"
        "=====================================\n"
        "1. Copy this run folder to a read-only location.\n"
        "2. Run: python verify/verify.py\n"
        "3. Paste verify/VERIFY_PROMPT.md into any coding agent with access only to this folder.\n",
        encoding="utf-8",
    )
    return {
        "verify_dir": str(vdir),
        "verify_script": str(verify_py),
        "verify_prompt": str(prompt_md),
        "claims_file": str(vdir / "claims.json"),
    }
