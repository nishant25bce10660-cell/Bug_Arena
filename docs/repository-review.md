# Repository organization review

[Documentation index](README.md)

## Scope

Reviewed the tracked-file inventory, Python module/test structure, tool signatures, documentation claims, configuration, and historical local evidence. Checked nonempty tracked files for exact duplicates. This was a repository organization and documentation review, not a claim of exhaustive semantic verification of every code path.

## Decisions

| Area | Decision and reason |
| --- | --- |
| README | Replace the old overview with navigation, expandable setup, workflow diagram and evidence links |
| Detailed documentation | Move subsystem/scoring explanations into `docs/`; add exact tool signatures and configuration guidance |
| Unsupported claims | Remove the MIT label without a license file; remove the nonexistent `fix_loop_start(dry_run=...)` argument |
| Source packages | Keep existing subsystem boundaries; no superseded implementation was established |
| Regression tests | Retain historical defect IDs and fixtures; they protect fixes rather than duplicate production code |
| Prompt files | Retain distinct role prompts and shared fix-author prompt; registry references them |
| Old report bundles | Ignore `bug_report/` and `bug-report ECC/`; keep them out of publication |
| Credentials and caches | Continue existing ignore rules |

No identical nonempty tracked files were found in the inspected local inventory. No production module was deleted solely because its name or age suggested it was obsolete. The replaced README content is superseded by the new overview and focused guides.

## Validation

Validated on Windows on 2026-11-26, against public code base `b4afc3b` plus this documentation/configuration cleanup:

- `python -m pytest -q --tb=short`: **110 passed in 54.36 seconds**, including the end-to-end repair fixture.
- `python -m ruff check src tests scripts`: **passed**.
- Parsed all **98 tracked Python files** in the publication checkout with Python's AST parser.
- All **13 MCP tools** appear in the README and signature reference.
- Checked local Markdown file links and heading anchors; all resolved. Code fences and expandable sections were balanced.
- Both historical report folders are covered by Git ignore rules.

The first test run had 109 passes and one environment-related failure: a Windows environment reset left an injected `GIT_CONFIG_COUNT` without its matching empty value. The passing rerun set `GIT_CONFIG_COUNT=0` for the test process only; no repository behavior or test assertion was changed. These are local results, not a hosted CI badge.

Live provider access, live container execution, clean-machine installation and cross-platform execution were not validated. Separate in-progress local report-generator changes were excluded from the publication checkout.
