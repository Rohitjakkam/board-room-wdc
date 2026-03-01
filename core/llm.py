"""
LLM initialization and prompt generators for the Board Room Simulation.
"""

import google.generativeai as genai
from typing import Dict, List


def initialize_llm(api_key: str) -> genai.GenerativeModel:
    """Initialize Gemini 2.0 Flash Lite model."""
    genai.configure(api_key=api_key)
    return genai.GenerativeModel(
        model_name="gemini-2.0-flash-lite",
        generation_config={
            "temperature": 0.7,
            "max_output_tokens": 2048,
        }
    )


def get_board_member_prompt(member: Dict, company_data: Dict, module_data: Dict) -> str:
    """Generate a system prompt for a board member persona."""
    return f"""You are {member['name']}, {member['role']} at {company_data['company_name']}.

PERSONALITY & BACKGROUND:
{member['personality']}

EXPERTISE: {member['expertise']}
TENURE: {member['tenure_years']} years on the board

COMPANY CONTEXT:
{company_data['company_overview']}

CURRENT CHALLENGES:
{chr(10).join(f"- {problem}" for problem in company_data['current_problems'])}

YOUR ROLE IN THIS SIMULATION:
- Stay in character as {member['name']} throughout the discussion
- Express opinions based on your expertise and personality
- Challenge or support decisions based on your perspective
- Reference relevant metrics and data when appropriate
- Consider the module topic: {module_data['module_name']}

KEY METRICS TO CONSIDER:
- Annual Revenue: {company_data['metrics']['total_revenue_annual']['value']} {company_data['metrics']['total_revenue_annual']['unit']}
- EBITDA: {company_data['metrics']['ebitda']['value']} {company_data['metrics']['ebitda']['unit']}
- Employee Count: {company_data['metrics']['employee_count']['value']}
- Platform Uptime: {company_data['metrics']['platform_uptime']['value']}%

Respond naturally as this board member would, considering their biases and priorities."""


def get_committee_prompt(committee: Dict, company_data: Dict, module_data: Dict, members_data: List[Dict]) -> str:
    """Generate a system prompt for a committee consultation."""
    member_details = []
    for member_name in committee['members']:
        member = next((m for m in members_data if m['name'] == member_name), None)
        if member:
            member_details.append(f"- {member['name']} ({member['role']}): {member['expertise']} expertise")

    return f"""You are representing the {committee['name']} of {company_data['company_name']}.

COMMITTEE DETAILS:
- Type: {committee['type']}
- Purpose: {committee['purpose']}
- Chairperson: {committee['chairperson']}
- Members:
{chr(10).join(member_details)}

COMPANY CONTEXT:
{company_data['company_overview']}

CURRENT CHALLENGES:
{chr(10).join(f"- {problem}" for problem in company_data['current_problems'])}

MODULE FOCUS: {module_data['module_name']}

As the {committee['name']}, provide a collective perspective that:
- Reflects the committee's specialized focus ({committee['purpose']})
- Incorporates viewpoints from all committee members
- Provides actionable recommendations
- References relevant governance frameworks and best practices

Respond as a unified committee voice, acknowledging different member perspectives where relevant."""


def get_member_stance_prompt(member: Dict, company_data: Dict, module_data: Dict,
                              scenario: str, player_decision: str, player_role: Dict) -> str:
    """Generate prompt for a board member to evaluate the player's decision."""
    return f"""You are {member['name']}, {member['role']} at {company_data['company_name']}.

PERSONALITY & BACKGROUND:
{member['personality']}

EXPERTISE: {member['expertise']}
TENURE: {member['tenure_years']} years on the board

YOUR TASK: Evaluate a fellow board member's decision and determine your stance.

SCENARIO PRESENTED:
{scenario}

DECISION MADE BY {player_role['name']} ({player_role['role']}):
{player_decision}

Based on your expertise in {member['expertise']} and your personality:
1. Would you APPROVE, OPPOSE, or remain NEUTRAL on this decision?
2. How does this decision relate to your area of expertise?
3. What is your honest reaction?

Respond in this EXACT format:
STANCE: [APPROVE/OPPOSE/NEUTRAL]
CONVICTION_LEVEL: [1-10, where 10 is absolute certainty]
EXPERTISE_RELEVANCE: [Brief explanation of how your expertise relates to this decision]
REACTION: [Your 2-3 sentence reaction as this board member, in first person]
COUNTER_OPINION: [If OPPOSE: Your specific objection and what you believe should be done instead. If APPROVE/NEUTRAL: Write "N/A"]

Stay in character. Consider how {member['name']}'s biases and priorities would influence their view."""


def get_debate_evaluation_prompt(member: Dict, company_data: Dict,
                                  original_counter_opinion: str,
                                  player_response: str,
                                  debate_history: List[Dict],
                                  player_role: Dict) -> str:
    """Generate prompt to evaluate player's response to a dissenter's argument."""
    history_text = ""
    for exchange in debate_history:
        history_text += f"\n{member['name']}'s argument: {exchange.get('dissenter_argument', '')}"
        history_text += f"\n{player_role['name']}'s response: {exchange.get('player_response', '')}\n"

    return f"""You are {member['name']}, {member['role']} at {company_data['company_name']}.

PERSONALITY & BACKGROUND:
{member['personality']}

EXPERTISE: {member['expertise']}

You OPPOSED a decision and raised this counter-opinion:
"{original_counter_opinion}"

DEBATE HISTORY SO FAR:
{history_text if history_text else "This is the first exchange."}

{player_role['name']} ({player_role['role']}) NOW RESPONDS:
"{player_response}"

Evaluate this response considering:
1. Does it address your specific concerns?
2. Is the reasoning sound and well-supported?
3. Does it account for your area of expertise ({member['expertise']})?
4. Would {member['name']} be convinced by this argument?

Respond in this EXACT format:
EVALUATION: [2-3 sentences assessing the response quality]
RESPONSE_SCORE: [0-100, how effective the response was]
STANCE_CHANGED: [YES/NO - has this response convinced you?]
FOLLOW_UP: [If STANCE_CHANGED is NO: Your follow-up challenge or continued objection. If YES: Your acknowledgment of their point and why you now support the decision]

Remember to stay in character as {member['name']}."""


def get_consultation_alignment_prompt(consultations: List[Dict],
                                       player_decision: str,
                                       member_stances: Dict) -> str:
    """Generate prompt to evaluate how well player's consultations aligned with their decision."""
    consultation_text = "\n".join([
        f"- Consulted {c.get('member', 'Unknown')}: Asked about '{c.get('content', '')}'"
        for c in consultations if c.get('role') == 'user'
    ])

    approving_members = [name for name, stance in member_stances.items()
                         if stance.get('stance') in ['APPROVE', 'approve']]
    opposing_members = [name for name, stance in member_stances.items()
                        if stance.get('stance') in ['OPPOSE', 'oppose']]

    return f"""Analyze the alignment between a player's board consultations and their final decision.

CONSULTATIONS MADE:
{consultation_text if consultation_text else "No consultations were made."}

FINAL DECISION:
{player_decision}

BOARD MEMBER REACTIONS:
- Approving: {', '.join(approving_members) if approving_members else 'None'}
- Opposing: {', '.join(opposing_members) if opposing_members else 'None'}

Evaluate:
1. Did the player consult members whose expertise was relevant to their decision?
2. Did the consultations help anticipate board opposition?
3. Was the consultation strategy effective?

Respond in this EXACT format:
ALIGNMENT_SCORE: [0-100]
REASONING: [2-3 sentences explaining the score]"""


def get_scenario_generator_prompt(company_data: Dict, module_data: Dict, round_config: Dict, player_role: Dict) -> str:
    """Generate prompt for creating simulation scenarios."""
    return f"""You are a corporate governance simulation scenario generator.

COMPANY: {company_data['company_name']}
{company_data['company_overview']}

CURRENT PROBLEMS:
{chr(10).join(f"- {problem}" for problem in company_data['current_problems'])}

MODULE FOCUS: {module_data['module_name']}
{module_data['overview']}

LEARNING OBJECTIVES:
{chr(10).join(f"- {obj}" for obj in module_data['learning_objectives'])}

PLAYER'S ROLE: {player_role['name']} - {player_role['role']}
Player's Expertise: {player_role['expertise']}

ROUND CONFIGURATION:
- Round Number: {round_config['round_number']}
- Difficulty: {round_config['difficulty']}
- Focus Area: {round_config.get('focus_area', 'General')}
- Round Type: {round_config['round_type']}

Generate a realistic boardroom scenario that:
1. Presents a specific challenge or decision point relevant to the player's role
2. Requires application of concepts from the module
3. Has multiple valid approaches with trade-offs
4. Creates tension between different board member perspectives
5. Is appropriate for the specified difficulty level

Format your response as:
SCENARIO TITLE: [Title]

SITUATION: [Detailed description of the situation - 2-3 paragraphs]

KEY QUESTION: [The main decision or question the player must address]

STAKEHOLDERS AFFECTED: [List of affected parties]

TIME SENSITIVITY: [How urgent is this decision]

OPTIONS TO CONSIDER:
A) [First option - brief description]
B) [Second option - brief description]
C) [Third option - brief description]
D) [Fourth option - brief description]

Make sure each option is distinct and represents a different strategic approach."""
