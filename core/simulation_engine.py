"""
LLM-driven simulation operations — scenario generation, board responses,
decision evaluation, stance generation, debate evaluation.
"""

import logging
import time
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


def generate_scenario(llm: object, company_data: Dict,
                      module_data: Dict, round_config: Dict, player_role: Dict,
                      previous_rounds: List[Dict] = None) -> str:
    """Generate a new scenario for the current round."""
    prompt = get_scenario_generator_prompt(company_data, module_data, round_config, player_role,
                                           previous_rounds=previous_rounds)
    full_prompt = f"""You are an expert corporate governance simulation designer.

{prompt}"""
    return _call_llm(llm, full_prompt)


def get_board_member_response(llm: object, members: List[Dict],
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


def get_committee_response(llm: object, committee: Dict,
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


# Unit-conversion table for canonicalizing LLM-returned units to the metric's stored unit.
# Ratio = (returned_unit_factor / stored_unit_factor). E.g. if metric stored as $M and
# LLM returns $B, multiply change by 1000 to convert.
_UNIT_SCALE_FACTORS = {
    # Currency / scale (relative to base 1)
    'B': 1_000_000_000, '$B': 1_000_000_000, '₹B': 1_000_000_000, '€B': 1_000_000_000, '£B': 1_000_000_000,
    'M': 1_000_000, '$M': 1_000_000, '₹M': 1_000_000, '€M': 1_000_000, '£M': 1_000_000,
    'K': 1_000, '$K': 1_000, '₹K': 1_000, '€K': 1_000, '£K': 1_000,
    'Cr': 10_000_000, '₹Cr': 10_000_000,    # 1 crore = 10M
    'L':  100_000,    '₹L':  100_000,        # 1 lakh = 100K
    'TB': 1_000_000_000_000, 'GB': 1_000_000_000, 'MB': 1_000_000,
}


def _convert_unit(change: float, returned_unit: str, stored_unit: str) -> float:
    """Convert a numeric change from returned_unit scale to stored_unit scale.

    If units match (or either is empty/non-scale), return change unchanged.
    If both are in _UNIT_SCALE_FACTORS, scale by ratio. Otherwise return as-is.
    """
    if not returned_unit or not stored_unit:
        return change
    r, s = returned_unit.strip(), stored_unit.strip()
    if r == s:
        return change
    rf = _UNIT_SCALE_FACTORS.get(r)
    sf = _UNIT_SCALE_FACTORS.get(s)
    if rf is None or sf is None:
        return change
    try:
        return change * (rf / sf)
    except (TypeError, ZeroDivisionError):
        return change


def calculate_metric_impacts(llm: object, company_data: Dict,
                              scenario: str, decision: str, score: int) -> Dict:
    """Calculate the impact of a decision on company metrics.

    Each requested impact has an explicit unit field that MUST match the metric's
    stored unit. Mismatched units are auto-converted server-side; non-numeric
    (categorical) metrics are excluded from the request and ignored if returned.
    """
    metrics = company_data['metrics']

    # Exclude categorical metrics from impact prediction — they have no numeric semantics
    numeric_keys = [
        k for k, v in metrics.items()
        if not v.get('categorical_value') and not v.get('non_numeric')
    ]

    metrics_context = "\n".join([
        f"- {key}: {metrics[key].get('description', key)} = "
        f"{metrics[key].get('value', 0)} {metrics[key].get('unit', '')} "
        f"(Priority: {metrics[key].get('priority') or 'Normal'})"
        for key in numeric_keys
    ])

    # Format requires explicit unit field. The unit MUST match the metric's stored unit.
    metric_keys_format = "\n".join([
        f'- {key}: <change_in_same_unit_as_above> {metrics[key].get("unit", "")} | <brief_reason>'
        for key in numeric_keys
    ])

    impact_prompt = f"""You are a business analyst evaluating the impact of a board decision on company metrics.

COMPANY: {company_data['company_name']}

CURRENT METRICS (the unit shown for each metric is the canonical unit — your impact MUST be in this same unit):
{metrics_context}

SCENARIO:
{scenario}

DECISION MADE (model impacts for THIS decision ONLY — do not reference or assume any other option was chosen):
<<<
{decision}
>>>

Based on this exact decision, analyze the realistic impact on company metrics. Consider:
1. Direct impacts from the decision
2. Indirect/ripple effects
3. Short-term vs long-term implications
4. Whether the decision actually addresses the scenario's core problem

UNIT DISCIPLINE — CRITICAL:
For EACH metric below, the change MUST be expressed in the EXACT same unit as the metric's current value.
- If the metric is "1200 $M" (1.2 billion in millions), a 5% drop is "-60 $M" — NOT "-0.06 $B" and NOT "-100".
- If the metric is "72 %", a 3-point drop is "-3 %" — NOT "-0.03" and NOT "-3.0%".
- If the metric is "8 count", a +1 incident is "1 count" — NOT "1.0" and NOT "+1 incidents".
- A change of 0 is fine (and expected) for metrics the decision does not affect.
- Changes larger than 10% of the metric's current value are RARE — require strong justification.

Provide metric impacts in this EXACT format (one line per metric, use these EXACT keys and units):
METRIC_IMPACTS:
{metric_keys_format}

IMPACT_SUMMARY: [2-3 sentence summary of overall business impact]

Be realistic — not every decision affects all metrics. Use 0 for unaffected metrics.
A decision can have mixed impacts: positive on some metrics, negative on others.
Focus on logical consequences of the decision, not on whether it seems "good" or "bad" overall."""

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
                if not (line.startswith("-") and ":" in line and "|" in line):
                    continue
                parts = line[1:].strip().split(":", 1)
                if len(parts) != 2:
                    continue
                metric_key = parts[0].strip()
                # Skip metrics not in the canonical numeric set (defends against LLM hallucinated keys)
                if metric_key not in numeric_keys:
                    continue
                value_reason = parts[1].strip().split("|", 1)
                if len(value_reason) < 2:
                    continue
                value_part = value_reason[0].strip()
                reason = value_reason[1].strip()

                # Parse "<number> <unit>" — unit token is whatever follows the first numeric token
                tokens = value_part.replace("+", "").split(None, 1)
                if not tokens:
                    continue
                try:
                    change = float(tokens[0])
                except ValueError:
                    continue
                returned_unit = tokens[1].strip() if len(tokens) > 1 else ""
                stored_unit = (metrics[metric_key].get('unit') or '').strip()

                # Server-side unit reconciliation — convert if LLM used a different scale
                converted = _convert_unit(change, returned_unit, stored_unit)
                if converted != change:
                    logger.warning(
                        "Metric %s: LLM returned %s %s, converted to %s %s (canonical)",
                        metric_key, change, returned_unit, converted, stored_unit
                    )
                    change = converted

                # Sanity guard against grossly oversized changes (catches lingering hallucinations)
                stored_val = metrics[metric_key].get('value')
                try:
                    stored_val_f = float(stored_val) if stored_val is not None else 0.0
                except (TypeError, ValueError):
                    stored_val_f = 0.0
                # If the absolute change exceeds 50% of the current value AND the metric is non-zero,
                # clamp to ±50% — apply_metric_impacts will further clamp via its per-round caps.
                if stored_val_f != 0 and abs(change) > abs(stored_val_f) * 0.5:
                    clamped = (abs(stored_val_f) * 0.5) * (1 if change > 0 else -1)
                    logger.warning(
                        "Metric %s: change %s exceeds 50%% of current %s — clamped to %s",
                        metric_key, change, stored_val_f, clamped
                    )
                    change = clamped

                impacts[metric_key] = change
                reasons[metric_key] = reason
        except Exception:
            logger.exception("Failed to parse METRIC_IMPACTS section")

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
    import datetime
    CURRENT_YEAR = datetime.datetime.now().year

    # Per-round change caps to prevent unrealistic single-round swings
    MAX_CHANGE = {
        '%': 3.0,           # percentage metrics: max 3pp per round (tightened from 5)
        'count': 3,         # count metrics (risks, etc.): max 3 per round
        'employees': 50,    # headcount: max 50 per round
        'units': 50,        # unit-count metrics (e.g. property sales): max 50 per round
        'year': 2,          # year metrics (e.g. IPO date): max 2 years shift per round
    }
    MAX_REVENUE_PCT = 0.05  # revenue/currency metrics: max 5% of current value per round

    updated_metrics = {}

    for key, metric in metrics.items():
        updated_metrics[key] = metric.copy()
        if key in impacts:
            try:
                change = float(impacts[key])
            except (TypeError, ValueError):
                continue
            raw_old = metric.get('value')
            try:
                old_value = float(raw_old) if raw_old is not None else 0
            except (TypeError, ValueError):
                old_value = 0
            unit = (metric.get('unit') or '').strip()

            # Clamp change to per-round caps
            if unit in MAX_CHANGE:
                cap = MAX_CHANGE[unit]
                change = max(-cap, min(cap, change))
            elif old_value != 0:
                # Currency/large-number metrics: cap at 5% of current value
                cap = abs(old_value) * MAX_REVENUE_PCT
                change = max(-cap, min(cap, change))

            new_value = old_value + change

            # Type-based bounds
            if unit == '%':
                # Also prevent dropping below 30% of starting value in one round
                floor = max(0, old_value * 0.5)
                new_value = max(floor, min(100, new_value))
            elif unit == 'year':
                # Year metrics (e.g. IPO date) cannot go into the past
                new_value = max(CURRENT_YEAR, round(new_value))
            elif unit in ('count', 'employees', 'units'):
                new_value = max(0, int(new_value))
            elif isinstance(new_value, float):
                new_value = max(0, round(new_value, 1))

            updated_metrics[key]['value'] = new_value
            updated_metrics[key]['previous_value'] = old_value
            updated_metrics[key]['change'] = change

    return updated_metrics


def evaluate_decision(llm: object, company_data: Dict,
                      module_data: Dict, scenario: str,
                      decision: str, round_config: Dict,
                      player_role: Dict) -> Dict:
    """Evaluate user's decision and provide feedback.

    Includes a Module Vocabulary sub-tracker that scores explicit invocation of the
    module's key_terms — making M6/Ind-AS pedagogy visible and rewarded independently
    of board persuasion outcomes.
    """
    # Build the module vocabulary block — leverages key_terms extracted by Agent 1 (PDF
    # glossary recovery) and ensured-present by Agent 2 (audit's Phase 3 generation).
    key_terms = module_data.get('key_terms', {}) or {}
    if isinstance(key_terms, dict) and key_terms:
        # Include up to 25 terms to keep prompt size bounded
        term_lines = "\n".join(
            f"  - {term}: {definition}" for term, definition in list(key_terms.items())[:25]
        )
        vocabulary_block = (
            "MODULE VOCABULARY (the canonical concepts this round tests — invoke these by name in the decision):\n"
            f"{term_lines}\n"
        )
    else:
        vocabulary_block = ""

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

{vocabulary_block}
SCENARIO PRESENTED:
{scenario}

PLAYER'S EXACT DECISION (evaluate THIS decision ONLY — do not reference, compare, or assume any other option was chosen):
<<<
{decision}
>>>

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
6. Did the decision invoke the module's canonical vocabulary (above) — by name or correct paraphrase?

DIMENSION DEFINITIONS (apply these consistently — do NOT inflate or deflate based on round number):

Governance Understanding (25): Knowledge of fiduciary duties, board procedures, audit/risk oversight,
disclosure standards, and corporate governance frameworks. Reward correct application; deduct only
for clear violations or misunderstandings.

Legal & Regulatory Compliance (20): Adherence to relevant laws (Companies Act, Ind AS, sector
regulators). Reward awareness of compliance constraints; deduct for actual violations or willful blind spots.

Stakeholder Consideration (20): Balance across investors, employees, customers, regulators, public.
Reward EITHER named-stakeholder analysis OR systematic framework that implicitly covers them.

Strategic Thinking (20): How well the decision integrates BOTH (a) operational/financial depth in
the player's domain AND (b) broader context (legal/regulatory/reputational/competitive). NEITHER axis
alone earns full marks — full marks require integration. Specifically reward responses that include
forward-looking risk mitigation, multi-stakeholder framing, AND multi-tier communication strategy
(institutional vs retail). Operational depth is NOT a deduction; lack of strategic breadth IS.

Role Alignment (15): Decision is appropriate for the player's role ({player_role['role']}). Reward:
implementation depth framed as governance pathway ("subject to board approval", "with Audit
Committee oversight", "pending CEO sign-off") because these stay within role mandate. Do NOT penalise
cross-disciplinary thinking that LENS-OF-OWN-ROLE — e.g. CFO speaking to strategic implications via
financial analysis is in-role; CFO unilaterally announcing PR strategy is overreach. Only penalise
unambiguous unilateral overreach into another C-suite domain.

Provide your evaluation in this EXACT format:
SCORE: [0-100] (Be HONEST - if decision is poor, give a low score)

SCORE_REASONING: [Explain SPECIFICALLY why you gave this score. Show points as X/MAX. Be critical where warranted:
- Governance Understanding: [points]/25 - [what was right/wrong]
- Legal/Regulatory Compliance: [points]/20 - [what was right/wrong]
- Stakeholder Consideration: [points]/20 - [who was helped/harmed]
- Strategic Thinking: [points]/20 - [integration of operational depth AND broader context — see definition above]
- Role Alignment: [points]/15 - [in-role with governance pathway? OR unilateral cross-domain overreach? — see definition above]
Total: [sum]/100]

MODULE_VOCABULARY_SCORE: [0-100] (Independent of the main score — purely measures application of MODULE VOCABULARY above. 100 = invoked all relevant terms by name with correct usage; 0 = no module vocabulary visible. Penalize misuse: e.g. if module forbids a term and the player used it.)

VOCABULARY_INVOKED: [Comma-separated list of vocabulary terms (from MODULE VOCABULARY above) that the decision INVOKED CORRECTLY — by name or unambiguous paraphrase. Empty list "[]" if none.]

VOCABULARY_MISSED: [Comma-separated list of vocabulary terms that were RELEVANT to this scenario but the decision DID NOT invoke. Empty list "[]" if all relevant terms were used or vocabulary is empty.]

VOCABULARY_MISUSED: [Comma-separated list of terms the decision used INCORRECTLY (e.g. used "extraordinary item" when Ind AS forbids it). Empty list "[]" if none.]

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

    # Extract Module Vocabulary fields (P1-5/P1-6 — independent M6-correctness axis)
    def _extract_section(label: str, stop_markers: List[str]) -> str:
        if label not in content:
            return ""
        try:
            section = content.split(label, 1)[1]
            for marker in stop_markers:
                if marker in section:
                    section = section.split(marker, 1)[0]
                    break
            return section.strip()
        except Exception:
            return ""

    def _parse_term_list(raw: str) -> List[str]:
        """Parse a comma-separated term list like 'Term A, Term B' or '[Term A, Term B]'."""
        if not raw:
            return []
        raw = raw.strip().strip('[]').strip()
        if not raw or raw.lower() in ('none', 'n/a', 'empty', '[]'):
            return []
        return [t.strip() for t in raw.split(',') if t.strip()]

    vocab_score_raw = _extract_section(
        "MODULE_VOCABULARY_SCORE:",
        ["VOCABULARY_INVOKED:", "VOCABULARY_MISSED:", "STRENGTHS:"]
    )
    try:
        vocabulary_score = int(''.join(filter(str.isdigit, vocab_score_raw[:10]))) if vocab_score_raw else 0
        vocabulary_score = min(100, max(0, vocabulary_score))
    except (ValueError, TypeError):
        vocabulary_score = 0

    vocabulary_invoked = _parse_term_list(_extract_section(
        "VOCABULARY_INVOKED:",
        ["VOCABULARY_MISSED:", "VOCABULARY_MISUSED:", "STRENGTHS:"]
    ))
    vocabulary_missed = _parse_term_list(_extract_section(
        "VOCABULARY_MISSED:",
        ["VOCABULARY_MISUSED:", "STRENGTHS:"]
    ))
    vocabulary_misused = _parse_term_list(_extract_section(
        "VOCABULARY_MISUSED:", ["STRENGTHS:"]
    ))

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
        "metric_impacts": metric_impacts,
        # Module Application axis (P1-5, P1-6) — independent of board persuasion
        "vocabulary_score": vocabulary_score,
        "vocabulary_invoked": vocabulary_invoked,
        "vocabulary_missed": vocabulary_missed,
        "vocabulary_misused": vocabulary_misused,
    }


def generate_member_stances(llm: object, company_data: Dict,
                             module_data: Dict, scenario: str,
                             player_decision: str, player_role: Dict,
                             all_member_histories: Dict = None) -> Dict[str, Dict]:
    """Generate each board member's stance on the player's decision."""
    logger.debug(f"generate_member_stances called with {len(company_data.get('board_members', []))} board members")

    stances = {}
    available_members = [m for m in company_data['board_members']
                         if m['name'] != player_role['name']]

    logger.debug(f"Processing {len(available_members)} available members (excluding player)")

    for member in available_members:
        logger.debug(f"Generating stance for {member['name']}")
        member_history = (all_member_histories or {}).get(member['name'])
        prompt = get_member_stance_prompt(member, company_data, module_data,
                                          scenario, player_decision, player_role,
                                          member_history=member_history)

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

        # Semantic guard: OPPOSE without a substantive counter_opinion is contradictory — downgrade
        if stance == "OPPOSE" and not counter_opinion:
            stance = "NEUTRAL"
            logger.debug(f"Downgraded {member['name']} from OPPOSE to NEUTRAL (no counter_opinion)")

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


def evaluate_debate_response(llm: object, member: Dict,
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

    updated_conviction = None
    if "UPDATED_CONVICTION:" in content:
        try:
            conv_str = content.split("UPDATED_CONVICTION:")[1].split("\n")[0].strip()
            updated_conviction = int(''.join(filter(str.isdigit, conv_str[:3])))
            updated_conviction = max(1, min(10, updated_conviction))
        except Exception:
            updated_conviction = None

    if "STANCE_CHANGED:" in content:
        stance_line = content.split("STANCE_CHANGED:")[1].split("\n")[0].strip().upper()
        stance_changed = "YES" in stance_line

    if "FOLLOW_UP:" in content:
        try:
            follow_up = content.split("FOLLOW_UP:")[1].strip()
        except Exception:
            pass

    # If stance changed, conviction should drop to 0
    if stance_changed:
        updated_conviction = 0

    return {
        'evaluation': evaluation,
        'score': score,
        'stance_changed': stance_changed,
        'follow_up': follow_up,
        'updated_conviction': updated_conviction,
    }


def evaluate_consultation_alignment(llm: object, consultations: List[Dict],
                                     player_decision: str, member_stances: Dict) -> Dict:
    """Evaluate how well player's consultations aligned with their decision."""
    user_consultations = [c for c in consultations if c.get('role') == 'user']
    if not user_consultations:
        return {'alignment_score': 50, 'reasoning': 'No consultations were made this round.'}

    prompt = get_consultation_alignment_prompt(consultations, player_decision, member_stances)

    content = _call_llm(llm, prompt)

    alignment_score = 50
    reasoning = ""

    if "ALIGNMENT_SCORE:" in content:
        try:
            score_str = content.split("ALIGNMENT_SCORE:")[1].split("\n")[0].strip()
            digits = ''.join(filter(str.isdigit, score_str))
            alignment_score = int(digits[:3]) if digits else 50
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

    if 0 < len(options) < 4:
        logger.warning(
            f"parse_scenario_options: only {len(options)} option(s) parsed (expected 4). "
            "Scenario may be malformed or LLM did not follow the OPTIONS TO CONSIDER format."
        )

    return options


def parse_scenario_sections(scenario: str) -> Dict:
    """Parse LLM scenario text into structured sections for display.

    Expected LLM format:
        SCENARIO TITLE: ...
        SITUATION: ...
        KEY QUESTION: ...
        STAKEHOLDERS AFFECTED: ...
        TIME SENSITIVITY: ...
        OPTIONS TO CONSIDER: A) ... B) ... C) ... D) ...
    """
    import re

    sections: Dict = {
        'title': '',
        'situation': '',
        'key_question': '',
        'stakeholders': '',
        'time_sensitivity': '',
        'options_text': '',
        'raw': scenario,
    }

    # Section headers the LLM is instructed to produce
    markers = [
        ('SCENARIO TITLE:', 'title'),
        ('SITUATION:', 'situation'),
        ('KEY QUESTION:', 'key_question'),
        ('STAKEHOLDERS AFFECTED:', 'stakeholders'),
        ('TIME SENSITIVITY:', 'time_sensitivity'),
        ('OPTIONS TO CONSIDER:', 'options_text'),
    ]

    # Build regex that splits on any of the markers
    marker_labels = [re.escape(m[0]) for m in markers]
    pattern = '(' + '|'.join(marker_labels) + ')'
    parts = re.split(pattern, scenario, flags=re.IGNORECASE)

    # parts = [preamble, MARKER1, content1, MARKER2, content2, ...]
    i = 1  # skip preamble (usually empty)
    while i < len(parts) - 1:
        header = parts[i].strip().rstrip(':').upper() + ':'
        content = parts[i + 1].strip()
        for marker_text, key in markers:
            if marker_text.upper() == header:
                sections[key] = content
                break
        i += 2

    # If no markers found, treat entire text as situation (graceful fallback)
    if not any(sections[k] for k in ('title', 'situation', 'key_question')):
        sections['situation'] = scenario

    return sections
