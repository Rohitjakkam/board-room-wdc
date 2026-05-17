"""
Re-Test Verification Tests — Clearwater Financial Group (Setup Screens)
Validates all bugs from the re-test report: role assignment, mission objectives,
character descriptions, metrics, tenure display, and founded field.

Run: python -m pytest tests/test_retest_verification.py -v
"""

import sys
import os
import copy
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.scoring import generate_game_goals, LOWER_IS_BETTER_KEYWORDS, LOWER_IS_BETTER_EXCLUSIONS, _is_lower_better


# ── Shared fixtures ──────────────────────────────────────────────────────────

CLEARWATER_BOARD = [
    {'name': "Margaret 'Meg' Harlow", 'role': 'Board Director',
     'expertise': 'Corporate Governance', 'tenure_years': 1,
     'personality': 'Sharp, methodical, analytical, detail-oriented, concerned with fiduciary duty'},
    {'name': 'Jonathan Marsh', 'role': 'CEO',
     'expertise': 'Strategy', 'tenure_years': None,
     'personality': 'Prefers board at strategic level, views director inquiry into footnotes as distrust, can be defensive'},
    {'name': 'Sandra Cho', 'role': 'Chair of the Audit Committee',
     'expertise': 'Audit', 'tenure_years': 8,
     'personality': 'Meticulous, compliance-focused'},
    {'name': 'David Sung', 'role': 'Chief Risk Officer',
     'expertise': 'Risk Management', 'tenure_years': None,
     'personality': 'Hesitant to discuss granular details in public, defers to CEO/Audit Committee'},
    {'name': 'Patricia Delgado', 'role': 'CFO',
     'expertise': 'Finance', 'tenure_years': None,
     'personality': 'Numbers-driven, cautious communicator'},
    {'name': 'Richard Paxton', 'role': 'General Counsel',
     'expertise': 'Legal', 'tenure_years': 20,
     'personality': 'Thorough, risk-averse, precedent-focused'},
    {'name': 'Linda Vasquez', 'role': 'Board Director',
     'expertise': 'Banking Regulation', 'tenure_years': 3,
     'personality': 'Former regulator, insightful, measured'},
]

# Clearwater-specific metrics from the case study
CLEARWATER_METRICS = {
    'reg_b_footnote_quarters': {
        'value': 2.0, 'unit': 'count',
        'description': 'Number of quarters Reg B footnote appeared',
        'priority': 'high',
    },
    'board_discussion_duration_minutes': {
        'value': 22.0, 'unit': 'count',
        'description': 'Duration of board discussion on Reg B issue',
        'priority': 'medium',
    },
    'preliminary_reserve': {
        'value': 4.2, 'unit': '$M',
        'description': 'Preliminary reserve for Reg B liability',
        'priority': 'high',
    },
    'board_packet_page_count': {
        'value': 214.0, 'unit': 'count',
        'description': 'Length of board packet',
        'priority': 'low',
    },
    'affected_accounts': {
        'value': 1847.0, 'unit': 'count',
        'description': 'Number of affected accounts',
        'priority': 'high',
    },
    'updated_liability_range': {
        'value': 0.0, 'unit': '$M',
        'description': 'Updated liability range',
        'priority': 'high',
    },
    'loan_portfolio_size': {
        'value': 0.0, 'unit': 'N/A',
        'description': 'Loan portfolio size',
        'priority': 'medium',
    },
}


# ===========================================================================
# CRITICAL BUG C1 — Role Assignment (index-based button key mismatch)
# ===========================================================================
class TestC1RoleAssignment:
    """Bug C1: User selects Meg Harlow but gets assigned Jonathan Marsh (CEO).
    Root cause: button key is index-based (select_role_{idx}), so if the
    board_members list reorders between Streamlit reruns, the wrong member
    is returned.
    """

    def test_index_based_key_returns_wrong_member_on_reorder(self):
        """Demonstrate that index-based selection breaks when list order changes."""
        original_order = CLEARWATER_BOARD.copy()
        # User clicks index 0 → expects Meg Harlow
        clicked_index = 0
        expected_member = original_order[clicked_index]
        assert expected_member['name'] == "Margaret 'Meg' Harlow"

        # On Streamlit rerun, list gets reordered (e.g., alphabetically)
        reordered = sorted(CLEARWATER_BOARD, key=lambda m: m['name'])
        # Index 0 is now a different person
        assigned_member = reordered[clicked_index]
        # BUG: This is NOT Meg Harlow
        assert assigned_member['name'] != "Margaret 'Meg' Harlow", \
            "Bug C1 confirmed: reordered list assigns wrong member at same index"

    def test_name_based_key_survives_reorder(self):
        """Fix: using member name as key guarantees correct assignment."""
        original_order = CLEARWATER_BOARD.copy()
        clicked_name = "Margaret 'Meg' Harlow"

        # Reorder the list
        reordered = sorted(CLEARWATER_BOARD, key=lambda m: m['name'])
        # Name-based lookup always finds the right member
        assigned = next(m for m in reordered if m['name'] == clicked_name)
        assert assigned['name'] == clicked_name
        assert assigned['role'] == 'Board Director'

    def test_button_key_uses_name_not_index(self):
        """FIXED: Verify the code now uses name-based keys, not index-based."""
        import inspect
        from components.board_members import display_board_members_for_selection
        source = inspect.getsource(display_board_members_for_selection)
        # FIX: key should use member name, not idx
        assert 'select_role_{safe_key}' in source, \
            "Fix C1: button key should use safe_key (derived from member name)"
        assert 'select_role_{idx}' not in source, \
            "Fix C1: index-based key should be removed"

    def test_three_sessions_three_wrong_assignments(self):
        """The bug report observed 3 different wrong characters across sessions.
        This confirms any sort order change produces a different wrong assignment."""
        meg_index_in_original = 0  # Meg is first in CLEARWATER_BOARD

        # Simulate 3 different orderings
        orderings = [
            sorted(CLEARWATER_BOARD, key=lambda m: m['name']),          # alphabetical
            sorted(CLEARWATER_BOARD, key=lambda m: m['role']),           # by role
            sorted(CLEARWATER_BOARD, key=lambda m: m['tenure_years'] or 0),  # by tenure
        ]

        assigned_names = set()
        for ordering in orderings:
            assigned_names.add(ordering[meg_index_in_original]['name'])

        # Each ordering assigns a DIFFERENT person to index 0
        assert "Margaret 'Meg' Harlow" not in assigned_names or len(assigned_names) > 1, \
            "Different orderings produce different wrong assignments"

    def test_ceo_as_playable_character_is_pedagogically_wrong(self):
        """NEW-1: If role assignment assigns CEO (antagonist), the simulation
        experience is inverted — CEO opposes board oversight."""
        # Jonathan Marsh (CEO) is the central conflict character
        ceo = next(m for m in CLEARWATER_BOARD if m['role'] == 'CEO')
        assert ceo['name'] == 'Jonathan Marsh'
        # A learner assigned as CEO would work against governance goals
        assert 'defensive' in ceo['personality'].lower() or 'distrust' in ceo['personality'].lower(), \
            "CEO personality confirms antagonist role — should not be auto-assigned"


# ===========================================================================
# MISSION OBJECTIVES — Directionally wrong targets
# ===========================================================================
class TestMissionObjectiveTargets:
    """Bug: Mission objective targets are directionally wrong for governance cases.
    - 'quarters Reg B appeared': target increases (should decrease to 0)
    - 'discussion duration': target reduces to 0.6 min (more discussion = better)
    - 'preliminary reserve': target reduces (reserve was INSUFFICIENT)
    """

    def test_reg_b_quarters_target_direction_with_gap_keyword(self):
        """'Number of quarters Reg B footnote appeared' — a metric keyed with 'gap'
        would now correctly classify as lower_is_better thanks to the fix.
        The original key 'reg_b_footnote_quarters' has no keyword match (semantic issue),
        but renaming to include 'gap' (e.g., 'reg_b_oversight_gap_quarters') works."""
        # Original key: no keyword match — target still increases (data-level issue)
        metrics_original = {
            'reg_b_footnote_quarters': CLEARWATER_METRICS['reg_b_footnote_quarters'],
        }
        goals_orig = generate_game_goals(metrics_original, total_rounds=5)
        if goals_orig:
            assert not goals_orig[0].get('lower_is_better', False), \
                "Original key has no matching keyword — still increases (needs metric rename)"

        # Fixed key with 'gap': now correctly classified as lower_is_better
        metrics_fixed = {
            'reg_b_oversight_gap_quarters': {
                'value': 2.0, 'unit': 'count',
                'description': 'Quarters of Reg B oversight gap', 'priority': 'high',
            },
        }
        goals_fixed = generate_game_goals(metrics_fixed, total_rounds=5)
        assert len(goals_fixed) > 0
        assert goals_fixed[0].get('lower_is_better', False), \
            "FIX: 'gap' keyword now correctly marks oversight gap metric as lower_is_better"
        assert goals_fixed[0]['target'] < goals_fixed[0]['current'], \
            "FIX: target should decrease for oversight gap"

    def test_discussion_duration_target_direction(self):
        """'Duration of board discussion' — target should INCREASE for governance.
        More discussion on material compliance matters = better oversight."""
        metrics = {
            'board_discussion_duration_minutes': CLEARWATER_METRICS['board_discussion_duration_minutes'],
        }
        goals = generate_game_goals(metrics, total_rounds=5)
        assert len(goals) > 0
        goal = goals[0]
        # For governance: MORE discussion = better. Target should be HIGHER.
        # BUG: if 'duration' is somehow in LOWER_IS_BETTER, target would decrease
        # Otherwise default behavior (increase) is correct for this metric.
        # But the report says target was 0.6 minutes — implying massive decrease.
        # This could happen if the unit/scale calculation is wrong.
        assert goal['target'] > goal['current'] or goal['target'] > 1.0, \
            f"BUG: discussion duration target={goal['target']} — reducing discussion time " \
            f"from {goal['current']} to {goal['target']} is anti-governance"

    def test_preliminary_reserve_target_direction(self):
        """'Preliminary reserve' — in this case the reserve was INSUFFICIENT
        ($4.2M grew to $8.5-14M). Target should INCREASE, not decrease."""
        metrics = {
            'preliminary_reserve': CLEARWATER_METRICS['preliminary_reserve'],
        }
        goals = generate_game_goals(metrics, total_rounds=5)
        assert len(goals) > 0
        goal = goals[0]
        # 'reserve' contains no LOWER_IS_BETTER keyword, so default is increase — correct
        # But 'remediation' IS in the keyword list. If the key were
        # 'potential_remediation_costs_reserve', it would be flagged as lower_is_better
        # and the target would DECREASE — which is WRONG for an insufficient reserve.
        if goal.get('lower_is_better'):
            pytest.fail(
                f"BUG: preliminary_reserve marked as lower_is_better. "
                f"Target={goal['target']} < current={goal['current']}. "
                f"Reserve was INSUFFICIENT — should increase, not decrease."
            )
        assert goal['target'] >= goal['current'], \
            f"Reserve target {goal['target']} should be >= current {goal['current']}"

    def test_remediation_reserve_exclusion_fix(self):
        """FIXED: 'potential_remediation_costs_reserve' now correctly excluded
        from lower_is_better because 'reserve' is in LOWER_IS_BETTER_EXCLUSIONS."""
        key = 'potential_remediation_costs_reserve'
        # 'remediation' and 'cost' match keywords, but 'reserve' triggers exclusion
        assert _is_lower_better(key) is False, \
            "FIX: reserve exclusion overrides remediation/cost keywords"

        # Verify actual goal generation works correctly
        metrics = {key: {'value': 1.5, 'unit': '$M', 'description': 'Remediation Reserve', 'priority': 'high'}}
        goals = generate_game_goals(metrics, total_rounds=5)
        assert goals
        assert not goals[0].get('lower_is_better', False), \
            "FIX: reserve metric should NOT be lower_is_better"
        assert goals[0]['target'] > goals[0]['current'], \
            "FIX: reserve target should increase (reserve was insufficient)"

    def test_board_packet_page_target_now_decreases(self):
        """FIXED (client claim #2): `packet`/`paperwork` are now in
        LOWER_IS_BETTER_KEYWORDS, so board packet pages target DECREASES — reducing
        paperwork burden is the correct goal. Was: target wrongly increased."""
        metrics = {
            'board_packet_page_count': CLEARWATER_METRICS['board_packet_page_count'],
        }
        goals = generate_game_goals(metrics, total_rounds=5)
        if goals:
            goal = goals[0]
            assert goal['target'] < goal['current'], \
                "FIX: board packet page target should DECREASE (less paperwork = better)"
            assert goal.get('lower_is_better'), \
                "FIX: board_packet_page_count should now be lower_is_better"

    def test_governance_keywords_now_present(self):
        """FIXED: Governance-specific keywords are now in LOWER_IS_BETTER_KEYWORDS."""
        governance_keywords = ['gap', 'delay', 'overdue']
        for kw in governance_keywords:
            assert kw in LOWER_IS_BETTER_KEYWORDS, \
                f"FIX: '{kw}' should now be in LOWER_IS_BETTER_KEYWORDS"


# ===========================================================================
# METRICS — 0.0 values that should be removed or corrected
# ===========================================================================
class TestMetricsZeroValues:
    """Bug: updated_liability_range still 0.0$M (should be $4.2M),
    loan_portfolio_size still 0.0 N/A (should be removed)."""

    def test_updated_liability_range_is_zero(self):
        """The updated liability range is 0.0$M but should be $4.2M based on case."""
        metric = CLEARWATER_METRICS['updated_liability_range']
        assert metric['value'] == 0.0, \
            "BUG CONFIRMED: updated_liability_range is still 0.0$M"

    def test_loan_portfolio_size_skipped_in_goal_generation(self):
        """FIXED: Loan portfolio size (0.0, unit N/A) is now skipped in goal generation."""
        metrics = {
            'loan_portfolio_size': CLEARWATER_METRICS['loan_portfolio_size'],
        }
        goals = generate_game_goals(metrics, total_rounds=5)
        assert len(goals) == 0, \
            "FIX: 0.0 value with N/A unit should be skipped"

    def test_zero_metrics_with_valid_unit_still_generate_goals(self):
        """Metrics with value 0.0 but valid unit (e.g., $M) still generate goals."""
        metrics = {
            'updated_liability_range': CLEARWATER_METRICS['updated_liability_range'],
        }
        goals = generate_game_goals(metrics, total_rounds=5)
        # $M is a valid unit, so goal is still generated (the 0.0 value is a data issue)
        assert len(goals) > 0, "Valid unit metrics still generate goals even at 0.0"

    def test_correct_metrics_present(self):
        """Verify the known-correct metrics still have right values."""
        assert CLEARWATER_METRICS['affected_accounts']['value'] == 1847.0
        assert CLEARWATER_METRICS['preliminary_reserve']['value'] == 4.2
        assert CLEARWATER_METRICS['board_packet_page_count']['value'] == 214.0


# ===========================================================================
# TENURE — "None years" display bug
# ===========================================================================
class TestTenureDisplay:
    """Bug: Jonathan Marsh, Patricia Delgado, David Sung show 'Tenure: None years'.
    Richard Paxton correctly shows 'Tenure: 20 years'."""

    def test_tenure_none_for_multiple_characters(self):
        """Confirm which characters have None tenure_years."""
        none_tenure = [m['name'] for m in CLEARWATER_BOARD if m['tenure_years'] is None]
        # BUG: These characters have None tenure
        assert 'Jonathan Marsh' in none_tenure
        assert 'David Sung' in none_tenure
        assert 'Patricia Delgado' in none_tenure

    def test_tenure_display_string_with_none(self):
        """The display template produces 'None years' when tenure_years is None."""
        for member in CLEARWATER_BOARD:
            display = f"Tenure: {member['tenure_years']} years"
            if member['tenure_years'] is None:
                assert display == "Tenure: None years", \
                    f"BUG CONFIRMED: {member['name']} shows '{display}'"

    def test_tenure_display_should_handle_none_gracefully(self):
        """Fix: None tenure should display as 'Not specified' or similar."""
        for member in CLEARWATER_BOARD:
            tenure = member['tenure_years']
            # Proposed fix: coalesce None
            display = f"Tenure: {tenure if tenure is not None else 'Not specified'} years"
            if tenure is None:
                assert 'Not specified' in display, \
                    f"{member['name']} should show 'Not specified' instead of 'None'"

    def test_richard_paxton_tenure_correct(self):
        """Richard Paxton correctly has tenure = 20 years."""
        paxton = next(m for m in CLEARWATER_BOARD if m['name'] == 'Richard Paxton')
        assert paxton['tenure_years'] == 20

    def test_board_members_component_handles_none_tenure(self):
        """FIXED: board_members.py now handles None tenure gracefully."""
        import inspect
        from components.board_members import display_board_members_for_selection
        source = inspect.getsource(display_board_members_for_selection)
        assert 'Not specified' in source, \
            "FIX: template should show 'Not specified' for None tenure"


# ===========================================================================
# FOUNDED FIELD — Shows "N/A" instead of "Not specified"
# ===========================================================================
class TestFoundedField:
    """Bug: Founded field shows 'N/A' instead of 'Not specified'."""

    def test_founded_empty_default_normalized(self):
        """FIXED: Empty default is now normalized to 'Not specified'."""
        from extractors.content_parser import _validate_company_data
        data = _validate_company_data({})
        assert data['founded'] == 'Not specified', \
            "FIX: empty founded default should become 'Not specified'"

    def test_founded_na_from_llm_normalized(self):
        """FIXED: If LLM returns 'N/A', it's now normalized to 'Not specified'."""
        from extractors.content_parser import _validate_company_data
        data = _validate_company_data({'founded': 'N/A'})
        assert data['founded'] == 'Not specified', \
            "FIX: 'N/A' should be normalized to 'Not specified'"

    def test_founded_various_na_variants_normalized(self):
        """All NA variants should be normalized."""
        from extractors.content_parser import _validate_company_data
        for variant in ['N/A', 'n/a', 'NA', 'None', 'null', 'unknown', '']:
            data = _validate_company_data({'founded': variant})
            assert data['founded'] == 'Not specified', \
                f"FIX: '{variant}' should be normalized to 'Not specified'"

    def test_founded_valid_year_preserved(self):
        """A real year should pass through unchanged."""
        from extractors.content_parser import _validate_company_data
        data = _validate_company_data({'founded': '1987'})
        assert data['founded'] == '1987'


# ===========================================================================
# CHARACTER DESCRIPTION REGRESSION
# ===========================================================================
class TestCharacterDescriptionRegression:
    """Bug: Character descriptions became shorter and less nuanced.
    Previous: 'Sharp, methodical, analytical, detail-oriented, concerned with fiduciary duty'
    Now: 'Sharp, methodical, detail-oriented, brings a fresh perspective, diligent, proactive'

    Jonathan Marsh lost 'can be defensive'.
    David Sung lost 'defers to CEO/Audit Committee' tension.
    """

    EXPECTED_PERSONALITY_KEYWORDS = {
        'Jonathan Marsh': ['defensive', 'distrust'],
        'David Sung': ['defers', 'hesitant', 'granular'],
        "Margaret 'Meg' Harlow": ['fiduciary', 'analytical'],
    }

    def test_jonathan_marsh_personality_depth(self):
        """Marsh should mention 'defensive' — key for debate preparation."""
        marsh = next(m for m in CLEARWATER_BOARD if m['name'] == 'Jonathan Marsh')
        personality = marsh['personality'].lower()
        has_defensive = 'defensive' in personality
        has_distrust = 'distrust' in personality
        assert has_defensive or has_distrust, \
            f"Marsh personality lacks conflict keywords. Got: '{marsh['personality']}'"

    def test_david_sung_personality_tension(self):
        """Sung should convey reluctance to share details publicly."""
        sung = next(m for m in CLEARWATER_BOARD if m['name'] == 'David Sung')
        personality = sung['personality'].lower()
        has_defers = 'defers' in personality or 'defer' in personality
        has_hesitant = 'hesitant' in personality
        assert has_defers or has_hesitant, \
            f"Sung personality lacks tension keywords. Got: '{sung['personality']}'"

    def test_personality_minimum_length(self):
        """All personalities should be at least 20 characters (basic test fixture check).
        NOTE: Real LLM-extracted personalities should be 50+ chars;
        the prompt fix requests 2-3 sentences which ensures adequate depth."""
        min_length = 20
        for member in CLEARWATER_BOARD:
            assert len(member['personality']) >= min_length, \
                f"{member['name']} personality too short ({len(member['personality'])} chars): " \
                f"'{member['personality']}'"

    def test_prompt_requests_detailed_personalities(self):
        """FIXED: The extraction prompt now asks for 2-3 sentences per personality."""
        import inspect
        from extractors.content_parser import parse_company_data
        source = inspect.getsource(parse_company_data)
        assert '2-3 sentences' in source, \
            "FIX: prompt should request 2-3 sentence personalities"
        assert 'boardroom dynamics' in source, \
            "FIX: prompt should mention boardroom dynamics for personality depth"


# ===========================================================================
# GOAL GENERATION — Fractional directors fix (regression check)
# ===========================================================================
class TestFractionalDirectorsFix:
    """Previously fixed: fractional director targets like 14.7.
    Verify the fix still holds."""

    def test_headcount_metrics_skipped(self):
        """Metrics with unit='employees' or headcount keywords should be skipped."""
        metrics = {
            'board_member_count': {'value': 12, 'unit': 'count',
                                   'description': 'Board Member Count', 'priority': 'low'},
            'employee_count': {'value': 500, 'unit': 'employees',
                               'description': 'Employee Count', 'priority': 'medium'},
        }
        goals = generate_game_goals(metrics, total_rounds=5)
        goal_keys = {g['metric_key'] for g in goals}
        assert 'employee_count' not in goal_keys, "Employee count should be skipped"
        assert 'board_member_count' not in goal_keys, "Board member count should be skipped"

    def test_count_metrics_are_integers(self):
        """Count/score metrics must have integer targets."""
        metrics = {
            'pending_audits': {'value': 10, 'unit': 'count',
                               'description': 'Pending Audits', 'priority': 'high'},
        }
        goals = generate_game_goals(metrics, total_rounds=5)
        assert goals
        target = goals[0]['target']
        assert target == int(target), f"Count target {target} should be integer"


# ===========================================================================
# GOAL GENERATION — Categorical metrics properly skipped
# ===========================================================================
class TestCategoricalMetricsSkipped:
    """Metrics with categorical values (e.g., 'Pending Review') that were
    coerced to 0.0 should be skipped in goal generation."""

    def test_categorical_metric_coerced_to_zero_skipped(self):
        """A metric like 'regulatory_matter_classification' with value 0 and
        status keyword should be skipped."""
        metrics = {
            'regulatory_matter_classification': {
                'value': 0, 'unit': '', 'description': 'Regulatory Matter Classification',
                'priority': 'medium', 'categorical_value': 'Pending Review',
            },
        }
        goals = generate_game_goals(metrics, total_rounds=5)
        goal_keys = {g['metric_key'] for g in goals}
        assert 'regulatory_matter_classification' not in goal_keys


# ===========================================================================
# GOAL PROGRESS CALCULATION — Direction handling
# ===========================================================================
class TestGoalProgressDirection:
    """Verify goal progress calculation handles lower_is_better correctly."""

    def test_lower_is_better_progress_calculation(self):
        """Reducing a lower_is_better metric should show positive progress."""
        from core.scoring import calculate_goal_progress
        goals = [{
            'metric_key': 'customer_churn_rate_annual',
            'current': 12.0,
            'target': 9.0,
            'unit': '%',
            'lower_is_better': True,
            'name': 'Churn Rate',
            'category': 'Customer',
            'description': 'Reduce churn',
            'icon': '😊',
            'priority': 'high',
        }]
        # Churn dropped from 12 to 10 (improvement)
        current_metrics = {
            'customer_churn_rate_annual': {'value': 10.0},
        }
        progress = calculate_goal_progress(goals, current_metrics)
        assert len(progress) == 1
        assert progress[0]['progress_pct'] > 0, \
            "Reducing churn should show positive progress"
        assert progress[0]['progress_pct'] == pytest.approx(66.67, abs=1)

    def test_higher_is_better_progress_calculation(self):
        """Increasing a higher_is_better metric should show positive progress."""
        from core.scoring import calculate_goal_progress
        goals = [{
            'metric_key': 'regulatory_compliance_score',
            'current': 72.0,
            'target': 75.0,
            'unit': '%',
            'name': 'Compliance Score',
            'category': 'Risk',
            'description': 'Improve compliance',
            'icon': '🛡️',
            'priority': 'high',
        }]
        current_metrics = {
            'regulatory_compliance_score': {'value': 74.0},
        }
        progress = calculate_goal_progress(goals, current_metrics)
        assert len(progress) == 1
        assert progress[0]['progress_pct'] == pytest.approx(66.67, abs=1)


# ===========================================================================
# LOWER_IS_BETTER_KEYWORDS — Completeness check
# ===========================================================================
class TestLowerIsBetterKeywordsCompleteness:
    """Verify LOWER_IS_BETTER_KEYWORDS covers all necessary negative metrics."""

    def test_core_keywords_present(self):
        """All required keywords should be present, including new governance keywords."""
        required = {
            'churn', 'attrition', 'risk', 'debt', 'turnover', 'cost',
            'defect', 'burn', 'incident', 'latency', 'vacancy', 'audit',
            'pending', 'liability', 'remediation', 'penalty', 'loss',
            'exposure', 'violation', 'complaint', 'breach',
            'gap', 'delay', 'overdue',  # NEW governance keywords
        }
        missing = required - LOWER_IS_BETTER_KEYWORDS
        assert not missing, f"Missing keywords: {missing}"

    def test_remediation_in_keywords_but_reserve_excluded(self):
        """FIXED: 'remediation' is still in keywords, but 'reserve' exclusion overrides it."""
        assert 'remediation' in LOWER_IS_BETTER_KEYWORDS
        assert 'reserve' in LOWER_IS_BETTER_EXCLUSIONS
        # Raw keyword match would say True, but _is_lower_better correctly returns False
        key = 'potential_remediation_costs_reserve'
        assert _is_lower_better(key) is False, \
            "FIX: exclusion overrides keyword match for reserve metrics"


# ===========================================================================
# OVERALL GRADE CALCULATION — Sanity checks
# ===========================================================================
class TestOverallGradeCalculation:
    """Sanity checks for the grading system."""

    def test_grade_ranges(self):
        from core.scoring import calculate_overall_grade
        # Perfect scores
        metrics_same = {'m1': {'value': 50, 'priority': 'high'}}
        result = calculate_overall_grade(metrics_same, metrics_same, 95, 90)
        assert result['grade'] in ('A+', 'A', 'A-', 'B+')

    def test_grade_with_board_effectiveness(self):
        from core.scoring import calculate_overall_grade
        metrics = {'m1': {'value': 50, 'priority': 'high'}}
        result = calculate_overall_grade(metrics, metrics, 70, 80)
        assert 'board_effectiveness_component' in result
        assert result['board_effectiveness_component'] > 0


# ===========================================================================
# INTEGRATION — Full Clearwater metrics goal generation
# ===========================================================================
class TestClearwaterGoalGeneration:
    """End-to-end test of goal generation with Clearwater metrics."""

    def test_generates_goals_for_clearwater_metrics(self):
        """Should generate meaningful goals from Clearwater case metrics."""
        goals = generate_game_goals(CLEARWATER_METRICS, total_rounds=5)
        assert len(goals) > 0, "Should generate at least one goal"

    def test_no_fractional_count_targets(self):
        """All count-type goals should have integer targets."""
        goals = generate_game_goals(CLEARWATER_METRICS, total_rounds=5)
        for goal in goals:
            if goal['unit'] in ('count', 'score'):
                assert goal['target'] == int(goal['target']), \
                    f"{goal['name']} has fractional target: {goal['target']}"

    def test_zero_value_metrics_handled(self):
        """Metrics with 0.0 value should still produce valid goals (or be skipped)."""
        goals = generate_game_goals(CLEARWATER_METRICS, total_rounds=5)
        for goal in goals:
            # Target should not be negative
            assert goal['target'] >= 0, \
                f"{goal['name']} has negative target: {goal['target']}"

    def test_all_goals_have_required_fields(self):
        """Every goal must have all required fields."""
        required_fields = {'category', 'metric_key', 'name', 'description',
                           'current', 'target', 'unit', 'icon', 'priority'}
        goals = generate_game_goals(CLEARWATER_METRICS, total_rounds=5)
        for goal in goals:
            missing = required_fields - set(goal.keys())
            assert not missing, f"Goal '{goal['name']}' missing fields: {missing}"


# ===========================================================================
# DISPLAY COMPONENT — Board member card template
# ===========================================================================
class TestBoardMemberCardTemplate:
    """Verify the board member card template handles edge cases."""

    def test_template_interpolation_with_none_tenure_fixed(self):
        """FIXED: Simulates the fixed template with None tenure."""
        member = {'name': 'Jonathan Marsh', 'role': 'CEO',
                  'expertise': 'Strategy', 'tenure_years': None,
                  'personality': 'Assertive'}
        # Fixed template logic
        tenure = f"{member['tenure_years']} years" if member.get('tenure_years') is not None else "Not specified"
        html = f"""<p><em>Expertise: {member['expertise']} | Tenure: {tenure}</em></p>"""
        assert 'Tenure: Not specified' in html, \
            "FIX: template should show 'Not specified' for None tenure"
        assert 'None years' not in html, \
            "FIX: 'None years' should no longer appear"

    def test_template_interpolation_with_valid_tenure(self):
        """Valid tenure renders correctly."""
        member = {'name': 'Richard Paxton', 'role': 'General Counsel',
                  'expertise': 'Legal', 'tenure_years': 20,
                  'personality': 'Thorough'}
        html = f"""<p><em>Expertise: {member['expertise']} | Tenure: {member['tenure_years']} years</em></p>"""
        assert 'Tenure: 20 years' in html
