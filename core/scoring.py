"""
Scoring, grading, goal generation, and metric impact calculations.
"""

from typing import Dict, List

from core.models import TIME_PRESSURE_MINUTES

# Metrics where a lower value represents improvement.
#
# IMPORTANT: matching is TOKEN-based after underscore-splitting and Porter
# Step-1A depluralization (see _is_lower_better below). Substring matching
# was abandoned because it produces false positives for short tokens like
# `fine` (matches `refine`, `final`) and silently rewards harmful outcomes
# (e.g. `regulatory_fine_amount` was previously classified as higher-better).
#
# Add SINGULAR forms only — plurals (penalties, fines, breaches, lawsuits,
# disputes, incidents) are handled automatically by the depluralizer.
# Add EXCLUSIONS (below) for multi-token phrases where the keyword is
# contextually higher-is-better (e.g. asset_turnover, return_on_equity).
LOWER_IS_BETTER_KEYWORDS = {
    # Financial / accounting
    'cost', 'expense', 'expenditure', 'opex', 'overhead', 'loss', 'writeoff',
    'writedown', 'chargeoff', 'impairment', 'arrears', 'overdue', 'shortfall',
    'deficit', 'slippage', 'markdown', 'dilution', 'liability', 'debt',
    'provision', 'npl', 'nonperforming', 'delinquency', 'delinquent',
    'arrear',  # mass-noun form after depluralizer strips trailing 's'
    # Regulatory / legal / compliance
    'penalty', 'fine', 'sanction', 'lawsuit', 'litigation', 'investigation',
    'infraction', 'violation', 'noncompliance', 'nonconformance', 'nonconformity',
    'subpoena', 'injunction', 'remediation', 'materialweakness',
    # Risk / security
    'risk', 'exposure', 'incident', 'breach', 'vulnerability', 'threat',
    'attack', 'intrusion', 'compromise', 'malware', 'phishing', 'ransomware',
    'cve', 'mttd', 'mttr', 'backlog', 'pending', 'audit',
    # Operations / manufacturing
    'defect', 'downtime', 'outage', 'failure', 'scrap', 'rework', 'reject',
    'recall', 'breakdown', 'stoppage', 'bottleneck', 'wip',
    # HR / people
    'attrition', 'turnover', 'absentee', 'absenteeism', 'grievance', 'harassment',
    'discrimination', 'injury', 'accident', 'fatality', 'ltifr', 'trir',
    'disengagement', 'vacancy',
    # Customer
    'churn', 'complaint', 'escalation', 'dissatisfaction', 'detractor',
    'cancellation', 'refund', 'chargeback', 'dispute', 'abandonment',
    # IT / tech
    'latency', 'error', 'bug', 'crash', 'rollback', 'regression', 'flaky',
    # ESG / environment
    'carbon', 'emission', 'pollution', 'pollutant', 'spill', 'effluent',
    'waste', 'hazardous', 'nox', 'ghg', 'footprint', 'greenhouse', 'flaring',
    # Misc problem indicators
    'gap', 'delay', 'lateness', 'burn', 'complaint',
    # Paperwork / process burden
    'packet', 'paperwork', 'paperload',
}

# Multi-token phrases where the LOWER_IS_BETTER keyword is contextually
# higher-is-better. Checked as substrings of the FULL metric key (not tokenized)
# so they can match across underscores. Check is done BEFORE keyword matching.
LOWER_IS_BETTER_EXCLUSIONS = {
    # Pools you WANT to grow
    'reserve', 'budget', 'fund', 'allocation',
    # Finance / accounting where keyword reverses meaning
    'asset_turnover', 'inventory_turnover', 'receivables_turnover',
    'capital_turnover', 'portfolio_turnover',
    'return_on', 'returns_on',
    'cost_savings', 'cost_avoidance', 'cost_reduction', 'cost_efficiency',
    'debt_capacity', 'debt_coverage', 'debt_service_coverage',
    # Risk metrics where keyword reverses meaning
    'risk_appetite', 'risk_capacity', 'risk_adjusted',
    # Audit metrics where keyword reverses meaning
    'audit_score', 'audit_rating', 'audit_coverage', 'audit_completion',
    # Recovery / prevention / resolution metrics
    'recovery', 'recovered', 'prevention', 'prevented', 'resolution_rate',
    'resolved_rate', 'avoided',
    # Quality metrics named in inverted form
    'defect_free', 'error_free', 'zero_defect', 'zero_incident',
    # Compliance metrics where lower-better keyword reverses meaning
    'compliance_score', 'compliance_rate',
    # ESG metrics where lower-better keyword reverses meaning
    'emission_reduction', 'carbon_offset', 'carbon_removal',
    'waste_diversion', 'waste_recycled',
    # IT metrics where lower-better keyword reverses meaning
    'uptime', 'availability', 'mtbf',
    # Wellness contexts
    'weight_loss',
}


def _depluralize(token: str) -> str:
    """Tiny Porter Step-1A depluralizer (stdlib-only).

    Handles regular English plural endings so penalty/penalties, fine/fines,
    breach/breaches, lawsuit/lawsuits all match the same singular keyword.
    Length guards prevent stem collisions on short non-plural words.
    """
    if len(token) < 4:
        return token
    if token.endswith('sses'):
        return token[:-2]                  # losses -> loss
    if token.endswith('ies'):
        return token[:-3] + 'y'            # penalties -> penalty
    if token.endswith(('ches', 'shes', 'xes', 'zes')):
        return token[:-2]                  # breaches -> breach
    if token.endswith('es') and not token.endswith(('ses', 'aes', 'oes', 'ies')):
        return token[:-1]                  # disputes -> dispute, escalates -> escalate
    if token.endswith('s') and not token.endswith('ss') and len(token) > 4:
        return token[:-1]                  # incidents -> incident
    return token


def _is_lower_better(metric_key: str) -> bool:
    """Determine if a lower value is better for this metric.

    Algorithm:
      1. Check EXCLUSIONS as substrings of the full key first (catches multi-token
         phrases like `asset_turnover`, `return_on_equity` where the keyword's
         contextual meaning is reversed).
      2. Tokenize the key on underscores, depluralize each token, and check
         whether any depluralized token matches the keyword set.

    Token-based matching avoids substring false positives like `fine` matching
    `refine` or `define`. Depluralization avoids requiring both singular and
    plural forms in the keyword set.
    """
    key_lower = metric_key.lower()
    for exc in LOWER_IS_BETTER_EXCLUSIONS:
        if exc in key_lower:
            return False
    tokens = [_depluralize(t) for t in key_lower.split('_') if t]
    return any(t in LOWER_IS_BETTER_KEYWORDS for t in tokens)


def calculate_board_effectiveness_score(round_number: int,
                                          member_stances: Dict,
                                          debate_history: List[Dict],
                                          consultation_alignment: float,
                                          force_submitted: bool,
                                          max_debate_rounds: int = 3) -> Dict:
    """Calculate the board effectiveness score for a round."""
    total_members = len(member_stances)
    initially_approving = sum(1 for s in member_stances.values()
                              if s.get('stance') == 'APPROVE')
    # CONVINCED members started as OPPOSE — include them for accurate initial opposition count
    initially_opposing = sum(1 for s in member_stances.values()
                             if s.get('stance') in ('OPPOSE', 'CONVINCED'))
    convinced = sum(1 for s in member_stances.values()
                    if s.get('convinced_in_round') is not None)

    total_debate_exchanges = sum(s.get('debate_exchanges', 0) for s in member_stances.values())

    # 1. Initial approval rate (25 points max)
    initial_approval_score = (initially_approving / max(total_members, 1)) * 25

    # 2. Consultation alignment (25 points max)
    try:
        consultation_alignment = float(consultation_alignment) if consultation_alignment is not None else 50
    except (TypeError, ValueError):
        consultation_alignment = 50
    consultation_score = (consultation_alignment / 100) * 25

    # 3. Debate effectiveness (30 points max)
    if initially_opposing > 0:
        debate_effectiveness = (convinced / initially_opposing) * 30
    else:
        debate_effectiveness = 30

    # 4. Efficiency bonus (20 points max)
    if force_submitted:
        efficiency_score = 5
    elif initially_opposing == 0:
        efficiency_score = 20
    elif total_debate_exchanges == 0:
        efficiency_score = 20
    else:
        efficiency_score = max(5, 20 - (total_debate_exchanges * 2))

    total_score = initial_approval_score + consultation_score + debate_effectiveness + efficiency_score

    return {
        'round_number': round_number,
        'consultation_alignment_score': consultation_alignment,
        'members_initially_approving': initially_approving,
        'members_initially_opposing': initially_opposing,
        'members_convinced': convinced,
        'total_debate_exchanges': total_debate_exchanges,
        'force_submitted': force_submitted,
        'deliberation_score': round(total_score, 1),
        'score_breakdown': {
            'initial_approval': round(initial_approval_score, 1),
            'consultation': round(consultation_score, 1),
            'debate_effectiveness': round(debate_effectiveness, 1),
            'efficiency': round(efficiency_score, 1)
        }
    }


def generate_game_goals(metrics: Dict, total_rounds: int) -> List[Dict]:
    """Generate goals dynamically from whatever metrics the company has, scaled by round count."""

    # Category detection from metric key/description
    CATEGORY_MAP = {
        'revenue': 'Financial', 'profit': 'Financial', 'ebitda': 'Financial',
        'margin': 'Financial', 'growth': 'Financial', 'debt': 'Financial',
        'customer': 'Customer', 'churn': 'Customer', 'promoter': 'Customer',
        'satisfaction': 'Customer', 'retention': 'Customer',
        'employee': 'HR', 'engagement': 'HR', 'attrition': 'HR', 'headcount': 'HR',
        'uptime': 'Operations', 'deployment': 'Operations', 'platform': 'Operations',
        'risk': 'Risk', 'compliance': 'Risk', 'regulatory': 'Risk', 'severity': 'Risk',
    }

    CATEGORY_ICONS = {
        'Financial': '💰', 'Customer': '😊', 'HR': '👥',
        'Operations': '⚙️', 'Risk': '🛡️',
    }

    # Scale factor: 5 rounds is the baseline
    round_scale = total_rounds / 5.0

    # Keywords indicating a metric is categorical/status-based (not numeric performance)
    CATEGORICAL_KEYWORDS = {
        'status', 'classification', 'rating', 'tier', 'level', 'phase',
        'stage', 'category', 'type', 'mode', 'state',
    }

    # Keywords indicating a metric is a headcount / discrete person count
    HEADCOUNT_KEYWORDS = {
        'member', 'director', 'headcount', 'staff', 'employee', 'workforce',
        'board_size', 'committee_size', 'seat',
    }

    goals = []
    for key, metric in metrics.items():
        raw_val = metric.get('value')
        # Skip metrics flagged as categorical during normalization
        if metric.get('categorical_value'):
            continue
        try:
            current = float(raw_val) if raw_val is not None else 0
        except (TypeError, ValueError):
            # Non-numeric value (categorical data like "Medium", "Active") — skip
            continue
        unit = metric.get('unit', '')
        description = metric.get('description', key.replace('_', ' ').title())
        priority = (metric.get('priority') or 'medium').lower()

        # Skip zero-value metrics with meaningless units (placeholder/empty data)
        if current == 0.0 and unit in ('', 'N/A', 'n/a'):
            continue

        key_lower = key.lower()
        desc_lower = description.lower()

        # Skip categorical/status metrics that were forced to 0.0 during normalization
        if any(kw in key_lower or kw in desc_lower for kw in CATEGORICAL_KEYWORDS):
            if current == 0:
                continue  # Likely a categorical value that was coerced to 0

        # Detect direction
        lower_is_better = _is_lower_better(key)

        # Detect category
        category = 'General'
        for kw, cat in CATEGORY_MAP.items():
            if kw in key_lower or kw in desc_lower:
                category = cat
                break

        # Skip headcount/person-count metrics — not performance goals
        is_headcount = (unit == 'employees' or
                        any(kw in key_lower for kw in HEADCOUNT_KEYWORDS))
        if is_headcount:
            continue

        # Calculate target delta based on unit type, scaled by rounds
        if unit == '%':
            base_delta = 3.0
        elif unit in ('count', 'score'):
            base_delta = max(2, abs(current) * 0.05) if current != 0 else 2
        else:
            # Currency or other large-number metrics
            base_delta = abs(current) * 0.05 if current != 0 else 5

        delta = base_delta * round_scale

        if lower_is_better:
            target = max(current - delta, 0)
        else:
            if unit == '%':
                target = min(current + delta, 100)
            else:
                target = current + delta

        # Round targets appropriately — count metrics must be integers
        if unit in ('count', 'score'):
            target = round(target)
        else:
            target = round(target, 2) if isinstance(target, float) else target

        goals.append({
            'category': category,
            'metric_key': key,
            'name': description,
            'description': f"{'Reduce' if lower_is_better else 'Improve'} {description.lower()}",
            'current': current,
            'target': target,
            'unit': unit,
            'icon': CATEGORY_ICONS.get(category, '📊'),
            'priority': priority if priority in ('high', 'medium', 'low') else 'medium',
            **({"lower_is_better": True} if lower_is_better else {}),
        })

    # Sort: high priority first, then medium, then low
    priority_order = {'high': 0, 'medium': 1, 'low': 2}
    goals.sort(key=lambda g: priority_order.get(g['priority'], 1))

    return goals


def calculate_goal_progress(goals: List[Dict], current_metrics: Dict) -> List[Dict]:
    """Calculate progress toward each goal based on current metrics."""
    progress_list = []

    for goal in goals:
        metric_key = goal['metric_key']
        if metric_key in current_metrics:
            raw_cv = current_metrics[metric_key].get('value')
            try:
                current_value = float(raw_cv) if raw_cv is not None else 0
            except (TypeError, ValueError):
                current_value = 0
            start_value = float(goal.get('current') or 0)
            target_value = float(goal.get('target') or 0)

            lower_is_better = goal.get('lower_is_better', False)

            if lower_is_better:
                total_improvement_needed = start_value - target_value
                actual_improvement = start_value - current_value
            else:
                total_improvement_needed = target_value - start_value
                actual_improvement = current_value - start_value

            if total_improvement_needed != 0:
                progress_pct = min(100, max(0, (actual_improvement / total_improvement_needed) * 100))
            else:
                progress_pct = 100 if actual_improvement >= 0 else 0

            achieved = progress_pct >= 100

            progress_list.append({
                **goal,
                'current_value': current_value,
                'progress_pct': progress_pct,
                'achieved': achieved
            })

    return progress_list


def get_time_pressure_minutes(time_pressure: str) -> int:
    """Get the time limit in minutes based on time pressure setting."""
    return TIME_PRESSURE_MINUTES.get(time_pressure, 10)


# Composite round-score weights. Must sum to 1.0. Mirrors the final-grade
# weighting in calculate_overall_grade so per-round and final scores are on
# the same scale. Closes client claim #3 (round score should be a composite
# of decision quality, module application, and business impact).
COMPOSITE_ROUND_WEIGHTS = {
    'decision': 0.50,   # LLM rubric judgment of decision quality
    'metric':   0.30,   # Per-round business impact (priority-weighted % change)
    'vocab':    0.20,   # Module vocabulary application
}


def compute_round_metric_score(metrics_before: Dict, metrics_after: Dict) -> Dict:
    """Compute the per-round metric movement score on a 0-100 scale.

    Mirrors the metric component of calculate_overall_grade, but scoped to a
    single round delta (before this round -> after this round) rather than
    the full initial-vs-final span.

    Returns a dict with normalized_score (0-100), improvements/declines counts,
    and the raw priority-weighted avg pct change for transparency.
    """
    PRIORITY_WEIGHTS = {'high': 1.5, 'medium': 1.0, 'low': 0.6}
    metric_score = 0.0
    total_weight = 0.0
    improvements = 0
    declines = 0

    for k, before in metrics_before.items():
        if k not in metrics_after:
            continue
        # Skip categorical / non-numeric metrics (defends against J1-style data)
        if (before.get('categorical_value') or before.get('non_numeric')
                or isinstance(before.get('value'), str)):
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
            pct_change = av * 10  # bootstrap from zero baseline
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
        normalized = 50  # no movement => neutral

    return {
        'normalized_score': round(normalized, 1),
        'improvements': improvements,
        'declines': declines,
        'weighted_avg_pct_change': round(metric_score / total_weight, 2) if total_weight else 0.0,
    }


def compute_composite_round_score(decision_score: float,
                                   vocab_score: float,
                                   metrics_before: Dict,
                                   metrics_after: Dict,
                                   weights: Dict = None) -> Dict:
    """Compute the player-facing composite round score.

    The composite combines three dimensions (decision quality, module vocabulary,
    business impact this round) into a single 0-100 number on the same scale as
    the final grade. This addresses client feedback that the round-level score
    was a single noisy LLM signal that didn't reflect actual metric movement
    or module mastery.

    Args:
        decision_score: 0-100, the LLM rubric judgment of the decision.
        vocab_score:    0-100, the module-vocabulary application score.
        metrics_before / metrics_after: metric dicts before and after this round.
        weights:        optional override of COMPOSITE_ROUND_WEIGHTS. Must contain
                        keys 'decision', 'metric', 'vocab' summing to 1.0.

    Returns:
        Dict with keys:
            composite          — the headline 0-100 score
            decision_component — weighted contribution from decision_score
            metric_component   — weighted contribution from per-round metric movement
            vocab_component    — weighted contribution from vocab_score
            metric_breakdown   — the full compute_round_metric_score() result
            weights            — the weights actually used (for UI display)
    """
    w = dict(COMPOSITE_ROUND_WEIGHTS)
    if weights:
        w.update(weights)
        total = sum(w.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Composite weights must sum to 1.0 (got {total})")

    decision_score = max(0, min(100, float(decision_score)))
    vocab_score = max(0, min(100, float(vocab_score)))
    metric_breakdown = compute_round_metric_score(metrics_before, metrics_after)
    metric_score = metric_breakdown['normalized_score']

    decision_component = decision_score * w['decision']
    metric_component   = metric_score   * w['metric']
    vocab_component    = vocab_score    * w['vocab']
    composite = decision_component + metric_component + vocab_component

    return {
        'composite': round(composite, 1),
        'decision_component': round(decision_component, 2),
        'metric_component': round(metric_component, 2),
        'vocab_component': round(vocab_component, 2),
        'metric_breakdown': metric_breakdown,
        'weights': w,
    }


# Late-submission penalty thresholds. Closes TIMER_ISSUES.md #2 (flat penalty
# regardless of overtime). Penalty starts at 15% on first second of overtime
# and grows linearly to 50% at 10 minutes overtime, then capped.
_PENALTY_BASE = 0.15
_PENALTY_MAX = 0.50
_PENALTY_RAMP_SECONDS = 600  # 10 min from base to max


def compute_force_submit_penalty(overtime_seconds: float) -> float:
    """Return the late-submission penalty fraction (0.15-0.50) for given overtime.

    Used to scale metric impacts when the player submits after timer expiry.
    Symmetric: positive impacts get reduced by this fraction, negative impacts
    amplified by the same fraction (so a bad late decision is more costly than
    a bad on-time decision).
    """
    if overtime_seconds <= 0:
        return _PENALTY_BASE  # 15% even immediately at expiry
    growth = (overtime_seconds / _PENALTY_RAMP_SECONDS) * (_PENALTY_MAX - _PENALTY_BASE)
    return min(_PENALTY_MAX, _PENALTY_BASE + growth)


def round_time_limit_minutes(round_index: int, time_pressure: str) -> int:
    """Time limit for a given round, applying the Round 1 onboarding bonus.

    Round 1 (round_index == 0) gets +5 min over the configured time_pressure
    when pressure is not 'urgent', so first-time players have room to learn
    the interface. Closes feedback PDF A8/F.
    """
    base = get_time_pressure_minutes(time_pressure)
    if round_index == 0 and time_pressure != "urgent":
        return base + 5
    return base


def calculate_overall_grade(initial_metrics: Dict, final_metrics: Dict, avg_decision_score: float,
                            avg_board_effectiveness: float = None) -> Dict:
    """Calculate overall simulation grade based on metric changes, decision scores, and board effectiveness."""

    # Priority-based weights for grading
    PRIORITY_WEIGHTS = {'high': 1.5, 'medium': 1.0, 'low': 0.6}

    metric_score = 0
    total_weight = 0
    improvements = 0
    declines = 0

    # Grade based on all metrics that exist in both initial and final
    for metric_key in initial_metrics:
        if metric_key in final_metrics:
            raw_init = initial_metrics[metric_key].get('value')
            raw_final = final_metrics[metric_key].get('value')
            try:
                initial_val = float(raw_init) if raw_init is not None else 0
            except (TypeError, ValueError):
                initial_val = 0
            try:
                final_val = float(raw_final) if raw_final is not None else 0
            except (TypeError, ValueError):
                final_val = 0
            priority = (initial_metrics[metric_key].get('priority') or 'medium').lower()
            weight = PRIORITY_WEIGHTS.get(priority, 1.0)

            # Detect direction from metric key
            higher_better = not _is_lower_better(metric_key)

            if initial_val != 0:
                pct_change = ((final_val - initial_val) / abs(initial_val)) * 100
            else:
                pct_change = final_val * 10

            if not higher_better:
                pct_change = -pct_change

            capped_change = max(-20, min(20, pct_change))
            metric_score += capped_change * weight
            total_weight += weight

            if pct_change > 0:
                improvements += 1
            elif pct_change < 0:
                declines += 1

    if total_weight > 0:
        avg_metric_change = metric_score / total_weight
        normalized_metric_score = 50 + (avg_metric_change * 2.5)
        normalized_metric_score = max(0, min(100, normalized_metric_score))
    else:
        normalized_metric_score = 50

    if avg_board_effectiveness is not None:
        final_score = (avg_decision_score * 0.5) + (normalized_metric_score * 0.3) + (avg_board_effectiveness * 0.2)
        board_effectiveness_component = avg_board_effectiveness * 0.2
    else:
        final_score = (avg_decision_score * 0.6) + (normalized_metric_score * 0.4)
        board_effectiveness_component = 0

    final_score = max(0, min(100, final_score))

    if final_score >= 90:
        grade, grade_description = 'A+', 'Outstanding Performance'
    elif final_score >= 85:
        grade, grade_description = 'A', 'Excellent Performance'
    elif final_score >= 80:
        grade, grade_description = 'A-', 'Very Good Performance'
    elif final_score >= 75:
        grade, grade_description = 'B+', 'Good Performance'
    elif final_score >= 70:
        grade, grade_description = 'B', 'Above Average Performance'
    elif final_score >= 65:
        grade, grade_description = 'B-', 'Satisfactory Performance'
    elif final_score >= 60:
        grade, grade_description = 'C+', 'Fair Performance'
    elif final_score >= 55:
        grade, grade_description = 'C', 'Average Performance'
    elif final_score >= 50:
        grade, grade_description = 'C-', 'Below Average Performance'
    elif final_score >= 45:
        grade, grade_description = 'D', 'Poor Performance'
    else:
        grade, grade_description = 'F', 'Needs Significant Improvement'

    return {
        'grade': grade,
        'grade_description': grade_description,
        'final_score': final_score,
        'decision_score_component': avg_decision_score * (0.5 if avg_board_effectiveness is not None else 0.6),
        'metric_score_component': normalized_metric_score * (0.3 if avg_board_effectiveness is not None else 0.4),
        'board_effectiveness_component': board_effectiveness_component,
        'metrics_improved': improvements,
        'metrics_declined': declines,
        'normalized_metric_score': normalized_metric_score,
        'avg_board_effectiveness': avg_board_effectiveness
    }
