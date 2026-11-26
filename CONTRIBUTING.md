# Contributing

Start with the [quickstart](README.md#quickstart), [architecture](docs/architecture.md) and [tool reference](docs/tools.md).

## Local checks

Use your virtual environment's Python:

```bash
python -m ruff check src tests scripts
python -m pytest -q --tb=short
```

`tests/unit` covers component contracts, `tests/regression` preserves defect fixes, and `tests/integration` exercises a complete repair fixture. Regression filenames retain ECC identifiers for traceability.

Run a focused demonstration without provider calls:

```bash
python -m pytest tests/integration/test_e2e_autonomous_repair.py -q
```

Follow applicable `AGENTS.md` instructions in your checkout, including report regeneration if configured there.

## Changes

Explain observable behavior and include appropriate regression coverage for behavioral changes. Update documentation when tool signatures change. Distinguish executed evidence from static analysis and model suggestions.

Keep code in its subsystem package, guides in `docs/`, utilities in `scripts/`, and generated audit output in ignored directories. Do not commit credentials, environments, caches, or historical report bundles.

Do not delete tests because their defects were fixed. Remove modules only when imports, interfaces, tests and documented workflows show that replacements cover them.
