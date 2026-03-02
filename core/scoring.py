"""
Scoring, grading, goal generation, and metric impact calculations.
"""

from typing import Dict, List

from core.models import TIME_PRESSURE_MINUTES


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
    initially_opposing = sum(1 for s in member_stances.values()
                             if s.get('stance') == 'OPPOSE')
    convinced = sum(1 for s in member_stances.values()
                    if s.get('convinced_in_round') is not None)

    total_debate_exchanges = sum(s.get('debate_exchanges', 0) for s in member_stances.values())

    # 1. Initial approval rate (25 points max)
    initial_approval_score = (initially_approving / max(total_members, 1)) * 25

    # 2. Consultation alignment (25 points max)
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
    # Metrics where lower values are better
    LOWER_IS_BETTER_KEYWORDS = {'churn', 'attrition', 'risk', 'debt', 'turnover', 'cost', 'defect'}

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

    goals = []
    for key, metric in metrics.items():
        raw_val = metric.get('value')
        try:
            current = float(raw_val) if raw_val is not None else 0
        except (TypeError, ValueError):
            current = 0
        unit = metric.get('unit', '')
        description = metric.get('description', key.replace('_', ' ').title())
        priority = (metric.get('priority') or 'medium').lower()

        # Detect direction
        key_lower = key.lower()
        lower_is_better = any(kw in key_lower for kw in LOWER_IS_BETTER_KEYWORDS)

        # Detect category
        category = 'General'
        for kw, cat in CATEGORY_MAP.items():
            if kw in key_lower or kw in description.lower():
                category = cat
                break

        # Calculate target delta based on unit type, scaled by rounds
        if unit == '%':
            base_delta = 3.0
        elif unit in ('count', 'score'):
            base_delta = max(2, abs(current) * 0.05) if current != 0 else 2
        elif unit == 'employees':
            continue  # Skip headcount — not a performance goal
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
            current_value = current_metrics[metric_key]['value']
            start_value = goal['current']
            target_value = goal['target']

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


def calculate_overall_grade(initial_metrics: Dict, final_metrics: Dict, avg_decision_score: float,
                            avg_board_effectiveness: float = None) -> Dict:
    """Calculate overall simulation grade based on metric changes, decision scores, and board effectiveness."""
    # Metrics where lower values are better
    LOWER_IS_BETTER_KEYWORDS = {'churn', 'attrition', 'risk', 'debt', 'turnover', 'cost', 'defect'}

    # Priority-based weights for grading
    PRIORITY_WEIGHTS = {'high': 1.5, 'medium': 1.0, 'low': 0.6}

    metric_score = 0
    total_weight = 0
    improvements = 0
    declines = 0

    # Grade based on all metrics that exist in both initial and final
    for metric_key in initial_metrics:
        if metric_key in final_metrics:
            initial_val = initial_metrics[metric_key]['value']
            final_val = final_metrics[metric_key]['value']
            priority = (initial_metrics[metric_key].get('priority') or 'medium').lower()
            weight = PRIORITY_WEIGHTS.get(priority, 1.0)

            # Detect direction from metric key
            key_lower = metric_key.lower()
            higher_better = not any(kw in key_lower for kw in LOWER_IS_BETTER_KEYWORDS)

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
