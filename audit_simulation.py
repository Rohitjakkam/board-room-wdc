"""
End-to-end metrics audit: drives a full simulation against the Clearwater fixture
using a real LLM, captures every metric mutation, and emits a markdown audit report
plus a JSON sidecar of raw data.

Usage:
    python audit_simulation.py

Reads GEMINI_API_KEY from .streamlit/secrets.toml (or env var).
"""

import copy
import datetime
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from core.llm import initialize_llm
from core.simulation_engine import (
    apply_metric_impacts,
    calculate_metric_impacts,
    evaluate_consultation_alignment,
    evaluate_decision,
    generate_member_stances,
    generate_scenario,
    parse_scenario_options,
    parse_scenario_sections,
)
from core.scoring import (
    calculate_board_effectiveness_score,
    calculate_goal_progress,
    calculate_overall_grade,
    compute_force_submit_penalty,
    generate_game_goals,
    _is_lower_better,
)
from tests.test_scenarios import (
    CLEARWATER_BOARD,
    CLEARWATER_COMPANY,
    CLEARWATER_MODULE,
    PLAYER_MEG,
    ROUND_CONFIG_R1,
    ROUND_CONFIG_R2,
)

ROUND_CONFIG_R3 = {
    'round_number': 3,
    'difficulty': 'medium',
    'focus_area': 'Disclosure Decisions',
    'round_type': 'both',
    'time_pressure': 'normal',
}

TOTAL_ROUNDS = 3

# Per-round caps mirrored from simulation_engine.apply_metric_impacts so the audit
# can independently flag cap-trips without trusting the function under test.
EXPECTED_MAX_CHANGE = {
    '%': 3.0,
    'count': 3,
    'employees': 50,
    'units': 50,
    'year': 2,
}
EXPECTED_MAX_REVENUE_PCT = 0.05


# ─────────────────────────────────────────────────────────────────────────────
# API-key loader
# ─────────────────────────────────────────────────────────────────────────────
def load_api_key() -> str:
    if os.environ.get('GEMINI_API_KEY'):
        return os.environ['GEMINI_API_KEY']
    secrets_path = REPO_ROOT / '.streamlit' / 'secrets.toml'
    if secrets_path.exists():
        for line in secrets_path.read_text(encoding='utf-8').splitlines():
            if line.strip().startswith('GEMINI_API_KEY'):
                return line.split('=', 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("GEMINI_API_KEY not found in env or .streamlit/secrets.toml")


# ─────────────────────────────────────────────────────────────────────────────
# Logging handler that captures warnings from core.simulation_engine
# (unit conversion + sanity clamp messages emit at WARNING level)
# ─────────────────────────────────────────────────────────────────────────────
class WarningCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.records: List[Dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append({
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'timestamp': datetime.datetime.now().isoformat(timespec='seconds'),
        })

    def drain(self) -> List[Dict[str, Any]]:
        out, self.records = self.records, []
        return out


# ─────────────────────────────────────────────────────────────────────────────
# Three "player" decision flavors, designed to surface metric variance
# ─────────────────────────────────────────────────────────────────────────────
DECISION_FLAVORS = [
    {
        'label': 'thoughtful',
        'force_submitted': False,
        # Detailed, vocabulary-rich, multi-stakeholder framing — should score high
        'decision_template': (
            "I select Option {letter}: {option_text}\n\n"
            "Rationale: This decision discharges our fiduciary duty by prioritizing "
            "transparent disclosure to the OCC while protecting institutional and retail "
            "shareholders. I would (1) convene an emergency Audit Committee session under "
            "Sandra Cho's chair, (2) engage outside counsel to scope the Regulation B gap "
            "in footnote 23, (3) authorize a remediation reserve subject to CFO Delgado's "
            "quantification, and (4) prepare tiered communications — institutional first, "
            "retail with plain-language framing — pending CEO sign-off. This stays within "
            "my Board Director mandate and preserves long-term franchise value over "
            "short-term reputational comfort."
        ),
    },
    {
        'label': 'baseline',
        'force_submitted': False,
        # Plain pick of option A — average effort
        'decision_template': "I'll go with Option {letter}: {option_text}",
    },
    {
        'label': 'lazy_late',
        'force_submitted': True,
        'overtime_seconds': 240,  # 4 min late
        # Vague non-answer + late timer — should score low and trigger force-penalty
        'decision_template': (
            "Let's defer this to the next meeting and have management circulate a memo."
        ),
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Per-round audit record
# ─────────────────────────────────────────────────────────────────────────────
def snapshot_metrics(metrics: Dict) -> Dict:
    return {k: {'value': v.get('value'), 'unit': v.get('unit'), 'priority': v.get('priority')}
            for k, v in metrics.items()}


def diff_metrics(before: Dict, after: Dict) -> List[Dict]:
    rows = []
    for key in before:
        bv = before[key]['value']
        av = after.get(key, {}).get('value', bv)
        try:
            change = float(av) - float(bv) if av is not None and bv is not None else None
        except (TypeError, ValueError):
            change = None
        rows.append({
            'metric': key,
            'before': bv,
            'after': av,
            'change': change,
            'unit': before[key]['unit'],
            'priority': before[key]['priority'],
            'lower_is_better': _is_lower_better(key),
        })
    return rows


def expected_cap_for(metric: Dict) -> float:
    unit = (metric.get('unit') or '').strip()
    if unit in EXPECTED_MAX_CHANGE:
        return EXPECTED_MAX_CHANGE[unit]
    val = metric.get('value')
    try:
        v = float(val) if val is not None else 0
    except (TypeError, ValueError):
        v = 0
    return abs(v) * EXPECTED_MAX_REVENUE_PCT if v != 0 else float('inf')


def run_round(llm, company_data, module_data, round_config, player_role,
              decision_flavor, previous_rounds, capture: WarningCapture) -> Dict:
    """Drive a single round end-to-end and return a fat audit record."""
    audit: Dict[str, Any] = {
        'round_number': round_config['round_number'],
        'decision_flavor': decision_flavor['label'],
        'force_submitted': decision_flavor['force_submitted'],
    }

    # Snapshot pre-round metrics
    pre_metrics = copy.deepcopy(company_data['metrics'])
    audit['metrics_before'] = snapshot_metrics(pre_metrics)

    # 1) Scenario
    print(f"  [R{round_config['round_number']}] generating scenario...")
    scenario = generate_scenario(llm, company_data, module_data, round_config,
                                 player_role, previous_rounds=previous_rounds)
    audit['scenario_raw'] = scenario
    audit['scenario_sections'] = parse_scenario_sections(scenario)
    options = parse_scenario_options(scenario)
    audit['options_parsed_count'] = len(options)
    audit['options'] = options

    # Pick option A if present, else first one, else placeholder
    chosen = options[0] if options else {'letter': 'X', 'text': '(no options parsed)'}
    audit['chosen_option'] = chosen
    decision_text = decision_flavor['decision_template'].format(
        letter=chosen['letter'], option_text=chosen['text']
    )
    audit['decision_text'] = decision_text

    # 2) Evaluate decision (also computes metric impacts internally)
    print(f"  [R{round_config['round_number']}] evaluating decision...")
    evaluation = evaluate_decision(llm, company_data, module_data, scenario,
                                   decision_text, round_config, player_role)
    audit['decision_score'] = evaluation['score']
    audit['score_reasoning'] = evaluation['score_reasoning']
    audit['vocabulary_score'] = evaluation['vocabulary_score']
    audit['vocabulary_invoked'] = evaluation['vocabulary_invoked']
    audit['metric_impacts_raw'] = evaluation['metric_impacts']

    # 3) Force-submit penalty (mirrors pages/simulation.py logic)
    impacts = dict(evaluation['metric_impacts']['impacts'])
    if decision_flavor['force_submitted']:
        overtime = decision_flavor.get('overtime_seconds', 0)
        penalty = compute_force_submit_penalty(overtime)
        # Symmetric: positive impacts reduced, negative amplified
        impacts = {k: (v * (1 - penalty) if v > 0 else v * (1 + penalty))
                   for k, v in impacts.items()}
        audit['force_submit_penalty'] = penalty
        audit['force_submit_overtime_sec'] = overtime
        audit['impacts_post_penalty'] = impacts

    # 4) Member stances (no debate this round to keep token budget tame)
    print(f"  [R{round_config['round_number']}] generating member stances...")
    stances = generate_member_stances(llm, company_data, module_data, scenario,
                                      decision_text, player_role)
    audit['member_stances'] = {n: {'stance': s['stance'],
                                   'conviction': s['conviction_level'],
                                   'has_counter': bool(s.get('counter_opinion'))}
                               for n, s in stances.items()}

    stance_counts = {'APPROVE': 0, 'OPPOSE': 0, 'NEUTRAL': 0, 'CONVINCED': 0}
    for s in stances.values():
        stance_counts[s['stance']] = stance_counts.get(s['stance'], 0) + 1
    audit['stance_counts'] = stance_counts

    # 5) Board effectiveness (no consultations / no debate in this audit)
    board_eff = calculate_board_effectiveness_score(
        round_number=round_config['round_number'],
        member_stances=stances,
        debate_history=[],
        consultation_alignment=50.0,  # neutral default — no consultations made
        force_submitted=decision_flavor['force_submitted'],
        max_debate_rounds=3,
    )
    audit['board_effectiveness'] = board_eff

    # 6) Apply impacts to live metrics (mutates company_data['metrics'])
    print(f"  [R{round_config['round_number']}] applying metric impacts...")
    pre_apply = copy.deepcopy(company_data['metrics'])
    new_metrics = apply_metric_impacts(company_data['metrics'], impacts)
    company_data['metrics'] = new_metrics

    # Per-metric audit row (proposed vs applied, cap-trip detection)
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
        cap_tripped = (proposed is not None and applied_change is not None
                       and abs(proposed) > cap + 1e-6
                       and abs(applied_change) <= cap + 1e-3)
        rows.append({
            'metric': k,
            'unit': pre.get('unit'),
            'priority': pre.get('priority'),
            'value_before': pre.get('value'),
            'value_after': post.get('value'),
            'proposed_change': proposed,
            'applied_change': applied_change,
            'expected_cap': cap if cap != float('inf') else None,
            'cap_tripped': cap_tripped,
            'lower_is_better': _is_lower_better(k),
            'categorical': bool(pre.get('categorical_value') or pre.get('non_numeric')),
            'reason': evaluation['metric_impacts']['reasons'].get(k, ''),
        })
    audit['metric_movements'] = rows

    # 7) Captured warnings (unit conversions, sanity clamps, parse errors)
    audit['captured_warnings'] = capture.drain()

    audit['metrics_after'] = snapshot_metrics(new_metrics)
    return audit


# ─────────────────────────────────────────────────────────────────────────────
# Invariant checks
# ─────────────────────────────────────────────────────────────────────────────
def run_invariants(initial_metrics: Dict, final_metrics: Dict,
                   per_round_audits: List[Dict]) -> List[Dict]:
    invariants: List[Dict] = []

    def add(name, ok, detail=""):
        invariants.append({'invariant': name, 'pass': bool(ok), 'detail': detail})

    # I1: Categorical metrics never received an impact
    cat_keys = {k for k, v in initial_metrics.items()
                if v.get('categorical_value') or v.get('non_numeric')
                or not isinstance(v.get('value'), (int, float))}
    cat_changed = []
    for k in cat_keys:
        before = initial_metrics[k].get('value')
        after = final_metrics.get(k, {}).get('value')
        if before != after:
            cat_changed.append(f"{k}: {before!r} → {after!r}")
    add("I1: Categorical/non-numeric metrics untouched",
        not cat_changed,
        "; ".join(cat_changed) if cat_changed else f"verified for {sorted(cat_keys)}")

    # I2: No per-round applied change ever exceeded its expected cap
    cap_breaches = []
    for r in per_round_audits:
        for row in r['metric_movements']:
            if row['applied_change'] is None or row['expected_cap'] is None:
                continue
            if abs(row['applied_change']) > row['expected_cap'] + 1e-3:
                cap_breaches.append(
                    f"R{r['round_number']} {row['metric']}: applied "
                    f"{row['applied_change']:+.4f} > cap {row['expected_cap']:.4f}"
                )
    add("I2: Per-round applied Δ within expected cap", not cap_breaches,
        "; ".join(cap_breaches) if cap_breaches else "all rounds, all metrics within cap")

    # I3: Percentage metrics stayed in [0,100]
    pct_breaches = []
    for r in per_round_audits:
        for row in r['metric_movements']:
            if row['unit'] != '%':
                continue
            v = row['value_after']
            try:
                vf = float(v)
            except (TypeError, ValueError):
                continue
            if vf < 0 or vf > 100:
                pct_breaches.append(f"R{r['round_number']} {row['metric']}: {vf}")
    add("I3: % metrics within [0,100]", not pct_breaches,
        "; ".join(pct_breaches) if pct_breaches else "all % metrics in range")

    # I4: Count metrics stayed ≥ 0 and integer
    count_breaches = []
    for r in per_round_audits:
        for row in r['metric_movements']:
            if row['unit'] not in ('count', 'employees', 'units'):
                continue
            v = row['value_after']
            if v is None:
                continue
            if isinstance(v, float) and not v.is_integer():
                count_breaches.append(f"R{r['round_number']} {row['metric']}: non-int {v}")
            if isinstance(v, (int, float)) and v < 0:
                count_breaches.append(f"R{r['round_number']} {row['metric']}: negative {v}")
    add("I4: count/employees/units metrics are non-negative integers",
        not count_breaches,
        "; ".join(count_breaches) if count_breaches else "all count metrics valid")

    # I5: Lower-is-better classification consistency check on key examples
    lib_checks = []
    for k in initial_metrics:
        kl = k.lower()
        if 'remediation_costs_reserve' in kl or 'reserve' in kl:
            if _is_lower_better(k):
                lib_checks.append(f"{k}: incorrectly classified as lower-is-better")
        elif any(t in kl for t in ('churn', 'liability', 'risk', 'attrition')):
            if not _is_lower_better(k):
                lib_checks.append(f"{k}: should be lower-is-better but isn't")
    add("I5: lower-is-better keyword/exclusion logic", not lib_checks,
        "; ".join(lib_checks) if lib_checks else "checked exclusions (reserve) and keywords (churn/risk/liability)")

    return invariants


# ─────────────────────────────────────────────────────────────────────────────
# Markdown report rendering
# ─────────────────────────────────────────────────────────────────────────────
def fmt_num(x):
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:.3f}".rstrip('0').rstrip('.') or "0"
    return str(x)


def fmt_change(x):
    if x is None:
        return "—"
    try:
        return f"{float(x):+.3f}".rstrip('0').rstrip('.').replace('+0', '0').replace('-0', '0') or "0"
    except (TypeError, ValueError):
        return str(x)


def render_markdown(report: Dict) -> str:
    lines: List[str] = []
    lines.append(f"# Metrics Audit — {report['company_name']}")
    lines.append(f"_Run: {report['timestamp']}  ·  Model: {report['model']}  ·  Rounds: {report['total_rounds']}_")
    lines.append("")
    lines.append(f"Player: **{report['player_role']['name']}** ({report['player_role']['role']})")
    lines.append("")

    # Initial metrics
    lines.append("## Starting metrics")
    lines.append("")
    lines.append("| Metric | Value | Unit | Priority | Lower-is-better |")
    lines.append("|---|---|---|---|---|")
    for k, m in report['initial_metrics'].items():
        lines.append(f"| `{k}` | {fmt_num(m['value'])} | {m['unit'] or '—'} | "
                     f"{m['priority'] or '—'} | "
                     f"{'✓' if _is_lower_better(k) else ''} |")
    lines.append("")

    # Initial goals
    lines.append("## Initial goals (auto-generated)")
    lines.append("")
    lines.append("| Metric | Direction | Current → Target | Priority |")
    lines.append("|---|---|---|---|")
    for g in report['initial_goals']:
        direction = "↓" if g.get('lower_is_better') else "↑"
        lines.append(f"| `{g['metric_key']}` | {direction} | "
                     f"{fmt_num(g['current'])} → {fmt_num(g['target'])} {g['unit']} | "
                     f"{g['priority']} |")
    lines.append("")
    lines.append(f"_Round-scale factor used: {report['round_scale']:.2f} (= total_rounds {report['total_rounds']} / 5)_")
    lines.append("")

    # Per-round
    for r in report['rounds']:
        lines.append(f"## Round {r['round_number']} — `{r['decision_flavor']}` decision"
                     + (" · **force-submitted**" if r['force_submitted'] else ""))
        lines.append("")
        title = r['scenario_sections'].get('title') or '(no title parsed)'
        lines.append(f"**Scenario title:** {title[:200]}")
        lines.append(f"**Options parsed:** {r['options_parsed_count']} "
                     f"(picked **{r['chosen_option']['letter']}**)")
        lines.append("")
        lines.append(f"**Decision text:**")
        lines.append("```")
        lines.append(r['decision_text'][:600] + ("…" if len(r['decision_text']) > 600 else ""))
        lines.append("```")
        lines.append("")
        lines.append(f"**Decision score:** {r['decision_score']}/100  "
                     f"·  Vocabulary score: {r['vocabulary_score']}/100  "
                     f"·  Vocab invoked: {r['vocabulary_invoked'] or 'none'}")
        lines.append("")

        # Force-submit details
        if r['force_submitted']:
            lines.append(f"**Force-submit penalty applied:** {r['force_submit_penalty']:.3f} "
                         f"(overtime: {r['force_submit_overtime_sec']}s)  "
                         f"_— positives × (1−penalty), negatives × (1+penalty)_")
            lines.append("")

        # Stance counts
        sc = r['stance_counts']
        lines.append(f"**Board stances:** APPROVE={sc.get('APPROVE', 0)}, "
                     f"OPPOSE={sc.get('OPPOSE', 0)}, "
                     f"NEUTRAL={sc.get('NEUTRAL', 0)}, "
                     f"CONVINCED={sc.get('CONVINCED', 0)}")
        be = r['board_effectiveness']
        lines.append(f"**Board effectiveness:** {be['deliberation_score']}/100 "
                     f"_(initial_approval={be['score_breakdown']['initial_approval']}, "
                     f"debate_eff={be['score_breakdown']['debate_effectiveness']}, "
                     f"efficiency={be['score_breakdown']['efficiency']}, "
                     f"consultation={be['score_breakdown']['consultation']})_")
        lines.append("")

        # Per-metric movement table
        lines.append("### Metric movements")
        lines.append("")
        lines.append("| Metric | Unit | Pri | Before | Proposed Δ | Applied Δ | After | Cap | Cap-tripped | Reason |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        for row in r['metric_movements']:
            cap_str = fmt_num(row['expected_cap']) if row['expected_cap'] is not None else '—'
            cat_marker = ' *(cat)*' if row['categorical'] else ''
            lib_marker = ' ↓' if row['lower_is_better'] else ''
            lines.append(
                f"| `{row['metric']}`{cat_marker}{lib_marker} | "
                f"{row['unit'] or '—'} | {row['priority'] or '—'} | "
                f"{fmt_num(row['value_before'])} | {fmt_change(row['proposed_change'])} | "
                f"{fmt_change(row['applied_change'])} | {fmt_num(row['value_after'])} | "
                f"{cap_str} | {'⚠ YES' if row['cap_tripped'] else ''} | "
                f"{(row['reason'] or '')[:80]} |"
            )
        lines.append("")

        # Captured warnings
        warns = r.get('captured_warnings') or []
        if warns:
            lines.append("**Captured warnings from `core.simulation_engine`:**")
            for w in warns:
                lines.append(f"- `{w['logger']}` — {w['message']}")
            lines.append("")
        else:
            lines.append("_No warnings from simulation_engine this round._")
            lines.append("")

    # Goal progress
    lines.append("## Goal progress after final round")
    lines.append("")
    lines.append("| Metric | Direction | Start → Current → Target | Progress | Achieved |")
    lines.append("|---|---|---|---|---|")
    for g in report['final_goal_progress']:
        direction = "↓" if g.get('lower_is_better') else "↑"
        lines.append(f"| `{g['metric_key']}` | {direction} | "
                     f"{fmt_num(g['current'])} → {fmt_num(g['current_value'])} → {fmt_num(g['target'])} {g['unit']} | "
                     f"{g['progress_pct']:.1f}% | {'✓' if g['achieved'] else ''} |")
    lines.append("")

    # Final grade
    grade = report['final_grade']
    lines.append("## Final grade")
    lines.append("")
    lines.append(f"**Grade: {grade['grade']}** — {grade['grade_description']}  "
                 f"·  Final score: **{grade['final_score']:.1f}/100**")
    lines.append("")
    lines.append("| Component | Value |")
    lines.append("|---|---|")
    lines.append(f"| Decision score (50%) | {grade['decision_score_component']:.2f} |")
    lines.append(f"| Metric score (30%)   | {grade['metric_score_component']:.2f} (normalized: {grade['normalized_metric_score']:.1f}) |")
    lines.append(f"| Board effectiveness (20%) | {grade['board_effectiveness_component']:.2f} |")
    lines.append(f"| Metrics improved / declined | {grade['metrics_improved']} / {grade['metrics_declined']} |")
    lines.append("")

    # Invariant check results
    lines.append("## Invariant checks")
    lines.append("")
    lines.append("| # | Check | Result | Detail |")
    lines.append("|---|---|---|---|")
    for inv in report['invariants']:
        mark = '✅' if inv['pass'] else '❌'
        lines.append(f"| {inv['invariant'].split(':')[0]} | {inv['invariant'].split(':', 1)[1].strip()} | {mark} | {inv['detail']} |")
    lines.append("")

    # Drift summary
    lines.append("## Net metric drift (initial → final)")
    lines.append("")
    lines.append("| Metric | Initial | Final | Δ | Direction | Lower-is-better |")
    lines.append("|---|---|---|---|---|---|")
    for k in report['initial_metrics']:
        iv = report['initial_metrics'][k]['value']
        fv = report['final_metrics'][k]['value']
        try:
            d = float(fv) - float(iv) if iv is not None and fv is not None else None
        except (TypeError, ValueError):
            d = None
        direction_ok = ''
        if d is not None and isinstance(d, (int, float)) and d != 0:
            if _is_lower_better(k):
                direction_ok = '✅ improved' if d < 0 else '⚠ worsened'
            else:
                direction_ok = '✅ improved' if d > 0 else '⚠ worsened'
        lines.append(f"| `{k}` | {fmt_num(iv)} | {fmt_num(fv)} | "
                     f"{fmt_change(d)} | {direction_ok} | {'↓' if _is_lower_better(k) else ''} |")
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

    print(f"Initializing Gemini LLM...")
    llm = initialize_llm(api_key)

    company_data = copy.deepcopy(CLEARWATER_COMPANY)
    module_data = copy.deepcopy(CLEARWATER_MODULE)
    player_role = copy.deepcopy(PLAYER_MEG)

    initial_metrics = copy.deepcopy(company_data['metrics'])
    initial_goals = generate_game_goals(initial_metrics, TOTAL_ROUNDS)

    round_configs = [ROUND_CONFIG_R1, ROUND_CONFIG_R2, ROUND_CONFIG_R3]
    flavors = DECISION_FLAVORS  # one per round, ordered

    round_records: List[Dict] = []
    previous_rounds: List[Dict] = []
    t0 = time.time()
    for cfg, flavor in zip(round_configs, flavors):
        print(f"\n=== Round {cfg['round_number']} ({flavor['label']}) ===")
        record = run_round(llm, company_data, module_data, cfg, player_role,
                           flavor, previous_rounds, capture)
        round_records.append(record)
        title = (record['scenario_sections'].get('title')
                 or f"Round {cfg['round_number']} scenario")[:120]
        # Pull a short impact summary from the metric_impacts payload when present
        outcome = (record['metric_impacts_raw'].get('summary')
                   or f"Decision scored {record['decision_score']}/100")[:300]
        previous_rounds.append({
            'round_number': cfg['round_number'],
            'title': title,
            'decision_summary': record['decision_text'][:300],
            'outcome_summary': outcome,
        })
    elapsed = time.time() - t0
    print(f"\nAll rounds done in {elapsed:.1f}s.")

    final_metrics = copy.deepcopy(company_data['metrics'])

    # Final goal progress and grade
    final_goal_progress = calculate_goal_progress(initial_goals, final_metrics)
    avg_decision_score = sum(r['decision_score'] for r in round_records) / len(round_records)
    avg_board_eff = sum(r['board_effectiveness']['deliberation_score']
                        for r in round_records) / len(round_records)
    final_grade = calculate_overall_grade(initial_metrics, final_metrics,
                                          avg_decision_score, avg_board_eff)

    invariants = run_invariants(initial_metrics, final_metrics, round_records)

    report = {
        'company_name': company_data['company_name'],
        'timestamp': datetime.datetime.now().isoformat(timespec='seconds'),
        'model': 'gemini-2.5-flash-lite',
        'total_rounds': TOTAL_ROUNDS,
        'round_scale': TOTAL_ROUNDS / 5.0,
        'player_role': player_role,
        'initial_metrics': snapshot_metrics(initial_metrics),
        'final_metrics': snapshot_metrics(final_metrics),
        'initial_goals': initial_goals,
        'final_goal_progress': final_goal_progress,
        'rounds': round_records,
        'final_grade': final_grade,
        'invariants': invariants,
        'elapsed_seconds': elapsed,
    }

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path = REPO_ROOT / f"audit_report_{stamp}.md"
    json_path = REPO_ROOT / f"audit_data_{stamp}.json"

    md_path.write_text(render_markdown(report), encoding='utf-8')
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')

    print(f"\n[OK] Wrote {md_path.name}")
    print(f"[OK] Wrote {json_path.name}")
    print(f"\nFinal grade: {final_grade['grade']} ({final_grade['final_score']:.1f}/100)")
    failed = [i for i in invariants if not i['pass']]
    if failed:
        print(f"[WARN] {len(failed)} invariant(s) failed:")
        for f in failed:
            print(f"  - {f['invariant']}: {f['detail']}")
    else:
        print(f"[OK] All {len(invariants)} invariants passed.")


if __name__ == '__main__':
    main()
