"""
Core models and constants for the Board Room Simulation.
"""

from dataclasses import dataclass


# Time pressure settings (in minutes)
TIME_PRESSURE_MINUTES = {
    "relaxed": 15,
    "normal": 10,
    "urgent": 5
}


@dataclass
class SimulationState:
    """Lightweight carrier for round/total passed to run_simulation_round and deliberation."""
    current_round: int = 0
    total_rounds: int = 5
