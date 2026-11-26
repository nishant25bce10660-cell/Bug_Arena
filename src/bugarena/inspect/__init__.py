"""DevTools inspection package covering all 14 panels and coverage_matrix.md generation."""

from bugarena.inspect.matrix import ALL_PANELS, InspectCoverageMatrix, PanelCoverage
from bugarena.inspect.runner import (
    capture_screenshots,
    collect_cross_browser_diff,
    run_full_site_inspection,
)
from bugarena.inspect.site_audit import SiteAuditCoordinator

__all__ = [
    "ALL_PANELS",
    "InspectCoverageMatrix",
    "PanelCoverage",
    "SiteAuditCoordinator",
    "capture_screenshots",
    "collect_cross_browser_diff",
    "run_full_site_inspection",
]
