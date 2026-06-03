"""
Pydantic schema for scenario generation via Gemini structured output.

Replaces the v1.4.7 text-format parser. The schema is passed to
GenerateContentConfig.response_schema so Gemini emits valid JSON matching
this shape, eliminating regex parsing of model output.

Downstream code keeps consuming the text-format scenario string for
backwards compatibility — core.simulation_engine renders this structured
response into that text format via _render_scenario_text().

Note: Gemini API does not support `additionalProperties`, so stances and
counters are lists of objects (member_name + value) rather than dicts.
The renderer converts them to dict form for downstream consumers.
"""

from typing import List, Literal
from pydantic import BaseModel, Field


CalibrationTier = Literal[
    'unanimous',
    'mild_dissent',
    'controversial',
    'highly_controversial',
]

Stance = Literal['APPROVE', 'OPPOSE', 'NEUTRAL']

TimeSensitivity = Literal['Low', 'Moderate', 'High', 'Urgent']

OptionLetter = Literal['A', 'B', 'C', 'D']


class StanceAssignment(BaseModel):
    """One non-player member's stance on a single option."""

    member_name: str = Field(
        ...,
        description="Exact name from the non-player board members roster.",
    )
    stance: Stance


class CounterArgument(BaseModel):
    """An OPPOSE member's objection to a single option."""

    member_name: str = Field(
        ...,
        description="Must match a member_name in the same option's stances list with stance=OPPOSE.",
    )
    objection: str = Field(
        ...,
        description="1-2 sentence objection grounded in that member's expertise.",
    )


class ScenarioOption(BaseModel):
    """One of the four calibrated board options."""

    letter: OptionLetter
    calibration: CalibrationTier
    action: str = Field(
        ...,
        description=(
            "3-5 substantive sentences describing the action and its honest "
            "trade-offs (financial, regulatory, reputational, operational). "
            "Must NOT telegraph the calibration tier — no phrases like "
            "'this is the safest option' or 'the board will reject this'."
        ),
    )
    stances: List[StanceAssignment] = Field(
        ...,
        description=(
            "One entry per non-player board member, using the exact names "
            "from the roster. Every non-player member must appear exactly once."
        ),
    )
    counters: List[CounterArgument] = Field(
        default_factory=list,
        description=(
            "One entry per OPPOSE member in this option. Each objection "
            "must be grounded in that member's expertise."
        ),
    )


class ScenarioResponse(BaseModel):
    """Full scenario emitted by the generator LLM."""

    title: str = Field(..., description="Short scenario title (one line).")
    situation: str = Field(
        ...,
        description="2-3 paragraph description of the boardroom situation.",
    )
    key_question: str = Field(
        ...,
        description="The single decision the player must address.",
    )
    stakeholders: List[str] = Field(
        ...,
        description="Affected parties — shareholders, employees, regulators, etc.",
    )
    time_sensitivity: TimeSensitivity = Field(
        ...,
        description=(
            "How urgent the decision is. Do NOT downgrade from a prior round's "
            "High/Urgent if the crisis is ongoing or escalating."
        ),
    )
    options: List[ScenarioOption] = Field(
        ...,
        min_length=4,
        max_length=4,
        description=(
            "EXACTLY 4 options labeled A, B, C, D. Each option must be a genuinely "
            "different strategic approach. Across the 4 options, calibrations must "
            "include one of each tier: unanimous, mild_dissent, controversial, "
            "highly_controversial. Letter-to-calibration mapping should be "
            "randomized per round."
        ),
    )
