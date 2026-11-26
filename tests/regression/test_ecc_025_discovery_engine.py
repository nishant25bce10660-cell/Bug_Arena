"""Regression test for ECC-025 (BA-013): indexed repo, suffix preference, dedup, confidence."""

from bugarena.discovery.engine import BugDiscoveryEngine


def test_ecc_025_suffix_match_preference_dedup_and_excluded_dirs(tmp_path):
    repo = tmp_path / "repo"
    (repo / "pkg_a").mkdir(parents=True)
    (repo / "pkg_b").mkdir(parents=True)
    (repo / "build" / "lib").mkdir(parents=True)

    (repo / "pkg_a" / "helper.py").write_text("def run():\n    return 1\n")
    (repo / "pkg_b" / "helper.py").write_text("def run():\n    return 1 / 0\n")
    (repo / "build" / "lib" / "other.py").write_text("def x():\n    pass\n")

    # External CI build path sharing trailing suffix 'pkg_b/helper.py' plus repeated recursive frames
    tb = (
        "Traceback (most recent call last):\n"
        '  File "/ci/runner/pkg_b/helper.py", line 2, in run\n'
        "    return 1 / 0\n"
        '  File "/ci/runner/pkg_b/helper.py", line 2, in run\n'
        "    return 1 / 0\n"
        '  File "/ci/runner/build/lib/other.py", line 1, in x\n'
        "    pass\n"
        "ZeroDivisionError: division by zero\n"
    )
    spec = BugDiscoveryEngine(repo).discover_from_trace(tb, max_candidates=5)
    files = [s.file_path for s in spec.suspects]
    assert "build/lib/other.py" not in files
    assert files == ["pkg_b/helper.py"]
