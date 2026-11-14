"""Multi-model LLM provider integration for competing repair agents."""

from bugarena.tournament.providers.dispatcher import (
    MultiModelDispatcher,
    build_repair_prompt,
    extract_diff_and_explanation,
    get_recommended_model_for_persona,
)

__all__ = [
    "MultiModelDispatcher",
    "build_repair_prompt",
    "extract_diff_and_explanation",
    "get_recommended_model_for_persona",
]
