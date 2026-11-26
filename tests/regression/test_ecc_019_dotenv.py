"""Regression test for ECC-019 (BA-021): safe load_env_file scoping, encoding, and parsing."""

import os
from unittest.mock import patch

from bugarena.config import load_env_file


def test_ecc_019_explicit_path_and_no_cwd_autoload(tmp_path, monkeypatch):
    explicit_env = tmp_path / "explicit.env"
    explicit_env.write_text('export CUSTOM_A="val1" # inline comment\nCUSTOM_B=\'val2\'\n', encoding="utf-8")

    cwd_dir = tmp_path / "untrusted_cwd"
    cwd_dir.mkdir()
    (cwd_dir / ".env").write_text("UNTRUSTED_CWD_KEY=injected\n", encoding="utf-8")

    monkeypatch.chdir(cwd_dir)
    with patch.dict(os.environ, {}, clear=False):
        for k in ("CUSTOM_A", "CUSTOM_B", "UNTRUSTED_CWD_KEY"):
            os.environ.pop(k, None)

        load_env_file(explicit_env)
        assert os.environ.get("CUSTOM_A") == "val1"
        assert os.environ.get("CUSTOM_B") == "val2"
        assert "UNTRUSTED_CWD_KEY" not in os.environ

        for k in ("CUSTOM_A", "CUSTOM_B", "UNTRUSTED_CWD_KEY"):
            os.environ.pop(k, None)

        # Calling with None must NOT auto-load cwd/.env either
        load_env_file(None)
        assert "UNTRUSTED_CWD_KEY" not in os.environ


def test_ecc_019_utf16_and_blank_key_fallback(tmp_path):
    p1 = tmp_path / "first.env"
    p2 = tmp_path / "second.env"
    p1.write_text("EMPTY_KEY=\nSHARED_KEY=  \n", encoding="utf-16")
    p2.write_text("EMPTY_KEY=real_secret\nHASH_VAL=abc#not_comment\n", encoding="utf-8-sig")

    with patch.dict(os.environ, {}, clear=False):
        for k in ("EMPTY_KEY", "SHARED_KEY", "HASH_VAL"):
            os.environ.pop(k, None)
        load_env_file(p1)
        assert "EMPTY_KEY" not in os.environ
        assert "SHARED_KEY" not in os.environ
        load_env_file(p2)
        assert os.environ.get("EMPTY_KEY") == "real_secret"
        assert os.environ.get("HASH_VAL") == "abc#not_comment"
