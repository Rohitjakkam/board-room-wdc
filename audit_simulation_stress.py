"""
Extended metrics audit — stress-tests three client-reported issues:
  1. LLM impact bias (toward zero / toward positive / incremental)
  2. Penalty/fine/sanction metric direction misclassification
  3. Per-round score should be composite (decision + business + module)

Adds to the baseline audit:
  - STRESS_COMPANY fixture with explicit penalty/fine/lawsuit/downtime metrics
    including deliberate "canary" metrics that SHOULD be lower-is-better but
    aren't (because the keywords are missing from core/scoring.py)
  - A `destructive` decision flavor (deny, conceal, retaliate) — designed to
    elicit large negative impacts on financial/penalty metrics
  - Shadow composite per-round score, computed alongside the LLM rubric score
  - Bias distribution stats (zero%, positive%, negative%, mean, std) per round
"""

import copy
import datetime
import json
import logging
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from core.llm import initialize_llm
from core.simulation_engine import (
    apply_metric_impacts,
    evaluate_decision,
    generate_member_stances,
    generate_scenario,
    parse_scenario_options,
    parse_scenario_sections,
)
from core.scoring import (
    LOWER_IS_BETTER_KEYWORDS,
    LOWER_IS_BETTER_EXCLUSIONS,
    _is_lower_better,
    calculate_board_effectiveness_score,
    calculate_goal_progress,
    calculate_overall_grade,
    compute_force_submit_penalty,
    generate_game_goals,
)
from audit_simulation import (
    EXPECTED_MAX_CHANGE,
    EXPECTED_MAX_REVENUE_PCT,
    WarningCapture,
    expected_cap_for,
    fmt_change,
    fmt_num,
    load_api_key,
    snapshot_metrics,
)


# ─────────────────────────────────────────────────────────────────────────────
# STRESS FIXTURE — Sentinel Industries
# Mix of: correctly-classified lower-is-better controls, canary metrics whose
# keywords are MISSING from LOWER_IS_BETTER_KEYWORDS, higher-is-better controls,
# and a categorical metric.
# ─────────────────────────────────────────────────────────────────────────────
SENTINEL_BOARD = [
    {'name': 'Helen Park', 'role': 'CEO', 'expertise': 'Operations',
     'tenure_years': 9, 'personality': 'Decisive, defensive of company reputation'},
    {'name': 'Marcus Lee', 'role': 'Chief Risk Officer', 'expertise': 'Risk Management',
     'tenure_years': 6, 'personality': 'Rigorously cautious, surfaces dissent early'},
    {'name': 'Priya Raman', 'role': 'CFO', 'expertise': 'Finance',
     'tenure_years': 7, 'personality': 'Numbers-driven, transparency-focused'},
    {'name': 'Theodore Vance', 'role': 'Chair of the Audit Committee', 'expertise': 'Audit',
     'tenure_years': 11, 'personality': 'Compliance-first, low tolerance for shortcuts'},
    {'name': 'Janet Okafor', 'role': 'Board Director', 'expertise': 'Corporate Governance',
     'tenure_years': 3, 'personality': 'Independent voice, asks tough questions'},
]

STRESS_COMPANY = {
    'company_name': 'Sentinel Industries',
    'company_overview': ('A mid-cap industrial manufacturer facing converging '
                         'regulatory, legal, and reputational pressure across plants.'),
    'industry': 'Industrial Manufacturing',
    'founded': '1995',
    'current_problems': [
        'OSHA investigation underway following a workplace injury',
        'Three open distributor lawsuits alleging breach of contract',
        'Plant downtime exceeding the 2% quarterly tolerance',
        'Customer satisfaction declining due to recent product defects',
        'Pending SEC inquiry on revenue recognition disclosure',
    ],
    'board_members': SENTINEL_BOARD,
    'committees': [
        {'name': 'Audit Committee', 'type': 'Standing',
         'purpose': 'Oversight of financial reporting and compliance',
         'chairperson': 'Theodore Vance', 'members': ['Theodore Vance', 'Priya Raman']},
        {'name': 'Risk Committee', 'type': 'Standing',
         'purpose': 'Enterprise risk oversight',
         'chairperson': 'Marcus Lee', 'members': ['Marcus Lee', 'Janet Okafor']},
    ],
    'metrics': {
        # ── Correctly classified lower-is-better (CONTROLS) ──
        'product_defect_rate':       {'value': 4.2,   'unit': '%',     'description': 'Product Defect Rate',     'priority': 'high'},     # 'defect' ✓
        'customer_complaints':       {'value': 320,   'unit': 'count', 'description': 'Open Customer Complaints', 'priority': 'high'},    # 'complaint' ✓ (substring of 'complaints')
        'compliance_breaches_ytd':   {'value': 7,     'unit': 'count', 'description': 'Compliance Breaches YTD',  'priority': 'high'},    # 'breach' ✓

        # ── CANARIES: should be lower-is-better but WON'T be (missing from LOWER_IS_BETTER_KEYWORDS) ──
        'regulatory_fine_amount':    {'value': 5.0,   'unit': '$M',    'description': 'Outstanding Regulatory Fine', 'priority': 'high'}, # 'fine' MISSING
        'outstanding_lawsuits':      {'value': 3,     'unit': 'count', 'description': 'Outstanding Lawsuits',     'priority': 'high'},    # 'lawsuit' MISSING
        'system_downtime_pct':       {'value': 2.8,   'unit': '%',     'description': 'System Downtime %',        'priority': 'medium'},  # 'downtime' MISSING
        'total_penalties_ytd':       {'value': 0.85,  'unit': '$M',    'description': 'Total Penalties YTD',      'priority': 'medium'},  # 'penalties' (plural) NOT substring of 'penalty'

        # ── Higher-is-better (CONTROLS) ──
        'total_revenue_annual':      {'value': 1200,  'unit': '$M',    'description': 'Total Revenue',            'priority': 'high'},
        'employee_engagement_score': {'value': 68,    'unit': '%',     'description': 'Employee Engagement',      'priority': 'medium'},
        'on_time_delivery_rate':     {'value': 89,    'unit': '%',     'description': 'On-Time Delivery Rate',    'priority': 'medium'},

        # ── Categorical (must be excluded from impacts) ──
        'sec_filing_status':         {'value': 'Active Review', 'unit': '', 'description': 'SEC Filing Status',   'priority': 'medium'},
    },
    'initial_scenario': 'The board convenes during a quarter of converging crises.',
}

STRESS_MODULE = {
    'module_name': 'Crisis Governance & Regulatory Response',
    'overview': 'Boards managing simultaneous regulatory, legal, and operational pressure.',
    'learning_objectives': [
        'Disclosure obligations under active investigation',
        'Whistleblower protection and retaliation prohibitions',
        'Litigation strategy oversight at the board level',
    ],
    'topics': [
        {'name': 'Regulatory Disclosure', 'description': 'When and what to disclose to regulators'},
        {'name': 'Crisis Communication', 'description': 'Stakeholder-tiered communication strategy'},
        {'name': 'Whistleblower Protection', 'description': 'Anti-retaliation requirements'},
    ],
    'key_terms': {
        'Fiduciary Duty': 'Obligation to act in best interest of company and shareholders',
        'Duty of Candor': 'Obligation to fully disclose material information to the board',
        'Whistleblower Protection': 'Legal protection against retaliation for good-faith reporting',
        'Material Misstatement': 'Misrepresentation significant enough to influence decisions',
    },
    'frameworks': [],
    'assessment_criteria': [],
}

PLAYER_JANET = {'name': 'Janet Okafor', 'role': 'Board Director', 'expertise': 'Corporate Governance'}

ROUND_CONFIGS = [
    {'round_number': 1, 'difficulty': 'medium', 'focus_area': 'Regulatory Disclosure',
     'round_type': 'both', 'time_pressure': 'normal'},
    {'round_number': 2, 'difficulty': 'medium', 'focus_area': 'Litigation Oversight',
     'round_type': 'both', 'time_pressure': 'normal'},
    {'round_number': 3, 'difficulty': 'hard', 'focus_area': 'Whistleblower Protection',
     'round_type': 'both', 'time_pressure': 'normal'},
    {'round_number': 4, 'difficulty': 'hard', 'focus_area': 'Crisis Communication',
     'round_type': 'both', 'time_pressure': 'urgent'},
]

TOTAL_ROUNDS = 4


# ─────────────────────────────────────────────────────────────────────────────
# Decision flavors — including a destructive one to test negative-impact elicitation
# ─────────────────────────────────────────────────────────────────────────────
DECISION_FLAVORS = [
    {
        'label': 'thoughtful_compliant',
        'force_submitted': False,
        'decision_template': (
            "I select Option {letter}: {option_text}\n\n"
            "Rationale: This action discharges my fiduciary duty by prioritizing full "
            "regulatory disclosure and candor with the audit committee. I would (1) "
            "engage external counsel to scope the issue, (2) brief Theodore Vance and "
            "the Audit Committee within 48 hours, (3) commission an independent "
            "investigation under Marcus Lee's oversight, and (4) ensure whistleblower "
            "protections are reaffirmed in writing. Material findings will be disclosed "
            "promptly per our duty of candor."
        ),
    },
    {
        'label': 'destructive_cover_up',
        'force_submitted': False,
        # A deliberately bad decision: deny, conceal, retaliate. Designed to elicit
        # large NEGATIVE impacts on penalty/fine/lawsuit metrics. If the LLM still
        # returns mostly zeros here, that confirms the zero-bias hypothesis.
        'decision_template': (
            "I select Option {letter}: {option_text}\n\n"
            "Rationale: We should deny the allegations publicly, instruct the legal team "
            "to delay all document production, intimidate the whistleblower into "
            "retracting their report, and avoid any voluntary disclosure to the SEC or "
            "OSHA. We will redirect press inquiries with a categorical denial and "
            "terminate the whistleblower for unrelated performance reasons. The fines "
            "are manageable and litigation can be drawn out for years."
        ),
    },
    {
        'label': 'baseline',
        'force_submitted': False,
        'decision_template': "I'll go with Option {letter}: {option_text}",
    },
    {
        'label': 'lazy_late',
        'force_submitted': True,
        'overtime_seconds': 300,
        'decision_template': (
            "Let's table this and revisit at the next quarterly meeting."
        ),
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Bias distribution stats
# ─────────────────────────────────────────────────────────────────────────────
def compute_bias_stats(impacts: Dict, metrics: Dict) -> Dict:
    """Distribution stats over the raw LLM-proposed impacts for this round."""
    eligible = [k for k, v in metrics.items()
                if not (v.get('categorical_value') or v.get('non_numeric'))
                and isinstance(v.get('value'), (int, float))]
    proposed = [impacts.get(k, 0) for k in eligible]
    nonzero = [v for v in proposed if v != 0]

    total = len(proposed)
    zero_count = sum(1 for v in proposed if v == 0)
    positive_count = sum(1 for v in proposed if v > 0)
    negative_count = sum(1 for v in proposed if v < 0)

    # Direction-aware: positive impact on lower-is-better = bad
    bad_count = 0
    good_count = 0
    for k in eligible:
        v = impacts.get(k, 0)
        if v == 0:
            continue
        lib = _is_lower_better(k)
        if (v > 0 and lib) or (v < 0 and not lib):
            bad_count += 1
        else:
            good_count += 1

    return {
        'eligible_metrics': total,
        'zero_impacts': zero_count,
        'zero_pct': (zero_count / total * 100) if total else 0,
        'positive_impacts': positive_count,
        'negative_impacts': negative_count,
        'good_direction': good_count,
        'bad_direction': bad_count,
        'nonzero_mean': statistics.mean(nonzero) if nonzero else 0,
        'nonzero_stdev': statistics.stdev(nonzero) if len(nonzero) > 1 else 0,
        'nonzero_abs_mean': statistics.mean([abs(v) for v in nonzero]) if nonzero else 0,
        'nonzero_max_abs': max([abs(v) for v in nonzero]) if nonzero else 0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Shadow composite per-round score
# Mirrors calculate_overall_grade's metric normalization but scoped to ONE round
# delta (initial -> after-this-round vs. before-this-round -> after-this-round).
# ─────────────────────────────────────────────────────────────────────────────
def compute_per_round_metric_score(metrics_before: Dict, metrics_after: Dict) -> Dict:
    """Replicate calculate_overall_grade's metric component, but over a single round."""
    PRIORITY_WEIGHTS = {'high': 1.5, 'medium': 1.0, 'low': 0.6}
    metric_score = 0.0
    total_weight = 0.0
    improvements = 0
    declines = 0

    for k, before in metrics_before.items():
        if k not in metrics_after:
            continue
        try:
            bv = float(before.get('value')) if before.get('value') is not None else 0
            av = float(metrics_after[k].get('value')) if metrics_after[k].get('value') is not None else 0
        except (TypeError, ValueError):
            continue
        priority = (before.get('priority') or 'medium').lower()
        weight = PRIORITY_WEIGHTS.get(priority, 1.0)

        higher_better = not _is_lower_better(k)
        if bv != 0:
            pct_change = ((av - bv) / abs(bv)) * 100
        else:
            pct_change = av * 10

        if not higher_better:
            pct_change = -pct_change

        capped = max(-20, min(20, pct_change))
        metric_score += capped * weight
        total_weight += weight

        if pct_change > 0:
            improvements += 1
        elif pct_change < 0:
            declines += 1

    if total_weight > 0:
        avg = metric_score / total_weight
        normalized = max(0, min(100, 50 + avg * 2.5))
    else:
        normalized = 50

    return {
        'normalized_score': normalized,
        'improvements': improvements,
        'declines': declines,
    }


def compute_composite_round_score(decision_score: int, vocab_score: int,
                                   round_metric_score: float) -> Dict:
    """Proposed composite round score: 50% decision + 20% vocab + 30% metric movement.
    This is a SHADOW score — not used by the live system. The point of showing it is
    to give the client a concrete alternative to compare against the inflated LLM
    decision score."""
    composite = (decision_score * 0.5) + (vocab_score * 0.2) + (round_metric_score * 0.3)
    return {
        'composite': composite,
        'decision_component': decision_score * 0.5,
        'vocab_component': vocab_score * 0.2,
        'metric_component': round_metric_score * 0.3,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Round runner (similar to baseline harness but adds composite + bias stats)
# ─────────────────────────────────────────────────────────────────────────────
def run_round(llm, company_data, module_data, round_config, player_role,
              decision_flavor, previous_rounds, capture: WarningCapture) -> Dict:
    audit: Dict[str, Any] = {
        'round_number': round_config['round_number'],
        'decision_flavor': decision_flavor['label'],
        'force_submitted': decision_flavor['force_submitted'],
    }

    pre_metrics = copy.deepcopy(company_data['metrics'])
    audit['metrics_before'] = snapshot_metrics(pre_metrics)

    print(f"  [R{round_config['round_number']}] generating scenario...")
    scenario = generate_scenario(llm, company_data, module_data, round_config,
                                 player_role, previous_rounds=previous_rounds)
    audit['scenario_sections'] = parse_scenario_sections(scenario)
    options = parse_scenario_options(scenario)
    audit['options_parsed_count'] = len(options)
    chosen = options[0] if options else {'letter': 'X', 'text': '(no options parsed)'}
    audit['chosen_option'] = chosen
    decision_text = decision_flavor['decision_template'].format(
        letter=chosen['letter'], option_text=chosen['text']
    )
    audit['decision_text'] = decision_text
    audit['scenario_raw'] = scenario

    print(f"  [R{round_config['round_number']}] evaluating decision...")
    evaluation = evaluate_decision(llm, company_data, module_data, scenario,
                                   decision_text, round_config, player_role)
    audit['decision_score'] = evaluation['score']
    audit['score_reasoning'] = evaluation['score_reasoning']
    audit['vocabulary_score'] = evaluation['vocabulary_score']
    audit['vocabulary_invoked'] = evaluation['vocabulary_invoked']
    audit['metric_impacts_raw'] = evaluation['metric_impacts']

    raw_impacts = dict(evaluation['metric_impacts']['impacts'])
    audit['bias_stats_raw'] = compute_bias_stats(raw_impacts, pre_metrics)

    impacts = dict(raw_impacts)
    if decision_flavor['force_submitted']:
        overtime = decision_flavor.get('overtime_seconds', 0)
        penalty = compute_force_submit_penalty(overtime)
        impacts = {k: (v * (1 - penalty) if v > 0 else v * (1 + penalty))
                   for k, v in impacts.items()}
        audit['force_submit_penalty'] = penalty
        audit['force_submit_overtime_sec'] = overtime

    print(f"  [R{round_config['round_number']}] generating member stances...")
    stances = generate_member_stances(llm, company_data, module_data, scenario,
                                      decision_text, player_role)
    stance_counts = {'APPROVE': 0, 'OPPOSE': 0, 'NEUTRAL': 0, 'CONVINCED': 0}
    for s in stances.values():
        stance_counts[s['stance']] = stance_counts.get(s['stance'], 0) + 1
    audit['stance_counts'] = stance_counts

    board_eff = calculate_board_effectiveness_score(
        round_number=round_config['round_number'],
        member_stances=stances,
        debate_history=[],
        consultation_alignment=50.0,
        force_submitted=decision_flavor['force_submitted'],
        max_debate_rounds=3,
    )
    audit['board_effectiveness'] = board_eff

    print(f"  [R{round_config['round_number']}] applying metric impacts...")
    pre_apply = copy.deepcopy(company_data['metrics'])
    new_metrics = apply_metric_impacts(company_data['metrics'], impacts)
    company_data['metrics'] = new_metrics

    rows = []
    for k, pre in pre_apply.items():
        post = new_metrics.get(k, pre)
        proposed = impacts.get(k)
        try:
            applied_change = (float(post.get('value')) - float(pre.get('value'))
                              if post.get('value') is not None and pre.get('value') is not None
                              else None)
        except (TypeError, ValueError):
            applied_change = None
        cap = expected_cap_for(pre)
        rows.append({
            'metric': k,
            'unit': pre.get('unit'),
            'priority': pre.get('priority'),
            'value_before': pre.get('value'),
            'value_after': post.get('value'),
            'proposed_change': proposed,
            'applied_change': applied_change,
            'expected_cap': cap if cap != float('inf') else None,
            'cap_tripped': (proposed is not None and applied_change is not None
                            and abs(proposed) > cap + 1e-6
                            and abs(applied_change) <= cap + 1e-3),
            'lower_is_better': _is_lower_better(k),
            'categorical': bool(pre.get('categorical_value') or pre.get('non_numeric'))
                           or not isinstance(pre.get('value'), (int, float)),
            'reason': evaluation['metric_impacts']['reasons'].get(k, ''),
        })
    audit['metric_movements'] = rows
    audit['metrics_after'] = snapshot_metrics(new_metrics)
    audit['captured_warnings'] = capture.drain()

    # SHADOW composite per-round score
    round_metric = compute_per_round_metric_score(pre_apply, new_metrics)
    audit['round_metric_score'] = round_metric
    audit['composite_round_score'] = compute_composite_round_score(
        decision_score=evaluation['score'],
        vocab_score=evaluation['vocabulary_score'],
        round_metric_score=round_metric['normalized_score'],
    )

    return audit


# ─────────────────────────────────────────────────────────────────────────────
# Markdown rendering — adds claims sections
# ─────────────────────────────────────────────────────────────────────────────
def detect_canary_metrics(metrics: Dict) -> List[Dict]:
    """Find metrics whose name suggests lower-is-better but who aren't classified as such."""
    SUSPICIOUS = {'fine', 'fines', 'penalt', 'lawsuit', 'litigation', 'sanction',
                  'downtime', 'outage', 'fraud', 'theft', 'error_rate', 'arrears',
                  'default', 'waste', 'dispute'}
    canaries = []
    for k in metrics:
        kl = k.lower()
        if _is_lower_better(k):
            continue
        for s in SUSPICIOUS:
            if s in kl:
                canaries.append({
                    'metric': k,
                    'matched_word': s,
                    'classified_as': 'higher-is-better',
                    'expected': 'lower-is-better',
                })
                break
    return canaries


def render_markdown(report: Dict) -> str:
    lines: List[str] = []
    lines.append(f"# Extended Metrics Audit — {report['company_name']}")
    lines.append(f"_Run: {report['timestamp']}  ·  Model: {report['model']}  ·  Rounds: {report['total_rounds']}_")
    lines.append("")
    lines.append("**Purpose:** stress-test three client-reported concerns:")
    lines.append("1. LLM bias toward positive / incremental impacts")
    lines.append("2. Penalty/fine/sanction metrics not affecting the score correctly")
    lines.append("3. Per-round score should be a composite (decision + business + module)")
    lines.append("")

    # ── Claim 2: canary metrics summary upfront ──
    lines.append("## Claim #2 — Misclassified penalty/fine canary metrics")
    lines.append("")
    canaries = report['canary_metrics']
    if not canaries:
        lines.append("_No misclassified canary metrics detected in this fixture._")
    else:
        lines.append("These metrics' names suggest lower-is-better, but the keyword logic in "
                     "`core/scoring.py` classifies them as higher-is-better:")
        lines.append("")
        lines.append("| Metric | Matched word | Classified as | Expected |")
        lines.append("|---|---|---|---|")
        for c in canaries:
            lines.append(f"| `{c['metric']}` | `{c['matched_word']}` | "
                         f"{c['classified_as']} | **{c['expected']}** |")
        lines.append("")
        lines.append("**Consequence:** when these metrics go UP (worse for the business), the system "
                     "treats it as IMPROVEMENT — inflating the grade and the wrong direction for goals.")
    lines.append("")

    # ── Initial state ──
    lines.append("## Starting metrics")
    lines.append("")
    lines.append("| Metric | Value | Unit | Priority | Lower-is-better | Note |")
    lines.append("|---|---|---|---|---|---|")
    canary_keys = {c['metric'] for c in canaries}
    for k, m in report['initial_metrics'].items():
        note = '🐤 canary (misclassified)' if k in canary_keys else ''
        lines.append(f"| `{k}` | {fmt_num(m['value'])} | {m['unit'] or '—'} | "
                     f"{m['priority'] or '—'} | "
                     f"{'✓' if _is_lower_better(k) else ''} | {note} |")
    lines.append("")

    # ── Per-round audit ──
    for r in report['rounds']:
        lines.append(f"## Round {r['round_number']} — `{r['decision_flavor']}` decision"
                     + (" · **force-submitted**" if r['force_submitted'] else ""))
        lines.append("")
        title = r['scenario_sections'].get('title') or '(no title parsed)'
        lines.append(f"**Scenario:** {title[:200]}  ·  Options parsed: {r['options_parsed_count']}  ·  Picked: **{r['chosen_option']['letter']}**")
        lines.append("")

        # CLAIM 3 — composite vs LLM score comparison
        comp = r['composite_round_score']
        rm = r['round_metric_score']
        lines.append("### Claim #3 — LLM decision score vs proposed COMPOSITE round score")
        lines.append("")
        lines.append("| Component | Weight | This round | Weighted |")
        lines.append("|---|---|---|---|")
        lines.append(f"| LLM decision score (current player-visible) | 50% | {r['decision_score']:.0f}/100 | {comp['decision_component']:.1f} |")
        lines.append(f"| Vocabulary score                            | 20% | {r['vocabulary_score']:.0f}/100 | {comp['vocab_component']:.1f} |")
        lines.append(f"| This round's metric movement (normalized)   | 30% | {rm['normalized_score']:.1f}/100 | {comp['metric_component']:.1f} |")
        lines.append(f"| **Composite round score** | — | — | **{comp['composite']:.1f}/100** |")
        lines.append("")
        delta = comp['composite'] - r['decision_score']
        lines.append(f"_LLM-only score: **{r['decision_score']}/100**  ·  Composite: **{comp['composite']:.1f}/100**  ·  "
                     f"Δ: **{delta:+.1f}**  ·  Round metric movement: {rm['improvements']} improved / {rm['declines']} declined_")
        lines.append("")

        # CLAIM 1 — bias distribution stats on raw LLM impacts
        bs = r['bias_stats_raw']
        lines.append("### Claim #1 — Bias distribution of raw LLM-proposed impacts")
        lines.append("")
        lines.append(f"- Eligible numeric metrics: **{bs['eligible_metrics']}**")
        lines.append(f"- Zero impacts: **{bs['zero_impacts']}** ({bs['zero_pct']:.0f}%)  ·  "
                     f"Positive: {bs['positive_impacts']}  ·  Negative: {bs['negative_impacts']}")
        lines.append(f"- Direction-aware: **good** = {bs['good_direction']}  ·  **bad** = {bs['bad_direction']}")
        lines.append(f"- Of the {bs['eligible_metrics'] - bs['zero_impacts']} nonzero impacts: "
                     f"mean = {bs['nonzero_mean']:+.2f}  ·  "
                     f"|mean| = {bs['nonzero_abs_mean']:.2f}  ·  "
                     f"max |Δ| = {bs['nonzero_max_abs']:.2f}")
        lines.append("")

        sc = r['stance_counts']
        be = r['board_effectiveness']
        lines.append(f"**Board stances:** APPROVE={sc.get('APPROVE', 0)}, "
                     f"OPPOSE={sc.get('OPPOSE', 0)}, "
                     f"NEUTRAL={sc.get('NEUTRAL', 0)}  ·  "
                     f"**Board effectiveness:** {be['deliberation_score']}/100")
        if r['force_submitted']:
            lines.append(f"**Force-submit penalty:** {r['force_submit_penalty']:.3f} "
                         f"({r['force_submit_overtime_sec']}s late)")
        lines.append("")

        # Metric movements table
        lines.append("### Metric movements")
        lines.append("")
        lines.append("| Metric | Unit | Pri | Before | Proposed Δ | Applied Δ | After | Cap-tripped | Direction-on-LIB |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for row in r['metric_movements']:
            canary_marker = ' 🐤' if row['metric'] in canary_keys else ''
            cat_marker = ' *(cat)*' if row['categorical'] else ''
            lib_marker = ' ↓' if row['lower_is_better'] else ''
            # Direction good/bad annotation
            dir_note = ''
            if row['applied_change'] is not None and row['applied_change'] != 0:
                if row['lower_is_better']:
                    dir_note = '✅ good' if row['applied_change'] < 0 else '⚠ bad'
                else:
                    dir_note = '✅ good' if row['applied_change'] > 0 else '⚠ bad'
            lines.append(
                f"| `{row['metric']}`{canary_marker}{cat_marker}{lib_marker} | "
                f"{row['unit'] or '—'} | {row['priority'] or '—'} | "
                f"{fmt_num(row['value_before'])} | {fmt_change(row['proposed_change'])} | "
                f"{fmt_change(row['applied_change'])} | {fmt_num(row['value_after'])} | "
                f"{'⚠ YES' if row['cap_tripped'] else ''} | {dir_note} |"
            )
        lines.append("")

        warns = r.get('captured_warnings') or []
        if warns:
            lines.append("**Warnings:**")
            for w in warns:
                lines.append(f"- {w['message']}")
            lines.append("")

    # ── Aggregate Claim #1 stats across all rounds ──
    lines.append("## Claim #1 — Aggregate bias across all rounds")
    lines.append("")
    total_elig = sum(r['bias_stats_raw']['eligible_metrics'] for r in report['rounds'])
    total_zero = sum(r['bias_stats_raw']['zero_impacts'] for r in report['rounds'])
    total_pos  = sum(r['bias_stats_raw']['positive_impacts'] for r in report['rounds'])
    total_neg  = sum(r['bias_stats_raw']['negative_impacts'] for r in report['rounds'])
    total_good = sum(r['bias_stats_raw']['good_direction'] for r in report['rounds'])
    total_bad  = sum(r['bias_stats_raw']['bad_direction'] for r in report['rounds'])

    lines.append(f"- Total impact opportunities (rounds × eligible metrics): **{total_elig}**")
    lines.append(f"- Zero-impact opportunities: **{total_zero}** "
                 f"({total_zero / total_elig * 100:.0f}% of all opportunities) — **bias-toward-zero indicator**")
    lines.append(f"- Positive impacts: **{total_pos}**  ·  Negative impacts: **{total_neg}**  ·  "
                 f"Positive : Negative ratio = **{(total_pos / max(total_neg, 1)):.2f}** "
                 f"_(>1.0 = positive-biased)_")
    lines.append(f"- Direction-aware: **{total_good}** good vs **{total_bad}** bad")
    lines.append("")
    lines.append("**Note on the destructive decision:** R2 was a deliberately bad "
                 "(deny/conceal/retaliate) decision. If the negative-impact count for R2 isn't "
                 "dramatically higher than baseline, the LLM is failing to model harm — "
                 "evidence for the zero-bias hypothesis.")
    lines.append("")

    # ── Net drift and final grade ──
    lines.append("## Net metric drift (initial → final)")
    lines.append("")
    lines.append("| Metric | Initial | Final | Δ | LIB | Direction | Canary? |")
    lines.append("|---|---|---|---|---|---|---|")
    for k in report['initial_metrics']:
        iv = report['initial_metrics'][k]['value']
        fv = report['final_metrics'][k]['value']
        try:
            d = float(fv) - float(iv) if iv is not None and fv is not None else None
        except (TypeError, ValueError):
            d = None
        lib = _is_lower_better(k)
        direction = ''
        if d is not None and isinstance(d, (int, float)) and d != 0:
            if lib:
                direction = '✅ improved' if d < 0 else '⚠ worsened'
            else:
                direction = '✅ improved' if d > 0 else '⚠ worsened'
        canary_marker = '🐤' if k in canary_keys else ''
        lines.append(f"| `{k}` | {fmt_num(iv)} | {fmt_num(fv)} | "
                     f"{fmt_change(d)} | {'↓' if lib else ''} | {direction} | {canary_marker} |")
    lines.append("")

    grade = report['final_grade']
    lines.append("## Final grade (using current production formula)")
    lines.append("")
    lines.append(f"**Grade: {grade['grade']}** — {grade['grade_description']}  ·  "
                 f"Final score: **{grade['final_score']:.1f}/100**")
    lines.append("")
    lines.append("| Component | Value |")
    lines.append("|---|---|")
    lines.append(f"| Decision score (50%) | {grade['decision_score_component']:.2f} |")
    lines.append(f"| Metric score (30%)   | {grade['metric_score_component']:.2f} (normalized: {grade['normalized_metric_score']:.1f}) |")
    lines.append(f"| Board effectiveness (20%) | {grade['board_effectiveness_component']:.2f} |")
    lines.append(f"| Metrics improved / declined | {grade['metrics_improved']} / {grade['metrics_declined']} |")
    lines.append("")

    # Composite vs LLM average
    avg_llm = sum(r['decision_score'] for r in report['rounds']) / len(report['rounds'])
    avg_comp = sum(r['composite_round_score']['composite'] for r in report['rounds']) / len(report['rounds'])
    lines.append("### Average per-round score: LLM-only vs Composite (Claim #3 summary)")
    lines.append("")
    lines.append(f"- Avg LLM decision score: **{avg_llm:.1f}/100**")
    lines.append(f"- Avg composite round score: **{avg_comp:.1f}/100**")
    lines.append(f"- Gap: **{avg_llm - avg_comp:+.1f}** _(positive = LLM-only inflates over composite)_")
    lines.append("")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    api_key = load_api_key()
    capture = WarningCapture()
    logging.getLogger("core.simulation_engine").addHandler(capture)
    logging.getLogger("core.simulation_engine").setLevel(logging.WARNING)

    print("Initializing Gemini LLM...")
    llm = initialize_llm(api_key)

    company_data = copy.deepcopy(STRESS_COMPANY)
    module_data = copy.deepcopy(STRESS_MODULE)
    player_role = copy.deepcopy(PLAYER_JANET)
    initial_metrics = copy.deepcopy(company_data['metrics'])

    canaries = detect_canary_metrics(initial_metrics)
    print(f"\nDetected {len(canaries)} canary (misclassified) metrics:")
    for c in canaries:
        print(f"  - {c['metric']}: matched '{c['matched_word']}' but classified as {c['classified_as']}")

    round_records: List[Dict] = []
    previous_rounds: List[Dict] = []
    t0 = time.time()
    for cfg, flavor in zip(ROUND_CONFIGS, DECISION_FLAVORS):
        print(f"\n=== Round {cfg['round_number']} ({flavor['label']}) ===")
        record = run_round(llm, company_data, module_data, cfg, player_role,
                           flavor, previous_rounds, capture)
        round_records.append(record)
        title = (record['scenario_sections'].get('title')
                 or f"Round {cfg['round_number']} scenario")[:120]
        outcome = (record['metric_impacts_raw'].get('summary')
                   or f"Decision scored {record['decision_score']}/100")[:300]
        previous_rounds.append({
            'round_number': cfg['round_number'],
            'title': title,
            'decision_summary': record['decision_text'][:300],
            'outcome_summary': outcome,
        })
    elapsed = time.time() - t0

    final_metrics = copy.deepcopy(company_data['metrics'])
    initial_goals = generate_game_goals(initial_metrics, TOTAL_ROUNDS)
    avg_decision_score = sum(r['decision_score'] for r in round_records) / len(round_records)
    avg_board_eff = sum(r['board_effectiveness']['deliberation_score']
                        for r in round_records) / len(round_records)
    final_grade = calculate_overall_grade(initial_metrics, final_metrics,
                                          avg_decision_score, avg_board_eff)

    report = {
        'company_name': company_data['company_name'],
        'timestamp': datetime.datetime.now().isoformat(timespec='seconds'),
        'model': 'gemini-2.0-flash-lite',
        'total_rounds': TOTAL_ROUNDS,
        'player_role': player_role,
        'initial_metrics': snapshot_metrics(initial_metrics),
        'final_metrics': snapshot_metrics(final_metrics),
        'initial_goals': initial_goals,
        'final_goal_progress': calculate_goal_progress(initial_goals, final_metrics),
        'rounds': round_records,
        'final_grade': final_grade,
        'canary_metrics': canaries,
        'elapsed_seconds': elapsed,
    }

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path = REPO_ROOT / f"audit_stress_{stamp}.md"
    json_path = REPO_ROOT / f"audit_stress_{stamp}.json"
    md_path.write_text(render_markdown(report), encoding='utf-8')
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')

    print(f"\n[OK] Wrote {md_path.name}")
    print(f"[OK] Wrote {json_path.name}")
    print(f"Elapsed: {elapsed:.1f}s")
    print(f"Final grade: {final_grade['grade']} ({final_grade['final_score']:.1f}/100)")


if __name__ == '__main__':
    main()
