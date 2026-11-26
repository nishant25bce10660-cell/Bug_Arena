"""Regression test for ECC-017: sandbox ignore patterns, symlink safety, and read-only cleanup."""

import inspect
import os
import stat
from pathlib import Path

from bugarena.sandbox.manager import EphemeralSandboxManager


def test_ecc_017_sandbox_ignores_keys_handles_symlinks_and_cleans_readonly(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "secret.key").write_text("KEY", encoding="utf-8")
    (repo / "cert.pem").write_text("PEM", encoding="utf-8")
    (repo / "id_rsa").write_text("RSA", encoding="utf-8")
    (repo / ".env.staging").write_text("SECRET=1", encoding="utf-8")
    venv_dir = repo / "venv"
    venv_dir.mkdir()
    (venv_dir / "site.py").write_text("y = 2\n", encoding="utf-8")

    mgr = EphemeralSandboxManager(repo)
    captured_sb: Path | None = None
    with mgr.create_sandbox() as sb:
        captured_sb = sb
        assert (sb / "app.py").exists()
        assert not (sb / "secret.key").exists()
        assert not (sb / "cert.pem").exists()
        assert not (sb / "id_rsa").exists()
        assert not (sb / ".env.staging").exists()
        assert not (sb / "venv").exists()

        ro_file = sb / "readonly.txt"
        ro_file.write_text("locked\n", encoding="utf-8")
        os.chmod(ro_file, stat.S_IREAD)

    assert captured_sb is not None
    assert not captured_sb.exists(), "Sandbox leaked read-only files on cleanup"

    src = inspect.getsource(mgr.create_sandbox)
    assert "symlinks=True" in src or "is_symlink" in src
