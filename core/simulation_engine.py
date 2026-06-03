"""
LLM-driven simulation operations — scenario generation, board responses,
decision evaluation, stance generation, debate evaluation.
"""

import json
import logging
import time
from google.api_core import exceptions as google_exceptions
from google.genai import types as genai_types
from pydantic import ValidationError
from typing import Dict, List, Optional

from core.llm import (
    get_board_member_prompt,
    get_committee_prompt,
    get_member_stance_prompt,
    get_debate_evaluation_prompt,
    get_consultation_alignment_prompt,
    get_scenario_generator_prompt,
)
from core.scenario_schema import ScenarioResponse

logger = logging.getLogger(__name__)

_RETRYABLE_EXCEPTIONS = (
    google_exceptions.ResourceExhausted,
    google_exceptions.ServiceUnavailable,
    google_exceptions.InternalServerError,
    google_exceptions.DeadlineExceeded,
)


def _call_llm(llm, prompt, max_retries=3, config_override: Optional[genai_types.GenerateContentConfig] = None):
    """Call Gemini API with exponential backoff retry on transient errors.

    config_override lets callers (e.g. structured-output scenario generation)
    swap in a per-call config without affecting the model's baseline config.
    """
    for attempt in range(max_retries + 1):
        try:
            if config_override is not None:
                response = llm.generate_content(prompt, config_override=config_override)
            else:
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
                      previous_rounds: List[Dict] = None,
                      max_attempts: int = 3) -> str:
    """Generate a new scenario for the current round.

    Uses Gemini structured output (response_schema=ScenarioResponse) so the
    model emits JSON conforming to the schema — eliminating regex parsing
    failures that previously caused the "got 0 options" production bug.

    The returned value is still the canonical text format (SCENARIO TITLE /
    OPTIONS TO CONSIDER / OPTION X | CALIBRATION: ...) so downstream consumers
    (member-stance prompts, session storage, debug artifacts, the legacy
    parse_scenario_options) continue to work unchanged.

    Retry loop targets the calibration distribution contract (0/2/3+/3+
    opposers), not the format — schema enforcement makes format failures
    impossible. The placeholder synthesizer remains as a defense-in-depth net.
    """
    prompt = get_scenario_generator_prompt(company_data, module_data, round_config, player_role,
                                           previous_rounds=previous_rounds)
    base_prompt = f"""You are an expert corporate governance simulation designer.

{prompt}

OUTPUT FORMAT: Return your response as JSON matching the provided schema. The
schema fields map to the format above as follows: title → SCENARIO TITLE,
situation → SITUATION, key_question → KEY QUESTION, stakeholders → list of
affected parties, time_sensitivity → one of Low / Moderate / High / Urgent,
options → exactly 4 entries with letter / calibration / action / stances /
counters. Every option's stances list must include every non-player board
member exactly once."""

    non_player_count = max(1, sum(
        1 for m in company_data.get('board_members', [])
        if m.get('name') != player_role.get('name')
    ))

    structured_config = genai_types.GenerateContentConfig(
        temperature=0.7,
        max_output_tokens=6144,
        response_mime_type='application/json',
        response_schema=ScenarioResponse,
    )

    last_scenario = ''
    last_errors: List[str] = []
    last_opts: List[Dict] = []
    for attempt in range(max_attempts):
        full_prompt = base_prompt
        if attempt > 0 and last_errors:
            full_prompt += (
                "\n\nPREVIOUS ATTEMPT FAILED CALIBRATION VALIDATION:\n"
                + "\n".join(f"- {e}" for e in last_errors)
                + "\n\nFIX THESE ISSUES. The 4 options' OPPOSE counts MUST be EXACTLY one each of:\n"
                "  - one option with 0 OPPOSE (unanimous)\n"
                "  - one option with 2 OPPOSE (mild_dissent)\n"
                "  - one option with 3 OPPOSE (controversial)\n"
                "  - one option with 4 OPPOSE (highly_controversial; or all non-player members "
                f"if there are fewer than 4)\n"
                "Count your OPPOSE entries before emitting. Do NOT produce two options at the "
                "same calibration tier."
            )

        raw_json = _call_llm(llm, full_prompt, config_override=structured_config)
        try:
            parsed = ScenarioResponse.model_validate_json(raw_json)
        except (ValidationError, ValueError) as e:
            # Schema failure is rare with response_schema enforced, but possible
            # if the API returns malformed JSON. Log and retry.
            logger.warning("generate_scenario attempt %d/%d: schema validation failed: %s",
                           attempt + 1, max_attempts, e)
            last_errors = [f"schema validation: {e}"]
            last_scenario = raw_json or ''
            continue

        last_scenario = _render_scenario_text(parsed)
        last_opts = _scenario_response_to_options(parsed)
        last_errors = validate_option_calibration(last_opts, non_player_count)
        if not last_errors:
            return last_scenario
        logger.warning(
            "generate_scenario attempt %d/%d failed calibration validation: %s",
            attempt + 1, max_attempts, "; ".join(last_errors),
        )

    if last_errors:
        logger.warning(
            "generate_scenario: returning best-effort scenario after %d attempts "
            "(unresolved: %s). Stances will fall back to dynamic generation.",
            max_attempts, "; ".join(last_errors),
        )
        try:
            _dump_scenario_debug(last_scenario, last_opts, last_errors,
                                  round_config, company_data, player_role)
        except Exception:
            logger.exception("Failed to dump scenario debug artifact (non-fatal)")

    # ── FINAL SAFETY NET — guarantee the player always sees 4 options ──
    # With structured output this branch should be unreachable, but keeping it
    # as defense-in-depth in case schema validation fails on every attempt.
    final_opts = parse_scenario_options(last_scenario)
    if len(final_opts) < 4:
        before = len(final_opts)
        padded = _ensure_four_options(list(final_opts), company_data, player_role)
        synthesized = [o for o in padded if o.get('synthesized')]
        logger.warning(
            "generate_scenario: synthesizing %d placeholder option(s) after parsing yielded "
            "only %d. Letters synthesized: %s. Guarantees the player sees 4 options.",
            len(synthesized), before, [o['letter'] for o in synthesized],
        )
        for opt in synthesized:
            last_scenario += _format_option_as_scenario_block(opt)
    return last_scenario


def _render_scenario_text(resp: ScenarioResponse) -> str:
    """Render a structured ScenarioResponse into the canonical text format
    that downstream consumers (member-stance prompts, session storage,
    parse_scenario_options, parse_scenario_sections, debug artifacts) expect.
    """
    parts = [
        f"SCENARIO TITLE: {resp.title}",
        "",
        f"SITUATION:\n{resp.situation}",
        "",
        f"KEY QUESTION:\n{resp.key_question}",
        "",
        f"STAKEHOLDERS AFFECTED:\n{', '.join(resp.stakeholders)}",
        "",
        f"TIME SENSITIVITY:\n{resp.time_sensitivity}",
        "",
        "OPTIONS TO CONSIDER:",
        "",
    ]

    for opt in resp.options:
        stances_line = ', '.join(f"{s.member_name}={s.stance}" for s in opt.stances)
        if opt.counters:
            counters_line = ' | '.join(f"{c.member_name}: {c.objection}" for c in opt.counters)
        else:
            counters_line = '(none)'
        parts.extend([
            f"OPTION {opt.letter} | CALIBRATION: {opt.calibration}",
            f"ACTION: {opt.action}",
            f"STANCES: {stances_line}",
            f"COUNTERS: {counters_line}",
            "",
        ])

    return "\n".join(parts)


def _scenario_response_to_options(resp: ScenarioResponse) -> List[Dict]:
    """Convert a structured ScenarioResponse into the list-of-dicts shape that
    validate_option_calibration and the rest of the codebase expect (matches
    parse_scenario_options output)."""
    out: List[Dict] = []
    for opt in resp.options:
        stance_distribution = {s.member_name: s.stance for s in opt.stances}
        counters = {c.member_name: c.objection for c in opt.counters}
        opposer_count = sum(1 for v in stance_distribution.values() if v == 'OPPOSE')
        derived = _calibration_from_opposers(opposer_count, len(stance_distribution))
        out.append({
            'letter': opt.letter,
            'text': opt.action,
            'calibration': derived or opt.calibration,
            'calibration_label_from_llm': opt.calibration,
            'stance_distribution': stance_distribution,
            'counters': counters,
        })
    return out


def _dump_scenario_debug(scenario: str, parsed_options: List[Dict],
                          errors: List[str], round_config: Dict,
                          company_data: Dict, player_role: Dict) -> None:
    """Persist the raw LLM scenario + parse result + validation errors when
    generate_scenario falls back to best-effort. Files are written to
    `_scenario_debug/` at the project root so they survive across sessions and
    can be reviewed without needing to reproduce the exact failure."""
    import datetime
    import json
    import os

    debug_dir = os.path.join(os.getcwd(), '_scenario_debug')
    try:
        os.makedirs(debug_dir, exist_ok=True)
    except OSError:
        return  # CWD might be read-only; don't crash the game

    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]
    company = (company_data.get('company_name', 'unknown')[:40]
               .replace(' ', '_').replace('/', '_'))
    fname = f"scenario_failure_{stamp}_{company}_r{round_config.get('round_number', '?')}.json"
    path = os.path.join(debug_dir, fname)

    artifact = {
        'timestamp': datetime.datetime.now().isoformat(timespec='seconds'),
        'company': company_data.get('company_name'),
        'round_config': round_config,
        'player_role': player_role,
        'parse_errors': errors,
        'parsed_options_count': len(parsed_options),
        'parsed_options_summary': [
            {
                'letter': o.get('letter'),
                'calibration': o.get('calibration'),
                'calibration_label_from_llm': o.get('calibration_label_from_llm'),
                'opposers': sum(1 for v in (o.get('stance_distribution') or {}).values()
                                if v == 'OPPOSE'),
                'text_chars': len(o.get('text', '')),
                'text_preview': (o.get('text') or '')[:200],
            }
            for o in parsed_options
        ],
        'raw_scenario_chars': len(scenario),
        'raw_scenario': scenario,
    }
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(artifact, f, indent=2, default=str)
        logger.warning("Scenario debug artifact saved: %s", path)
    except Exception:
        logger.exception("Could not write scenario debug artifact to %s", path)


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

    # Exclude categorical metrics from impact prediction — they have no numeric semantics.
    # Also exclude metrics whose stored value is a string (defends against fixtures
    # that don't set the categorical_value/non_numeric flags explicitly — closes J1).
    def _is_categorical(v: Dict) -> bool:
        if v.get('categorical_value') or v.get('non_numeric'):
            return True
        val = v.get('value')
        if isinstance(val, str):
            return True
        return False

    numeric_keys = [k for k, v in metrics.items() if not _is_categorical(v)]

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
2. Indirect/ripple effects (legal, regulatory, reputational, operational)
3. Short-term vs long-term implications
4. Whether the decision actually addresses the scenario's core problem
5. Second-order consequences that materialize within the next reporting cycle

CAUSAL CHAINS YOU MUST MODEL (apply when the decision matches the pattern):

A. DECISIONS THAT CONCEAL, DENY, RETALIATE, OR EVADE REGULATORS/LAW:
   These ALWAYS produce non-zero NEGATIVE impacts on:
   - any metric containing fine/penalty/sanction/lawsuit/litigation (INCREASE — worse)
   - any metric containing compliance/disclosure score (DECREASE — worse)
   - any metric containing reputation/sentiment/trust (DECREASE — worse)
   - any metric containing employee engagement/retention (DECREASE — whistleblower chill effect)
   You may NOT return all zeros for these decisions. At minimum 3 metrics must move.

B. DECISIONS THAT INVESTIGATE / SURFACE A KNOWN PROBLEM:
   Do NOT penalize the metric being investigated. Surfacing a compliance gap that
   ALREADY EXISTS is not the same as causing it. The metric reflects underlying
   reality, not the act of measurement. Score these as NEUTRAL or POSITIVE on
   the surfaced metric, with positive impact on long-term risk reduction.

C. DECISIONS THAT DEFER / DELAY ON URGENT MATTERS:
   Apply moderate NEGATIVE drift on revenue/customer/operational metrics (lost
   opportunity cost) AND on the metric most directly tied to the deferred issue.
   Do NOT return all zeros — "no decision" is itself a decision with consequences.

D. DECISIONS THAT PROACTIVELY DISCLOSE / REMEDIATE / COMPLY:
   Short-term: small negative on revenue / share price (market reaction).
   Long-term: positive on compliance score, reduced fine/lawsuit exposure,
   improved employee engagement and stakeholder trust.

UNIT DISCIPLINE — CRITICAL:
For EACH metric below, the change MUST be expressed in the EXACT same unit as the metric's current value.
- If the metric is "1200 $M" (1.2 billion in millions), a 5% drop is "-60 $M" — NOT "-0.06 $B" and NOT "-100".
- If the metric is "72 %", a 3-point drop is "-3 %" — NOT "-0.03" and NOT "-3.0%".
- If the metric is "8 count", a +1 incident is "1 count" — NOT "1.0" and NOT "+1 incidents".
- Changes larger than 10% of the metric's current value are RARE — require strong justification.

Provide metric impacts in this EXACT format (one line per metric, use these EXACT keys and units):
METRIC_IMPACTS:
{metric_keys_format}

IMPACT_SUMMARY: [2-3 sentence summary of overall business impact, including any
legal/regulatory/reputational consequences the decision triggers]

A decision can have mixed impacts: positive on some metrics, negative on others.
Use 0 ONLY for metrics with no plausible causal connection to the decision —
NOT as a default for metrics you find hard to reason about. If the decision is
clearly harmful (per causal chain A or C above), returning all zeros is WRONG."""

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
            # Defense in depth (closes J1): never apply impacts to a metric whose
            # stored value is non-numeric. The upstream filter in
            # calculate_metric_impacts excludes string values, but if the LLM
            # hallucinates an impact for a categorical metric, the previous code
            # silently coerced "Active Review" -> 0.0 and clobbered the value.
            if isinstance(raw_old, str) or metric.get('categorical_value') or metric.get('non_numeric'):
                continue
            try:
                old_value = float(raw_old) if raw_old is not None else 0
            except (TypeError, ValueError):
                continue  # was: old_value = 0  (silent clobber)
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
                      player_role: Dict,
                      engagement_data: Dict = None) -> Dict:
    """Evaluate user's decision and provide feedback.

    Args:
        engagement_data: Optional dict with this round's engagement metrics used
            to score the new Behavioural Governance dimension (v1.4.9+). Keys:
              - board_consultations: int     count of director consultations used
              - committee_consultations: int count of committee consultations used
              - debate_exchanges: int        total debate exchanges across dissenters
              - dissenters_addressed: int    how many opposing members the player engaged
              - dissenters_total: int        how many opposing members existed
              - force_submitted: bool        whether the timer forced submission
            When None, Behavioural Governance defaults to a neutral 3/5 per the prompt.

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

    # Engagement-data block — drives Behavioural Governance scoring (v1.4.9+).
    # When the caller doesn't provide engagement_data, the block is omitted and
    # the dimension definition tells the evaluator to default to a neutral 3/5.
    engagement_block = ""
    if engagement_data:
        bc = int(engagement_data.get('board_consultations', 0) or 0)
        cc = int(engagement_data.get('committee_consultations', 0) or 0)
        de = int(engagement_data.get('debate_exchanges', 0) or 0)
        da = int(engagement_data.get('dissenters_addressed', 0) or 0)
        dt = int(engagement_data.get('dissenters_total', 0) or 0)
        force = bool(engagement_data.get('force_submitted', False))
        engagement_block = f"""
PLAYER ENGAGEMENT DATA FOR THIS ROUND (use for Behavioural Governance dimension):
- Board (director) consultations used:    {bc}
- Committee consultations used:           {cc}
- Total debate exchanges with dissenters: {de}
- Dissenters addressed:                   {da} of {dt}
- Force-submitted (timer expired):        {'YES' if force else 'no'}
"""

    evaluation_prompt = f"""You are a STRICT and RIGOROUS corporate governance evaluator. Your role is to provide HONEST, ACCURATE assessments.
DO NOT give undeserved praise. If a decision is poor, say so clearly. Be direct about mistakes and their consequences.

HARD SCORE CEILINGS (apply BEFORE any other scoring):
- Decisions that propose unlawful actions (obstruction of justice, retaliation against whistleblowers,
  document destruction, intimidation, concealment from regulators): MAXIMUM SCORE = 15/100.
- Decisions that defer/table an urgent matter without substantive engagement
  ("let's revisit later", "circulate a memo", "table this"): MAXIMUM SCORE = 35/100.
- One-sentence picks with no rationale provided ("I'll go with Option X"): MAXIMUM SCORE = 60/100.
- Decisions that violate the player's role boundary (e.g. a CFO unilaterally
  announcing a PR strategy reserved for the CEO): MAXIMUM SCORE = 55/100.

If any ceiling applies, set the headline SCORE to AT MOST the ceiling value AND
explain which ceiling was triggered in SCORE_REASONING. The dimension breakdown
must be internally consistent with the headline score — the sum of dimensions
should approximately equal the headline (within ±10 points).

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

{vocabulary_block}{engagement_block}
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

Legal & Regulatory Compliance (25): Adherence to relevant laws (Companies Act, Ind AS, sector
regulators). Reward awareness of compliance constraints; deduct for actual violations or willful blind spots.

Stakeholder Consideration (15): Balance across investors, employees, customers, regulators, public.
Reward EITHER named-stakeholder analysis OR systematic framework that implicitly covers them.

Strategic Thinking (15): How well the decision integrates BOTH (a) operational/financial depth in
the player's domain AND (b) broader context (legal/regulatory/reputational/competitive). NEITHER axis
alone earns full marks — full marks require integration. Specifically reward responses that include
forward-looking risk mitigation, multi-stakeholder framing, AND multi-tier communication strategy
(institutional vs retail). Operational depth is NOT a deduction; lack of strategic breadth IS.

Role Alignment (5): Decision is appropriate for the player's role ({player_role['role']}). Reward:
implementation depth framed as governance pathway ("subject to board approval", "with Audit
Committee oversight", "pending CEO sign-off") because these stay within role mandate. Do NOT penalise
cross-disciplinary thinking that LENS-OF-OWN-ROLE — e.g. CFO speaking to strategic implications via
financial analysis is in-role; CFO unilaterally announcing PR strategy is overreach. Only penalise
unambiguous unilateral overreach into another C-suite domain.

Behavioural Governance (5): HOW the player engaged with the board process during this round.
Score based on the PLAYER ENGAGEMENT DATA block above (consultations used, dissenters debated,
committee consultations). 5 = used both consultation tracks AND engaged with every dissenter via
substantive debate; 3 = used one consultation track and engaged with at least one dissenter;
1 = no consultations and no debate engagement; 0 = no consultations and the player force-submitted
to avoid engagement. If no engagement data is provided in this prompt, default to 3 (neutral).

Decision Integrity (5): Honesty and consistency of rationale. Does the rationale match the action
taken? Is the reasoning self-consistent? Reward: clear reasoning grounded in the scenario facts,
acknowledged trade-offs, transparent uncertainty. Deduct: contradictions, evasive language, claims
that don't match the chosen option, or rationale that telegraphs different intent than the action.

Ethics & Judgment Under Pressure (5): Did the decision address the ETHICAL dimension explicitly,
beyond mere legality? Reward: consideration of fairness, conflicts of interest, whistleblower
protection, long-term reputational integrity, treatment of vulnerable stakeholders, or willingness
to take a short-term hit to do the right thing. Deduct: pure cost-benefit framing that ignores
ethical questions raised by the scenario, or decisions that satisfy the letter of the law while
violating its spirit.

Provide your evaluation in this EXACT format:
SCORE: [0-100] (Be HONEST - if decision is poor, give a low score)

SCORE_REASONING: [Explain SPECIFICALLY why you gave this score. Show points as X/MAX. Be critical where warranted. Dimensions MUST sum to the headline SCORE above (within ±10 pts):
- Governance Understanding: [points]/25 - [what was right/wrong]
- Legal/Regulatory Compliance: [points]/25 - [what was right/wrong]
- Stakeholder Consideration: [points]/15 - [who was helped/harmed]
- Strategic Thinking: [points]/15 - [integration of operational depth AND broader context — see definition above]
- Role Alignment: [points]/5 - [in-role with governance pathway? OR unilateral cross-domain overreach? — see definition above]
- Behavioural Governance: [points]/5 - [engagement with the board process per the ENGAGEMENT DATA block above]
- Decision Integrity: [points]/5 - [rationale matches the action; self-consistent reasoning]
- Ethics & Judgment Under Pressure: [points]/5 - [ethical dimension addressed beyond mere legality]
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

    # Extract score — use a line-anchored regex to avoid matching SCORE: as a
    # substring of MODULE_VOCABULARY_SCORE: (which would silently grab the vocab
    # score, defaulting to 100 — the source of grade inflation seen in audits).
    score = None
    import re as _re
    score_match = _re.search(r'(?m)^\s*SCORE\s*:\s*(\d{1,3})\b', content)
    if score_match:
        try:
            score = int(score_match.group(1))
        except (TypeError, ValueError):
            score = None
    if score is None:
        # Defensive fallback: parse dimension breakdown from SCORE_REASONING
        # (e.g. "- Governance Understanding: 12/25 ...") and sum if present.
        # v1.4.9 rubric has 8 dims with caps {25, 25, 15, 15, 5, 5, 5, 5} = 100.
        # Older rubric had 5 dims with caps {25, 20, 20, 20, 15} = 100. Both shapes
        # supported here so checkpointed sessions and stale LLM outputs still parse.
        dim_total = 0
        dim_max = 0
        for m in _re.finditer(r'(\d{1,3})\s*/\s*(\d{1,3})', content):
            n, d = int(m.group(1)), int(m.group(2))
            if d in (5, 15, 20, 25) and n <= d:  # known dimension caps (old + new)
                dim_total += n
                dim_max += d
        if dim_max in (95, 100):  # full rubric (5 or 8 dims) sums to ~100
            score = round(dim_total * 100 / dim_max)
            logger.warning(
                "evaluate_decision: SCORE line missing; recovered from dimension sum (%d/%d -> %d)",
                dim_total, dim_max, score,
            )
    if score is None:
        score = 50
        logger.warning("evaluate_decision: SCORE could not be parsed; defaulted to 50")
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

    # Reconcile vocab_score with the invoked/missed/misused evidence. The LLM
    # frequently returns vocab_score=100 even when invoked=[] (the player used
    # zero module vocabulary) — sometimes simultaneously listing terms the
    # player SHOULD have invoked. We override the LLM's headline number based
    # on what the evidence actually shows. Closes C1+C2 grade-inflation bug.
    if not vocabulary_invoked:
        if vocabulary_missed:
            # Player failed to invoke relevant terms. Floor at the lower of the
            # LLM's score or 30 — they get partial credit for terms being
            # identifiable but lose most of it for not using them.
            vocabulary_score = min(vocabulary_score, 30)
        elif not vocabulary_misused:
            # No invoked, no missed, no misused — LLM punted on assessment.
            # Default to 50 (neutral) rather than trust an unsubstantiated
            # high score. Also covers the case where no key_terms exist.
            if vocabulary_score >= 90 or not key_terms:
                vocabulary_score = 50
    if vocabulary_misused:
        # Penalize misuse explicitly (e.g. using a forbidden term).
        vocabulary_score = max(0, vocabulary_score - 20 * len(vocabulary_misused))

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


def build_stances_from_option(option: Dict, company_data: Dict,
                               player_role: Dict) -> Dict[str, Dict]:
    """Build the deterministic per-member stance map from a calibrated option.

    Returns the same shape as generate_member_stances() so callers are
    drop-in compatible. Used when the player picks one of the 4 calibrated
    options — no LLM call needed.

    Args:
        option: A dict with 'stance_distribution' (name -> APPROVE/OPPOSE/NEUTRAL)
                and 'counters' (name -> counter-opinion text). Produced by
                parse_scenario_options() on a new-format scenario.
        company_data: Source for member metadata (role, expertise, name lookup).
        player_role: The current player — excluded from stance generation.

    Returns:
        {member_name: {member_name, member_role, member_expertise, stance,
                       initial_reaction, counter_opinion, expertise_relevance,
                       conviction_level, convinced_in_round, debate_exchanges}}
    """
    distribution = option.get('stance_distribution') or {}
    counters = option.get('counters') or {}
    member_lookup = {m['name']: m for m in company_data.get('board_members', [])}

    # Conviction defaults — higher for OPPOSE since these are the dissenters
    # the player must engage with. APPROVE members default to 5 (neutral support).
    CONVICTION_OPPOSE = 7   # Strong-ish dissent — engages player in debate
    CONVICTION_APPROVE = 5
    CONVICTION_NEUTRAL = 4

    stances: Dict[str, Dict] = {}
    for member_name, stance in distribution.items():
        if member_name == player_role.get('name'):
            continue  # Skip the player
        member = member_lookup.get(member_name)
        if not member:
            logger.warning(
                "build_stances_from_option: option references unknown member %r — skipping",
                member_name,
            )
            continue

        counter = counters.get(member_name) if stance == 'OPPOSE' else None
        if stance == 'OPPOSE' and not counter:
            # Defensive: an OPPOSE without a counter wouldn't survive the
            # generate_member_stances semantic guard. Synthesize a generic one.
            counter = f"{member['role']} expresses concerns about this approach."
        if stance == 'OPPOSE':
            conviction = CONVICTION_OPPOSE
            reaction = counter[:140]
        elif stance == 'APPROVE':
            conviction = CONVICTION_APPROVE
            reaction = f"{member['role']} supports this approach."
        else:
            conviction = CONVICTION_NEUTRAL
            reaction = f"{member['role']} has reservations but no firm position."

        stances[member_name] = {
            'member_name': member_name,
            'member_role': member['role'],
            'member_expertise': member.get('expertise', ''),
            'stance': stance,
            'initial_reaction': reaction,
            'counter_opinion': counter,
            'expertise_relevance': '',
            'conviction_level': conviction,
            'convinced_in_round': None,
            'debate_exchanges': 0,
        }

    # Ensure every non-player member has a stance (default NEUTRAL if option
    # didn't list them — defensive against partial LLM outputs).
    for m in company_data.get('board_members', []):
        if m['name'] == player_role.get('name'):
            continue
        if m['name'] not in stances:
            logger.warning(
                "build_stances_from_option: member %r missing from option stance "
                "distribution — defaulting to NEUTRAL",
                m['name'],
            )
            stances[m['name']] = {
                'member_name': m['name'],
                'member_role': m['role'],
                'member_expertise': m.get('expertise', ''),
                'stance': 'NEUTRAL',
                'initial_reaction': 'No strong opinion expressed.',
                'counter_opinion': None,
                'expertise_relevance': '',
                'conviction_level': CONVICTION_NEUTRAL,
                'convinced_in_round': None,
                'debate_exchanges': 0,
            }

    return stances


def generate_member_stances(llm: object, company_data: Dict,
                             module_data: Dict, scenario: str,
                             player_decision: str, player_role: Dict,
                             all_member_histories: Dict = None,
                             selected_option: Dict = None) -> Dict[str, Dict]:
    """Generate each board member's stance on the player's decision.

    If `selected_option` is provided AND it carries a valid stance_distribution,
    use the deterministic pre-baked stances (saves one LLM call per round and
    matches the calibrated difficulty contract). Otherwise — for free-form
    decisions or old-format scenarios — fall back to LLM-based generation.
    """
    # Fast path: deterministic stances from a calibrated option
    if selected_option and selected_option.get('stance_distribution'):
        logger.debug(
            "generate_member_stances: using pre-baked stances from option %s",
            selected_option.get('letter'),
        )
        return build_stances_from_option(selected_option, company_data, player_role)
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


_OPTION_BLOCK_RE = None  # Compiled lazily — keeps import-time cost down


def _calibration_from_opposers(opposer_count: int, total_members: int) -> str:
    """Map an opposer count to the canonical calibration tier.
    Single source of truth — used by the parser to derive calibration from data
    (not the LLM's label) so audit / UI / picker stay consistent.

    Returns one of: 'unanimous' / 'mild_dissent' / 'controversial' /
    'highly_controversial' / '' (when neither applies, rare)."""
    if opposer_count <= 0:
        return 'unanimous'
    if opposer_count == 2:
        return 'mild_dissent'
    if opposer_count == 1:
        # 1 opposer — closest to mild_dissent but the LLM rarely produces this.
        # Treat as mild_dissent for calibration matching.
        return 'mild_dissent'
    if opposer_count == 3:
        return 'controversial'
    if opposer_count >= 4 or (total_members and opposer_count >= total_members):
        return 'highly_controversial'
    return ''


def _parse_stances_line(line: str) -> Dict[str, str]:
    """Parse 'Name1=APPROVE, Name2=OPPOSE, ...' into a dict.
    Tolerant of stray whitespace and case variations in the stance value."""
    result = {}
    if not line:
        return result
    for token in line.split(','):
        if '=' not in token:
            continue
        name, stance = token.split('=', 1)
        name = name.strip().strip('"').strip("'")
        stance = stance.strip().upper()
        if stance not in ('APPROVE', 'OPPOSE', 'NEUTRAL'):
            continue
        if name:
            result[name] = stance
    return result


def _parse_counters_line(line: str) -> Dict[str, str]:
    """Parse 'Name1: text | Name2: text | ...' into {name: counter_text}.
    The literal token '(none)' or empty input returns {}."""
    result = {}
    if not line or line.strip().lower() in ('(none)', 'none', 'n/a', ''):
        return result
    for chunk in line.split('|'):
        chunk = chunk.strip()
        if ':' not in chunk:
            continue
        name, counter = chunk.split(':', 1)
        name = name.strip().strip('"').strip("'")
        counter = counter.strip()
        if name and counter:
            result[name] = counter
    return result


_CALIB_LABELS = ('unanimous', 'mild_dissent', 'controversial', 'highly_controversial')


# Generic placeholder ACTION text per calibration tier — used by the synthesized
# fallback when the LLM fails to produce 4 options after all retries. Designed
# to be plausible boardroom actions independent of the specific scenario, with
# clear progression from consensus to highly contested.
_PLACEHOLDER_ACTIONS = {
    'unanimous': (
        "Convene the relevant standing committee, engage external counsel as needed, "
        "and prepare a transparent communication plan with all material stakeholders "
        "before taking further action. Document the deliberation process and rationale "
        "for the board record, and disclose findings promptly per the board's duty of candor."
    ),
    'mild_dissent': (
        "Take measured action within the board's existing governance authority, balancing "
        "speed against thoroughness. Engage with affected committees and key external "
        "advisors. Some board members may raise concerns about timing or implementation "
        "specifics, but the overall direction aligns with established governance practice."
    ),
    'controversial': (
        "Pursue an assertive approach that prioritizes decisiveness over consensus, "
        "accepting that several board members will object on procedural or risk-management "
        "grounds. The chair and management would need to actively rally support and address "
        "specific concerns about the direction before the board fully aligns."
    ),
    'highly_controversial': (
        "Take a decisive, high-risk action that materially departs from established governance "
        "norms and customary board oversight. The board would largely oppose this on multiple "
        "grounds — legal exposure, reputational risk, procedural propriety, or fiduciary duty. "
        "Significant persuasion and additional safeguards would be required to proceed."
    ),
}


def _synthesize_placeholder_option(letter: str, calibration: str,
                                    non_player_members: List[Dict]) -> Dict:
    """Build a generic placeholder option for a missing letter + calibration tier.

    Used as a last-resort fallback when the LLM consistently fails to produce
    4 options after all retries. The result is clearly tagged so the UI can
    surface the synthesis to the player and so audit harnesses can distinguish
    real LLM content from filler.
    """
    opposer_targets = {'unanimous': 0, 'mild_dissent': 2,
                       'controversial': 3, 'highly_controversial': 4}
    opposers_target = opposer_targets.get(calibration, 2)
    # Cap at the non-player member count for small boards
    opposers_target = min(opposers_target, len(non_player_members))

    # Round-robin assignment so different placeholders don't always pick the same opposers
    opposing = non_player_members[:opposers_target]
    opposing_names = {m['name'] for m in opposing}
    stances = {m['name']: ('OPPOSE' if m['name'] in opposing_names else 'APPROVE')
               for m in non_player_members}
    counters = {
        m['name']: (f"{m.get('role', 'Board member')} raises concerns about this approach "
                    f"based on their {m.get('expertise', 'domain')} expertise.")
        for m in opposing
    }
    action = (_PLACEHOLDER_ACTIONS.get(calibration, _PLACEHOLDER_ACTIONS['mild_dissent'])
              + " [Synthesized fallback — the model did not produce a complete option in time.]")

    return {
        'letter': letter,
        'text': action,
        'calibration': calibration,
        'calibration_label_from_llm': None,
        'stance_distribution': stances,
        'counters': counters,
        'synthesized': True,
    }


def _ensure_four_options(options: List[Dict], company_data: Dict,
                         player_role: Dict) -> List[Dict]:
    """Pad an options list to exactly 4 by synthesizing placeholders for the
    missing letters and missing calibration tiers. Called as the LAST step
    after all LLM retries — guarantees the player always sees 4 options."""
    if len(options) >= 4:
        return options

    have_letters = {o.get('letter') for o in options if o.get('letter')}
    have_calibrations = {o.get('calibration') for o in options if o.get('calibration')}
    all_letters = ['A', 'B', 'C', 'D']
    all_calibrations = list(_CALIB_LABELS)
    missing_letters = [l for l in all_letters if l not in have_letters]
    missing_calibrations = [c for c in all_calibrations if c not in have_calibrations]

    non_player_members = [m for m in company_data.get('board_members', [])
                          if m.get('name') != player_role.get('name')]

    # Pair missing letters with missing calibrations one-to-one; if more letters
    # than calibrations (e.g., LLM produced 2 controversial options), reuse
    # mild_dissent as a sensible default for the leftover slots.
    for i, letter in enumerate(missing_letters):
        if i < len(missing_calibrations):
            calibration = missing_calibrations[i]
        else:
            calibration = 'mild_dissent'
        options.append(_synthesize_placeholder_option(letter, calibration, non_player_members))

    options.sort(key=lambda o: o.get('letter', 'Z'))
    return options


def _format_option_as_scenario_block(opt: Dict) -> str:
    """Serialize a synthesized option back into the new-format text block so
    callers can append it to the raw scenario string and re-parse cleanly."""
    stances_line = ', '.join(f"{name}={stance}"
                              for name, stance in (opt.get('stance_distribution') or {}).items())
    counters = opt.get('counters') or {}
    if counters:
        counters_line = ' | '.join(f"{name}: {text}" for name, text in counters.items())
    else:
        counters_line = '(none)'
    return (
        f"\n\nOPTION {opt['letter']} | CALIBRATION: {opt.get('calibration', 'mild_dissent')}\n"
        f"ACTION: {opt['text']}\n"
        f"STANCES: {stances_line}\n"
        f"COUNTERS: {counters_line}\n"
    )


def _parse_new_format_options(scenario: str) -> List[Dict]:
    """Parse v1.4.7+ calibrated-format options. Tolerant of format variations
    the LLM commonly produces.

    Tolerated variations on the OPTION header line:
      OPTION A | CALIBRATION: unanimous          (canonical)
      **OPTION A** | CALIBRATION: unanimous       (markdown bold)
      OPTION A: CALIBRATION: unanimous            (colon instead of pipe)
      OPTION A | unanimous                        (missing CALIBRATION: prefix)
      OPTION A (unanimous)                        (parens)
      OPTION A — CALIBRATION: unanimous           (em-dash separator)
      OPTION A                                    (no calibration on header — derive from stances)
    """
    import re

    # Find every line that looks like an OPTION header, regardless of separator.
    # We capture the letter and the rest of the line (for calibration extraction).
    header_re = re.compile(
        r'(?m)^[\s\*_]*OPTION\s+([A-D])\b[\s\*_]*([^\n]*)',
        re.IGNORECASE,
    )
    # Extract a calibration label from anywhere in the header's trailing text
    calib_re = re.compile(
        r'\b(' + '|'.join(_CALIB_LABELS) + r')\b',
        re.IGNORECASE,
    )

    matches = list(header_re.finditer(scenario))
    if not matches:
        return []

    options: List[Dict] = []
    for idx, m in enumerate(matches):
        letter = m.group(1).upper()
        header_trail = m.group(2) or ''
        calib_match = calib_re.search(header_trail)
        calibration = calib_match.group(1).lower() if calib_match else None

        # Block content runs from end of this header to start of next header (or EOF)
        block_start = m.end()
        block_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(scenario)
        content = scenario[block_start:block_end]

        # ── ACTION (the option text) ──
        # Tolerate: ACTION:, ACTION —, ACTION -, just text after the header,
        # markdown bold like **ACTION:**, etc.
        action_text = ''
        action_match = re.search(
            r'(?ms)^[\s\*_]*ACTION[\s\*_]*[:\-—–]\s*(.*?)(?=^[\s\*_]*(?:STANCES|COUNTERS|OPTION)\b|\Z)',
            content,
        )
        if action_match:
            action_text = action_match.group(1).strip()
        else:
            # No explicit ACTION: marker — use everything before STANCES/COUNTERS
            stripped = re.split(r'(?m)^[\s\*_]*(?:STANCES|COUNTERS)\b', content, maxsplit=1)
            action_text = stripped[0].strip()
        # Strip any trailing markdown bold markers + extra whitespace
        action_text = action_text.strip('*_ \n\t')

        # ── STANCES ──
        stances: Dict[str, str] = {}
        stances_match = re.search(
            r'(?m)^[\s\*_]*STANCES[\s\*_]*[:\-—–]\s*(.+?)$',
            content,
        )
        if stances_match:
            stances = _parse_stances_line(stances_match.group(1))

        # ── COUNTERS ──
        counters: Dict[str, str] = {}
        counters_match = re.search(
            r'(?m)^[\s\*_]*COUNTERS[\s\*_]*[:\-—–]\s*(.+?)$',
            content,
        )
        if counters_match:
            counters = _parse_counters_line(counters_match.group(1))

        # Skip options with nothing parseable (truncated by token limit, etc.)
        if not (action_text or stances):
            continue

        opposer_count = sum(1 for v in stances.values() if v == 'OPPOSE')
        derived_calibration = _calibration_from_opposers(opposer_count, len(stances))
        if calibration and derived_calibration and calibration != derived_calibration:
            logger.warning(
                "parse_scenario_options: option %s label '%s' disagrees with "
                "opposer count %d (derived='%s') — using derived value.",
                letter, calibration, opposer_count, derived_calibration,
            )

        options.append({
            'letter': letter,
            'text': action_text,
            'calibration': derived_calibration or calibration,
            'calibration_label_from_llm': calibration,
            'stance_distribution': stances,
            'counters': counters,
        })

    return options


def _parse_old_format_options(scenario: str) -> List[Dict]:
    """Parse the bare 'A) text' / 'A. text' format (legacy). Returns options
    without stance_distribution — caller falls back to dynamic LLM stances."""
    options: List[Dict] = []
    current_option = None
    for line in scenario.split('\n'):
        line = line.strip()
        # Strip common markdown wrappers around the letter prefix
        line = line.lstrip('*_# ').rstrip()
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


def parse_scenario_options(scenario: str) -> List[Dict]:
    """Parse options from scenario text. Multi-tier parser.

    Tries:
      1. NEW v1.4.7+ calibrated format (tolerant of markdown bold, colons,
         parens, missing CALIBRATION: prefix, em-dashes).
      2. If new format yields <4 options, ALSO try OLD format and fill the
         gaps (by letter) — useful when the LLM mixed formats or only the
         first few options have the new headers.
      3. If still <4 options, return what we have. Caller / generate_scenario's
         retry loop decides whether to regenerate.

    The hybrid step (2) closes a real failure mode reported by clients:
    sometimes the LLM partially follows the new format (e.g. 2 options with
    OPTION/CALIBRATION headers, 2 options with bare 'C)' / 'D)' lines).
    Without the hybrid step the user would see only 2 options.

    Returned dict keys:
      letter, text, calibration (or None), stance_distribution (or {}), counters (or {}).
    """
    # ── Tier 1: NEW format with tolerant headers ──
    options = _parse_new_format_options(scenario)
    have_letters = {o['letter'] for o in options}

    # ── Tier 2: hybrid fallback ──
    if len(options) < 4:
        old_options = _parse_old_format_options(scenario)
        # Fill gaps by letter — don't overwrite a successfully parsed new-format option
        for old in old_options:
            if old['letter'] not in have_letters and old.get('text'):
                # Old-format options have no stance metadata. Caller will fall
                # back to dynamic LLM stance generation for these.
                options.append({
                    'letter': old['letter'],
                    'text': old['text'],
                    'calibration': None,
                    'calibration_label_from_llm': None,
                    'stance_distribution': {},
                    'counters': {},
                })
                have_letters.add(old['letter'])

    # Sort by letter so output order is stable
    options.sort(key=lambda o: o.get('letter', 'Z'))

    if 0 < len(options) < 4:
        logger.warning(
            "parse_scenario_options: only %d option(s) parsed (expected 4). "
            "Scenario may be malformed or truncated by token limit.",
            len(options),
        )

    return options


def validate_option_calibration(options: List[Dict], expected_non_player_count: int) -> List[str]:
    """Check a parsed option list against the calibrated-distribution contract.

    Returns a list of human-readable validation errors. An empty list means
    the calibration is valid and the scenario can be used as-is. A non-empty
    list signals the caller (generate_scenario) to retry with a stricter prompt.

    Expected distribution (per client claim):
      - 1 option with 0 OPPOSE (unanimous)
      - 1 option with exactly 2 OPPOSE (mild_dissent)
      - 2 options with >=3 OPPOSE (controversial / highly_controversial)
    """
    errors: List[str] = []

    if len(options) != 4:
        errors.append(f"Expected exactly 4 options, got {len(options)}")
        return errors  # downstream checks rely on 4 options

    # Each option needs a stance distribution sized to the non-player member count
    opposer_counts: List[int] = []
    for opt in options:
        sd = opt.get('stance_distribution') or {}
        if len(sd) < max(1, expected_non_player_count):
            errors.append(
                f"Option {opt.get('letter')} has stances for {len(sd)} member(s); "
                f"expected {expected_non_player_count}"
            )
        opposer_counts.append(sum(1 for v in sd.values() if v == 'OPPOSE'))

    if len(opposer_counts) != 4:
        return errors

    # Sorted opposer counts should match the calibrated profile:
    #   0 (unanimous), 2 (mild), and two values >=3 (controversial / highly)
    sorted_counts = sorted(opposer_counts)
    if sorted_counts[0] != 0:
        errors.append(
            f"No option with 0 opposers (unanimous). Got opposer counts {sorted_counts}"
        )
    if sorted_counts[1] != 2:
        errors.append(
            f"No option with exactly 2 opposers (mild_dissent). Got {sorted_counts}"
        )
    if sorted_counts[2] < 3:
        errors.append(
            f"Third option needs >=3 opposers (controversial). Got {sorted_counts}"
        )
    if sorted_counts[3] < 3:
        errors.append(
            f"Fourth option needs >=3 opposers (highly_controversial). Got {sorted_counts}"
        )

    return errors


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
