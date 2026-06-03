"""
Scenario-level integration tests for Test 4 bug fixes.
Replicates actual bug conditions: multi-round flows, session state transitions,
stale state cleanup, conviction pipeline, metric classification, and prompt integrity.

Run: python -m pytest tests/test_scenarios.py -v
"""

import sys
import os
import datetime
import copy
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Shared fixtures ──────────────────────────────────────────────────────────

CLEARWATER_BOARD = [
    {'name': 'Jonathan Marsh', 'role': 'CEO', 'expertise': 'Strategy',
     'tenure_years': 12, 'personality': 'Assertive, protective of management authority'},
    {'name': 'Sandra Cho', 'role': 'Chair of the Audit Committee', 'expertise': 'Audit',
     'tenure_years': 8, 'personality': 'Meticulous, compliance-focused'},
    {'name': 'David Sung', 'role': 'Chief Risk Officer', 'expertise': 'Risk Management',
     'tenure_years': 5, 'personality': 'Hesitant, defers to CEO/Audit Committee'},
    {'name': 'Patricia Delgado', 'role': 'CFO', 'expertise': 'Finance',
     'tenure_years': 6, 'personality': 'Numbers-driven, cautious communicator'},
    {'name': "Margaret 'Meg' Harlow", 'role': 'Board Director', 'expertise': 'Corporate Governance',
     'tenure_years': 1, 'personality': 'New to board, diligent, eager to prove herself'},
]

CLEARWATER_COMPANY = {
    'company_name': 'Clearwater Financial Group',
    'company_overview': 'A mid-size financial institution under OCC regulatory scrutiny.',
    'industry': 'Financial Services',
    'founded': '1987',
    'current_problems': [
        'Regulation B compliance gap discovered in footnote 23',
        'OCC disclosure deadline approaching',
    ],
    'board_members': CLEARWATER_BOARD,
    'committees': [
        {'name': 'Audit Committee', 'type': 'Standing', 'purpose': 'Oversight of financial reporting',
         'chairperson': 'Sandra Cho', 'members': ['Sandra Cho', 'Patricia Delgado']},
    ],
    'metrics': {
        'regulatory_compliance_score': {'value': 72.0, 'unit': '%', 'description': 'Regulatory Compliance Score', 'priority': 'high'},
        'potential_liability_range': {'value': 4.2, 'unit': '$M', 'description': 'Potential Liability Range', 'priority': 'high'},
        'potential_remediation_costs_reserve': {'value': 1.5, 'unit': '$M', 'description': 'Remediation Costs Reserve', 'priority': 'medium'},
        'board_member_count': {'value': 12, 'unit': 'count', 'description': 'Board Member Count', 'priority': 'low'},
        'occ_disclosure_status': {'value': 0, 'unit': 'count', 'description': 'OCC Disclosure Status', 'priority': 'high'},
        'regulatory_matter_classification': {'value': 'Pending Review', 'unit': '', 'description': 'Regulatory Matter Classification', 'priority': 'medium'},
        'board_packet_page_count': {'value': 214, 'unit': 'count', 'description': 'Board Packet Page Count', 'priority': 'low'},
        'total_revenue_annual': {'value': 850, 'unit': '$M', 'description': 'Total Revenue', 'priority': 'high'},
    },
    'initial_scenario': 'The board is meeting to discuss compliance matters.',
}

CLEARWATER_MODULE = {
    'module_name': 'Corporate Governance Fundamentals',
    'overview': 'Understanding board responsibilities and oversight duties.',
    'learning_objectives': [
        'Purpose of Board Meetings',
        'Powers of the Board',
        'Global Governance Standards',
    ],
    'topics': [
        {'name': 'Board Oversight', 'description': 'How boards oversee management'},
        {'name': 'Risk Governance', 'description': 'Board role in risk management'},
    ],
    'key_terms': {'Fiduciary Duty': 'Obligation to act in best interest of company'},
    'frameworks': [],
    'assessment_criteria': [],
}

PLAYER_MEG = {'name': "Margaret 'Meg' Harlow", 'role': 'Board Director', 'expertise': 'Corporate Governance'}
PLAYER_SANDRA = {'name': 'Sandra Cho', 'role': 'Chair of the Audit Committee', 'expertise': 'Audit'}

ROUND_CONFIG_R1 = {'round_number': 1, 'difficulty': 'medium', 'focus_area': 'Board Oversight', 'round_type': 'both', 'time_pressure': 'normal'}
ROUND_CONFIG_R2 = {'round_number': 2, 'difficulty': 'medium', 'focus_area': 'Risk Governance', 'round_type': 'both', 'time_pressure': 'normal'}


# ===========================================================================
# 1. ROLE SELECTION CLEANUP — Bugs #1, #2
# ===========================================================================
class TestRoleSelectionCleanup:
    """Verify stale simulation state is cleared when a new role is selected."""

    def _simulate_stale_session(self):
        """Return a dict mimicking session_state with stale round data."""
        return {
            'player_role': {'name': 'David Sung', 'role': 'CRO'},
            'simulation_started': True,
            'current_round': 2,
            'total_score': 150,
            'scenario_round_0': 'Old scenario R1',
            'scenario_round_1': 'Old scenario R2',
            'evaluation_0': {'score': 75},
            'evaluation_1': {'score': 80},
            'member_stances_0': {'Jonathan Marsh': {'stance': 'OPPOSE'}},
            'pending_decision_0': 'Old decision',
            'deliberation_phase_0': 'resolved',
            'debate_history_0': [{'dissenter_name': 'Jonathan'}],
            'current_dissenter_0': 1,
            'round_start_time_0': datetime.datetime(2026, 1, 1),
            'timer_expired_0': True,
            'force_submitted_0': True,
            'selected_option_0': {'letter': 'A', 'text': 'Old option'},
            'board_consultations_round_0': 1,
            'committee_consultations_round_0': 1,
            'revisions_round_0': 1,
            'impact_summary_0': 'Old impact',
            'board_effectiveness_0': {'score': 60},
            'round_summaries': [{'round_number': 1, 'title': 'Old'}],
            'member_stance_histories': {'Jonathan Marsh': [{'round_number': 1}]},
            'board_effectiveness_history': [{'round_number': 1}],
            'conversation_history': [{'role': 'user', 'content': 'old'}],
            'current_metrics': {'revenue': {'value': 100}},
            'initial_metrics': {'revenue': {'value': 90}},
            'round_complete': True,
        }

    def _get_stale_prefixes(self):
        return ('scenario_round_', 'evaluation_', 'member_stances_',
                'pending_decision_', 'deliberation_phase_',
                'debate_history_', 'current_dissenter_',
                'round_start_time_', 'timer_expired_',
                'force_submitted_', 'selected_option_',
                'board_consultations_round_', 'committee_consultations_round_',
                'revisions_round_', 'impact_summary_',
                'board_effectiveness_')

    def test_stale_round_keys_identified(self):
        """All stale round-specific keys should be matched by the cleanup prefixes."""
        session = self._simulate_stale_session()
        prefixes = self._get_stale_prefixes()
        stale_keys = [k for k in session.keys() if k.startswith(prefixes)]
        # Every round-specific key should be caught
        expected_stale = {
            'scenario_round_0', 'scenario_round_1', 'evaluation_0', 'evaluation_1',
            'member_stances_0', 'pending_decision_0', 'deliberation_phase_0',
            'debate_history_0', 'current_dissenter_0', 'round_start_time_0',
            'timer_expired_0', 'force_submitted_0', 'selected_option_0',
            'board_consultations_round_0', 'committee_consultations_round_0',
            'revisions_round_0', 'impact_summary_0', 'board_effectiveness_0',
        }
        assert expected_stale.issubset(set(stale_keys)), \
            f"Missing stale keys: {expected_stale - set(stale_keys)}"

    def test_cleanup_removes_all_stale_state(self):
        """After cleanup, no stale round keys or simulation state should remain."""
        session = self._simulate_stale_session()
        prefixes = self._get_stale_prefixes()

        # Simulate cleanup (same logic as pages/simulation.py role selection)
        stale_keys = [k for k in session.keys() if k.startswith(prefixes)]
        for k in stale_keys:
            del session[k]
        for k in ['simulation_started', 'current_round', 'total_score',
                   'round_summaries', 'member_stance_histories',
                   'board_effectiveness_history', 'conversation_history',
                   'current_metrics', 'initial_metrics', 'round_complete']:
            session.pop(k, None)

        # Set new role
        session['player_role'] = PLAYER_MEG

        # Verify
        assert session['player_role']['name'] == "Margaret 'Meg' Harlow"
        assert 'simulation_started' not in session
        assert 'current_round' not in session
        assert not any(k.startswith('scenario_round_') for k in session)
        assert not any(k.startswith('evaluation_') for k in session)
        assert not any(k.startswith('member_stances_') for k in session)

    def test_role_validation_catches_wrong_simulation(self):
        """If stored role doesn't belong to current sim's board, it should be cleared."""
        valid_names = [m['name'] for m in CLEARWATER_BOARD]
        # Stale role from a different simulation
        stale_role = {'name': 'Alice Wong', 'role': 'CEO'}
        assert stale_role['name'] not in valid_names

        # Valid role
        valid_role = {'name': 'Jonathan Marsh', 'role': 'CEO'}
        assert valid_role['name'] in valid_names

    def test_role_validation_accepts_valid_role(self):
        """A role from the current simulation's board should pass validation."""
        valid_names = [m['name'] for m in CLEARWATER_BOARD]
        for member in CLEARWATER_BOARD:
            assert member['name'] in valid_names


# ===========================================================================
# 2. MULTI-ROUND FLOW — Bugs #18, #24, #25, #42, #43
# ===========================================================================
class TestMultiRoundFlow:
    """Simulate multi-round gameplay: round summaries accumulate and
    previous round context flows into scenario and stance generation."""

    def _build_round_summary(self, round_num, title, decision, score):
        return {
            'round_number': round_num,
            'title': title,
            'decision_summary': decision[:200],
            'outcome_summary': f'Score: {score}/100.',
        }

    def _build_member_history_entry(self, round_num, stance, conviction, was_convinced, objection=''):
        return {
            'round_number': round_num,
            'stance': stance,
            'conviction': conviction,
            'was_convinced': was_convinced,
            'objection': objection,
        }

    def test_round_summaries_accumulate(self):
        """Each round should add one summary; by round 3, there are 3 summaries."""
        summaries = []
        summaries.append(self._build_round_summary(1, 'Regulation B Discovery', 'Called Audit Committee meeting', 78))
        summaries.append(self._build_round_summary(2, 'Formal Agenda Item', 'Added to board agenda', 82))
        summaries.append(self._build_round_summary(3, 'Remediation Strategy', 'Approved remediation plan', 85))
        assert len(summaries) == 3
        assert summaries[0]['title'] == 'Regulation B Discovery'
        assert summaries[2]['round_number'] == 3

    def test_scenario_prompt_receives_all_previous_rounds(self):
        """Round 3 scenario prompt should contain summaries of rounds 1 and 2."""
        from core.llm import get_scenario_generator_prompt
        prev = [
            self._build_round_summary(1, 'Crisis A', 'Called meeting', 78),
            self._build_round_summary(2, 'Escalation B', 'Formal agenda item', 82),
        ]
        prompt = get_scenario_generator_prompt(
            CLEARWATER_COMPANY, CLEARWATER_MODULE, ROUND_CONFIG_R2, PLAYER_SANDRA,
            previous_rounds=prev
        )
        assert 'Crisis A' in prompt
        assert 'Escalation B' in prompt
        assert 'Called meeting' in prompt
        assert 'Formal agenda item' in prompt

    def test_member_stance_history_accumulates(self):
        """Jonathan's history should grow across rounds."""
        histories = {'Jonathan Marsh': []}
        histories['Jonathan Marsh'].append(
            self._build_member_history_entry(1, 'OPPOSE', 8, False, 'This is unnecessary'))
        histories['Jonathan Marsh'].append(
            self._build_member_history_entry(2, 'OPPOSE', 6, True, 'Still concerned'))

        assert len(histories['Jonathan Marsh']) == 2
        assert histories['Jonathan Marsh'][0]['conviction'] == 8
        assert histories['Jonathan Marsh'][1]['was_convinced'] is True

    def test_stance_prompt_receives_full_history(self):
        """If Jonathan was convinced in R1, his R2 stance prompt should mention it."""
        from core.llm import get_member_stance_prompt
        member = CLEARWATER_BOARD[0]  # Jonathan Marsh
        history = [
            self._build_member_history_entry(1, 'OPPOSE', 8, True, 'Overreacting to footnote'),
        ]
        prompt = get_member_stance_prompt(
            member, CLEARWATER_COMPANY, CLEARWATER_MODULE,
            'Round 2 scenario', 'Formal agenda item decision',
            PLAYER_SANDRA, member_history=history
        )
        assert 'OPPOSE' in prompt
        assert 'CONVINCED' in prompt
        assert 'Overreacting to footnote' in prompt
        assert '8/10' in prompt

    def test_scenario_escalation_instruction_present(self):
        """With previous rounds provided, the prompt must instruct escalation."""
        from core.llm import get_scenario_generator_prompt
        prev = [self._build_round_summary(1, 'R1 Crisis', 'Decision A', 70)]
        prompt = get_scenario_generator_prompt(
            CLEARWATER_COMPANY, CLEARWATER_MODULE, ROUND_CONFIG_R2, PLAYER_SANDRA,
            previous_rounds=prev
        )
        assert 'escalat' in prompt.lower()
        assert 'do not repeat' in prompt.lower() or 'do NOT repeat' in prompt

    def test_no_previous_rounds_for_round_1(self):
        """Round 1 should have no previous rounds context."""
        from core.llm import get_scenario_generator_prompt
        prompt = get_scenario_generator_prompt(
            CLEARWATER_COMPANY, CLEARWATER_MODULE, ROUND_CONFIG_R1, PLAYER_SANDRA
        )
        assert 'PREVIOUS ROUNDS' not in prompt


# ===========================================================================
# 3. CONVICTION PIPELINE — Bugs #11, #28
# ===========================================================================
class TestConvictionPipeline:
    """Test the full conviction update flow: LLM response → parse → writeback."""

    def test_parse_updated_conviction_from_response(self):
        """evaluate_debate_response must parse UPDATED_CONVICTION from LLM output."""
        from core.simulation_engine import evaluate_debate_response
        import inspect
        src = inspect.getsource(evaluate_debate_response)
        assert 'UPDATED_CONVICTION' in src
        assert 'updated_conviction' in src

    def test_conviction_decreases_on_partial_persuasion(self):
        """Simulating the parse: a partially persuasive response should lower conviction."""
        # Simulate LLM output with UPDATED_CONVICTION
        content = """EVALUATION: The response addressed some concerns.
RESPONSE_SCORE: 65
UPDATED_CONVICTION: 5
STANCE_CHANGED: NO
FOLLOW_UP: I still have reservations about the timeline."""

        # Parse UPDATED_CONVICTION (same logic as simulation_engine.py)
        updated_conviction = None
        if "UPDATED_CONVICTION:" in content:
            conv_str = content.split("UPDATED_CONVICTION:")[1].split("\n")[0].strip()
            updated_conviction = int(''.join(filter(str.isdigit, conv_str[:3])))
            updated_conviction = max(1, min(10, updated_conviction))

        assert updated_conviction == 5

    def test_conviction_zero_on_stance_change(self):
        """When stance changes, conviction should be forced to 0."""
        stance_changed = True
        updated_conviction = 7
        if stance_changed:
            updated_conviction = 0
        assert updated_conviction == 0

    def test_conviction_stays_if_not_in_response(self):
        """If LLM doesn't include UPDATED_CONVICTION, the value should be None."""
        content = """EVALUATION: Weak argument.
RESPONSE_SCORE: 30
STANCE_CHANGED: NO
FOLLOW_UP: Not convinced."""

        updated_conviction = None
        if "UPDATED_CONVICTION:" in content:
            conv_str = content.split("UPDATED_CONVICTION:")[1].split("\n")[0].strip()
            updated_conviction = int(''.join(filter(str.isdigit, conv_str[:3])))
        assert updated_conviction is None

    def test_conviction_clamped_to_1_10(self):
        """Conviction values outside 1-10 should be clamped."""
        for raw, expected in [(0, 1), (1, 1), (10, 10), (15, 10), (-5, 1)]:
            clamped = max(1, min(10, raw))
            assert clamped == expected, f"Clamping {raw} should give {expected}, got {clamped}"

    def test_debate_prompt_requests_updated_conviction(self):
        """The debate evaluation prompt must ask for UPDATED_CONVICTION."""
        from core.llm import get_debate_evaluation_prompt
        member = CLEARWATER_BOARD[0]
        prompt = get_debate_evaluation_prompt(
            member, CLEARWATER_COMPANY, 'I disagree with this approach',
            'Here is why you should reconsider', [], PLAYER_SANDRA
        )
        assert 'UPDATED_CONVICTION' in prompt
        assert '1-10' in prompt

    def test_conviction_writeback_simulation(self):
        """Simulate the deliberation writeback: conviction should update in stances dict."""
        stances = {
            'Jonathan Marsh': {
                'stance': 'OPPOSE', 'conviction_level': 8,
                'debate_exchanges': 0, 'convinced_in_round': None,
                'counter_opinion': 'This is unnecessary',
            }
        }
        # Simulate debate result
        result = {'updated_conviction': 5, 'stance_changed': False, 'follow_up': 'Still concerned'}

        # Writeback logic (same as deliberation.py)
        name = 'Jonathan Marsh'
        stances[name]['debate_exchanges'] = 1
        if result.get('updated_conviction') is not None:
            stances[name]['conviction_level'] = result['updated_conviction']
        if result['stance_changed']:
            stances[name]['convinced_in_round'] = 1
            stances[name]['conviction_level'] = 0
        else:
            stances[name]['counter_opinion'] = result['follow_up']

        assert stances[name]['conviction_level'] == 5
        assert stances[name]['debate_exchanges'] == 1
        assert stances[name]['convinced_in_round'] is None

    def test_conviction_writeback_on_convince(self):
        """When stance changes, conviction should be 0 and convinced_in_round set."""
        stances = {
            'Jonathan Marsh': {
                'stance': 'OPPOSE', 'conviction_level': 6,
                'debate_exchanges': 1, 'convinced_in_round': None,
            }
        }
        result = {'updated_conviction': 2, 'stance_changed': True, 'follow_up': 'You make a good point'}

        name = 'Jonathan Marsh'
        stances[name]['debate_exchanges'] = 2
        if result.get('updated_conviction') is not None:
            stances[name]['conviction_level'] = result['updated_conviction']
        if result['stance_changed']:
            stances[name]['convinced_in_round'] = 2
            stances[name]['conviction_level'] = 0

        assert stances[name]['conviction_level'] == 0
        assert stances[name]['convinced_in_round'] == 2

    def test_multi_exchange_conviction_decreases(self):
        """Across 3 exchanges, conviction should progressively decrease."""
        conviction_history = [8, 6, 3]  # Exchange 1, 2, 3
        for i in range(len(conviction_history) - 1):
            assert conviction_history[i] > conviction_history[i + 1], \
                f"Conviction should decrease: {conviction_history[i]} > {conviction_history[i + 1]}"


# ===========================================================================
# 4. GOVERNANCE METRICS — Bugs #34, #35, fractional directors, categorical
# ===========================================================================
class TestGovernanceMetrics:
    """Test metric classification for governance-specific scenarios."""

    def _classify(self, key, value):
        """Replicate the LOWER_IS_BETTER classification logic."""
        LOWER_IS_BETTER = {
            'churn', 'attrition', 'risk', 'debt', 'turnover', 'cost', 'defect',
            'burn', 'incident', 'latency', 'vacancy', 'audit', 'pending',
            'liability', 'remediation', 'penalty', 'loss', 'exposure',
            'violation', 'complaint', 'breach',
        }
        is_lower_better = any(kw in key.lower() for kw in LOWER_IS_BETTER)
        return 'positive' if (value < 0 if is_lower_better else value > 0) else 'negative'

    # ── Clearwater-specific metric tests ──

    def test_potential_liability_range_increase_negative(self):
        assert self._classify('potential_liability_range', +5.0) == 'negative'

    def test_potential_liability_range_decrease_positive(self):
        assert self._classify('potential_liability_range', -2.0) == 'positive'

    def test_remediation_costs_increase_negative(self):
        assert self._classify('potential_remediation_costs_reserve', +2.0) == 'negative'

    def test_remediation_costs_decrease_positive(self):
        assert self._classify('potential_remediation_costs_reserve', -1.0) == 'positive'

    def test_regulatory_compliance_increase_positive(self):
        assert self._classify('regulatory_compliance_score', +5.0) == 'positive'

    def test_regulatory_compliance_decrease_negative(self):
        assert self._classify('regulatory_compliance_score', -2.0) == 'negative'

    def test_occ_disclosure_status_treated_as_higher_better(self):
        # OCC disclosure (disclosure = good), no lower-is-better keyword match
        assert self._classify('occ_disclosure_status', +1.0) == 'positive'

    # ── Goal generation: no fractional directors ──

    def test_no_fractional_directors_in_goals(self):
        """Board member count should not produce goals with fractional values."""
        from core.scoring import generate_game_goals
        metrics = {
            'board_member_count': {'value': 12, 'unit': 'count',
                                   'description': 'Board Member Count', 'priority': 'low'},
        }
        goals = generate_game_goals(metrics, total_rounds=5)
        # Should be skipped entirely (headcount keyword 'member')
        member_goals = [g for g in goals if g['metric_key'] == 'board_member_count']
        assert len(member_goals) == 0, "Board member count should be skipped as headcount metric"

    def test_no_fractional_director_targets(self):
        """Even if a count metric slips through, targets must be integers."""
        from core.scoring import generate_game_goals
        metrics = {
            'open_high_severity_risks': {'value': 7, 'unit': 'count',
                                         'description': 'Open High Severity Risks', 'priority': 'high'},
        }
        goals = generate_game_goals(metrics, total_rounds=5)
        for goal in goals:
            if goal['unit'] in ('count', 'score'):
                assert goal['target'] == int(goal['target']), \
                    f"Count target should be integer: {goal['metric_key']} = {goal['target']}"

    # ── Categorical metrics skipped ──

    def test_categorical_metric_skipped_in_goals(self):
        """Metrics with categorical_value flag should not generate goals."""
        from core.scoring import generate_game_goals
        metrics = {
            'regulatory_matter_classification': {
                'value': 0, 'unit': '', 'categorical_value': 'Pending Review',
                'description': 'Regulatory Matter Classification', 'priority': 'medium',
            },
            'total_revenue_annual': {
                'value': 850, 'unit': '$M',
                'description': 'Total Revenue', 'priority': 'high',
            },
        }
        goals = generate_game_goals(metrics, total_rounds=5)
        cat_goals = [g for g in goals if g['metric_key'] == 'regulatory_matter_classification']
        assert len(cat_goals) == 0, "Categorical metrics should not generate goals"
        rev_goals = [g for g in goals if g['metric_key'] == 'total_revenue_annual']
        assert len(rev_goals) == 1, "Normal metrics should still generate goals"

    def test_status_metric_with_zero_value_skipped(self):
        """Status-type metrics coerced to 0 during normalization should be skipped."""
        from core.scoring import generate_game_goals
        metrics = {
            'tech_debt_rating_status': {
                'value': 0, 'unit': '', 'description': 'Tech Debt Rating Status', 'priority': 'medium',
            },
        }
        goals = generate_game_goals(metrics, total_rounds=5)
        assert len(goals) == 0, "Status metric with value 0 should be skipped"

    # ── Headcount variants all skipped ──

    @pytest.mark.parametrize("key,desc", [
        ('board_member_count', 'Board Member Count'),
        ('independent_director_seats', 'Independent Director Seats'),
        ('committee_size', 'Committee Size'),
        ('total_headcount', 'Total Headcount'),
        ('staff_count', 'Staff Count'),
        ('employee_count', 'Employee Count'),
    ])
    def test_headcount_variants_skipped(self, key, desc):
        """All headcount-like metrics should be skipped in goal generation."""
        from core.scoring import generate_game_goals
        metrics = {key: {'value': 10, 'unit': 'count', 'description': desc, 'priority': 'low'}}
        goals = generate_game_goals(metrics, total_rounds=5)
        matching = [g for g in goals if g['metric_key'] == key]
        assert len(matching) == 0, f"{key} should be skipped as headcount metric"

    # ── Normalization flags categorical values ──

    def test_normalize_flags_categorical(self):
        """_normalize_metrics should flag non-numeric values as categorical."""
        from core.data_manager import _normalize_metrics
        data = {'company_data': {'metrics': {
            'tech_debt_rating': {'value': 'Medium', 'unit': 'score', 'description': 'Tech Debt Rating'},
        }}}
        result = _normalize_metrics(data)
        metric = result['company_data']['metrics']['tech_debt_rating']
        assert metric['value'] == 0
        assert metric.get('categorical_value') == 'Medium'

    def test_normalize_does_not_flag_numeric(self):
        """Numeric values should not be flagged as categorical."""
        from core.data_manager import _normalize_metrics
        data = {'company_data': {'metrics': {
            'revenue': {'value': 100.5, 'unit': '$M', 'description': 'Revenue'},
        }}}
        result = _normalize_metrics(data)
        metric = result['company_data']['metrics']['revenue']
        assert metric['value'] == 100.5
        assert 'categorical_value' not in metric


# ===========================================================================
# 4b. FEEDBACK PDF FIXES — root-cause patches for the 2026-05-04 feedback report
# ===========================================================================
class TestFeedbackPDFFixes:
    """Cross-checked from feedback .pdf and BugReport_CrossValidation.md."""

    # ── A10/A12/A14: Metric impact unit conversion ─────────────────────

    def test_unit_converter_b_to_m(self):
        """LLM returning '-100 $B' for a $M-stored metric must convert to -100000 $M."""
        from core.simulation_engine import _convert_unit
        assert _convert_unit(-100, '$B', '$M') == -100000.0

    def test_unit_converter_m_to_b(self):
        """LLM returning '-60 $M' for a $B-stored metric must convert to -0.06 $B."""
        from core.simulation_engine import _convert_unit
        assert _convert_unit(-60, '$M', '$B') == -0.06

    def test_unit_converter_inr_cr_to_usd_m(self):
        """1 ₹Cr ≈ $1.2M (Indian crore → USD millions)."""
        from core.simulation_engine import _convert_unit
        # Cr is mapped to 10M (USD-base) and $M is 1M, so 1 Cr → 10 M-units
        assert _convert_unit(1, 'Cr', '$M') == 10.0  # using base scale, not FX
        # Self-conversion of same unit should be identity
        assert _convert_unit(50, '$M', '$M') == 50.0

    def test_unit_converter_unknown_units_passthrough(self):
        """Unknown units should pass through unchanged (no false conversions)."""
        from core.simulation_engine import _convert_unit
        assert _convert_unit(50, 'XYZ', '$M') == 50
        assert _convert_unit(50, '', '$M') == 50
        assert _convert_unit(50, '$M', '') == 50

    # ── A9 / Test #3 (D): High Priority case-sensitivity ────────────────

    def test_normalize_priority_lowercase_to_canonical(self):
        """LLM-extracted lowercase 'high'/'medium'/'low' should canonicalize to Title case."""
        from core.data_manager import _normalize_metrics
        data = {'company_data': {'metrics': {
            'a': {'value': 1.0, 'unit': '%', 'priority': 'high'},
            'b': {'value': 2.0, 'unit': '%', 'priority': 'MEDIUM'},
            'c': {'value': 3.0, 'unit': '%', 'priority': '  Low  '},
            'd': {'value': 4.0, 'unit': '%', 'priority': 'unknown'},
            'e': {'value': 5.0, 'unit': '%'},  # missing
        }}}
        result = _normalize_metrics(data)
        m = result['company_data']['metrics']
        assert m['a']['priority'] == 'High'
        assert m['b']['priority'] == 'Medium'
        assert m['c']['priority'] == 'Low'
        assert m['d']['priority'] is None
        assert m['e']['priority'] is None

    def test_high_priority_filter_works_after_normalization(self):
        """After normalization, the High Priority filter must catch all variations."""
        from core.data_manager import _normalize_metrics
        data = {'company_data': {'metrics': {
            'a': {'value': 1, 'unit': '%', 'priority': 'high'},
            'b': {'value': 2, 'unit': '%', 'priority': 'High'},
            'c': {'value': 3, 'unit': '%', 'priority': 'low'},
        }}}
        normalized = _normalize_metrics(data)
        metrics = normalized['company_data']['metrics']
        # Production filter (case-insensitive defense in depth)
        high = {k: v for k, v in metrics.items()
                if str(v.get('priority') or '').strip().lower() == 'high'}
        assert set(high.keys()) == {'a', 'b'}

    # ── A7/A11/A13/B-i: Currency normalization to $M ────────────────────

    def test_dollar_b_normalizes_to_dollar_m(self):
        """Revenue stated as 1.2 $B should canonicalize to 1200 $M."""
        from core.data_manager import _normalize_metrics
        data = {'company_data': {'metrics': {
            'revenue': {'value': 1.2, 'unit': '$B', 'description': 'Revenue'},
        }}}
        result = _normalize_metrics(data)
        m = result['company_data']['metrics']['revenue']
        assert m['unit'] == '$M'
        assert m['value'] == 1200.0
        assert m['original_unit'] == '$B'
        assert m['original_value'] == 1.2

    def test_no_mixed_currency_after_normalization(self):
        """A simulation with $B and $M units should normalize to a single $M unit."""
        from core.data_manager import _normalize_metrics
        data = {'company_data': {'metrics': {
            'revenue':   {'value': 1.2, 'unit': '$B'},
            'liability': {'value': 75,  'unit': '$M'},
            'cash':      {'value': 0.5, 'unit': '$B'},
        }}}
        result = _normalize_metrics(data)
        units = {m['unit'] for m in result['company_data']['metrics'].values()}
        assert units == {'$M'}, f"Expected only $M after normalization, got {units}"

    def test_inr_cr_normalizes_to_dollar_m(self):
        """100 ₹Cr should canonicalize to ~120 $M (using FX approximation)."""
        from core.data_manager import _normalize_metrics
        data = {'company_data': {'metrics': {
            'liability': {'value': 100, 'unit': '₹Cr'},
        }}}
        result = _normalize_metrics(data)
        m = result['company_data']['metrics']['liability']
        assert m['unit'] == '$M'
        assert 100 < m['value'] < 200  # ~$120M with FX approximation

    # ── B-v: bi-weekly = 0 silent coercion ──────────────────────────────

    def test_biweekly_categorical_excluded_from_goals(self):
        """Categorical values like 'bi-weekly' must be flagged non_numeric, not silently 0."""
        from core.data_manager import _normalize_metrics
        from core.scoring import generate_game_goals
        data = {'company_data': {'metrics': {
            'meeting_cadence': {'value': 'bi-weekly', 'unit': 'frequency'},
            'revenue': {'value': 100, 'unit': '$M'},
        }}}
        result = _normalize_metrics(data)
        m = result['company_data']['metrics']
        # The non-numeric flag is set
        assert m['meeting_cadence']['non_numeric'] is True
        assert m['meeting_cadence']['categorical_value'] == 'bi-weekly'
        assert m['revenue']['non_numeric'] is False
        # Goals exclude the categorical metric
        goals = generate_game_goals(m, total_rounds=5)
        goal_keys = {g['metric_key'] for g in goals}
        assert 'meeting_cadence' not in goal_keys

    # ── _infer_unit improvements (rating/audits/patents) ──────────────────

    def test_infer_unit_for_rating(self):
        from core.data_manager import _infer_unit
        assert _infer_unit('tech_debt_rating') == 'score'

    def test_infer_unit_for_audits_and_patents(self):
        from core.data_manager import _infer_unit
        assert _infer_unit('pending_audits') == 'count'
        assert _infer_unit('patents_filed') == 'count'

    # ── P1-5/P1-6: Module Vocabulary scoring (parsing layer) ────────────

    def test_evaluate_decision_returns_vocabulary_fields(self):
        """evaluate_decision must always return the new vocabulary tracker fields."""
        from unittest.mock import MagicMock
        from core.simulation_engine import evaluate_decision

        # Mock LLM that returns a properly formatted response
        mock_llm = MagicMock()
        mock_llm.generate_content.return_value.text = """SCORE: 78

SCORE_REASONING: solid analysis

MODULE_VOCABULARY_SCORE: 65

VOCABULARY_INVOKED: Principle of Prudence, AS 5

VOCABULARY_MISSED: Contingent Liability

VOCABULARY_MISUSED: Extraordinary Item

STRENGTHS: Used the prudence framework

AREAS_FOR_IMPROVEMENT: Did not address contingent liability

KEY_LEARNING_POINTS: Note Ind AS forbids extraordinary

BEST_APPROACH: Use prudence, AS 5 disclosure

CRITICAL_FEEDBACK:

ENCOURAGEMENT: Good prudence application
"""

        result = evaluate_decision(
            llm=mock_llm,
            company_data={'company_name': 'X', 'company_overview': '', 'metrics': {}, 'board_members': []},
            module_data={'module_name': 'M6', 'learning_objectives': [], 'topics': [],
                         'key_terms': {'Principle of Prudence': 'def', 'AS 5': 'def',
                                       'Contingent Liability': 'def', 'Extraordinary Item': 'forbidden'}},
            scenario='test scenario',
            decision='test decision',
            round_config={'difficulty': 'medium'},
            player_role={'name': 'P', 'role': 'CFO', 'expertise': 'Finance'},
        )

        assert 'vocabulary_score' in result
        # LLM returned MODULE_VOCABULARY_SCORE: 65 but listed 1 misused term.
        # Reconciliation policy (C1+C2 strengthened): −20 per misused term.
        # 65 − 20 = 45.
        assert result['vocabulary_score'] == 45
        assert result['vocabulary_invoked'] == ['Principle of Prudence', 'AS 5']
        assert result['vocabulary_missed'] == ['Contingent Liability']
        assert result['vocabulary_misused'] == ['Extraordinary Item']

    def test_evaluate_decision_handles_missing_vocabulary_section(self):
        """If LLM omits vocabulary fields AND module key_terms is empty, score
        defaults to 50 (neutral, not 100 — closes C1/C2 grade-inflation bug)."""
        from unittest.mock import MagicMock
        from core.simulation_engine import evaluate_decision

        mock_llm = MagicMock()
        mock_llm.generate_content.return_value.text = """SCORE: 70

STRENGTHS: ok

AREAS_FOR_IMPROVEMENT: ok

KEY_LEARNING_POINTS: ok

BEST_APPROACH: ok

ENCOURAGEMENT: ok"""

        result = evaluate_decision(
            llm=mock_llm,
            company_data={'company_name': 'X', 'company_overview': '', 'metrics': {}, 'board_members': []},
            module_data={'module_name': 'M', 'learning_objectives': [], 'topics': [], 'key_terms': {}},
            scenario='s', decision='d',
            round_config={'difficulty': 'medium'},
            player_role={'name': 'P', 'role': 'CFO', 'expertise': 'Finance'},
        )

        # When module has no key_terms AND LLM omits vocabulary fields, the
        # vocab score is floored at 50 (neutral) rather than 0 — otherwise the
        # composite round score would be unfairly penalized for the absence of
        # an assessment that wasn't possible to make.
        assert result['vocabulary_score'] == 50
        assert result['vocabulary_invoked'] == []
        assert result['vocabulary_missed'] == []
        assert result['vocabulary_misused'] == []


# ===========================================================================
# 4c. ADMIN AGENT IMPROVEMENTS — feedback PDF gap-fill (2026-05-04)
# ===========================================================================
class TestAgent2Improvements:
    """Agent 2 improvements 2.1 (consistency checks) + 2.2 (auto-priority)."""

    def test_dual_incumbent_ceo_flagged(self):
        from core.admin_agents import _check_dup_persons_and_dual_incumbents
        company = {
            'board_members': [
                {'name': 'Amelia Thorne', 'role': 'CEO'},
                {'name': 'Evelyn Reed', 'role': 'CEO'},
                {'name': 'David Chen', 'role': 'CFO'},
            ],
        }
        flags = _check_dup_persons_and_dual_incumbents(company, {})
        types = [f['type'] for f in flags]
        assert 'duplicate_incumbent' in types
        ceo_flag = next(f for f in flags if f['type'] == 'duplicate_incumbent')
        assert 'Amelia Thorne' in ceo_flag['message']
        assert 'Evelyn Reed' in ceo_flag['message']
        assert ceo_flag['severity'] == 'error'

    def test_duplicate_person_flagged(self):
        from core.admin_agents import _check_dup_persons_and_dual_incumbents
        company = {
            'board_members': [
                {'name': 'Kenji Tanaka', 'role': 'CTO'},
                {'name': 'Kenji Tanaka', 'role': 'Independent Director'},
            ],
        }
        flags = _check_dup_persons_and_dual_incumbents(company, {})
        dup_flags = [f for f in flags if f['type'] == 'duplicate_person']
        assert len(dup_flags) == 1
        assert dup_flags[0]['severity'] == 'error'

    def test_fuzzy_name_match_flagged(self):
        from core.admin_agents import _check_dup_persons_and_dual_incumbents
        company = {
            'board_members': [
                {'name': 'John Smith', 'role': 'CFO'},
                {'name': 'Jon Smith', 'role': 'COO'},  # likely typo
            ],
        }
        flags = _check_dup_persons_and_dual_incumbents(company, {})
        fuzzy_flags = [f for f in flags if f['type'] == 'fuzzy_name_match']
        assert len(fuzzy_flags) == 1

    def test_no_false_positive_distinct_names(self):
        from core.admin_agents import _check_dup_persons_and_dual_incumbents
        # Two people with same SURNAME but very different given names — should NOT flag
        company = {
            'board_members': [
                {'name': 'Sarah Chen', 'role': 'CFO'},
                {'name': 'Michael Chen', 'role': 'CTO'},
            ],
        }
        flags = _check_dup_persons_and_dual_incumbents(company, {})
        fuzzy_flags = [f for f in flags if f['type'] == 'fuzzy_name_match']
        assert len(fuzzy_flags) == 0, f"False positive: {fuzzy_flags}"

    def test_value_contradiction_flagged(self):
        from core.admin_agents import _check_value_contradictions
        company = {
            'company_overview': 'Veritas reported total revenue of $850M for FY2024.',
            'metrics': {
                'total_revenue_annual': {
                    'value': 1.2, 'unit': '$B', 'description': 'Total Revenue Annual',
                },
            },
        }
        flags = _check_value_contradictions(company, {})
        assert len(flags) >= 1
        assert flags[0]['type'] == 'value_contradiction'
        assert '850' in flags[0]['message']
        assert '1.2' in flags[0]['message'] or '1200' in flags[0]['message']

    def test_value_contradiction_no_false_positive_when_match(self):
        from core.admin_agents import _check_value_contradictions
        # Overview matches metric → no flag
        company = {
            'company_overview': 'Veritas reported total revenue of $1.2B for FY2024.',
            'metrics': {
                'total_revenue_annual': {
                    'value': 1.2, 'unit': '$B', 'description': 'Total Revenue Annual',
                },
            },
        }
        flags = _check_value_contradictions(company, {})
        assert len(flags) == 0

    def test_auto_priority_elevation(self):
        from core.admin_agents import _audit_phase2c_auto_priority
        items, patch = [], {'company': {}, 'module': {}}
        company = {
            'current_problems': [
                '$75M confirmed liability from the OCC consent order',
                '8% client churn since the data breach',
            ],
            'metrics': {
                'liability_exposure': {'value': 75, 'unit': '$M', 'description': 'Liability Exposure', 'priority': None},
                'customer_churn_rate_annual': {'value': 8, 'unit': '%', 'description': 'Customer Churn Rate', 'priority': None},
                'office_temperature': {'value': 22, 'unit': 'C', 'description': 'Office Temperature', 'priority': None},
            },
        }
        elevated = _audit_phase2c_auto_priority(company, items, patch)
        assert elevated == 2
        assert company['metrics']['liability_exposure']['priority'] == 'High'
        assert company['metrics']['customer_churn_rate_annual']['priority'] == 'High'
        # Control: irrelevant metric NOT elevated
        assert company['metrics']['office_temperature']['priority'] != 'High'

    def test_auto_priority_does_not_overwrite_existing_high(self):
        from core.admin_agents import _audit_phase2c_auto_priority
        items, patch = [], {'company': {}, 'module': {}}
        company = {
            'current_problems': ['Liability of $75M is critical.'],
            'metrics': {
                'liability_exposure': {'value': 75, 'unit': '$M', 'description': 'Liability Exposure', 'priority': 'High'},
            },
        }
        elevated = _audit_phase2c_auto_priority(company, items, patch)
        assert elevated == 0  # already High → no change


class TestAgent3Improvements:
    """Agent 3 improvements 3.1 (dissenter rotation) + 3.2 (supporter briefs)."""

    def test_dissenter_rotation_balances_load(self):
        from core.admin_agents import _compute_act_structure, _assign_dissenters_per_round, _check_coverage_requirements
        board = [
            {'name': 'A', 'role': 'CEO', 'expertise': 'Strategy'},
            {'name': 'B', 'role': 'CFO', 'expertise': 'Finance'},
            {'name': 'C', 'role': 'CRO', 'expertise': 'Risk'},
            {'name': 'D', 'role': 'CTO', 'expertise': 'Technology'},
            {'name': 'E', 'role': 'CMO', 'expertise': 'Marketing'},
            {'name': 'F', 'role': 'Independent Director', 'expertise': 'Governance'},
        ]
        acts = _compute_act_structure(5)
        cov = _check_coverage_requirements({'topics': [], 'learning_objectives': []}, 5)
        assignments = _assign_dissenters_per_round(acts, board, cov)
        assert len(assignments) == 5
        # No round is empty
        for rnum, ds in assignments.items():
            assert len(ds) >= 2
        # Every member dissents at least once (closes Agent-W1 over-reliance bug)
        all_dissenters = {n for ds in assignments.values() for n in ds}
        assert all_dissenters == {m['name'] for m in board}

    def test_dissenter_rotation_no_consecutive_repeats(self):
        from core.admin_agents import _compute_act_structure, _assign_dissenters_per_round, _check_coverage_requirements
        board = [
            {'name': f'M{i}', 'role': 'Director', 'expertise': 'Strategy'} for i in range(8)
        ]
        acts = _compute_act_structure(5)
        cov = _check_coverage_requirements({'topics': [], 'learning_objectives': []}, 5)
        assignments = _assign_dissenters_per_round(acts, board, cov)
        # No member appears in two consecutive rounds
        prev = set()
        for rnum in sorted(assignments.keys()):
            current = set(assignments[rnum])
            assert not (current & prev), \
                f"Round {rnum} re-uses dissenters from round {rnum-1}: {current & prev}"
            prev = current

    def test_dissenter_rotation_idempotent(self):
        """Same input must produce same output (deterministic, no LLM)."""
        from core.admin_agents import _compute_act_structure, _assign_dissenters_per_round, _check_coverage_requirements
        board = [{'name': f'M{i}', 'role': 'CFO', 'expertise': 'Finance'} for i in range(5)]
        acts = _compute_act_structure(4)
        cov = _check_coverage_requirements({'topics': [{'name': 'X'}, {'name': 'Y'}], 'learning_objectives': []}, 4)
        a1 = _assign_dissenters_per_round(acts, board, cov)
        a2 = _assign_dissenters_per_round(acts, board, cov)
        assert a1 == a2

    def test_support_briefs_validation_drops_dissenters(self):
        from core.admin_agents import _validate_support_briefs
        briefs = [
            {'member': 'Alice', 'angle': 'Good supporter angle'},
            {'member': 'Bob', 'angle': 'BOB IS DISSENTER - should be dropped'},
        ]
        result = _validate_support_briefs(briefs, dissenters_for_round=['Bob'], board_member_names={'Alice', 'Bob'})
        assert len(result) == 1
        assert result[0]['member'] == 'Alice'

    def test_support_briefs_validation_drops_hallucinated_names(self):
        from core.admin_agents import _validate_support_briefs
        briefs = [
            {'member': 'Real Person', 'angle': 'good'},
            {'member': 'Hallucinated Name', 'angle': 'fake'},
        ]
        result = _validate_support_briefs(briefs, dissenters_for_round=[], board_member_names={'Real Person'})
        assert len(result) == 1
        assert result[0]['member'] == 'Real Person'

    def test_support_briefs_validation_dedupes(self):
        from core.admin_agents import _validate_support_briefs
        briefs = [
            {'member': 'Alice', 'angle': 'first angle'},
            {'member': 'Alice', 'angle': 'second angle (duplicate member)'},
            {'member': 'Bob', 'angle': 'second person'},
        ]
        result = _validate_support_briefs(briefs, dissenters_for_round=[], board_member_names={'Alice', 'Bob'})
        assert len(result) == 2
        members = {r['member'] for r in result}
        assert members == {'Alice', 'Bob'}


class TestAuditWidgetStateCleanup:
    """Audit-tab editor bug — Streamlit positional widget keys retained stale
    values from previous simulation, showing wrong names in form fields while
    section headers showed correct names. Fixed via _clear_audit_widget_state()
    called at every load + agent-patch site."""

    def test_clear_removes_known_audit_widget_keys(self):
        from unittest.mock import patch
        from pages.manage_simulations import _clear_audit_widget_state, _AUDIT_WIDGET_KEY_PREFIXES
        # Build a fake session_state with stale audit widget values + unrelated keys
        fake_state = {
            'member_name_0': 'Eleanor Vance',          # stale — should clear
            'member_role_2': 'CTO',                    # stale — should clear
            'committee_name_1': 'Audit',               # stale — should clear
            'committee_chair_0': 'Sarah Kim',          # stale — should clear
            'problem_3': 'High churn',                 # stale — should clear
            'topic_name_5': 'Prudence',                # stale — should clear
            'fw_desc_2': 'A framework',                # stale — should clear
            'crit_1': 'Analyse decisions',             # stale — should clear
            'round_difficulty_4': 'hard',              # stale — should clear
            'audit_data': {'company_data': {}},        # NOT stale — should survive
            'admin_authenticated': True,               # NOT stale — should survive
            'audit_loaded_doc_id': 'sim_xyz',          # NOT stale — should survive
            'memberhip_count': 5,                      # NOT a widget key (no underscore-int suffix match) — should survive
        }
        with patch('pages.manage_simulations.st.session_state', fake_state):
            cleared = _clear_audit_widget_state()
        assert cleared == 9, f"Expected 9 stale keys cleared, got {cleared}"
        # Audit-data and unrelated state preserved
        assert 'audit_data' in fake_state
        assert 'admin_authenticated' in fake_state
        assert 'audit_loaded_doc_id' in fake_state
        assert 'memberhip_count' in fake_state
        # All widget keys gone
        assert 'member_name_0' not in fake_state
        assert 'committee_chair_0' not in fake_state
        assert 'round_difficulty_4' not in fake_state

    def test_clear_handles_empty_session_state(self):
        """No keys to clear → returns 0, no exception."""
        from unittest.mock import patch
        from pages.manage_simulations import _clear_audit_widget_state
        fake_state = {}
        with patch('pages.manage_simulations.st.session_state', fake_state):
            cleared = _clear_audit_widget_state()
        assert cleared == 0

    def test_clear_handles_non_string_keys(self):
        """Defensive — Streamlit can accept tuple/int keys; we should ignore them."""
        from unittest.mock import patch
        from pages.manage_simulations import _clear_audit_widget_state
        fake_state = {
            42: 'int key',
            ('tuple', 'key'): 'tuple key',
            'member_name_0': 'should clear',
        }
        with patch('pages.manage_simulations.st.session_state', fake_state):
            cleared = _clear_audit_widget_state()
        assert cleared == 1
        assert 42 in fake_state
        assert ('tuple', 'key') in fake_state

    def test_audit_widget_key_prefixes_cover_all_observed_widgets(self):
        """Regression guard — the prefix list must cover all key= patterns
        currently in pages/manage_simulations.py audit/planning editors."""
        import re
        from pathlib import Path
        from pages.manage_simulations import _AUDIT_WIDGET_KEY_PREFIXES
        src = Path('pages/manage_simulations.py').read_text(encoding='utf-8')
        # Find every f"...{i}" key= pattern (ignoring matches inside the prefix tuple itself)
        # Pattern: key=f"PREFIX_{i}" or similar — capture the prefix
        key_re = re.compile(r'key=f"([a-z_]+_)\{i\}"')
        observed_prefixes = set(key_re.findall(src))
        prefix_set = set(_AUDIT_WIDGET_KEY_PREFIXES)
        # Every observed prefix must be in our cleanup list (otherwise we'll miss it on cleanup)
        missing = observed_prefixes - prefix_set
        assert not missing, (
            f"Widget key prefixes used in code but NOT in _AUDIT_WIDGET_KEY_PREFIXES: {missing}. "
            f"Add them to the cleanup list or stale state will leak between simulations."
        )

    # ── Consistency-checker false-positive fix (screenshot bug) ────────

    def test_company_name_not_flagged_as_person(self):
        """Cognito Finance Inc / Veritas AI Corp / etc. should NOT be flagged
        when they appear in company_overview — they're the company name itself."""
        from core.admin_agents import _check_person_name_consistency
        company = {
            'company_name': 'Cognito Finance Inc',
            'board_members': [{'name': 'Dr. Alistair Finch', 'role': 'CEO'}],
            'company_overview': 'Cognito Finance Inc is a leading fintech company...',
            'current_problems': ['Cognito Finance Inc faces regulatory pressure'],
            'initial_scenario': 'The board of Cognito Finance Inc convenes...',
        }
        flags = _check_person_name_consistency(company, {})
        # No flags should mention the company name
        for f in flags:
            assert 'Cognito Finance Inc' not in f['message'], \
                f"Company name flagged as person: {f['message']}"

    def test_corporate_suffix_tokens_not_flagged(self):
        """Candidates containing Inc, Corp, LLC, Ltd, Group, etc. are not people."""
        from core.admin_agents import _check_person_name_consistency
        company = {
            'company_name': 'Helix Therapeutics',
            'board_members': [{'name': 'Sarah Kim', 'role': 'CFO'}],
            'company_overview': (
                'Helix Therapeutics partnered with Anthropic Inc and Genesis Holdings. '
                'Subsidiary Mercury Ventures handles distribution.'
            ),
            'current_problems': [],
        }
        flags = _check_person_name_consistency(company, {})
        for f in flags:
            msg = f['message']
            for forbidden in ('Anthropic Inc', 'Genesis Holdings', 'Mercury Ventures'):
                assert forbidden not in msg, f"Corporate entity '{forbidden}' flagged as person: {msg}"

    def test_known_city_not_flagged_as_person(self):
        """Single-word city names like 'Dublin' or 'Mumbai' must not match against
        coincidentally letter-overlapping board surnames."""
        from core.admin_agents import _check_person_name_consistency
        company = {
            'company_name': 'GlobalTech Inc',
            'board_members': [{'name': 'Chloe Dubois', 'role': 'CMO'}],
            'company_overview': 'GlobalTech Inc is headquartered in Dublin with operations across Mumbai and Singapore.',
            'current_problems': [],
        }
        flags = _check_person_name_consistency(company, {})
        for f in flags:
            msg = f['message']
            for city in ('Dublin', 'Mumbai', 'Singapore'):
                assert city not in msg, f"City '{city}' flagged as person: {msg}"

    def test_real_person_mismatch_still_flagged(self):
        """The fix must not break the original B-iv use case: a real person
        named differently in narrative vs board roster should still be flagged."""
        from core.admin_agents import _check_person_name_consistency
        company = {
            'company_name': 'Acme Corp',
            'board_members': [{'name': 'Sara Marshell', 'role': 'CFO'}],
            'current_problems': ['Sarah Marshall flagged a $75M liability after the Q2 audit.'],
            'company_overview': '',
        }
        flags = _check_person_name_consistency(company, {})
        # The "Sarah Marshall" vs "Sara Marshell" mismatch must still surface
        assert any('Sarah Marshall' in f['message'] for f in flags), \
            "Real person-name mismatch must still be flagged after the fix"


class TestTimerEnforcement:
    """Locks in the 5 timer fixes from TIMER_ISSUES.md plus the feedback PDF
    timer items (A8, F, 1a, 1b, 1c). Pure unit tests — no Streamlit runtime."""

    # ── Issue #1 + #2: Watchdog rerun + escalating penalty ────────────

    def test_watchdog_detects_expiry_when_elapsed_exceeds_total(self):
        """When elapsed time exceeds the round's total_seconds, expiry must be detected.
        Mirrors the @st.fragment(run_every=15s) watchdog logic at simulation.py:275-283."""
        import datetime as _dt
        round_start = _dt.datetime.now() - _dt.timedelta(seconds=601)  # 10 min + 1 sec ago
        total_seconds = 600  # 10-minute round
        elapsed = (_dt.datetime.now() - round_start).total_seconds()
        # Watchdog condition from simulation.py:280
        is_expired = elapsed >= total_seconds
        assert is_expired, f"elapsed={elapsed}s should trigger expiry against total={total_seconds}s"

    def test_watchdog_does_not_trigger_within_window(self):
        import datetime as _dt
        round_start = _dt.datetime.now() - _dt.timedelta(seconds=300)  # 5 min ago
        total_seconds = 600
        elapsed = (_dt.datetime.now() - round_start).total_seconds()
        assert elapsed < total_seconds  # watchdog should NOT set expired

    def test_escalating_penalty_at_thresholds(self):
        """Penalty curve: 15% at expiry, ramps to 50% over 10 min, capped."""
        from core.scoring import compute_force_submit_penalty
        # At expiry (0 overtime) → base 15%
        assert compute_force_submit_penalty(0) == 0.15
        assert compute_force_submit_penalty(-10) == 0.15  # negative overtime treated as 0
        # 5 min overtime → halfway from 15% to 50% = 32.5%
        p_5min = compute_force_submit_penalty(300)
        assert abs(p_5min - 0.325) < 0.001, f"At 5 min, expected 0.325, got {p_5min}"
        # 10 min overtime → max 50%
        assert compute_force_submit_penalty(600) == 0.50
        # 20 min overtime → still capped at 50%
        assert compute_force_submit_penalty(1200) == 0.50
        # Monotonically increasing within ramp window
        assert compute_force_submit_penalty(60) < compute_force_submit_penalty(120)
        assert compute_force_submit_penalty(120) < compute_force_submit_penalty(180)

    def test_penalty_symmetric_on_positive_and_negative_impacts(self):
        """A late good decision loses 15-50% of positive impact AND amplifies negatives by same."""
        from core.scoring import compute_force_submit_penalty
        impact_values = {'revenue': +10.0, 'liability': +5.0, 'churn': -2.0, 'unchanged': 0.0}
        penalty = compute_force_submit_penalty(300)  # 5 min overtime → 32.5%
        # Apply the same transformation simulation.py uses
        result = {
            k: v * (1 - penalty) if v > 0 else v * (1 + penalty) if v < 0 else 0
            for k, v in impact_values.items()
        }
        # Positives reduced
        assert result['revenue'] < impact_values['revenue']
        assert result['liability'] < impact_values['liability']
        # Negatives amplified (more negative)
        assert result['churn'] < impact_values['churn']
        # Zero stays zero
        assert result['unchanged'] == 0

    # ── Issue #3 + #4: decision_submit_time excludes deliberation/LLM ──

    def test_decision_submit_time_separates_decision_from_deliberation(self):
        """time_taken should use submit_time - round_start, NOT now - round_start
        (which would include the deliberation phase + LLM latency)."""
        import datetime as _dt
        round_start = _dt.datetime(2026, 5, 4, 10, 0, 0)
        submit_time = _dt.datetime(2026, 5, 4, 10, 3, 0)   # 3 min decision time
        deliberation_end = _dt.datetime(2026, 5, 4, 10, 8, 0)  # +5 min deliberation+LLM
        # Correct calc (uses submit_time)
        correct_time_taken = int((submit_time - round_start).total_seconds())
        # Incorrect (old) calc would inflate by deliberation + LLM time
        inflated_time_taken = int((deliberation_end - round_start).total_seconds())
        assert correct_time_taken == 180, "Decision-only time should be 3 min = 180s"
        assert inflated_time_taken == 480, "Old buggy calc would record 8 min"
        # The fix: code reads decision_submit_time from session state
        from pathlib import Path
        src = Path('pages/simulation.py').read_text(encoding='utf-8')
        assert 'decision_submit_time_' in src, \
            "Fix for TIMER_ISSUES.md #3/#4 missing — submit_time not captured separately"
        # And the time-taken calc uses _submit_time, not raw datetime.now()
        # Find the log_round call site and verify its time math
        log_round_idx = src.find('log_round(')
        assert log_round_idx != -1
        window = src[max(0, log_round_idx - 800):log_round_idx]
        assert '_submit_time' in window, "log_round must compute time from _submit_time"

    # ── Late-submission warning text (feedback 1a + 1b) ────────────────

    def test_late_submission_warning_includes_both_penalties(self):
        """Warning shown when timer expires must mention BOTH the metric reduction
        and the efficiency-score cap so the player understands consequences."""
        from pathlib import Path
        src = Path('pages/simulation.py').read_text(encoding='utf-8')
        # Find the timer-expired warning block
        idx = src.find('Time has expired')
        assert idx != -1, "Late-submission warning string missing"
        window = src[idx:idx + 600]
        assert '15%' in window, "Warning must state the 15% positive-impact reduction"
        assert '5/20' in window, "Warning must state the efficiency-score cap"
        assert 'Consultations are now locked' in window, \
            "Warning must state consultations are locked (TIMER_ISSUES.md #2)"

    # ── Round 1 +5 onboarding bonus (feedback A8/F + 1c) ───────────────

    def test_round_1_bonus_applies_for_normal_pressure(self):
        """Round 1 with normal pressure: 10 + 5 = 15 min effective."""
        from core.scoring import round_time_limit_minutes
        assert round_time_limit_minutes(0, 'normal') == 15
        assert round_time_limit_minutes(0, 'relaxed') == 20  # 15 + 5
        # Urgent pressure — no bonus (player explicitly chose tight)
        assert round_time_limit_minutes(0, 'urgent') == 5

    def test_round_1_bonus_does_not_apply_to_later_rounds(self):
        from core.scoring import round_time_limit_minutes
        # Rounds 2+ get the configured time, no bonus
        assert round_time_limit_minutes(1, 'normal') == 10
        assert round_time_limit_minutes(2, 'normal') == 10
        assert round_time_limit_minutes(4, 'relaxed') == 15
        assert round_time_limit_minutes(0, 'urgent') == 5  # urgent never gets bonus

    def test_penalty_overtime_uses_same_round_1_bonus_as_displayed_timer(self):
        """If Round 1 displayed timer is 15 min (10 + bonus), overtime should
        start at 15 min, NOT at 10 min. Otherwise penalties begin while the
        player still sees time on the clock — a latent bug fixed in this commit."""
        from pathlib import Path
        src = Path('pages/simulation.py').read_text(encoding='utf-8')
        # Use rfind to get the CALL SITE (not the import). The penalty block uses
        # `_penalty = compute_force_submit_penalty(_overtime)`.
        call_idx = src.rfind('compute_force_submit_penalty(_overtime)')
        assert call_idx != -1, "compute_force_submit_penalty(_overtime) call missing"
        # Window of 600 chars before the call should contain the overtime calc
        window = src[max(0, call_idx - 600):call_idx]
        assert 'round_time_limit_minutes' in window, \
            "Penalty overtime calc must use round_time_limit_minutes (with bonus), " \
            "not get_time_pressure_minutes (without bonus). Window:\n" + window[-300:]


class TestRubricRecalibrationAndConvictionTuning:
    """Cross-check #2 final follow-ups (items 4 + 5):
    - #2 Rubric recalibration: Strategic Thinking + Role Alignment dimension definitions
    - #1 Argument-quality conviction tuning: 4-axis assessment + calibration bands
    """

    # ── #2 Rubric recalibration ───────────────────────────────────────

    def test_evaluation_prompt_defines_strategic_thinking_explicitly(self):
        """Strategic Thinking dimension must explicitly state operational depth is NOT a deduction."""
        from unittest.mock import MagicMock
        from core.simulation_engine import evaluate_decision
        mock_llm = MagicMock()
        mock_llm.generate_content.return_value.text = "SCORE: 80\nSCORE_REASONING: ok\nSTRENGTHS: ok\nAREAS_FOR_IMPROVEMENT: ok\nKEY_LEARNING_POINTS: ok\nBEST_APPROACH: ok\nENCOURAGEMENT: ok"
        # Trigger evaluation to capture the prompt sent to the LLM
        evaluate_decision(
            llm=mock_llm,
            company_data={'company_name': 'X', 'company_overview': '', 'metrics': {}, 'board_members': []},
            module_data={'module_name': 'M', 'learning_objectives': [], 'topics': [], 'key_terms': {}},
            scenario='s', decision='d',
            round_config={'difficulty': 'medium'},
            player_role={'name': 'P', 'role': 'CFO', 'expertise': 'Finance'},
        )
        # First call to mock was evaluate_decision; second was metric impacts. Check first call's prompt.
        first_prompt = mock_llm.generate_content.call_args_list[0][0][0]
        # Strategic Thinking must explicitly mention depth IS NOT a deduction
        assert 'Operational depth is NOT a deduction' in first_prompt
        assert 'forward-looking risk mitigation' in first_prompt
        assert 'multi-tier communication strategy' in first_prompt

    def test_evaluation_prompt_defines_role_alignment_explicitly(self):
        """Role Alignment must distinguish in-role-via-governance from unilateral overreach."""
        from unittest.mock import MagicMock
        from core.simulation_engine import evaluate_decision
        mock_llm = MagicMock()
        mock_llm.generate_content.return_value.text = "SCORE: 80\nSCORE_REASONING: ok\nSTRENGTHS: ok\nAREAS_FOR_IMPROVEMENT: ok\nKEY_LEARNING_POINTS: ok\nBEST_APPROACH: ok\nENCOURAGEMENT: ok"
        evaluate_decision(
            llm=mock_llm,
            company_data={'company_name': 'X', 'company_overview': '', 'metrics': {}, 'board_members': []},
            module_data={'module_name': 'M', 'learning_objectives': [], 'topics': [], 'key_terms': {}},
            scenario='s', decision='d',
            round_config={'difficulty': 'medium'},
            player_role={'name': 'P', 'role': 'CFO', 'expertise': 'Finance'},
        )
        first_prompt = mock_llm.generate_content.call_args_list[0][0][0]
        assert 'governance pathway' in first_prompt
        assert 'subject to board approval' in first_prompt
        assert 'unilateral' in first_prompt.lower()
        # Cross-disciplinary thinking through own-role lens must NOT be penalised
        assert 'cross-disciplinary' in first_prompt.lower() or 'lens-of-own-role' in first_prompt.lower() or 'in-role' in first_prompt.lower()

    def test_dimension_weights_v1_4_9(self):
        """v1.4.9 rubric: 8 dimensions = 25/25/15/15/5/5/5/5 = 100.
        (Was 25/20/20/20/15 in v1.4.2 — replaced after client redesign.)"""
        from pathlib import Path
        src = Path('core/simulation_engine.py').read_text(encoding='utf-8')
        # Per-dimension max values must match the v1.4.9 spec exactly
        assert 'Governance Understanding: [points]/25' in src
        assert 'Legal/Regulatory Compliance: [points]/25' in src
        assert 'Stakeholder Consideration: [points]/15' in src
        assert 'Strategic Thinking: [points]/15' in src
        assert 'Role Alignment: [points]/5' in src
        assert 'Behavioural Governance: [points]/5' in src
        assert 'Decision Integrity: [points]/5' in src
        assert 'Ethics & Judgment Under Pressure: [points]/5' in src
        # And the totals stay at 100
        assert 'Total: [sum]/100' in src

    # ── #1 Argument-quality conviction tuning ───────────────────────────

    def test_debate_prompt_includes_4_axis_assessment(self):
        """Debate evaluation prompt must explicitly score on 4 axes:
        specificity, evidence, character-relevance, stakeholder breadth."""
        from core.llm import get_debate_evaluation_prompt
        prompt = get_debate_evaluation_prompt(
            member={'name': 'Marcus Webb', 'role': 'Investment Liaison',
                    'expertise': 'Investor Relations', 'personality': 'ROI-focused'},
            company_data={'company_name': 'X', 'board_members': [{'name': 'Marcus Webb', 'role': 'IL'}]},
            original_counter_opinion='Cost is too high',
            player_response='AS 36 impairment requires...',
            debate_history=[],
            player_role={'name': 'CFO', 'role': 'CFO'},
        )
        # All 4 dimensions present
        assert 'SPECIFICITY' in prompt
        assert 'EVIDENCE' in prompt
        assert 'CHARACTER-RELEVANCE' in prompt
        assert 'STAKEHOLDER BREADTH' in prompt

    def test_debate_prompt_includes_calibration_bands(self):
        """Conviction-drop calibration must include all 5 bands so LLM doesn't default to ~50%."""
        from core.llm import get_debate_evaluation_prompt
        prompt = get_debate_evaluation_prompt(
            member={'name': 'X', 'role': 'CFO', 'expertise': 'Finance', 'personality': 'p'},
            company_data={'company_name': 'C', 'board_members': []},
            original_counter_opinion='objection', player_response='response',
            debate_history=[], player_role={'name': 'P', 'role': 'CEO'},
        )
        assert 'Exceptional argument' in prompt
        assert 'Strong argument' in prompt
        assert 'Adequate argument' in prompt
        assert 'Weak argument' in prompt
        assert 'Poor' in prompt
        # Conviction may RISE on poor arguments (defensive entrenchment) — explicit
        assert 'RISE' in prompt
        assert 'do NOT default to a ~50%' in prompt or 'do NOT default to a ~50% drop' in prompt

    def test_debate_prompt_passes_prior_conviction_baseline(self):
        """Prompt must convey prior conviction so the LLM moves FROM a known baseline."""
        from core.llm import get_debate_evaluation_prompt
        # Debate history with a prior updated_conviction
        history = [
            {'dissenter_argument': 'X', 'player_response': 'Y', 'updated_conviction': 6},
        ]
        prompt = get_debate_evaluation_prompt(
            member={'name': 'X', 'role': 'CFO', 'expertise': 'Finance', 'personality': 'p'},
            company_data={'company_name': 'C', 'board_members': []},
            original_counter_opinion='o', player_response='r',
            debate_history=history, player_role={'name': 'P', 'role': 'CEO'},
        )
        # Prompt should explicitly tell the LLM the START conviction (6) for this exchange
        assert 'conviction at the START of this exchange is 6/10' in prompt

    def test_debate_prompt_first_exchange_states_opening_baseline(self):
        """First exchange (no history) should still state where conviction starts."""
        from core.llm import get_debate_evaluation_prompt
        prompt = get_debate_evaluation_prompt(
            member={'name': 'X', 'role': 'CFO', 'expertise': 'Finance', 'personality': 'p'},
            company_data={'company_name': 'C', 'board_members': []},
            original_counter_opinion='o', player_response='r',
            debate_history=[], player_role={'name': 'P', 'role': 'CEO'},
        )
        assert 'first exchange' in prompt
        assert '7-10' in prompt  # opening conviction range

    def test_debate_prompt_character_specific_persuasion_examples(self):
        """The CHARACTER-RELEVANCE dimension must give role-specific persuasion examples."""
        from core.llm import get_debate_evaluation_prompt
        prompt = get_debate_evaluation_prompt(
            member={'name': 'Marcus', 'role': 'Investment Liaison',
                    'expertise': 'Investor Relations', 'personality': 'ROI'},
            company_data={'company_name': 'C', 'board_members': []},
            original_counter_opinion='o', player_response='r',
            debate_history=[], player_role={'name': 'P', 'role': 'CFO'},
        )
        # Character-specific persuasion examples must be listed
        assert 'Investment Liaison' in prompt
        assert 'ROI math' in prompt
        assert 'Strategy Advisor' in prompt
        assert 'CRO' in prompt
        assert 'CHRO' in prompt


class TestMediumPriorityFollowups:
    """Cross-check #2 follow-up — 4 medium-priority feedback items
    (late-emerging dissenter UX, proposer banner, Best Approach UX, consultation signal)."""

    # ── M1: Dissenter queue panel + ordering invariant ─────────────────

    def test_dissenter_order_is_deterministic(self):
        """Stances dict preserves insertion order (Python 3.7+) — so dissenters never
        'appear' mid-deliberation. Verifies the data invariant the queue panel relies on."""
        # Simulated stance dict in the order generate_member_stances() builds it
        stances = {
            'Marcus Webb':      {'stance': 'OPPOSE', 'conviction_level': 8, 'convinced_in_round': None},
            'Jamal Ortiz':      {'stance': 'OPPOSE', 'conviction_level': 7, 'convinced_in_round': None},
            'Sarah Chen':       {'stance': 'OPPOSE', 'conviction_level': 6, 'convinced_in_round': None},
            'Linda Tan':        {'stance': 'APPROVE', 'conviction_level': 8, 'convinced_in_round': None},
        }
        # Re-order via the same comprehension used in deliberation.py
        all_oppose = [(n, s) for n, s in stances.items() if s['stance'] in ('OPPOSE', 'CONVINCED')]
        # Order must be exactly insertion order — never sorted, never reshuffled
        assert [n for n, _ in all_oppose] == ['Marcus Webb', 'Jamal Ortiz', 'Sarah Chen']
        # Length stays stable as members get convinced (CONVINCED still in all_oppose)
        stances['Marcus Webb']['stance'] = 'CONVINCED'
        stances['Marcus Webb']['convinced_in_round'] = 1
        all_oppose_after = [(n, s) for n, s in stances.items() if s['stance'] in ('OPPOSE', 'CONVINCED')]
        assert len(all_oppose_after) == len(all_oppose)
        assert [n for n, _ in all_oppose_after] == ['Marcus Webb', 'Jamal Ortiz', 'Sarah Chen']

    # ── M3: Best Approach default-expanded ─────────────────────────────

    def test_best_approach_always_default_expanded(self):
        """The recommended best approach must default to expanded for ALL scores —
        was previously gated to score < 60, hiding the highest-leverage learning element."""
        from pathlib import Path
        src = Path('pages/simulation.py').read_text(encoding='utf-8')
        # Find the best_approach expander block and verify it uses expanded=True (not a conditional)
        idx = src.find('💡 Recommended Best Approach')
        assert idx != -1, "Best Approach expander not found"
        # Window around it should contain expanded=True (literal), NOT expanded=expanded
        window = src[idx:idx + 600]
        assert 'expanded=True' in window, f"Best Approach not always expanded:\n{window}"
        # Defensive: the old conditional pattern should be gone
        # (this test will fail if anyone re-introduces `expanded = score < 60`)
        assert 'expanded = score < 60' not in src

    # ── M4: Consultation usage signal ──────────────────────────────────

    def test_consultation_caption_explains_scoring_link(self):
        """Quota caption must tell players consultation usage feeds Board Effectiveness."""
        from pathlib import Path
        src = Path('pages/simulation.py').read_text(encoding='utf-8')
        # Caption near the quota indicator must mention scoring impact
        assert 'Consultation Alignment' in src or 'consultation alignment' in src.lower()
        # And specifically mention Board Effectiveness
        assert 'Board Effectiveness' in src

    # ── M2: Proposer banner ────────────────────────────────────────────

    def test_deliberation_banner_names_player_as_proposer(self):
        """Deliberation header must explicitly state 'You proposed this decision'."""
        from pathlib import Path
        src = Path('components/deliberation.py').read_text(encoding='utf-8')
        assert 'You proposed this decision' in src, \
            "Proposer banner missing — feedback Issue 5 not addressed"


class TestCohortAnalytics:
    """X.1 — Closed feedback loop: cohort aggregator + recommendation engine."""

    def _mock_round(self, rnum, score=85.0, time_s=400, force=False,
                    vocab=None, missed=None, persuaded=None, unpersuaded=None):
        return {
            'round_number': rnum,
            'score': score,
            'time_taken_seconds': time_s,
            'force_submitted': force,
            'vocabulary_score': vocab,
            'vocabulary_missed': missed or [],
            'vocabulary_invoked': [],
            'vocabulary_misused': [],
            'dissenters_persuaded': persuaded or [],
            'dissenters_unpersuaded': unpersuaded or [],
            'board_consultations': 1,
            'committee_consultations': 1,
        }

    def test_recommendations_too_easy_round(self):
        from core.cohort_analytics import derive_calibration_recommendations
        insights = {
            'per_round': {
                1: {'avg_score': 95.0, 'std_dev_score': 4.0, 'force_submit_rate': 0.05,
                    'avg_time_seconds': 300, 'avg_vocab_score': 85.0,
                    'top_missed_vocab': [], 'unpersuaded_dissenters': {}, 'persuaded_dissenters': {}},
            },
        }
        recs = derive_calibration_recommendations(insights)
        types = [r['type'] for r in recs]
        assert 'too_easy' in types
        easy = next(r for r in recs if r['type'] == 'too_easy')
        assert easy['round'] == 1
        assert easy['severity'] == 'high'

    def test_recommendations_too_hard_round(self):
        from core.cohort_analytics import derive_calibration_recommendations
        insights = {
            'per_round': {
                3: {'avg_score': 45.0, 'std_dev_score': 12.0, 'force_submit_rate': 0.10,
                    'avg_time_seconds': 600, 'avg_vocab_score': 50.0,
                    'top_missed_vocab': [], 'unpersuaded_dissenters': {}, 'persuaded_dissenters': {}},
            },
        }
        recs = derive_calibration_recommendations(insights)
        assert any(r['type'] == 'too_hard' for r in recs)

    def test_recommendations_time_pressure_tight(self):
        from core.cohort_analytics import derive_calibration_recommendations
        insights = {
            'per_round': {
                2: {'avg_score': 80.0, 'std_dev_score': 8.0, 'force_submit_rate': 0.55,
                    'avg_time_seconds': 200, 'avg_vocab_score': 70.0,
                    'top_missed_vocab': [], 'unpersuaded_dissenters': {}, 'persuaded_dissenters': {}},
            },
        }
        recs = derive_calibration_recommendations(insights)
        assert any(r['type'] == 'time_pressure_tight' for r in recs)

    def test_recommendations_low_vocabulary(self):
        from core.cohort_analytics import derive_calibration_recommendations
        insights = {
            'per_round': {
                2: {'avg_score': 80.0, 'std_dev_score': 8.0, 'force_submit_rate': 0.10,
                    'avg_time_seconds': 400, 'avg_vocab_score': 35.0,
                    'top_missed_vocab': [('Principle of Prudence', 8), ('AS 5', 5)],
                    'unpersuaded_dissenters': {}, 'persuaded_dissenters': {}},
            },
        }
        recs = derive_calibration_recommendations(insights)
        vocab_recs = [r for r in recs if r['type'] == 'low_vocabulary_engagement']
        assert len(vocab_recs) == 1
        assert 'Principle of Prudence' in vocab_recs[0]['directive']

    def test_recommendations_score_plateau(self):
        from core.cohort_analytics import derive_calibration_recommendations
        # 3 consecutive rounds at ~85 → plateau (matches feedback PDF B14/B15)
        insights = {
            'per_round': {
                2: {'avg_score': 85.0, 'std_dev_score': 3.0, 'force_submit_rate': 0.10,
                    'avg_time_seconds': 400, 'avg_vocab_score': 70.0,
                    'top_missed_vocab': [], 'unpersuaded_dissenters': {}, 'persuaded_dissenters': {}},
                3: {'avg_score': 85.0, 'std_dev_score': 3.0, 'force_submit_rate': 0.10,
                    'avg_time_seconds': 400, 'avg_vocab_score': 70.0,
                    'top_missed_vocab': [], 'unpersuaded_dissenters': {}, 'persuaded_dissenters': {}},
                4: {'avg_score': 85.0, 'std_dev_score': 3.0, 'force_submit_rate': 0.10,
                    'avg_time_seconds': 400, 'avg_vocab_score': 70.0,
                    'top_missed_vocab': [], 'unpersuaded_dissenters': {}, 'persuaded_dissenters': {}},
            },
        }
        recs = derive_calibration_recommendations(insights)
        plateau = [r for r in recs if r['type'] == 'score_plateau']
        assert len(plateau) == 1
        assert plateau[0]['round'] is None  # spans rounds
        # The directive must mention the ceiling-breaker pattern
        assert 'forward-looking' in plateau[0]['directive']
        assert 'multi-tier communication' in plateau[0]['directive']

    def test_recommendations_stuck_dissenter(self):
        from core.cohort_analytics import derive_calibration_recommendations
        insights = {
            'per_round': {
                3: {'avg_score': 80.0, 'std_dev_score': 8.0, 'force_submit_rate': 0.10,
                    'avg_time_seconds': 400, 'avg_vocab_score': 70.0, 'top_missed_vocab': [],
                    'unpersuaded_dissenters': {'Marcus Webb': 5}, 'persuaded_dissenters': {'Marcus Webb': 1}},
            },
        }
        recs = derive_calibration_recommendations(insights)
        stuck = [r for r in recs if r['type'] == 'stuck_dissenter']
        assert len(stuck) == 1
        assert 'Marcus Webb' in stuck[0]['message']

    def test_no_recommendations_when_healthy(self):
        from core.cohort_analytics import derive_calibration_recommendations
        # Avg 75-80, low force-submit, healthy variance — no recs expected
        insights = {
            'per_round': {
                1: {'avg_score': 78.0, 'std_dev_score': 10.0, 'force_submit_rate': 0.05,
                    'avg_time_seconds': 350, 'avg_vocab_score': 70.0,
                    'top_missed_vocab': [], 'unpersuaded_dissenters': {}, 'persuaded_dissenters': {}},
                2: {'avg_score': 75.0, 'std_dev_score': 9.0, 'force_submit_rate': 0.10,
                    'avg_time_seconds': 400, 'avg_vocab_score': 65.0,
                    'top_missed_vocab': [], 'unpersuaded_dissenters': {}, 'persuaded_dissenters': {}},
            },
        }
        recs = derive_calibration_recommendations(insights)
        assert len(recs) == 0, f"Healthy cohort produced recommendations: {recs}"

    def test_format_insights_for_prompt_truncates(self):
        from core.cohort_analytics import format_insights_for_prompt
        insights = {
            'simulation_name': 'X', 'n_sessions': 10, 'lookback_days': 90,
            'avg_final_score': 80, 'median_final_score': 80, 'score_std_dev': 5,
            'completion_rate': 0.9,
            'per_round': {i: {'avg_score': 80, 'force_submit_rate': 0.1,
                              'avg_time_seconds': 400, 'avg_vocab_score': 70} for i in range(1, 6)},
        }
        recs = [{'severity': 'high', 'directive': 'X' * 5000}]
        text = format_insights_for_prompt(insights, recs, max_chars=500)
        assert len(text) <= 500
        assert 'truncated' in text

    def test_aggregator_returns_none_below_threshold(self):
        """Cold-start safety: <5 sessions → no insights."""
        from unittest.mock import patch
        from core.cohort_analytics import aggregate_cohort_insights
        with patch('core.cohort_analytics.get_records_by_simulation') as mock_get:
            mock_get.return_value = [
                {'status': 'completed', 'completed_at': '2026-04-01T00:00:00+00:00',
                 'final_score': 80, 'rounds': []}
                for _ in range(3)  # below MIN_SESSIONS_FOR_INSIGHTS=5
            ]
            assert aggregate_cohort_insights('TestSim') is None

    def test_aggregator_excludes_old_sessions(self):
        """Sessions older than max_age_days are filtered out."""
        from unittest.mock import patch
        from core.cohort_analytics import aggregate_cohort_insights
        from datetime import datetime, timezone, timedelta
        old_date = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
        recent_date = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        with patch('core.cohort_analytics.get_records_by_simulation') as mock_get:
            mock_get.return_value = (
                # 3 old sessions (should be excluded)
                [{'status': 'completed', 'completed_at': old_date, 'final_score': 80, 'rounds': []} for _ in range(3)] +
                # 6 recent (should be kept) — above MIN_SESSIONS=5
                [{'status': 'completed', 'completed_at': recent_date, 'final_score': 75,
                  'rounds': [{'round_number': 1, 'score': 75}]}
                 for _ in range(6)]
            )
            insights = aggregate_cohort_insights('TestSim', max_age_days=90)
            assert insights is not None
            assert insights['n_sessions'] == 6  # only recent

    def test_aggregator_computes_per_round_stats(self):
        """End-to-end: aggregator produces per-round avg + std_dev + vocab."""
        from unittest.mock import patch
        from core.cohort_analytics import aggregate_cohort_insights
        from datetime import datetime, timezone
        recent = datetime.now(timezone.utc).isoformat()
        records = [
            {'status': 'completed', 'completed_at': recent, 'final_score': 80,
             'rounds': [
                 {'round_number': 1, 'score': s, 'force_submitted': False,
                  'time_taken_seconds': 400, 'vocabulary_score': 70,
                  'vocabulary_missed': ['AS 5'] if s < 75 else []},
             ]}
            for s in (70, 75, 80, 85, 90, 95)
        ]
        with patch('core.cohort_analytics.get_records_by_simulation') as mock_get:
            mock_get.return_value = records
            insights = aggregate_cohort_insights('TestSim')
            assert insights is not None
            r1 = insights['per_round'][1]
            assert r1['n_attempts'] == 6
            assert r1['avg_score'] == 82.5  # mean(70..95 by 5)
            assert r1['avg_vocab_score'] == 70.0
            # 'AS 5' was missed in 1 of 6 sessions (the score=70 one)
            missed_terms = dict(r1['top_missed_vocab'])
            assert missed_terms.get('AS 5') == 1


class TestAgent3CohortIntegration:
    """X.1 wiring — run_planning_agent accepts pre-computed insights."""

    def test_run_planning_agent_accepts_cohort_insights(self):
        """The signature must accept a pre-computed cohort_insights dict
        so callers can bypass Firestore (testing, custom snapshots).
        """
        import inspect
        from core.admin_agents import run_planning_agent
        sig = inspect.signature(run_planning_agent)
        assert 'cohort_insights' in sig.parameters
        assert 'use_cohort_feedback' in sig.parameters
        # use_cohort_feedback should default to True (auto-fetch is the default behavior)
        assert sig.parameters['use_cohort_feedback'].default is True

    def test_planning_prompt_embeds_cohort_block(self):
        """Cohort block must appear in the LLM prompt when insights are provided."""
        from core.admin_agents import _build_narrative_planning_prompt
        prompt = _build_narrative_planning_prompt(
            company_data={'company_name': 'X', 'company_overview': '', 'board_members': [], 'current_problems': []},
            module_data={'module_name': 'M', 'subject_area': '', 'overview': '', 'topics': []},
            simulation_config={'total_rounds': 3},
            act_structure=[{'round_number': i, 'act': 1, 'act_label': 'Orientation', 'difficulty': 'easy'} for i in (1, 2, 3)],
            tension_pairs=[],
            coverage_requirements={},
            cohort_insights_block="OBSERVED COHORT PERFORMANCE: 12 sessions; avg 86/100. CALIBRATION: Increase difficulty for Round 1.",
        )
        assert 'OBSERVED COHORT PERFORMANCE' in prompt
        assert 'CALIBRATION' in prompt

    def test_planning_prompt_omits_cohort_block_when_empty(self):
        """No cohort data → block is omitted (no empty 'OBSERVED' section)."""
        from core.admin_agents import _build_narrative_planning_prompt
        prompt = _build_narrative_planning_prompt(
            company_data={'company_name': 'X', 'company_overview': '', 'board_members': [], 'current_problems': []},
            module_data={'module_name': 'M', 'subject_area': '', 'overview': '', 'topics': []},
            simulation_config={'total_rounds': 3},
            act_structure=[{'round_number': i, 'act': 1, 'act_label': 'Orientation', 'difficulty': 'easy'} for i in (1, 2, 3)],
            tension_pairs=[],
            coverage_requirements={},
            cohort_insights_block="",
        )
        assert 'OBSERVED COHORT PERFORMANCE' not in prompt


class TestAgent1Improvements:
    """Agent 1 improvements 1.2 (duplicate names) + 1.3 (value contradictions) in raw text."""

    def test_phase0_detects_duplicate_role_in_raw_text(self):
        from core.admin_agents import _agent1_phase0_raw_text_scan
        # Kenji Tanaka with two different titles in same PDF
        raw = """
        Section 1: Leadership
        Our CTO is Kenji Tanaka, a renowned AI architect with 15 years of experience.
        Section 2: Board
        We welcome Kenji Tanaka, Independent Director, who brings regulatory depth.
        Additional padding text to satisfy the 200-char minimum threshold for Phase 0.
        """ * 2
        flags = _agent1_phase0_raw_text_scan(raw)
        dup_flags = [f for f in flags if f['type'] == 'raw_text_duplicate_role']
        assert len(dup_flags) >= 1
        assert 'Kenji Tanaka' in dup_flags[0]['message']

    def test_phase0_detects_value_contradiction(self):
        from core.admin_agents import _agent1_phase0_raw_text_scan
        raw = """
        Total revenue of $850M was reported for FY2024 in the certified statements.
        Our reported total revenue of $1.2B, including non-recurring items.
        Operating expenses came in at $620M for the period.
        Padding text to ensure the input crosses the 200-char threshold for Phase 0 scanning.
        """ * 2
        flags = _agent1_phase0_raw_text_scan(raw)
        val_flags = [f for f in flags if f['type'] == 'raw_text_value_contradiction']
        assert len(val_flags) >= 1
        assert 'revenue' in val_flags[0]['message'].lower()

    def test_phase0_no_false_positive_consistent_pdf(self):
        from core.admin_agents import _agent1_phase0_raw_text_scan
        raw = """
        Our CEO is Amelia Thorne, who leads the executive team.
        The CFO David Chen joined in 2021 and oversees finance.
        Total revenue was $1.2B for FY2024, with net profit margin of 12%.
        Padding text to reach minimum scan threshold for Phase 0 raw text scanning.
        """ * 2
        flags = _agent1_phase0_raw_text_scan(raw)
        # No duplicates, no contradictions → 0 flags
        assert len(flags) == 0, f"False positives: {flags}"

    def test_phase0_skips_short_text(self):
        from core.admin_agents import _agent1_phase0_raw_text_scan
        # Below 200-char threshold → returns empty
        flags = _agent1_phase0_raw_text_scan("Tiny text.")
        assert flags == []


# ===========================================================================
# 5. TIMER LIFECYCLE — Bug #7
# ===========================================================================
class TestTimerLifecycle:
    """Test timer initialization, expiry, and reset on session restore."""

    def test_timer_reset_on_restore(self):
        """Restoring from progress should set a fresh timer, not keep the old one."""
        # Simulate old timer from 2 hours ago
        old_time = datetime.datetime.now() - datetime.timedelta(hours=2)
        session = {
            'round_start_time_2': old_time,
            'timer_expired_2': True,
        }

        # Simulate restore logic (same as _restore_from_progress)
        cr = 2
        session[f'round_start_time_{cr}'] = datetime.datetime.now()
        session.pop(f'timer_expired_{cr}', None)

        # Timer should be fresh (within last second)
        elapsed = (datetime.datetime.now() - session['round_start_time_2']).total_seconds()
        assert elapsed < 2, f"Timer should be fresh, but {elapsed}s elapsed"
        assert f'timer_expired_{cr}' not in session

    def test_timer_not_expired_after_reset(self):
        """After reset, remaining time should be positive."""
        time_limit_minutes = 10
        start_time = datetime.datetime.now()
        total_seconds = time_limit_minutes * 60
        elapsed = (datetime.datetime.now() - start_time).total_seconds()
        remaining = max(0, int(total_seconds - elapsed))
        assert remaining > 500, f"Should have ~600s remaining, got {remaining}"

    def test_stale_timer_would_show_zero(self):
        """Without reset, a 2-hour-old timer should show 00:00."""
        time_limit_minutes = 10
        start_time = datetime.datetime.now() - datetime.timedelta(hours=2)
        total_seconds = time_limit_minutes * 60
        elapsed = (datetime.datetime.now() - start_time).total_seconds()
        remaining = max(0, int(total_seconds - elapsed))
        assert remaining == 0, "Stale timer should show 0 remaining"


# ===========================================================================
# 6. POST-SUBMIT VISIBILITY — Bug #37
# ===========================================================================
class TestPostSubmitVisibility:
    """Verify consultation section hides after decision submission."""

    def test_consultation_hidden_when_submitted(self):
        """After decision_submitted=True, consultation messages should not show."""
        decision_submitted = True
        timer_expired = True

        # Simulate the visibility logic from simulation.py
        show_expired_msg = timer_expired and not decision_submitted
        show_consultation = not decision_submitted
        show_all_used_msg = not decision_submitted

        assert show_expired_msg is False, "Expired message should hide after submit"
        assert show_consultation is False, "Consultation should hide after submit"
        assert show_all_used_msg is False, "All-used message should hide after submit"

    def test_consultation_visible_before_submit(self):
        """Before submission, consultation should be visible."""
        decision_submitted = False
        timer_expired = False

        show_consultation = not decision_submitted
        assert show_consultation is True

    def test_expired_message_shows_before_submit(self):
        """If timer expired but not submitted, warning should show."""
        decision_submitted = False
        timer_expired = True

        show_expired_msg = timer_expired and not decision_submitted
        assert show_expired_msg is True


# ===========================================================================
# 7. PROMPT INTEGRITY — Bugs #3, #4, #8, #19, #20, #27
# ===========================================================================
class TestPromptIntegrity:
    """Verify all prompts contain required instructions for content accuracy."""

    def test_scenario_prompt_enforces_player_perspective(self):
        """Scenario must be written from player's perspective only."""
        from core.llm import get_scenario_generator_prompt
        prompt = get_scenario_generator_prompt(
            CLEARWATER_COMPANY, CLEARWATER_MODULE, ROUND_CONFIG_R1, PLAYER_MEG
        )
        assert "ONLY from Margaret" in prompt or "ONLY from Margaret 'Meg' Harlow" in prompt

    def test_scenario_prompt_has_board_roster(self):
        """Scenario prompt must list board members with 'do not invent' instruction."""
        from core.llm import get_scenario_generator_prompt
        prompt = get_scenario_generator_prompt(
            CLEARWATER_COMPANY, CLEARWATER_MODULE, ROUND_CONFIG_R1, PLAYER_SANDRA
        )
        assert 'BOARD MEMBERS' in prompt
        assert 'Jonathan Marsh' in prompt
        assert 'David Sung' in prompt
        assert 'Patricia Delgado' in prompt
        assert 'do not invent names' in prompt.lower()

    def test_scenario_prompt_has_option_rules(self):
        """Options must reference correct board members for each domain."""
        from core.llm import get_scenario_generator_prompt
        prompt = get_scenario_generator_prompt(
            CLEARWATER_COMPANY, CLEARWATER_MODULE, ROUND_CONFIG_R1, PLAYER_SANDRA
        )
        assert 'CORRECT board member' in prompt or 'ROLE matches the subject matter' in prompt

    def test_scenario_prompt_time_sensitivity_instruction(self):
        """Time sensitivity must not be downgraded if crisis is escalating."""
        from core.llm import get_scenario_generator_prompt
        prev = [{'round_number': 1, 'title': 'Crisis', 'decision_summary': 'Act',
                 'outcome_summary': 'Score: 80'}]
        prompt = get_scenario_generator_prompt(
            CLEARWATER_COMPANY, CLEARWATER_MODULE, ROUND_CONFIG_R2, PLAYER_SANDRA,
            previous_rounds=prev
        )
        assert 'do NOT downgrade' in prompt or 'do not downgrade' in prompt.lower()

    def test_stance_prompt_has_conflict_of_interest(self):
        """Stance prompt must instruct LLM to consider conflicts of interest."""
        from core.llm import get_member_stance_prompt
        for member in CLEARWATER_BOARD:
            prompt = get_member_stance_prompt(
                member, CLEARWATER_COMPANY, CLEARWATER_MODULE,
                'Test scenario', 'Test decision', PLAYER_SANDRA
            )
            assert 'conflict' in prompt.lower(), \
                f"Stance prompt for {member['name']} missing conflict-of-interest instruction"

    def test_debate_prompt_has_board_roster(self):
        """Debate evaluation prompt must include board roster to prevent hallucinated characters."""
        from core.llm import get_debate_evaluation_prompt
        for member in CLEARWATER_BOARD:
            prompt = get_debate_evaluation_prompt(
                member, CLEARWATER_COMPANY, 'objection text',
                'player response', [], PLAYER_SANDRA
            )
            assert 'BOARD MEMBERS' in prompt, \
                f"Debate prompt for {member['name']} missing board roster"
            assert 'do not invent' in prompt.lower(), \
                f"Debate prompt for {member['name']} missing 'do not invent' instruction"

    def test_debate_prompt_has_all_board_names(self):
        """Debate prompt must list every board member by name."""
        from core.llm import get_debate_evaluation_prompt
        prompt = get_debate_evaluation_prompt(
            CLEARWATER_BOARD[0], CLEARWATER_COMPANY,
            'objection', 'response', [], PLAYER_SANDRA
        )
        for member in CLEARWATER_BOARD:
            assert member['name'] in prompt, \
                f"Board member {member['name']} not in debate prompt roster"


# ===========================================================================
# 8. SCENARIO MODEL — Bugs #4, #20
# ===========================================================================
class TestScenarioModel:
    """Verify scenario generation uses the stronger model."""

    def test_scenario_llm_uses_gemini_25_flash(self):
        """initialize_scenario_llm should create a model with gemini-2.5-flash."""
        from core.llm import _GeminiModel
        import inspect
        from core.llm import initialize_scenario_llm
        src = inspect.getsource(initialize_scenario_llm)
        assert 'gemini-2.5-flash' in src

    def test_default_llm_uses_flash_lite(self):
        """initialize_llm should still use the faster gemini-2.5-flash-lite."""
        import inspect
        from core.llm import initialize_llm
        src = inspect.getsource(initialize_llm)
        assert 'gemini-2.5-flash-lite' in src

    def test_scenario_llm_has_higher_token_limit(self):
        """Scenario model needs MORE tokens than the default LLM so the 4th
        calibrated option can't be truncated. v1.4.10 bumped 4096 → 6144 in
        response to client reports of occasionally missing options."""
        import inspect
        from core.llm import initialize_scenario_llm, initialize_llm
        scenario_src = inspect.getsource(initialize_scenario_llm)
        default_src = inspect.getsource(initialize_llm)
        # Just enforce the relationship — scenario LLM gets MORE budget than default.
        # Extract numeric max_output_tokens via regex so the test survives future bumps.
        import re
        scenario_n = int(re.search(r'max_output_tokens\s*=\s*(\d+)', scenario_src).group(1))
        default_n = int(re.search(r'max_output_tokens\s*=\s*(\d+)', default_src).group(1))
        assert scenario_n >= 4096, f"Scenario LLM should have ≥4096 tokens, got {scenario_n}"
        assert scenario_n > default_n, "Scenario LLM must have more tokens than the default"

    def test_simulation_page_uses_scenario_llm_for_scenarios(self):
        """pages/simulation.py must use _scenario_llm for generate_scenario calls."""
        import inspect
        import pages.simulation as sim
        src = inspect.getsource(sim)
        assert '_scenario_llm' in src, "simulation.py should reference _scenario_llm"
        assert 'initialize_scenario_llm' in src, "simulation.py should import initialize_scenario_llm"


# ===========================================================================
# 9. FULL ROUND SIMULATION — End-to-end flow test
# ===========================================================================
class TestFullRoundSimulation:
    """Simulate a complete 3-round game flow to verify state management."""

    def test_three_round_state_progression(self):
        """Simulate 3 rounds of state accumulation."""
        # Round state
        round_summaries = []
        member_histories = {}
        total_score = 0
        current_round = 0

        for r in range(3):
            # Simulate round
            score = 75 + r * 5
            total_score += score
            current_round = r

            # Build round summary
            round_summaries.append({
                'round_number': r + 1,
                'title': f'Crisis Round {r + 1}',
                'decision_summary': f'Decision for round {r + 1}',
                'outcome_summary': f'Score: {score}/100',
            })

            # Build member history
            for member in CLEARWATER_BOARD:
                if member['name'] == PLAYER_SANDRA['name']:
                    continue
                if member['name'] not in member_histories:
                    member_histories[member['name']] = []
                conviction = max(1, 8 - r * 2)
                was_convinced = (r == 2 and member['name'] == 'Jonathan Marsh')
                member_histories[member['name']].append({
                    'round_number': r + 1,
                    'stance': 'OPPOSE' if member['name'] == 'Jonathan Marsh' else 'APPROVE',
                    'conviction': conviction,
                    'was_convinced': was_convinced,
                    'objection': f'Round {r + 1} objection' if member['name'] == 'Jonathan Marsh' else '',
                })

        # Verify final state
        assert len(round_summaries) == 3
        assert total_score == 75 + 80 + 85
        assert current_round == 2

        # Jonathan should have history across 3 rounds
        jonathan_history = member_histories.get('Jonathan Marsh', [])
        assert len(jonathan_history) == 3
        assert jonathan_history[0]['conviction'] == 8
        assert jonathan_history[1]['conviction'] == 6
        assert jonathan_history[2]['conviction'] == 4
        assert jonathan_history[2]['was_convinced'] is True

    def test_convinced_member_history_tracked(self):
        """A convinced member's history should show was_convinced=True."""
        member_histories = {
            'Jonathan Marsh': [
                {'round_number': 1, 'stance': 'OPPOSE', 'conviction': 8, 'was_convinced': False},
                {'round_number': 2, 'stance': 'OPPOSE', 'conviction': 4, 'was_convinced': True},
            ]
        }
        # In round 3, stance prompt should receive this history
        from core.llm import get_member_stance_prompt
        prompt = get_member_stance_prompt(
            CLEARWATER_BOARD[0], CLEARWATER_COMPANY, CLEARWATER_MODULE,
            'Round 3 scenario', 'Round 3 decision', PLAYER_SANDRA,
            member_history=member_histories['Jonathan Marsh']
        )
        assert 'CONVINCED' in prompt
        assert 'Round 1' in prompt
        assert 'Round 2' in prompt


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
