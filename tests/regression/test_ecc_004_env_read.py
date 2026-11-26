"""Regression test for ECC-004: exclude .env/non-source files and scrub secrets in discovery/reports."""

from bugarena.discovery.engine import BugDiscoveryEngine
from bugarena.server import bug_detect, generate_bug_report


def test_ecc_004_discovery_ignores_env_and_non_source_files(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    secret = "sk-proj-" + "secretvalue1234567890abcdef"
    (repo / ".env").write_text(f"OPENAI_API_KEY={secret}\n", encoding="utf-8")
    (repo / "notes.txt").write_text("TOKEN=ghp_12345678901234567890\n", encoding="utf-8")

    engine = BugDiscoveryEngine(repo)
    spec = engine.discover_from_trace(
        error_log='  File ".env", line 1, in <module>\n    OPENAI_API_KEY=...\n  File "notes.txt", line 1, in <module>\nRuntimeError: fail'
    )
    assert spec.suspects == [] or spec.suspects == ()
    assert secret not in (spec.error_log or "")


def test_ecc_004_server_bug_detect_and_report_scrub_secrets(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    secret = "sk-ant-" + "secretvalue1234567890abcdef"
    (repo / "app.py").write_text(f'KEY = "{secret}"\n', encoding="utf-8")

    det = bug_detect(
        repo_path=str(repo),
        error_log=f'  File "app.py", line 1, in <module>\n    KEY = "{secret}"\nValueError: bad',
    )
    assert secret not in str(det)

    rep = generate_bug_report(
        repo_path=str(repo),
        error_log=f'  File "app.py", line 1, in <module>\n    KEY = "{secret}"\nValueError: bad',
    )
    assert secret not in rep["report_markdown"]
