"""
LLM-driven simulation operations — scenario generation, board responses,
decision evaluation, stance generation, debate evaluation.
"""

import logging
import time
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
from typing import Dict, List

from core.llm import (
    get_board_member_prompt,
    get_committee_prompt,
    get_member_stance_prompt,
    get_debate_evaluation_prompt,
    get_consultation_alignment_prompt,
    get_scenario_generator_prompt,
)

logger = logging.getLogger(__name__)

_RETRYABLE_EXCEPTIONS = (
    google_exceptions.ResourceExhausted,
    google_exceptions.ServiceUnavailable,
    google_exceptions.InternalServerError,
    google_exceptions.DeadlineExceeded,
)


def _call_llm(llm, prompt, max_retries=3):
    """Call Gemini API with exponential backoff retry on transient errors."""
    for attempt in range(max_retries + 1):
        try:
            response = llm.generate_content(prompt)
            return response.text
        except _RETRYABLE_EXCEPTIONS as e:
            if attempt == max_retries:
                raise
            wait = 2 ** (attempt + 1)
            logger.warning(f"Gemini API error (attempt {attempt+1}/{max_retries}): {e}. Retrying in {wait}s...")
            time.sleep(wait)
        except Exception:
            raise


def generate_scenario(llm: genai.GenerativeModel, company_data: Dict,
                      module_data: Dict, round_config: Dict, player_role: Dict) -> str:
    """Generate a new scenario for the current round."""
    prompt = get_scenario_generator_prompt(company_data, module_data, round_config, player_role)
    full_prompt = f"""You are an expert corporate governance simulation designer.

{prompt}"""
    return _call_llm(llm, full_prompt)


def get_board_member_response(llm: genai.GenerativeModel, members: List[Dict],
                               company_data: Dict, module_data: Dict,
                               scenario: str, user_input: str,
                               conversation_history: List[Dict],
                               player_role: Dict) -> str:
    """Get a response from one or multiple board member personas."""
    if len(members) == 1:
        member = members[0]
        system_prompt = get_board_member_prompt(member, company_data, module_data)

        history_text = ""
        for entry in conversation_history[-10:]:
            if entry['role'] == 'user':
                history_text += f"{player_role['name']}: {entry['content']}\n"
            else:
                history_text += f"{entry.get('member', 'Board Member')}: {entry['content']}\n"

        full_prompt = f"""{system_prompt}

CONVERSATION HISTORY:
{history_text}

CURRENT SCENARIO:
{scenario}

{player_role['name']} ({player_role['role']}) ASKS:
{user_input}

Respond as {member['name']} would, considering your expertise in {member['expertise']} and your personality traits.
Be concise but insightful. Express your genuine opinion based on your character.
Address {player_role['name']} directly in your response."""

    else:
        member_names = [m['name'] for m in members]
        member_details = "\n".join([f"- {m['name']} ({m['role']}): {m['personality']}" for m in members])

        history_text = ""
        for entry in conversation_history[-10:]:
            if entry['role'] == 'user':
                history_text += f"{player_role['name']}: {entry['content']}\n"
            else:
                history_text += f"{entry.get('member', 'Board Members')}: {entry['content']}\n"

        full_prompt = f"""You are simulating a group discussion between the following board members at {company_data['company_name']}:

{member_details}

COMPANY CONTEXT:
{company_data['company_overview']}

CURRENT CHALLENGES:
{chr(10).join(f"- {problem}" for problem in company_data['current_problems'])}

CONVERSATION HISTORY:
{history_text}

CURRENT SCENARIO:
{scenario}

{player_role['name']} ({player_role['role']}) ASKS THE GROUP:
{user_input}

Provide a group discussion response where each board member ({', '.join(member_names)}) briefly shares their perspective.
Format as:
**[Member Name]:** [Their response]

Each member should respond according to their expertise and personality. Keep each response concise (2-3 sentences).
Address {player_role['name']} directly."""

    return _call_llm(llm, full_prompt)


def get_committee_response(llm: genai.GenerativeModel, committee: Dict,
                           company_data: Dict, module_data: Dict,
                           scenario: str, user_input: str,
                           conversation_history: List[Dict],
                           player_role: Dict,
                           all_members: List[Dict]) -> str:
    """Get a response from a committee."""
    system_prompt = get_committee_prompt(committee, company_data, module_data, all_members)

    history_text = ""
    for entry in conversation_history[-10:]:
        if entry['role'] == 'user':
            history_text += f"{player_role['name']}: {entry['content']}\n"
        else:
            history_text += f"{entry.get('member', 'Committee')}: {entry['content']}\n"

    full_prompt = f"""{system_prompt}

CONVERSATION HISTORY:
{history_text}

CURRENT SCENARIO:
{scenario}

{player_role['name']} ({player_role['role']}) CONSULTS THE {committee['name'].upper()}:
{user_input}

Provide the committee's collective response, incorporating perspectives from:
- Chairperson {committee['chairperson']}'s leadership view
- Key insights from committee members

Be concise but comprehensive. Offer actionable recommendations aligned with the committee's purpose.
Address {player_role['name']} directly."""

    return _call_llm(llm, full_prompt)


def calculate_metric_impacts(llm: genai.GenerativeModel, company_data: Dict,
                              scenario: str, decision: str, score: int) -> Dict:
    """Calculate the impact of a decision on company metrics."""
    metrics = company_data['metrics']

    metrics_context = "\n".join([
        f"- {metrics[key]['description']}: {metrics[key]['value']} {metrics[key]['unit']} (Priority: {metrics[key].get('priority', 'Normal')})"
        for key in metrics.keys()
    ])

    impact_prompt = f"""You are a business analyst evaluating the impact of a board decision on company metrics.

COMPANY: {company_data['company_name']}

CURRENT METRICS:
{metrics_context}

SCENARIO:
{scenario}

DECISION MADE:
{decision}

DECISION QUALITY SCORE: {score}/100

Based on this decision, analyze the realistic impact on company metrics. Consider:
1. Direct impacts from the decision
2. Indirect/ripple effects
3. Short-term vs long-term implications
4. The quality of the decision (score: {score})

Provide metric impacts in this EXACT format (use these exact metric keys):
METRIC_IMPACTS:
- total_revenue_annual: [change as number, e.g., +5 or -3 or 0] | [brief reason]
- ebitda: [change as number] | [brief reason]
- net_profit_margin: [change as decimal, e.g., +0.5 or -0.2] | [brief reason]
- platform_uptime: [change as decimal] | [brief reason]
- net_promoter_score: [change as number] | [brief reason]
- customer_churn_rate_annual: [change as decimal] | [brief reason]
- employee_engagement_score: [change as number] | [brief reason]
- annual_attrition_rate: [change as decimal] | [brief reason]
- regulatory_compliance_score: [change as number] | [brief reason]
- open_high_severity_risks: [change as number] | [brief reason]
- deployment_frequency: [change as number] | [brief reason]
- revenue_growth_yoy: [change as decimal] | [brief reason]

IMPACT_SUMMARY: [2-3 sentence summary of overall business impact]

Be realistic - not every decision affects all metrics. Use 0 for unaffected metrics.
Good decisions (score > 70) should generally have positive impacts.
Poor decisions (score < 50) should have negative impacts."""

    content = _call_llm(llm, impact_prompt)

    impacts = {}
    reasons = {}

    if "METRIC_IMPACTS:" in content:
        try:
            impacts_section = content.split("METRIC_IMPACTS:")[1]
            if "IMPACT_SUMMARY:" in impacts_section:
                impacts_section = impacts_section.split("IMPACT_SUMMARY:")[0]

            for line in impacts_section.strip().split("\n"):
                line = line.strip()
                if line.startswith("-") and ":" in line and "|" in line:
                    parts = line[1:].strip().split(":", 1)
                    if len(parts) == 2:
                        metric_key = parts[0].strip()
                        value_reason = parts[1].strip().split("|")
                        if len(value_reason) >= 2:
                            try:
                                change_str = value_reason[0].strip().replace("+", "")
                                change = float(change_str)
                                reason = value_reason[1].strip()
                                impacts[metric_key] = change
                                reasons[metric_key] = reason
                            except ValueError:
                                pass
        except Exception:
            pass

    impact_summary = ""
    if "IMPACT_SUMMARY:" in content:
        try:
            impact_summary = content.split("IMPACT_SUMMARY:")[1].strip().split("\n")[0]
        except Exception:
            pass

    return {
        "impacts": impacts,
        "reasons": reasons,
        "summary": impact_summary
    }


def apply_metric_impacts(metrics: Dict, impacts: Dict) -> Dict:
    """Apply calculated impacts to metrics and return updated metrics."""
    updated_metrics = {}

    for key, metric in metrics.items():
        updated_metrics[key] = metric.copy()
        if key in impacts:
            change = impacts[key]
            old_value = metric['value']
            new_value = old_value + change

            unit = metric.get('unit', '')
            if unit == '%':
                new_value = max(0, min(100, new_value))
            elif unit in ('count', 'employees'):
                new_value = max(0, int(new_value))
            elif isinstance(new_value, float):
                new_value = max(0, round(new_value, 1))

            updated_metrics[key]['value'] = new_value
            updated_metrics[key]['previous_value'] = old_value
            updated_metrics[key]['change'] = change

    return updated_metrics


def evaluate_decision(llm: genai.GenerativeModel, company_data: Dict,
                      module_data: Dict, scenario: str,
                      decision: str, round_config: Dict,
                      player_role: Dict) -> Dict:
    """Evaluate user's decision and provide feedback."""
    evaluation_prompt = f"""You are a STRICT and RIGOROUS corporate governance evaluator. Your role is to provide HONEST, ACCURATE assessments.
DO NOT give undeserved praise. If a decision is poor, say so clearly. Be direct about mistakes and their consequences.

COMPANY CONTEXT:
{company_data['company_name']}
{company_data['company_overview']}

PLAYER'S ROLE: {player_role['name']} - {player_role['role']}
Player's Expertise: {player_role['expertise']}

MODULE: {module_data['module_name']}
Learning Objectives:
{chr(10).join(f"- {obj}" for obj in module_data['learning_objectives'])}

RELEVANT TOPICS:
{chr(10).join(f"- {topic['name']}: {topic['description']}" for topic in module_data['topics'][:5])}

SCENARIO PRESENTED:
{scenario}

PLAYER'S DECISION:
{decision}

DIFFICULTY: {round_config['difficulty']}

SCORING GUIDELINES (BE STRICT):
- 90-100: Exceptional - Decision demonstrates expert-level governance understanding, considers all stakeholders perfectly, and aligns with best practices
- 75-89: Good - Solid decision with minor oversights, mostly correct approach
- 60-74: Adequate - Decision has merit but misses important considerations
- 40-59: Below Average - Decision shows significant gaps in understanding or poor judgment
- 20-39: Poor - Decision fails to address key issues, may harm stakeholders
- 0-19: Very Poor - Decision is fundamentally flawed, shows lack of basic governance understanding

CRITICAL EVALUATION CRITERIA:
1. Does the decision actually solve the problem presented?
2. Are there obvious negative consequences the player ignored?
3. Does the decision violate any governance principles or laws?
4. Were stakeholder interests properly balanced?
5. Is the decision appropriate for the player's role as {player_role['role']}?

Provide your evaluation in this EXACT format:
SCORE: [0-100] (Be HONEST - if decision is poor, give a low score)

SCORE_REASONING: [Explain SPECIFICALLY why you gave this score. Be critical where warranted:
- Governance Understanding (0-25 pts): [points earned] - [what was right/wrong]
- Legal/Regulatory Compliance (0-20 pts): [points earned] - [what was right/wrong]
- Stakeholder Consideration (0-20 pts): [points earned] - [who was helped/harmed]
- Strategic Thinking (0-20 pts): [points earned] - [strengths/weaknesses in approach]
- Role Alignment (0-15 pts): [points earned] - [appropriate for their position?]]

STRENGTHS: [What was done well - if little was done well, say "Limited strengths identified" and explain why]

AREAS_FOR_IMPROVEMENT: [What went wrong - be SPECIFIC and CRITICAL about mistakes. List 3-5 issues if the decision was poor]

KEY_LEARNING_POINTS: [What the player should have known/applied from the module - 2-4 points]

BEST_APPROACH: [Describe in detail what the CORRECT decision would have been:
- The recommended action (be specific)
- Why this approach is superior to what the player chose
- Key considerations the player missed
- How it aligns with corporate governance best practices
- Expected outcomes if done correctly]

CRITICAL_FEEDBACK: [If score < 60, explain clearly what went WRONG and the potential negative consequences of this decision. Be direct but educational.]

ENCOURAGEMENT: [ONLY if score >= 60, provide encouraging feedback. If score < 60, instead provide constructive guidance on how to improve.]"""

    content = _call_llm(llm, evaluation_prompt)

    # Extract score
    score = 50
    if "SCORE:" in content:
        try:
            score_line = content.split("SCORE:")[1].split("\n")[0]
            score = int(''.join(filter(str.isdigit, score_line[:10])))
        except Exception:
            pass
    score = min(100, max(0, score))

    # Extract score reasoning
    score_reasoning = ""
    if "SCORE_REASONING:" in content:
        try:
            reasoning_section = content.split("SCORE_REASONING:")[1]
            for marker in ["STRENGTHS:", "AREAS_FOR_IMPROVEMENT:", "KEY_LEARNING_POINTS:"]:
                if marker in reasoning_section:
                    reasoning_section = reasoning_section.split(marker)[0]
                    break
            score_reasoning = reasoning_section.strip()
        except Exception:
            pass

    # Extract strengths
    strengths = ""
    if "STRENGTHS:" in content:
        try:
            strengths_section = content.split("STRENGTHS:")[1]
            for marker in ["AREAS_FOR_IMPROVEMENT:", "KEY_LEARNING_POINTS:", "BEST_APPROACH:"]:
                if marker in strengths_section:
                    strengths_section = strengths_section.split(marker)[0]
                    break
            strengths = strengths_section.strip()
        except Exception:
            pass

    # Extract areas for improvement
    improvements = ""
    if "AREAS_FOR_IMPROVEMENT:" in content:
        try:
            improvements_section = content.split("AREAS_FOR_IMPROVEMENT:")[1]
            for marker in ["KEY_LEARNING_POINTS:", "BEST_APPROACH:", "ENCOURAGEMENT:"]:
                if marker in improvements_section:
                    improvements_section = improvements_section.split(marker)[0]
                    break
            improvements = improvements_section.strip()
        except Exception:
            pass

    # Extract key learning points
    learning_points = ""
    if "KEY_LEARNING_POINTS:" in content:
        try:
            learning_section = content.split("KEY_LEARNING_POINTS:")[1]
            for marker in ["BEST_APPROACH:", "ENCOURAGEMENT:", "RECOMMENDED_APPROACH:"]:
                if marker in learning_section:
                    learning_section = learning_section.split(marker)[0]
                    break
            learning_points = learning_section.strip()
        except Exception:
            pass

    # Extract best approach
    best_approach = ""
    if "BEST_APPROACH:" in content:
        try:
            best_section = content.split("BEST_APPROACH:")[1]
            if "ENCOURAGEMENT:" in best_section:
                best_section = best_section.split("ENCOURAGEMENT:")[0]
            best_approach = best_section.strip()
        except Exception:
            pass

    # Extract critical feedback
    critical_feedback = ""
    if "CRITICAL_FEEDBACK:" in content:
        try:
            critical_section = content.split("CRITICAL_FEEDBACK:")[1]
            if "ENCOURAGEMENT:" in critical_section:
                critical_section = critical_section.split("ENCOURAGEMENT:")[0]
            critical_feedback = critical_section.strip()
        except Exception:
            pass

    # Extract encouragement
    encouragement = ""
    if "ENCOURAGEMENT:" in content:
        try:
            encouragement = content.split("ENCOURAGEMENT:")[1].strip()
        except Exception:
            pass

    # Calculate metric impacts
    metric_impacts = calculate_metric_impacts(llm, company_data, scenario, decision, score)

    return {
        "score": score,
        "feedback": content,
        "score_reasoning": score_reasoning,
        "strengths": strengths,
        "improvements": improvements,
        "learning_points": learning_points,
        "best_approach": best_approach,
        "critical_feedback": critical_feedback,
        "encouragement": encouragement,
        "decision": decision,
        "scenario": scenario,
        "metric_impacts": metric_impacts
    }


def generate_member_stances(llm: genai.GenerativeModel, company_data: Dict,
                             module_data: Dict, scenario: str,
                             player_decision: str, player_role: Dict) -> Dict[str, Dict]:
    """Generate each board member's stance on the player's decision."""
    logger.debug(f"generate_member_stances called with {len(company_data.get('board_members', []))} board members")

    stances = {}
    available_members = [m for m in company_data['board_members']
                         if m['name'] != player_role['name']]

    logger.debug(f"Processing {len(available_members)} available members (excluding player)")

    for member in available_members:
        logger.debug(f"Generating stance for {member['name']}")
        prompt = get_member_stance_prompt(member, company_data, module_data,
                                          scenario, player_decision, player_role)

        try:
            content = _call_llm(llm, prompt)
            logger.debug(f"Got response for {member['name']}, length: {len(content)}")
        except Exception as e:
            logger.error(f"Error getting stance for {member['name']}: {e}")
            content = "STANCE: NEUTRAL\nCONVICTION_LEVEL: 5\nREACTION: Unable to evaluate.\nCOUNTER_OPINION: N/A"

        # Parse response
        stance = "NEUTRAL"
        conviction = 5
        relevance = ""
        reaction = ""
        counter_opinion = None

        if "STANCE:" in content:
            stance_line = content.split("STANCE:")[1].split("\n")[0].strip().upper()
            if "APPROVE" in stance_line:
                stance = "APPROVE"
            elif "OPPOSE" in stance_line:
                stance = "OPPOSE"
            else:
                stance = "NEUTRAL"

        if "CONVICTION_LEVEL:" in content:
            try:
                conv_str = content.split("CONVICTION_LEVEL:")[1].split("\n")[0].strip()
                conviction = int(''.join(filter(str.isdigit, conv_str[:3])))
                conviction = max(1, min(10, conviction))
            except Exception:
                conviction = 5

        if "EXPERTISE_RELEVANCE:" in content:
            try:
                relevance = content.split("EXPERTISE_RELEVANCE:")[1].split("REACTION:")[0].strip()
            except Exception:
                pass

        if "REACTION:" in content:
            try:
                reaction = content.split("REACTION:")[1].split("COUNTER_OPINION:")[0].strip()
            except Exception:
                pass

        if "COUNTER_OPINION:" in content and stance == "OPPOSE":
            try:
                counter_opinion = content.split("COUNTER_OPINION:")[1].strip()
                if counter_opinion.upper().startswith("N/A"):
                    counter_opinion = None
            except Exception:
                pass

        stances[member['name']] = {
            'member_name': member['name'],
            'member_role': member['role'],
            'member_expertise': member['expertise'],
            'stance': stance,
            'initial_reaction': reaction,
            'counter_opinion': counter_opinion,
            'expertise_relevance': relevance,
            'conviction_level': conviction,
            'convinced_in_round': None,
            'debate_exchanges': 0
        }
        logger.debug(f"Member {member['name']} stance: {stance}, conviction: {conviction}")

    logger.debug(f"Generated stances for {len(stances)} members")
    return stances


def evaluate_debate_response(llm: genai.GenerativeModel, member: Dict,
                              company_data: Dict, original_counter: str,
                              player_response: str, debate_history: List[Dict],
                              player_role: Dict) -> Dict:
    """Evaluate player's response to a dissenter and determine if stance changes."""
    prompt = get_debate_evaluation_prompt(member, company_data, original_counter,
                                           player_response, debate_history, player_role)

    content = _call_llm(llm, prompt)

    evaluation = ""
    score = 50
    stance_changed = False
    follow_up = ""

    if "EVALUATION:" in content:
        try:
            evaluation = content.split("EVALUATION:")[1].split("RESPONSE_SCORE:")[0].strip()
        except Exception:
            pass

    if "RESPONSE_SCORE:" in content:
        try:
            score_str = content.split("RESPONSE_SCORE:")[1].split("\n")[0].strip()
            score = int(''.join(filter(str.isdigit, score_str[:3])))
            score = max(0, min(100, score))
        except Exception:
            score = 50

    if "STANCE_CHANGED:" in content:
        stance_line = content.split("STANCE_CHANGED:")[1].split("\n")[0].strip().upper()
        stance_changed = "YES" in stance_line

    if "FOLLOW_UP:" in content:
        try:
            follow_up = content.split("FOLLOW_UP:")[1].strip()
        except Exception:
            pass

    return {
        'evaluation': evaluation,
        'score': score,
        'stance_changed': stance_changed,
        'follow_up': follow_up
    }


def evaluate_consultation_alignment(llm: genai.GenerativeModel, consultations: List[Dict],
                                     player_decision: str, member_stances: Dict) -> Dict:
    """Evaluate how well player's consultations aligned with their decision."""
    prompt = get_consultation_alignment_prompt(consultations, player_decision, member_stances)

    content = _call_llm(llm, prompt)

    alignment_score = 50
    reasoning = ""

    if "ALIGNMENT_SCORE:" in content:
        try:
            score_str = content.split("ALIGNMENT_SCORE:")[1].split("\n")[0].strip()
            alignment_score = int(''.join(filter(str.isdigit, score_str[:3])))
            alignment_score = max(0, min(100, alignment_score))
        except Exception:
            alignment_score = 50

    if "REASONING:" in content:
        try:
            reasoning = content.split("REASONING:")[1].strip()
        except Exception:
            pass

    return {
        'alignment_score': alignment_score,
        'reasoning': reasoning
    }


def parse_scenario_options(scenario: str) -> List[Dict]:
    """Parse options from scenario text."""
    options = []
    lines = scenario.split('\n')

    current_option = None
    for line in lines:
        line = line.strip()
        for letter in ['A', 'B', 'C', 'D']:
            if line.startswith(f"{letter})") or line.startswith(f"{letter}."):
                if current_option:
                    options.append(current_option)
                option_text = line[2:].strip()
                current_option = {"letter": letter, "text": option_text}
                break

    if current_option:
        options.append(current_option)

    return options
