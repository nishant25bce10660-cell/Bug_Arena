# BugArena MCP Repository Instructions

## Mandatory Post-Change Report & Audit Rule
After any change to code, tests, scripts, packaging, or documentation in this repository, always regenerate and audit `PROJECT_REPORT.md` before finishing or committing:

```powershell
.\.venv\Scripts\python.exe scripts/update_project_report.py
```

On POSIX shells:

```bash
.venv/bin/python scripts/update_project_report.py
```

This runs `ruff check src tests scripts`, `pytest -q --tb=short`, and a read-only `LoopOperator` multi-agent audit, updating `PROJECT_REPORT.md` (and `.bugarena/latest_audit.md`). The `.githooks/pre-commit` hook also enforces and stages this update on every commit when `core.hooksPath` is set to `.githooks`.
