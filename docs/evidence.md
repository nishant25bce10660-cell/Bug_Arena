# Evidence and comparison

[Documentation index](README.md) · [Features](../README.md#features)

## A reproducible repair example

The [integration fixture](../tests/integration/test_e2e_autonomous_repair.py) constructs a calculator whose division by zero crashes. It supplies two candidate diffs, runs the composite repair workflow, and asserts:

1. `cand_surgical_01` wins, passes reproduction, has zero failing regressions, and scores above 90.
2. `cand_regressive_02`, which breaks addition, is disqualified with a zero score.
3. A report exists on disk and includes the winning patch and disqualification.

Reproduce it with `python -m pytest tests/integration/test_e2e_autonomous_repair.py -q`. These are fixture assertions, not live model results or a real-world success-rate benchmark.

## Claim-to-evidence map

| Claim | Source / test | Boundary |
| --- | --- | --- |
| Failing baseline is required | [Red validator tests](../tests/regression/test_ecc_010_red_validator.py) | Supported Python/pytest reproductions |
| Patch traversal and malformed hunks are checked | [Parser tests](../tests/regression/test_ecc_008_patch_parser.py) | Specific tested path and diff cases |
| Missing test/mutation evidence earns no free points | [Evaluator tests](../tests/regression/test_ecc_013_027_028_evaluator.py) | Formula behavior, not a calibrated accuracy metric |
| Audit finding verification and deduplication exist | [Audit engine tests](../tests/unit/test_audit_engine.py) | Synthetic fixtures and implemented detectors |
| Five provider routes have tests | [Provider negative-path tests](../tests/regression/test_ecc_039_provider_negative_paths.py) | Mock HTTP transport, not live service certification |
| Container command restrictions exist | [Isolation tests](../tests/regression/test_ecc_005_isolation_docs.py) | Command construction, not live container validation |

## Comparison with related MCP integrations

Sources reviewed on **2026-11-26**. This compares documented workflows, not measured superiority or exclusive capabilities.

| Project | Documented emphasis | How BugArena's focus relates |
| --- | --- | --- |
| [Semgrep Guardian / MCP](https://github.com/semgrep/semgrep/blob/develop/cli/src/semgrep/mcp/README.md) | Security scanning integrated with coding agents; findings can prompt code regeneration | BugArena emphasizes reproduction-driven candidate tournaments and pytest evaluation |
| [Sentry MCP](https://mcp.sentry.dev/) | Production error search, performance investigation, triage and project management | BugArena evaluates local source changes and records audit evidence |

Other products also support remediation workflows. No comparison here demonstrates that they lack similar capabilities. BugArena has no published head-to-head accuracy, latency, security or cost benchmark in this repository.

## Historical local material

The local report bundles were consulted as historical context. One older baseline log recorded 43 passing tests; another proof file identified an older commit. Neither establishes the current branch's correctness. Those bundles remain excluded from the repository as requested; public evidence links point to maintained source and tests instead.

## Limits to keep visible

- Python-focused implementation; no demonstrated general-language repair support.
- Audit area coverage is not code coverage or proof of completeness.
- Offline detectors include checks specific to BugArena's own modules.
- Model availability, credentials, quotas and response quality vary.
- Default host execution is not a security jail.
- Evaluated patches still need review before application.
- The evaluator does not currently run mutation testing.
