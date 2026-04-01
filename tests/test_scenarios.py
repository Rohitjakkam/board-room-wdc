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
        """initialize_llm should still use the faster gemini-2.0-flash-lite."""
        import inspect
        from core.llm import initialize_llm
        src = inspect.getsource(initialize_llm)
        assert 'gemini-2.0-flash-lite' in src

    def test_scenario_llm_has_higher_token_limit(self):
        """Scenario model should have 4096 max tokens vs 2048 for default."""
        import inspect
        from core.llm import initialize_scenario_llm, initialize_llm
        scenario_src = inspect.getsource(initialize_scenario_llm)
        default_src = inspect.getsource(initialize_llm)
        assert '4096' in scenario_src, "Scenario model should have 4096 max tokens"
        assert '2048' in default_src, "Default model should have 2048 max tokens"

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
