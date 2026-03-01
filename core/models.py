"""
Core models and constants for the Board Room Simulation.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List


# Time pressure settings (in minutes)
TIME_PRESSURE_MINUTES = {
    "relaxed": 15,
    "normal": 10,
    "urgent": 5
}


class SimulationPhase(Enum):
    SETUP = "setup"
    ROLE_SELECT = "role_select"
    BRIEFING = "briefing"
    DISCUSSION = "discussion"
    DECISION = "decision"
    FEEDBACK = "feedback"
    SUMMARY = "summary"


@dataclass
class SimulationState:
    """Tracks the current state of the simulation"""
    current_round: int = 0
    current_phase: SimulationPhase = SimulationPhase.SETUP
    total_rounds: int = 5
    score: int = 0
    decisions_made: List[Dict] = None
    conversation_history: List[Dict] = None
    consultations_used: int = 0
    max_consultations: int = 2

    def __post_init__(self):
        if self.decisions_made is None:
            self.decisions_made = []
        if self.conversation_history is None:
            self.conversation_history = []
