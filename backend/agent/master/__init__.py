"""Master/Pupil orchestration primitives."""

from agent.master.delegation import DelegationManager, DelegationResult
from agent.master.registry import PupilRegistry
from agent.master.state import MasterThreadState, MasterThreadStateStore

__all__ = [
    "DelegationManager",
    "DelegationResult",
    "MasterThreadState",
    "MasterThreadStateStore",
    "PupilRegistry",
]
