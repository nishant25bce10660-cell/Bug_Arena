"""Regression test for ECC-021: true LRU registry eviction and atomic tournament lookup/store."""

import bugarena.server as srv
from bugarena.models.tournament import TournamentRecord


def test_ecc_021_true_lru_eviction_on_read():
    with srv._REGISTRY_LOCK:
        srv._TOURNAMENT_REGISTRY.clear()

    # Populate MAX_REGISTRY_SIZE entries
    for i in range(srv.MAX_REGISTRY_SIZE):
        srv._store_tournament(f"t_{i}", TournamentRecord(tournament_id=f"t_{i}", repo_path="."))

    # Read t_0 via _get_tournament so t_0 becomes MRU (must survive when t_extra is inserted!)
    rec_0 = srv._get_tournament("t_0") if hasattr(srv, "_get_tournament") else None
    assert rec_0 is not None, "_get_tournament LRU helper missing"

    # Insert one more entry (should evict t_1, NOT t_0!)
    srv._store_tournament("t_extra", TournamentRecord(tournament_id="t_extra", repo_path="."))
    assert "t_0" in srv._TOURNAMENT_REGISTRY
    assert "t_1" not in srv._TOURNAMENT_REGISTRY
