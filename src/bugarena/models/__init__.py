"""Domain models package for BugArena."""

from bugarena.models.agent import AgentPersona, CandidatePatch, PersonaType
from bugarena.models.bug import BugSpec, FaultTrace, SuspectLocation
from bugarena.models.report import FixReport
from bugarena.models.repro import ExecutionOutcome, ReproTestSpec
from bugarena.models.tournament import PatchEvaluation, TournamentRecord

__all__ = [
    "AgentPersona",
    "BugSpec",
    "CandidatePatch",
    "ExecutionOutcome",
    "FaultTrace",
    "FixReport",
    "PatchEvaluation",
    "PersonaType",
    "ReproTestSpec",
    "SuspectLocation",
    "TournamentRecord",
]
