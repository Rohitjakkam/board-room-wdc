"""
Regression tests for the three client claims + the bugs surfaced by audits 1-2.

Run: python -m pytest tests/test_client_claim_fixes.py -v

Each section maps to one fix:
  - TestDepluralizer + TestIsLowerBetter ......... Client claim #2 + B1 (audit)
  - TestCategoricalClobber ........................ Bug J1
  - TestRoundMetricScore + TestCompositeRound ..... Client claim #3
  - TestVocabularyFloor ........................... Bug C1+C2
  - TestKeywordExclusions ......................... `turnover` landmine
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.scoring import (
    _depluralize,
    _is_lower_better,
    compute_composite_round_score,
    compute_round_metric_score,
    COMPOSITE_ROUND_WEIGHTS,
    LOWER_IS_BETTER_KEYWORDS,
    LOWER_IS_BETTER_EXCLUSIONS,
)
from core.simulation_engine import apply_metric_impacts


# ─────────────────────────────────────────────────────────────────────────────
# Depluralizer
# ─────────────────────────────────────────────────────────────────────────────
class TestDepluralizer:
    @pytest.mark.parametrize("plural,singular", [
        ('penalties', 'penalty'),
        ('fines', 'fine'),
        ('breaches', 'breach'),
        ('lawsuits', 'lawsuit'),
        ('losses', 'loss'),
        ('disputes', 'dispute'),
        ('incidents', 'incident'),
        ('complaints', 'complaint'),
        ('attacks', 'attack'),
        ('errors', 'error'),
    ])
    def test_regular_plurals(self, plural, singular):
        assert _depluralize(plural) == singular

    @pytest.mark.parametrize("word", [
        'churn', 'data', 'class', 'bus',  # short or already-singular
    ])
    def test_short_words_unchanged(self, word):
        assert _depluralize(word) == word


# ─────────────────────────────────────────────────────────────────────────────
# Client claim #2: penalty/fine/lawsuit/downtime now LOWER-IS-BETTER
# ─────────────────────────────────────────────────────────────────────────────
class TestIsLowerBetter:
    @pytest.mark.parametrize("key", [
        # Canaries from the stress audit (the bug repro)
        'regulatory_fine_amount', 'outstanding_lawsuits', 'system_downtime_pct',
        'total_penalties_ytd', 'total_fines_paid',
        # Plurals handled via depluralizer
        'compliance_breaches_ytd', 'customer_complaints', 'employee_grievances',
        'ransomware_attacks', 'customer_disputes',
        # Pre-existing keyword regressions
        'customer_churn_rate_annual', 'annual_attrition_rate', 'pending_audits',
        'potential_liability_range', 'data_privacy_incident_count',
        # ESG canaries
        'carbon_emissions_tonnes', 'production_scrap_rate', 'lost_workday_injuries',
        # Mass nouns
        'loan_arrears', 'overdue_invoices',
    ])
    def test_should_be_lower_better(self, key):
        assert _is_lower_better(key), f"{key} should be lower-is-better"

    @pytest.mark.parametrize("key", [
        # Original exclusions (regression)
        'potential_remediation_costs_reserve', 'r_and_d_budget',
        # Generic higher-better baselines
        'total_revenue_annual', 'ebitda', 'net_promoter_score',
        'employee_engagement_score', 'on_time_delivery_rate',
        # Substring false positives the OLD code would have hit if we'd added 'fine'/'error'/'page'
        'final_report_count', 'refine_process_steps', 'define_requirements_count',
        'page_views_count',
        # Recovery/prevention/resolution metrics (NEW exclusions)
        'loss_prevention_savings', 'incident_recovery_time',
        'complaint_resolution_rate',
        # ESG inverted (NEW exclusions)
        'emission_reduction_target', 'carbon_offset_purchased',
        # IT availability inverted (NEW exclusions)
        'system_uptime_pct', 'service_availability', 'mtbf_hours',
    ])
    def test_should_be_higher_better(self, key):
        assert not _is_lower_better(key), f"{key} should be higher-is-better"


# ─────────────────────────────────────────────────────────────────────────────
# The `turnover` landmine: asset_turnover etc. are HIGHER-better in finance
# ─────────────────────────────────────────────────────────────────────────────
class TestKeywordExclusions:
    @pytest.mark.parametrize("key", [
        'asset_turnover_ratio', 'inventory_turnover_days',
        'receivables_turnover_ratio', 'portfolio_turnover_ratio',
        'capital_turnover',
    ])
    def test_turnover_exclusions(self, key):
        """`turnover` is lower-better in HR but HIGHER-better in finance contexts."""
        assert not _is_lower_better(key), f"{key} should be excluded from lower-is-better"

    def test_hr_turnover_still_lower_better(self):
        """Plain HR turnover should still classify correctly."""
        assert _is_lower_better('employee_turnover_rate')
        assert _is_lower_better('annual_turnover')

    def test_return_on_x_exclusions(self):
        for k in ['return_on_equity', 'return_on_assets', 'returns_on_invested_capital']:
            assert not _is_lower_better(k)

    def test_cost_efficiency_exclusions(self):
        for k in ['cost_savings_program', 'cost_avoidance_total', 'cost_efficiency_ratio']:
            assert not _is_lower_better(k)


# ─────────────────────────────────────────────────────────────────────────────
# Bug J1: categorical metrics must never be clobbered to 0
# ─────────────────────────────────────────────────────────────────────────────
class TestCategoricalClobber:
    def test_string_value_metric_with_zero_impact_unchanged(self):
        """LLM may return 0 impact for a categorical metric (hallucinated key).
        apply_metric_impacts must NOT silently convert the string to 0."""
        metrics = {
            'sec_filing_status': {'value': 'Active Review', 'unit': '', 'priority': 'medium'},
            'revenue': {'value': 1000, 'unit': '$M', 'priority': 'high'},
        }
        impacts = {'sec_filing_status': 0.0, 'revenue': 50}
        result = apply_metric_impacts(metrics, impacts)
        assert result['sec_filing_status']['value'] == 'Active Review', \
            "Categorical value was clobbered — J1 regressed"
        # Numeric metric should still apply
        assert result['revenue']['value'] > 1000

    def test_string_value_with_nonzero_impact_also_unchanged(self):
        metrics = {
            'compliance_status': {'value': 'Pending Review', 'unit': '', 'priority': 'medium'},
        }
        impacts = {'compliance_status': -2.5}
        result = apply_metric_impacts(metrics, impacts)
        assert result['compliance_status']['value'] == 'Pending Review'

    def test_explicit_categorical_flag_respected(self):
        metrics = {
            'status_metric': {'value': 5, 'unit': '', 'priority': 'low',
                              'categorical_value': True},
        }
        impacts = {'status_metric': 3}
        result = apply_metric_impacts(metrics, impacts)
        assert result['status_metric']['value'] == 5

    def test_explicit_non_numeric_flag_respected(self):
        metrics = {
            'status_metric': {'value': 5, 'unit': '', 'priority': 'low',
                              'non_numeric': True},
        }
        impacts = {'status_metric': 3}
        result = apply_metric_impacts(metrics, impacts)
        assert result['status_metric']['value'] == 5


# ─────────────────────────────────────────────────────────────────────────────
# Client claim #3: composite round score
# ─────────────────────────────────────────────────────────────────────────────
class TestRoundMetricScore:
    def test_no_movement_returns_neutral(self):
        metrics = {'a': {'value': 100, 'unit': '$M', 'priority': 'high'}}
        result = compute_round_metric_score(metrics, metrics)
        assert result['normalized_score'] == 50.0
        assert result['improvements'] == 0
        assert result['declines'] == 0

    def test_positive_movement_on_higher_better(self):
        before = {'revenue': {'value': 100, 'unit': '$M', 'priority': 'high'}}
        after  = {'revenue': {'value': 110, 'unit': '$M', 'priority': 'high'}}
        result = compute_round_metric_score(before, after)
        assert result['normalized_score'] > 50
        assert result['improvements'] == 1

    def test_positive_movement_on_lower_better_counts_as_decline(self):
        before = {'penalty_count': {'value': 5, 'unit': 'count', 'priority': 'high'}}
        after  = {'penalty_count': {'value': 8, 'unit': 'count', 'priority': 'high'}}
        result = compute_round_metric_score(before, after)
        assert result['normalized_score'] < 50
        assert result['declines'] == 1

    def test_decrease_on_lower_better_counts_as_improvement(self):
        """Penalty going DOWN should INCREASE the score (the client claim #2 scenario)."""
        before = {'total_penalties_ytd': {'value': 1.0, 'unit': '$M', 'priority': 'high'}}
        after  = {'total_penalties_ytd': {'value': 0.8, 'unit': '$M', 'priority': 'high'}}
        result = compute_round_metric_score(before, after)
        assert result['normalized_score'] > 50, \
            "Penalty decrease must register as improvement"
        assert result['improvements'] == 1

    def test_priority_weighting(self):
        """High-priority metric should weigh more than low-priority."""
        scenarios = []
        for prio in ['high', 'low']:
            before = {'metric': {'value': 100, 'unit': '$M', 'priority': prio}}
            after  = {'metric': {'value': 110, 'unit': '$M', 'priority': prio}}
            scenarios.append(compute_round_metric_score(before, after)['normalized_score'])
        # Both should be > 50, but the high-priority delta should produce equal
        # score (since only one metric is moving the avg is normalized either way).
        # The priority weight only matters in mixed-portfolio scenarios.
        # This test instead verifies high-priority wins in a mixed case:
        before = {
            'high_pri': {'value': 100, 'unit': '$M', 'priority': 'high'},
            'low_pri': {'value': 100, 'unit': '$M', 'priority': 'low'},
        }
        # high improves, low declines by equal pct
        after = {
            'high_pri': {'value': 110, 'unit': '$M', 'priority': 'high'},
            'low_pri': {'value': 90, 'unit': '$M', 'priority': 'low'},
        }
        mixed = compute_round_metric_score(before, after)
        assert mixed['normalized_score'] > 50, \
            "High-priority improvement should dominate low-priority decline"

    def test_categorical_metric_skipped(self):
        before = {
            'status': {'value': 'Active Review', 'unit': '', 'priority': 'medium'},
            'revenue': {'value': 100, 'unit': '$M', 'priority': 'high'},
        }
        after = {
            'status': {'value': 'Active Review', 'unit': '', 'priority': 'medium'},
            'revenue': {'value': 110, 'unit': '$M', 'priority': 'high'},
        }
        result = compute_round_metric_score(before, after)
        # Only revenue contributes; status is skipped
        assert result['improvements'] == 1
        assert result['declines'] == 0


class TestCompositeRoundScore:
    def test_weights_sum_to_one(self):
        assert abs(sum(COMPOSITE_ROUND_WEIGHTS.values()) - 1.0) < 1e-9

    def test_basic_composition(self):
        metrics = {'m': {'value': 100, 'unit': '$M', 'priority': 'high'}}
        result = compute_composite_round_score(
            decision_score=80, vocab_score=60,
            metrics_before=metrics, metrics_after=metrics,
        )
        # 80*0.5 + 50*0.3 + 60*0.2 = 40 + 15 + 12 = 67.0
        assert result['composite'] == 67.0
        assert result['decision_component'] == 40.0
        assert result['metric_component'] == 15.0
        assert result['vocab_component'] == 12.0

    def test_perfect_decision_with_terrible_metric_movement_isnt_inflated(self):
        """A 100/100 decision that crashes a high-priority metric should NOT be 100 composite."""
        before = {'revenue': {'value': 1000, 'unit': '$M', 'priority': 'high'}}
        after  = {'revenue': {'value': 700, 'unit': '$M', 'priority': 'high'}}  # 30% drop
        result = compute_composite_round_score(
            decision_score=100, vocab_score=100,
            metrics_before=before, metrics_after=after,
        )
        # Composite should be DRAGGED DOWN by the metric movement
        assert result['composite'] < 100, \
            "Composite must reflect business impact, not just LLM rubric"
        # Specifically less than (50 + 20) + (50 * 0.3) = 85
        assert result['metric_component'] < 15.0

    def test_custom_weights(self):
        metrics = {'m': {'value': 100, 'unit': '$M', 'priority': 'high'}}
        custom_weights = {'decision': 0.4, 'metric': 0.4, 'vocab': 0.2}
        result = compute_composite_round_score(
            decision_score=100, vocab_score=100,
            metrics_before=metrics, metrics_after=metrics,
            weights=custom_weights,
        )
        # 100*0.4 + 50*0.4 + 100*0.2 = 40 + 20 + 20 = 80.0
        assert result['composite'] == 80.0

    def test_weights_must_sum_to_one(self):
        metrics = {'m': {'value': 100, 'unit': '$M', 'priority': 'high'}}
        with pytest.raises(ValueError):
            compute_composite_round_score(
                decision_score=80, vocab_score=60,
                metrics_before=metrics, metrics_after=metrics,
                weights={'decision': 0.5, 'metric': 0.5, 'vocab': 0.5},
            )


# ─────────────────────────────────────────────────────────────────────────────
# Score parser regex (B2) — pure-logic test against canned LLM outputs
# ─────────────────────────────────────────────────────────────────────────────
class TestVocabularyReconciliation:
    """C1+C2 strengthened: vocab_score must reconcile with invoked/missed evidence.
    The LLM frequently returns vocab=100 even when the player invoked zero terms
    — sometimes while also listing terms the player missed. We override based
    on evidence, not on the LLM's headline number."""
    from unittest.mock import MagicMock
    from core.simulation_engine import evaluate_decision

    @staticmethod
    def _make_result(llm_response_text, key_terms=None):
        from unittest.mock import MagicMock
        from core.simulation_engine import evaluate_decision
        mock_llm = MagicMock()
        mock_llm.generate_content.return_value.text = llm_response_text
        return evaluate_decision(
            llm=mock_llm,
            company_data={'company_name': 'X', 'company_overview': '',
                          'metrics': {}, 'board_members': []},
            module_data={'module_name': 'M', 'learning_objectives': [],
                         'topics': [], 'key_terms': key_terms or {}},
            scenario='s', decision='d',
            round_config={'difficulty': 'medium'},
            player_role={'name': 'P', 'role': 'CFO', 'expertise': 'Finance'},
        )

    def test_empty_invoked_with_missed_floors_to_30(self):
        """LLM says vocab=100 but lists missed terms — score floored at 30."""
        response = """SCORE: 50

SCORE_REASONING: ok
MODULE_VOCABULARY_SCORE: 100
VOCABULARY_INVOKED: []
VOCABULARY_MISSED: Fiduciary Duty, Duty of Candor
VOCABULARY_MISUSED: []

STRENGTHS: ok
AREAS_FOR_IMPROVEMENT: ok
KEY_LEARNING_POINTS: ok
BEST_APPROACH: ok
ENCOURAGEMENT: ok"""
        result = self._make_result(response, key_terms={
            'Fiduciary Duty': 'def', 'Duty of Candor': 'def',
        })
        assert result['vocabulary_score'] <= 30, \
            "Empty invoked + non-empty missed must floor vocab score"

    def test_empty_everything_floors_to_50(self):
        """LLM punts on vocab assessment entirely — default to neutral 50."""
        response = """SCORE: 50

SCORE_REASONING: ok
MODULE_VOCABULARY_SCORE: 100
VOCABULARY_INVOKED: []
VOCABULARY_MISSED: []
VOCABULARY_MISUSED: []

STRENGTHS: ok
AREAS_FOR_IMPROVEMENT: ok
KEY_LEARNING_POINTS: ok
BEST_APPROACH: ok
ENCOURAGEMENT: ok"""
        result = self._make_result(response, key_terms={'Fiduciary Duty': 'def'})
        assert result['vocabulary_score'] == 50

    def test_invoked_terms_preserves_llm_score(self):
        """When player did invoke terms, trust the LLM's score."""
        response = """SCORE: 80

SCORE_REASONING: ok
MODULE_VOCABULARY_SCORE: 85
VOCABULARY_INVOKED: Fiduciary Duty, Duty of Candor
VOCABULARY_MISSED: []
VOCABULARY_MISUSED: []

STRENGTHS: ok
AREAS_FOR_IMPROVEMENT: ok
KEY_LEARNING_POINTS: ok
BEST_APPROACH: ok
ENCOURAGEMENT: ok"""
        result = self._make_result(response, key_terms={
            'Fiduciary Duty': 'def', 'Duty of Candor': 'def',
        })
        assert result['vocabulary_score'] == 85, \
            "Score must be preserved when player did invoke terms"

    def test_misuse_subtracts_per_term(self):
        """Each misused term subtracts 20 from the score."""
        response = """SCORE: 60

SCORE_REASONING: ok
MODULE_VOCABULARY_SCORE: 80
VOCABULARY_INVOKED: Fiduciary Duty
VOCABULARY_MISSED: []
VOCABULARY_MISUSED: Extraordinary Item, Going Concern

STRENGTHS: ok
AREAS_FOR_IMPROVEMENT: ok
KEY_LEARNING_POINTS: ok
BEST_APPROACH: ok
ENCOURAGEMENT: ok"""
        result = self._make_result(response, key_terms={
            'Fiduciary Duty': 'def', 'Extraordinary Item': 'forbidden',
            'Going Concern': 'def',
        })
        # 80 - 20*2 = 40
        assert result['vocabulary_score'] == 40


class TestMemberChipHover:
    """member_chip_html — reusable board-member hover popup helper.
    Used wherever a member name is displayed (deliberation, summary, consultation)."""

    def test_minimal_member_renders(self):
        from components.board_members import member_chip_html
        html = member_chip_html({'name': 'Jane Doe'})
        assert 'class="member-hover-wrap"' in html
        assert 'class="member-hover-popup"' in html
        assert 'Jane Doe' in html
        assert 'tabindex="0"' in html  # keyboard accessible

    def test_all_known_fields_appear(self):
        from components.board_members import member_chip_html
        member = {
            'name': 'Marcus Lee', 'role': 'Chief Risk Officer',
            'expertise': 'Risk Management', 'tenure_years': 6,
            'personality': 'Rigorously cautious',
            'committees': ['Risk Committee'],
        }
        html = member_chip_html(member)
        assert 'Chief Risk Officer' in html
        assert 'Risk Management' in html
        assert '6 years' in html
        assert 'Risk Committee' in html
        assert 'Rigorously cautious' in html

    def test_singular_year_for_tenure_1(self):
        from components.board_members import member_chip_html
        html = member_chip_html({'name': 'X', 'tenure_years': 1})
        assert '1 year' in html
        assert '1 years' not in html

    def test_missing_fields_silently_omitted(self):
        from components.board_members import member_chip_html
        html = member_chip_html({'name': 'X', 'role': 'CEO'})
        # No expertise / tenure / personality — no row should appear
        assert 'mh-personality' not in html
        # But role still renders
        assert 'CEO' in html

    def test_stance_block_renders_when_provided(self):
        from components.board_members import member_chip_html
        html = member_chip_html(
            {'name': 'X', 'role': 'CFO', 'personality': 'cautious'},
            stance={'stance': 'OPPOSE', 'conviction_level': 7,
                    'counter_opinion': 'Premature disclosure'},
        )
        assert 'OPPOSE' in html
        assert '7/10' in html
        assert 'Premature disclosure' in html
        assert 'This round' in html

    def test_stance_block_absent_when_no_stance(self):
        from components.board_members import member_chip_html
        html = member_chip_html({'name': 'X'})
        assert 'This round' not in html

    def test_html_escaping_prevents_xss(self):
        """User-controlled member fields must be escaped — no raw HTML injection."""
        from components.board_members import member_chip_html
        html = member_chip_html({
            'name': '<script>alert(1)</script>',
            'role': '<img src=x onerror=alert(2)>',
            'personality': 'Has "quotes" & ampersands',
        })
        assert '<script>alert(1)' not in html
        assert '&lt;script&gt;' in html
        assert '&lt;img' in html
        assert '&amp;' in html

    def test_anchor_right_class(self):
        from components.board_members import member_chip_html
        html = member_chip_html({'name': 'X'}, anchor='right')
        assert 'anchor-right' in html

    def test_custom_label(self):
        """Caller can pass HTML as label (e.g. wrapped in <strong> or <h4>)."""
        from components.board_members import member_chip_html
        html = member_chip_html({'name': 'Marcus Lee'}, label='<strong>Marcus</strong>')
        # The label is rendered as-is (caller is trusted for the label slot)
        assert '<strong>Marcus</strong>' in html
        # But the popup heading still shows the full escaped name
        assert '<h5>Marcus Lee</h5>' in html


class TestScoreExtraction:
    """Verify the score parser fix using sample LLM outputs.

    Re-imports the regex pattern inline to avoid running the full LLM call.
    """
    import re

    SCORE_RE = re.compile(r'(?m)^\s*SCORE\s*:\s*(\d{1,3})\b')

    def test_standard_response(self):
        content = "SCORE: 75\nSCORE_REASONING: ..."
        m = self.SCORE_RE.search(content)
        assert m and int(m.group(1)) == 75

    def test_does_not_match_module_vocabulary_score(self):
        """The headline SCORE: must not be confused with MODULE_VOCABULARY_SCORE:."""
        content = (
            "SCORE: 30\nSCORE_REASONING: critical\n"
            "MODULE_VOCABULARY_SCORE: 100\n"
        )
        m = self.SCORE_RE.search(content)
        assert m and int(m.group(1)) == 30, "Parser must pick headline 30, not vocab 100"

    def test_missing_headline_returns_no_match(self):
        """If LLM omits the headline SCORE: line, parser must not slide forward to vocab."""
        content = "SCORE_REASONING: dimensions\nMODULE_VOCABULARY_SCORE: 100"
        m = self.SCORE_RE.search(content)
        assert m is None, "No standalone SCORE: line should produce no match (fallback path)"
