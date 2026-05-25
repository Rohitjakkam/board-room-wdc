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
        """v1.4.7 — composite now has 4 components.
        Weights: decision 40% + metric 25% + board_effectiveness 20% + vocab 15%.
        Without an explicit board_effectiveness_score arg, defaults to 50 (neutral)."""
        metrics = {'m': {'value': 100, 'unit': '$M', 'priority': 'high'}}
        result = compute_composite_round_score(
            decision_score=80, vocab_score=60,
            metrics_before=metrics, metrics_after=metrics,
        )
        # 80*.40 + 50*.25 + 50*.20 + 60*.15 = 32 + 12.5 + 10 + 9 = 63.5
        assert result['composite'] == 63.5
        assert result['decision_component'] == 32.0
        assert result['metric_component'] == 12.5
        assert result['board_effectiveness_component'] == 10.0
        assert result['vocab_component'] == 9.0

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
        """Custom 4-key weights (must sum to 1.0) override defaults."""
        metrics = {'m': {'value': 100, 'unit': '$M', 'priority': 'high'}}
        custom_weights = {
            'decision': 0.4, 'metric': 0.4,
            'board_effectiveness': 0.1, 'vocab': 0.1,
        }
        result = compute_composite_round_score(
            decision_score=100, vocab_score=100,
            metrics_before=metrics, metrics_after=metrics,
            board_effectiveness_score=50,
            weights=custom_weights,
        )
        # 100*.4 + 50*.4 + 50*.1 + 100*.1 = 40 + 20 + 5 + 10 = 75.0
        assert result['composite'] == 75.0

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


class TestCalibratedOptions:
    """v1.4.7 — scenario generator must produce 4 calibrated options with
    pre-baked stance distributions. Parser + validator + deterministic
    stance builder."""

    NEW_FORMAT_SCENARIO = """SCENARIO TITLE: Test
SITUATION: blah

OPTIONS TO CONSIDER:

OPTION A | CALIBRATION: unanimous
ACTION: Convene the audit committee, engage outside counsel, and disclose proactively. This protects shareholders and demonstrates good-faith remediation. Financial impact is modest.
STANCES: Sandra Cho=APPROVE, David Sung=APPROVE, Patricia Delgado=APPROVE, Jonathan Marsh=APPROVE
COUNTERS: (none)

OPTION B | CALIBRATION: mild_dissent
ACTION: Defer disclosure pending investigation. Buys time but delays informing the regulator. Some board members will worry about timing.
STANCES: Sandra Cho=OPPOSE, David Sung=APPROVE, Patricia Delgado=OPPOSE, Jonathan Marsh=APPROVE
COUNTERS: Sandra Cho: Delayed disclosure violates Rule 21F. | Patricia Delgado: Investor reaction could materially impact valuation.

OPTION C | CALIBRATION: controversial
ACTION: Issue narrow disclosure that downplays severity. Minimizes immediate damage but risks future enforcement.
STANCES: Sandra Cho=OPPOSE, David Sung=OPPOSE, Patricia Delgado=OPPOSE, Jonathan Marsh=APPROVE
COUNTERS: Sandra Cho: Selective disclosure violates Reg FD. | David Sung: Regulatory risk unmitigated. | Patricia Delgado: Restatement risk dwarfs current cost.

OPTION D | CALIBRATION: highly_controversial
ACTION: Conceal entirely, delay production, threaten the whistleblower. Unlawful but might buy time.
STANCES: Sandra Cho=OPPOSE, David Sung=OPPOSE, Patricia Delgado=OPPOSE, Jonathan Marsh=OPPOSE
COUNTERS: Sandra Cho: Mandatory disclosure obligations are clear. | David Sung: Risk catastrophic. | Patricia Delgado: SOX 806 liability. | Jonathan Marsh: Obstruction of justice.
"""

    def test_parser_extracts_all_four_options(self):
        from core.simulation_engine import parse_scenario_options
        opts = parse_scenario_options(self.NEW_FORMAT_SCENARIO)
        assert len(opts) == 4
        assert [o['letter'] for o in opts] == ['A', 'B', 'C', 'D']

    def test_parser_extracts_calibration(self):
        from core.simulation_engine import parse_scenario_options
        opts = parse_scenario_options(self.NEW_FORMAT_SCENARIO)
        assert opts[0]['calibration'] == 'unanimous'
        assert opts[1]['calibration'] == 'mild_dissent'
        assert opts[2]['calibration'] == 'controversial'
        assert opts[3]['calibration'] == 'highly_controversial'

    def test_parser_extracts_stance_distribution(self):
        from core.simulation_engine import parse_scenario_options
        opts = parse_scenario_options(self.NEW_FORMAT_SCENARIO)
        sd_a = opts[0]['stance_distribution']
        assert len(sd_a) == 4
        assert all(v == 'APPROVE' for v in sd_a.values())
        sd_d = opts[3]['stance_distribution']
        assert all(v == 'OPPOSE' for v in sd_d.values())
        sd_b = opts[1]['stance_distribution']
        assert sum(1 for v in sd_b.values() if v == 'OPPOSE') == 2

    def test_parser_extracts_counters(self):
        from core.simulation_engine import parse_scenario_options
        opts = parse_scenario_options(self.NEW_FORMAT_SCENARIO)
        assert opts[0]['counters'] == {}  # unanimous → no counters
        assert 'Sandra Cho' in opts[1]['counters']
        assert 'Rule 21F' in opts[1]['counters']['Sandra Cho']

    def test_validator_passes_on_calibrated(self):
        from core.simulation_engine import parse_scenario_options, validate_option_calibration
        opts = parse_scenario_options(self.NEW_FORMAT_SCENARIO)
        errors = validate_option_calibration(opts, expected_non_player_count=4)
        assert errors == []

    def test_validator_fails_when_no_unanimous(self):
        from core.simulation_engine import validate_option_calibration
        opts = [
            {'letter': 'A', 'stance_distribution': {'X': 'APPROVE', 'Y': 'OPPOSE'}, 'counters': {}},
            {'letter': 'B', 'stance_distribution': {'X': 'OPPOSE', 'Y': 'APPROVE'}, 'counters': {}},
            {'letter': 'C', 'stance_distribution': {'X': 'OPPOSE', 'Y': 'OPPOSE'}, 'counters': {}},
            {'letter': 'D', 'stance_distribution': {'X': 'OPPOSE', 'Y': 'OPPOSE'}, 'counters': {}},
        ]
        errors = validate_option_calibration(opts, expected_non_player_count=2)
        assert any('0 opposers' in e for e in errors)

    def test_validator_fails_when_wrong_count(self):
        from core.simulation_engine import validate_option_calibration
        opts = [{'letter': 'A', 'stance_distribution': {}, 'counters': {}},
                {'letter': 'B', 'stance_distribution': {}, 'counters': {}}]
        errors = validate_option_calibration(opts, expected_non_player_count=4)
        assert any('Expected exactly 4' in e for e in errors)

    def test_old_format_fallback(self):
        from core.simulation_engine import parse_scenario_options
        old_scenario = ("OPTIONS TO CONSIDER:\n"
                        "A) Do this\n"
                        "B) Do that\n"
                        "C) Or this\n"
                        "D) Maybe that\n")
        opts = parse_scenario_options(old_scenario)
        assert len(opts) == 4
        assert opts[0]['text'] == 'Do this'
        # Old format doesn't have stance metadata
        assert opts[0].get('stance_distribution') is None or opts[0].get('stance_distribution') == {}


class TestDeterministicStances:
    """build_stances_from_option — deterministic per-member stance map from a
    calibrated option. Skips the LLM call entirely."""

    COMPANY = {
        'company_name': 'TestCo',
        'board_members': [
            {'name': 'Sandra Cho', 'role': 'Chair of Audit', 'expertise': 'Audit'},
            {'name': 'David Sung', 'role': 'CRO', 'expertise': 'Risk'},
            {'name': 'Patricia Delgado', 'role': 'CFO', 'expertise': 'Finance'},
            {'name': "Margaret 'Meg' Harlow", 'role': 'Board Director', 'expertise': 'Governance'},
        ],
    }
    PLAYER = {'name': "Margaret 'Meg' Harlow", 'role': 'Board Director'}

    def test_unanimous_option_produces_all_approve(self):
        from core.simulation_engine import build_stances_from_option
        option = {
            'letter': 'A',
            'stance_distribution': {
                'Sandra Cho': 'APPROVE', 'David Sung': 'APPROVE',
                'Patricia Delgado': 'APPROVE',
            },
            'counters': {},
        }
        stances = build_stances_from_option(option, self.COMPANY, self.PLAYER)
        # Player is excluded
        assert "Margaret 'Meg' Harlow" not in stances
        # Every other member approves
        assert all(s['stance'] == 'APPROVE' for s in stances.values())
        assert len(stances) == 3

    def test_oppose_carries_counter_opinion(self):
        from core.simulation_engine import build_stances_from_option
        option = {
            'letter': 'B',
            'stance_distribution': {
                'Sandra Cho': 'OPPOSE', 'David Sung': 'APPROVE',
                'Patricia Delgado': 'OPPOSE',
            },
            'counters': {
                'Sandra Cho': 'Disclosure timing is premature.',
                'Patricia Delgado': 'Financial impact is unclear.',
            },
        }
        stances = build_stances_from_option(option, self.COMPANY, self.PLAYER)
        assert stances['Sandra Cho']['stance'] == 'OPPOSE'
        assert stances['Sandra Cho']['counter_opinion'] == 'Disclosure timing is premature.'
        assert stances['Patricia Delgado']['stance'] == 'OPPOSE'
        assert stances['Patricia Delgado']['counter_opinion'] == 'Financial impact is unclear.'
        assert stances['David Sung']['stance'] == 'APPROVE'
        # Conviction differs by stance
        assert stances['Sandra Cho']['conviction_level'] > stances['David Sung']['conviction_level']

    def test_oppose_without_counter_gets_synthetic_fallback(self):
        from core.simulation_engine import build_stances_from_option
        option = {
            'letter': 'X',
            'stance_distribution': {'Sandra Cho': 'OPPOSE'},
            'counters': {},  # malformed — OPPOSE without counter
        }
        stances = build_stances_from_option(option, self.COMPANY, self.PLAYER)
        # Synthesized fallback so the debate flow can still run
        assert stances['Sandra Cho']['counter_opinion']

    def test_missing_member_defaults_to_neutral(self):
        from core.simulation_engine import build_stances_from_option
        option = {
            'letter': 'X',
            'stance_distribution': {'Sandra Cho': 'APPROVE'},  # missing David + Patricia
            'counters': {},
        }
        stances = build_stances_from_option(option, self.COMPANY, self.PLAYER)
        # Every non-player member must have a stance
        assert 'David Sung' in stances
        assert 'Patricia Delgado' in stances
        assert stances['David Sung']['stance'] == 'NEUTRAL'
        assert stances['Patricia Delgado']['stance'] == 'NEUTRAL'

    def test_player_excluded_from_distribution(self):
        from core.simulation_engine import build_stances_from_option
        option = {
            'letter': 'X',
            # Even if LLM hallucinates a stance for the player, it must be excluded
            'stance_distribution': {
                "Margaret 'Meg' Harlow": 'OPPOSE',
                'Sandra Cho': 'APPROVE',
            },
            'counters': {},
        }
        stances = build_stances_from_option(option, self.COMPANY, self.PLAYER)
        assert "Margaret 'Meg' Harlow" not in stances


class TestCompositeRoundScore4Component:
    """v1.4.7 — composite now includes board_effectiveness as a 4th component.
    Weights: decision 40% + metric 25% + board_eff 20% + vocab 15%."""

    def test_weights_sum_to_one(self):
        from core.scoring import COMPOSITE_ROUND_WEIGHTS
        assert abs(sum(COMPOSITE_ROUND_WEIGHTS.values()) - 1.0) < 1e-9
        assert set(COMPOSITE_ROUND_WEIGHTS) == {'decision', 'metric',
                                                  'board_effectiveness', 'vocab'}

    def test_board_effectiveness_default_is_neutral(self):
        """Legacy callers that don't pass board_effectiveness get 50 (neutral)."""
        from core.scoring import compute_composite_round_score
        metrics = {'m': {'value': 100, 'unit': '$M', 'priority': 'high'}}
        result = compute_composite_round_score(
            decision_score=80, vocab_score=80,
            metrics_before=metrics, metrics_after=metrics,
        )
        # 80*.40 + 50*.25 + 50*.20 + 80*.15 = 32 + 12.5 + 10 + 12 = 66.5
        assert result['composite'] == 66.5
        assert result['board_effectiveness_component'] == 10.0

    def test_high_board_effectiveness_lifts_composite(self):
        from core.scoring import compute_composite_round_score
        metrics = {'m': {'value': 100, 'unit': '$M', 'priority': 'high'}}
        low_be = compute_composite_round_score(80, 80, metrics, metrics,
                                                board_effectiveness_score=20)
        high_be = compute_composite_round_score(80, 80, metrics, metrics,
                                                 board_effectiveness_score=100)
        assert high_be['composite'] > low_be['composite']
        # Delta should be (100-20) * 0.20 = 16 points
        assert abs((high_be['composite'] - low_be['composite']) - 16.0) < 0.01

    def test_returns_all_four_components(self):
        from core.scoring import compute_composite_round_score
        metrics = {'m': {'value': 100, 'unit': '$M', 'priority': 'high'}}
        result = compute_composite_round_score(
            decision_score=70, vocab_score=60,
            metrics_before=metrics, metrics_after=metrics,
            board_effectiveness_score=80,
        )
        for key in ('decision_component', 'metric_component',
                     'board_effectiveness_component', 'vocab_component'):
            assert key in result

    def test_custom_4key_weights_accepted(self):
        from core.scoring import compute_composite_round_score
        metrics = {'m': {'value': 100, 'unit': '$M', 'priority': 'high'}}
        # Heavy weight on board effectiveness
        result = compute_composite_round_score(
            decision_score=100, vocab_score=100,
            metrics_before=metrics, metrics_after=metrics,
            board_effectiveness_score=50,
            weights={'decision': 0.25, 'metric': 0.25,
                     'board_effectiveness': 0.40, 'vocab': 0.10},
        )
        # 100*.25 + 50*.25 + 50*.40 + 100*.10 = 25 + 12.5 + 20 + 10 = 67.5
        assert result['composite'] == 67.5


class TestRubricV149:
    """v1.4.9 rubric: 8 dimensions = 25/25/15/15/5/5/5/5 = 100.
    Three new dimensions (Behavioural Governance, Decision Integrity, Ethics &
    Judgment Under Pressure) join the existing five with rebalanced weights."""

    from unittest.mock import MagicMock

    @staticmethod
    def _evaluate(llm_text, engagement_data=None):
        from unittest.mock import MagicMock
        from core.simulation_engine import evaluate_decision
        mock = MagicMock()
        mock.generate_content.return_value.text = llm_text
        return mock, evaluate_decision(
            llm=mock,
            company_data={'company_name': 'X', 'company_overview': '',
                          'metrics': {}, 'board_members': []},
            module_data={'module_name': 'M', 'learning_objectives': [],
                         'topics': [], 'key_terms': {}},
            scenario='s', decision='d',
            round_config={'difficulty': 'medium'},
            player_role={'name': 'P', 'role': 'CFO', 'expertise': 'Finance'},
            engagement_data=engagement_data,
        )

    def test_all_eight_dimensions_in_prompt(self):
        mock, _ = self._evaluate("SCORE: 70\nSCORE_REASONING: ok\nSTRENGTHS: ok\nAREAS_FOR_IMPROVEMENT: ok\nKEY_LEARNING_POINTS: ok\nBEST_APPROACH: ok\nENCOURAGEMENT: ok")
        prompt = mock.generate_content.call_args_list[0][0][0]
        for label in ('Governance Understanding', 'Legal & Regulatory Compliance',
                      'Stakeholder Consideration', 'Strategic Thinking',
                      'Role Alignment', 'Behavioural Governance',
                      'Decision Integrity', 'Ethics & Judgment Under Pressure'):
            assert label in prompt, f"{label!r} missing from evaluation prompt"

    def test_dimension_weights_sum_to_100(self):
        """Per-dimension max points must sum to 100 — exactly."""
        from pathlib import Path
        import re
        src = Path('core/simulation_engine.py').read_text(encoding='utf-8')
        # Find the SCORE_REASONING block and extract every "[points]/N" pattern.
        m = re.search(r'SCORE_REASONING:.*?Total:\s*\[sum\]/100', src, re.DOTALL)
        assert m, "SCORE_REASONING block not found"
        block = m.group(0)
        caps = [int(n) for n in re.findall(r'\[points\]/(\d+)', block)]
        assert len(caps) == 8, f"Expected 8 dimension caps, found {len(caps)}: {caps}"
        assert sum(caps) == 100, f"Dimension caps must sum to 100, got {sum(caps)}: {caps}"
        # And the specific distribution
        assert sorted(caps, reverse=True) == [25, 25, 15, 15, 5, 5, 5, 5]

    def test_engagement_block_omitted_when_no_data(self):
        """When engagement_data is None, the prompt must NOT include the data block.
        The Behavioural Governance dimension definition references the block by name,
        so check for the actual data lines (which only render when data is provided)."""
        mock, _ = self._evaluate(
            "SCORE: 70\nSCORE_REASONING: ok\nSTRENGTHS: ok\nAREAS_FOR_IMPROVEMENT: ok\nKEY_LEARNING_POINTS: ok\nBEST_APPROACH: ok\nENCOURAGEMENT: ok"
        )
        prompt = mock.generate_content.call_args_list[0][0][0]
        # These specific lines only appear inside the actual engagement_block
        assert 'Board (director) consultations used:' not in prompt
        assert 'Dissenters addressed:' not in prompt
        assert 'Force-submitted (timer expired):' not in prompt

    def test_engagement_block_included_when_data_provided(self):
        """When engagement_data is provided, the prompt MUST surface every key."""
        engagement = {
            'board_consultations': 1, 'committee_consultations': 1,
            'debate_exchanges': 4, 'dissenters_addressed': 2,
            'dissenters_total': 3, 'force_submitted': False,
        }
        mock, _ = self._evaluate(
            "SCORE: 70\nSCORE_REASONING: ok\nSTRENGTHS: ok\nAREAS_FOR_IMPROVEMENT: ok\nKEY_LEARNING_POINTS: ok\nBEST_APPROACH: ok\nENCOURAGEMENT: ok",
            engagement_data=engagement,
        )
        prompt = mock.generate_content.call_args_list[0][0][0]
        assert 'PLAYER ENGAGEMENT DATA' in prompt
        assert 'Board (director) consultations used:    1' in prompt
        assert 'Committee consultations used:           1' in prompt
        assert 'Total debate exchanges with dissenters: 4' in prompt
        assert 'Dissenters addressed:                   2 of 3' in prompt
        assert 'Force-submitted (timer expired):        no' in prompt

    def test_force_submitted_renders_as_yes(self):
        engagement = {'board_consultations': 0, 'committee_consultations': 0,
                      'debate_exchanges': 0, 'dissenters_addressed': 0,
                      'dissenters_total': 0, 'force_submitted': True}
        mock, _ = self._evaluate(
            "SCORE: 70\nSCORE_REASONING: ok\nSTRENGTHS: ok\nAREAS_FOR_IMPROVEMENT: ok\nKEY_LEARNING_POINTS: ok\nBEST_APPROACH: ok\nENCOURAGEMENT: ok",
            engagement_data=engagement,
        )
        prompt = mock.generate_content.call_args_list[0][0][0]
        assert 'Force-submitted (timer expired):        YES' in prompt

    def test_score_parser_handles_8dim_breakdown(self):
        """Dimension-sum fallback must work when SCORE: is missing and dims include /5 caps."""
        llm_text = """SCORE_REASONING:
- Governance Understanding: 12/25
- Legal/Regulatory Compliance: 15/25
- Stakeholder Consideration: 10/15
- Strategic Thinking: 8/15
- Role Alignment: 3/5
- Behavioural Governance: 4/5
- Decision Integrity: 3/5
- Ethics & Judgment Under Pressure: 2/5
Total: 57/100

STRENGTHS: ok
AREAS_FOR_IMPROVEMENT: ok
KEY_LEARNING_POINTS: ok
BEST_APPROACH: ok
ENCOURAGEMENT: ok"""
        _, result = self._evaluate(llm_text)
        # 12+15+10+8+3+4+3+2 = 57. Allow parser to recover this if SCORE: missing.
        # Headline SCORE: line is missing here, so fallback parses dimensions and recovers.
        assert result['score'] == 57, f"Parser recovered {result['score']} (expected 57)"


class TestParserFormatTolerance:
    """v1.4.10 — parser must tolerate LLM format variations so the user always
    gets 4 options even when the model wanders from the prescribed template.

    Each variation below was observed in real LLM outputs (or close to them)
    that previously caused the user to see <4 options.
    """

    @staticmethod
    def _make_scenario(header_template):
        """Build a 4-option scenario where each header uses the given template
        (with {letter} and {calib} placeholders)."""
        opts = [
            (header_template.format(letter='A', calib='unanimous'),
             'Convene Audit Committee and engage external counsel proactively.',
             'Sandra Cho=APPROVE, David Sung=APPROVE, Patricia Delgado=APPROVE, Jonathan Marsh=APPROVE',
             '(none)'),
            (header_template.format(letter='B', calib='mild_dissent'),
             'Defer disclosure pending further investigation by management.',
             'Sandra Cho=OPPOSE, David Sung=APPROVE, Patricia Delgado=OPPOSE, Jonathan Marsh=APPROVE',
             'Sandra Cho: timing wrong | Patricia Delgado: financial concerns'),
            (header_template.format(letter='C', calib='controversial'),
             'Issue narrow disclosure to downplay severity to regulators.',
             'Sandra Cho=OPPOSE, David Sung=OPPOSE, Patricia Delgado=OPPOSE, Jonathan Marsh=APPROVE',
             'Sandra Cho: violates rules | David Sung: risk unmitigated | Patricia Delgado: restatement risk'),
            (header_template.format(letter='D', calib='highly_controversial'),
             'Conceal the issue and intimidate the whistleblower into silence.',
             'Sandra Cho=OPPOSE, David Sung=OPPOSE, Patricia Delgado=OPPOSE, Jonathan Marsh=OPPOSE',
             'Sandra Cho: illegal | David Sung: catastrophic | Patricia Delgado: SOX | Jonathan Marsh: obstruction'),
        ]
        blocks = []
        for header, action, stances, counters in opts:
            blocks.append(f"{header}\nACTION: {action}\nSTANCES: {stances}\nCOUNTERS: {counters}\n")
        return "SCENARIO TITLE: Test\nSITUATION: blah\n\nOPTIONS TO CONSIDER:\n\n" + "\n".join(blocks)

    @staticmethod
    def _parse(scenario):
        from core.simulation_engine import parse_scenario_options
        return parse_scenario_options(scenario)

    def test_canonical_format(self):
        s = self._make_scenario('OPTION {letter} | CALIBRATION: {calib}')
        opts = self._parse(s)
        assert len(opts) == 4
        assert [o['letter'] for o in opts] == ['A', 'B', 'C', 'D']

    def test_markdown_bold_around_option(self):
        """LLM sometimes wraps the header in **OPTION A**."""
        s = self._make_scenario('**OPTION {letter}** | CALIBRATION: {calib}')
        opts = self._parse(s)
        assert len(opts) == 4

    def test_colon_separator_instead_of_pipe(self):
        """LLM substitutes ':' for '|' between OPTION and CALIBRATION."""
        s = self._make_scenario('OPTION {letter}: CALIBRATION: {calib}')
        opts = self._parse(s)
        assert len(opts) == 4

    def test_em_dash_separator(self):
        s = self._make_scenario('OPTION {letter} — CALIBRATION: {calib}')
        opts = self._parse(s)
        assert len(opts) == 4

    def test_calibration_word_omitted(self):
        """LLM writes 'OPTION A | unanimous' (skipping the CALIBRATION: prefix)."""
        s = self._make_scenario('OPTION {letter} | {calib}')
        opts = self._parse(s)
        assert len(opts) == 4
        # Calibration should still be derived from opposer counts even if header
        # didn't carry the label explicitly
        unanimous = [o for o in opts if sum(1 for v in o['stance_distribution'].values()
                                              if v == 'OPPOSE') == 0]
        assert len(unanimous) == 1
        assert unanimous[0]['calibration'] == 'unanimous'

    def test_parens_around_calibration(self):
        s = self._make_scenario('OPTION {letter} ({calib})')
        opts = self._parse(s)
        assert len(opts) == 4

    def test_header_with_no_calibration_at_all(self):
        """LLM emits bare 'OPTION A' header — calibration derived from stances."""
        s = self._make_scenario('OPTION {letter}')
        opts = self._parse(s)
        assert len(opts) == 4
        # All 4 calibrations should still be derived correctly from data
        cals = sorted(o['calibration'] for o in opts if o['calibration'])
        assert cals == sorted(['unanimous', 'mild_dissent', 'controversial',
                                'highly_controversial'])

    def test_hybrid_fallback_when_new_format_partial(self):
        """LLM produces new format for A/B but bare 'C) ...' / 'D) ...' for C/D.
        Hybrid fallback fills the gaps so the user still sees 4 options."""
        scenario = """SCENARIO TITLE: Test
SITUATION: blah

OPTIONS TO CONSIDER:

OPTION A | CALIBRATION: unanimous
ACTION: Convene audit committee.
STANCES: Sandra Cho=APPROVE, David Sung=APPROVE, Patricia Delgado=APPROVE, Jonathan Marsh=APPROVE
COUNTERS: (none)

OPTION B | CALIBRATION: mild_dissent
ACTION: Defer disclosure pending investigation.
STANCES: Sandra Cho=OPPOSE, David Sung=APPROVE, Patricia Delgado=OPPOSE, Jonathan Marsh=APPROVE
COUNTERS: Sandra Cho: wrong timing | Patricia Delgado: financial concerns

C) Issue a narrow disclosure to minimize damage to the company.
D) Conceal the matter entirely from regulators.
"""
        opts = self._parse(scenario)
        assert len(opts) == 4, f"Hybrid fallback should give 4 options, got {len(opts)}"
        letters = [o['letter'] for o in opts]
        assert letters == ['A', 'B', 'C', 'D']
        # A and B have full new-format data
        assert opts[0]['stance_distribution']
        assert opts[1]['stance_distribution']
        # C and D come from old format — no stance metadata
        assert opts[2]['stance_distribution'] == {}
        assert opts[3]['stance_distribution'] == {}
        assert 'narrow disclosure' in opts[2]['text']

    def test_action_without_explicit_marker(self):
        """LLM forgets 'ACTION:' marker and just writes the text under the header."""
        scenario = """OPTIONS TO CONSIDER:

OPTION A | CALIBRATION: unanimous
Convene the audit committee immediately and engage external counsel.
STANCES: Sandra Cho=APPROVE, David Sung=APPROVE, Patricia Delgado=APPROVE, Jonathan Marsh=APPROVE
COUNTERS: (none)
"""
        opts = self._parse(scenario)
        assert len(opts) == 1
        assert 'audit committee' in opts[0]['text'].lower()


class TestSynthesizedFallback:
    """v1.4.10 — the synthesized fallback guarantees the player ALWAYS sees 4
    options, even if the LLM produces 0/1/2/3 valid options after all retries.

    This is the last line of defense after parser tolerance + hybrid fallback +
    retry loop. Only fires when those upstream mechanisms haven't yielded 4.
    """

    COMPANY = {
        'company_name': 'TestCo',
        'board_members': [
            {'name': 'Alice', 'role': 'CEO', 'expertise': 'Strategy'},
            {'name': 'Bob', 'role': 'CFO', 'expertise': 'Finance'},
            {'name': 'Carol', 'role': 'CRO', 'expertise': 'Risk'},
            {'name': 'Dave', 'role': 'Audit Chair', 'expertise': 'Audit'},
        ],
    }
    PLAYER = {'name': 'Player', 'role': 'Board Director'}

    def test_ensure_four_with_zero_options(self):
        """When parse yields 0 options, all 4 must be synthesized."""
        from core.simulation_engine import _ensure_four_options
        result = _ensure_four_options([], self.COMPANY, self.PLAYER)
        assert len(result) == 4
        assert [o['letter'] for o in result] == ['A', 'B', 'C', 'D']
        # All 4 synthesized
        assert all(o.get('synthesized') for o in result)
        # All 4 calibration tiers present
        cals = sorted(o['calibration'] for o in result)
        assert cals == sorted(['unanimous', 'mild_dissent',
                                'controversial', 'highly_controversial'])

    def test_ensure_four_with_partial_options(self):
        """When parse yields 2 options, the other 2 must be synthesized with
        the missing calibration tiers."""
        from core.simulation_engine import _ensure_four_options
        partial = [
            {'letter': 'A', 'text': 'Real LLM option A',
             'calibration': 'unanimous', 'stance_distribution': {},
             'counters': {}},
            {'letter': 'B', 'text': 'Real LLM option B',
             'calibration': 'mild_dissent', 'stance_distribution': {},
             'counters': {}},
        ]
        result = _ensure_four_options(partial, self.COMPANY, self.PLAYER)
        assert len(result) == 4
        # Real options preserved (no synthesized flag)
        assert not result[0].get('synthesized')
        assert not result[1].get('synthesized')
        # Missing letters synthesized
        assert result[2].get('synthesized') and result[2]['letter'] == 'C'
        assert result[3].get('synthesized') and result[3]['letter'] == 'D'
        # Missing calibration tiers filled
        synth_cals = {result[2]['calibration'], result[3]['calibration']}
        assert synth_cals == {'controversial', 'highly_controversial'}

    def test_ensure_four_is_noop_when_already_four(self):
        from core.simulation_engine import _ensure_four_options
        existing = [
            {'letter': l, 'text': f'opt {l}', 'calibration': c,
             'stance_distribution': {}, 'counters': {}}
            for l, c in zip('ABCD', _CALIB_LABELS_FOR_TEST)
        ]
        result = _ensure_four_options(list(existing), self.COMPANY, self.PLAYER)
        assert len(result) == 4
        assert not any(o.get('synthesized') for o in result), \
            "Already-four list must not get synthesized additions"

    def test_synthesized_option_has_stance_distribution(self):
        """Synthesized options must have a valid stance distribution so
        deterministic stance generation works on them."""
        from core.simulation_engine import _synthesize_placeholder_option
        non_player = [{'name': n, 'role': 'X', 'expertise': 'Y'}
                       for n in ['M1', 'M2', 'M3', 'M4']]
        opt = _synthesize_placeholder_option('D', 'highly_controversial', non_player)
        sd = opt['stance_distribution']
        assert len(sd) == 4
        opposers = sum(1 for v in sd.values() if v == 'OPPOSE')
        assert opposers == 4  # highly_controversial = all oppose

    def test_synthesized_option_marked_clearly_in_text(self):
        """Player should be able to tell they're seeing a synthesized option."""
        from core.simulation_engine import _synthesize_placeholder_option
        opt = _synthesize_placeholder_option('A', 'unanimous',
                                              [{'name': 'X', 'role': 'R'}])
        assert 'Synthesized fallback' in opt['text']

    def test_format_option_as_scenario_block_roundtrips(self):
        """A synthesized option, when serialized and re-parsed, must round-trip
        to the same letter / calibration / opposer count."""
        from core.simulation_engine import (_synthesize_placeholder_option,
                                              _format_option_as_scenario_block,
                                              parse_scenario_options)
        non_player = [{'name': n, 'role': 'X', 'expertise': 'Y'}
                       for n in ['M1', 'M2', 'M3', 'M4']]
        original = _synthesize_placeholder_option('C', 'controversial', non_player)
        block = _format_option_as_scenario_block(original)
        # Wrap in minimal scenario shell
        scenario = f"SCENARIO TITLE: Test\n\nOPTIONS TO CONSIDER:\n{block}"
        parsed = parse_scenario_options(scenario)
        assert len(parsed) == 1
        assert parsed[0]['letter'] == 'C'
        # Calibration derived from data should match
        opposers = sum(1 for v in parsed[0]['stance_distribution'].values() if v == 'OPPOSE')
        assert opposers == 3
        assert parsed[0]['calibration'] == 'controversial'


# Tiny helper so the test above can reference the canonical list without
# requiring the import to be inside the class definition.
_CALIB_LABELS_FOR_TEST = ('unanimous', 'mild_dissent', 'controversial',
                          'highly_controversial')


class TestOptionUINoCalibrationLeak:
    """v1.4.8 — Option-card UI must not reveal calibration / opposer-count.

    The calibration (unanimous / mild_dissent / controversial / highly_controversial)
    and stance_distribution are pedagogical metadata that drive deterministic board
    stances. Leaking them to the student via the option card lets them pick the
    "safe" option by counting badges instead of reasoning about the action.
    """
    import os
    from pathlib import Path

    REPO_ROOT = Path(__file__).resolve().parent.parent
    SIM_PATH = REPO_ROOT / 'pages' / 'simulation.py'

    @classmethod
    def _option_render_block(cls) -> str:
        import re
        content = cls.SIM_PATH.read_text(encoding='utf-8')
        m = re.search(r"for idx, opt in enumerate\(options\):.*?if st\.button",
                       content, re.DOTALL)
        assert m, "Could not locate the option-card render block — test needs updating"
        return m.group(0)

    @classmethod
    def _non_comment_lines(cls, block: str) -> str:
        # Strip Python comment lines so allowed words can appear inside comments.
        return '\n'.join(line for line in block.split('\n')
                         if not line.strip().startswith('#'))

    def test_no_likely_oppose_label(self):
        """The literal phrase 'likely oppose' must not appear in the card body."""
        block = self._non_comment_lines(self._option_render_block())
        assert 'likely oppose' not in block, \
            "Option card must not show 'likely oppose' — telegraphs the safe choice"

    def test_no_opposer_count_rendered(self):
        block = self._non_comment_lines(self._option_render_block())
        # f-string interpolations of opposer count
        assert '{opposers}' not in block
        # Inline calculation rendered in the UI
        assert "for v in sd.values() if v == 'OPPOSE'" not in block, \
            "Card must not compute opposer counts at render time"

    def test_no_calibration_field_rendered(self):
        """opt['calibration'] / opt.get('calibration') must not be used to render
        ANY visible markup in the card. Internal use (logging, conditional logic)
        is fine, but appending to an HTML string is not."""
        block = self._non_comment_lines(self._option_render_block())
        # No direct interpolation of calibration into a string
        assert "{calibration}" not in block
        assert '{opt["calibration"]}' not in block
        assert "{opt['calibration']}" not in block

    def test_no_stance_distribution_rendered(self):
        block = self._non_comment_lines(self._option_render_block())
        assert '{opt["stance_distribution"]}' not in block
        assert "{opt['stance_distribution']}" not in block
        assert '{sd}' not in block  # `sd` was the variable name used previously


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
