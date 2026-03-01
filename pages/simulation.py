"""
Board room simulation game engine page.
Contains simulation_page() and run_simulation_round().
"""

import logging
import streamlit as st
import google.generativeai as genai
from datetime import datetime, timedelta
from typing import Dict, List

from core.models import SimulationState
from core.llm import initialize_llm
from core.data_manager import load_simulation_data, get_available_simulations
from core.simulation_engine import (
    generate_scenario, get_board_member_response, get_committee_response,
    evaluate_decision, evaluate_consultation_alignment,
    apply_metric_impacts, parse_scenario_options,
)
from core.scoring import (
    calculate_board_effectiveness_score, generate_game_goals,
    calculate_goal_progress, get_time_pressure_minutes,
)
from components.dashboard import display_company_dashboard, display_current_problems, display_module_info
from components.board_members import display_board_members_for_selection, display_board_members
from components.deliberation import display_deliberation_phase
from components.summary import display_final_summary

logger = logging.getLogger(__name__)


def run_simulation_round(llm: genai.GenerativeModel, data: Dict,
                         state: SimulationState) -> None:
    """Run a single simulation round."""

    company_data = data['company_data']
    module_data = data['module_data']
    round_config = data['simulation_config']['rounds'][state.current_round]
    player_role = st.session_state.get('player_role')

    # Initialize separate consultation counters for this round
    board_consult_key = f"board_consultations_round_{state.current_round}"
    committee_consult_key = f"committee_consultations_round_{state.current_round}"
    revision_key = f"revisions_round_{state.current_round}"

    if board_consult_key not in st.session_state:
        st.session_state[board_consult_key] = 0
    if committee_consult_key not in st.session_state:
        st.session_state[committee_consult_key] = 0
    if revision_key not in st.session_state:
        st.session_state[revision_key] = 0

    # Initialize timer for this round
    timer_key = f"round_start_time_{state.current_round}"
    if timer_key not in st.session_state:
        st.session_state[timer_key] = datetime.now()

    time_pressure = round_config.get('time_pressure', 'normal')
    time_limit_minutes = get_time_pressure_minutes(time_pressure)

    eval_key = f"evaluation_{state.current_round}"
    decision_submitted = eval_key in st.session_state

    # Phase: Briefing
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        st.markdown(f"""
        <div class="round-indicator">
            Round {state.current_round + 1} of {state.total_rounds} |
            Difficulty: {round_config['difficulty'].title()} |
            Focus: {round_config.get('focus_area', 'General') or 'General'}
        </div>
        """, unsafe_allow_html=True)

    with col2:
        board_left = 1 - st.session_state[board_consult_key]
        committee_left = 1 - st.session_state[committee_consult_key]
        revision_left = 1 - st.session_state[revision_key]
        st.markdown(f"""
        <div class="consultation-counter">
            👥 Director: {board_left}/1 | 🏛️ Committee: {committee_left}/1 | ✏️ Revise: {revision_left}/1
        </div>
        """, unsafe_allow_html=True)

    with col3:
        if not decision_submitted:
            start_time = st.session_state[timer_key]
            elapsed = datetime.now() - start_time
            total_seconds = time_limit_minutes * 60
            remaining_seconds = max(0, int(total_seconds - elapsed.total_seconds()))

            timer_expired_key = f"timer_expired_{state.current_round}"
            if remaining_seconds <= 0:
                st.session_state[timer_expired_key] = True

            timer_id = f"timer_{state.current_round}"
            end_time = start_time + timedelta(seconds=total_seconds)
            end_timestamp_ms = int(end_time.timestamp() * 1000)

            if remaining_seconds <= 0:
                timer_class = "timer-expired"
            elif time_pressure == "urgent":
                timer_class = "timer-urgent"
            elif time_pressure == "normal":
                timer_class = "timer-normal"
            else:
                timer_class = "timer-relaxed"

            st.markdown(f"""
            <div id="{timer_id}" class="timer-container {timer_class}">
                <div class="timer-display" id="{timer_id}_display">⏱️ {remaining_seconds // 60:02d}:{remaining_seconds % 60:02d}</div>
                <div class="timer-label" id="{timer_id}_label">Time Pressure: {time_pressure.title()}</div>
            </div>
            <script>
                (function() {{
                    var endTime = {end_timestamp_ms};
                    var timerId = "{timer_id}";
                    var timePressure = "{time_pressure}";
                    if (window['timerInterval_' + timerId]) {{
                        clearInterval(window['timerInterval_' + timerId]);
                    }}
                    function updateTimer() {{
                        var now = Date.now();
                        var remainingMs = endTime - now;
                        var remainingSeconds = Math.max(0, Math.floor(remainingMs / 1000));
                        var displayEl = document.getElementById(timerId + "_display");
                        var labelEl = document.getElementById(timerId + "_label");
                        var container = document.getElementById(timerId);
                        if (!displayEl || !labelEl || !container) {{
                            clearInterval(window['timerInterval_' + timerId]);
                            return;
                        }}
                        if (remainingSeconds <= 0) {{
                            displayEl.innerHTML = "⏱️ 00:00";
                            labelEl.innerHTML = "⚠️ Time's Up!";
                            container.className = "timer-container timer-expired";
                            clearInterval(window['timerInterval_' + timerId]);
                            return;
                        }}
                        var minutes = Math.floor(remainingSeconds / 60);
                        var seconds = remainingSeconds % 60;
                        displayEl.innerHTML = "⏱️ " + String(minutes).padStart(2, '0') + ":" + String(seconds).padStart(2, '0');
                        if (remainingSeconds < 60) {{
                            container.className = "timer-container timer-urgent";
                        }} else if (remainingSeconds < 180 || timePressure === "urgent") {{
                            container.className = "timer-container timer-urgent";
                        }} else if (timePressure === "normal") {{
                            container.className = "timer-container timer-normal";
                        }} else {{
                            container.className = "timer-container timer-relaxed";
                        }}
                    }}
                    updateTimer();
                    window['timerInterval_' + timerId] = setInterval(updateTimer, 1000);
                }})();
            </script>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div class="timer-container timer-relaxed">
                <div class="timer-display">✅ Submitted</div>
                <div class="timer-label">Decision Recorded</div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown(f"**Playing as:** {player_role['name']} - {player_role['role']}")

    timer_expired_key = f"timer_expired_{state.current_round}"
    timer_expired = st.session_state.get(timer_expired_key, False)

    if timer_expired and not decision_submitted:
        st.warning("⚠️ **Time has expired!** You can still submit your decision, but this may affect your score.")

    # Generate or retrieve scenario
    scenario_key = f"scenario_round_{state.current_round}"
    if scenario_key not in st.session_state:
        with st.spinner("Generating scenario..."):
            st.session_state[scenario_key] = generate_scenario(
                llm, company_data, module_data, round_config, player_role
            )

    scenario = st.session_state[scenario_key]

    st.markdown("### 📋 Scenario")
    st.markdown(f"""
    <div class="scenario-box">
        {scenario}
    </div>
    """, unsafe_allow_html=True)

    options = parse_scenario_options(scenario)

    # Consultation Section
    st.markdown("### 💬 Consultation")

    board_consultation_used = st.session_state[board_consult_key] >= 1
    committee_consultation_used = st.session_state[committee_consult_key] >= 1

    if not board_consultation_used or not committee_consultation_used:
        consult_tab1, consult_tab2 = st.tabs(["👥 Consult Board Members", "🏛️ Consult Committee"])

        with consult_tab1:
            if board_consultation_used:
                st.warning("⚠️ You have already used your director consultation for this round.")
            else:
                available_members = [m for m in company_data['board_members'] if m['name'] != player_role['name']]
                member_names = [m['name'] for m in available_members]

                selected_members = st.multiselect(
                    "Select board member(s) to consult:",
                    member_names,
                    key=f"member_select_{state.current_round}",
                    help="You can select multiple members for a group discussion (1 consultation per round)"
                )

                user_question = st.text_input(
                    "Your question or topic for discussion:",
                    key=f"member_question_{state.current_round}",
                    placeholder="e.g., What are your thoughts on the compliance implications?"
                )

                if st.button("Ask Board Member(s)", key=f"ask_members_btn_{state.current_round}",
                            disabled=len(selected_members) == 0 or not user_question):
                    if selected_members and user_question:
                        selected_member_data = [m for m in available_members if m['name'] in selected_members]

                        with st.spinner(f"{'Board members are' if len(selected_members) > 1 else selected_members[0] + ' is'} responding..."):
                            response = get_board_member_response(
                                llm, selected_member_data, company_data, module_data,
                                scenario, user_question,
                                st.session_state.get('conversation_history', []),
                                player_role
                            )

                            st.session_state[board_consult_key] += 1

                            if 'conversation_history' not in st.session_state:
                                st.session_state.conversation_history = []

                            member_label = ", ".join(selected_members) if len(selected_members) > 1 else selected_members[0]

                            st.session_state.conversation_history.append({
                                'role': 'user', 'content': user_question, 'member': member_label
                            })
                            st.session_state.conversation_history.append({
                                'role': 'assistant', 'content': response, 'member': member_label
                            })

                        st.rerun()

        with consult_tab2:
            if committee_consultation_used:
                st.warning("⚠️ You have already used your committee consultation for this round.")
            else:
                committees = company_data.get('committees', [])

                if committees:
                    committee_names = [c['name'] for c in committees]
                    selected_committee = st.selectbox(
                        "Select committee to consult:",
                        committee_names,
                        key=f"committee_select_{state.current_round}"
                    )

                    committee_question = st.text_input(
                        "Your question for the committee:",
                        key=f"committee_question_{state.current_round}",
                        placeholder="e.g., What is the committee's recommendation on this matter?"
                    )

                    if st.button("Consult Committee", key=f"ask_committee_btn_{state.current_round}",
                                disabled=not committee_question):
                        if committee_question:
                            selected_committee_data = next(c for c in committees if c['name'] == selected_committee)

                            with st.spinner(f"{selected_committee} is deliberating..."):
                                response = get_committee_response(
                                    llm, selected_committee_data, company_data, module_data,
                                    scenario, committee_question,
                                    st.session_state.get('conversation_history', []),
                                    player_role,
                                    company_data['board_members']
                                )

                                st.session_state[committee_consult_key] += 1

                                if 'conversation_history' not in st.session_state:
                                    st.session_state.conversation_history = []

                                st.session_state.conversation_history.append({
                                    'role': 'user', 'content': committee_question, 'member': selected_committee
                                })
                                st.session_state.conversation_history.append({
                                    'role': 'assistant', 'content': response, 'member': selected_committee
                                })

                            st.rerun()
                else:
                    st.info("No committees are available for consultation.")
    else:
        st.warning("⚠️ You have used all consultations for this round. Please make your decision.")

    # Display conversation history
    if 'conversation_history' in st.session_state and st.session_state.conversation_history:
        with st.expander("📝 Discussion History", expanded=True):
            for entry in st.session_state.conversation_history:
                if entry['role'] == 'user':
                    st.markdown(f"**You asked {entry.get('member', 'Board')}:** {entry['content']}")
                else:
                    st.markdown(f"**{entry.get('member', 'Board Member')}:** {entry['content']}")
                st.markdown("---")

    # Decision Phase
    st.markdown("### ✅ Your Decision")

    decision_key = f"decision_input_{state.current_round}"
    if decision_key not in st.session_state:
        st.session_state[decision_key] = ""

    if options:
        st.markdown("**Quick Select an Option:**")
        option_cols = st.columns(2)
        for idx, opt in enumerate(options):
            with option_cols[idx % 2]:
                if st.button(f"Option {opt['letter']}: {opt['text']}",
                           key=f"option_{opt['letter']}_{state.current_round}",
                           use_container_width=True):
                    st.session_state[f"selected_option_{state.current_round}"] = opt
                    st.session_state[decision_key] = f"Option {opt['letter']}: {opt['text']}"
                    st.rerun()

        st.markdown("---")
        st.markdown("**Or provide your detailed reasoning:**")

    decision = st.text_area(
        "Enter your decision and reasoning:",
        key=decision_key,
        placeholder="Describe your decision, the rationale behind it, and how you would implement it...",
        height=200
    )

    # Check deliberation state
    pending_decision_key = f"pending_decision_{state.current_round}"
    delib_phase_key = f"deliberation_phase_{state.current_round}"

    logger.debug(f"Round {state.current_round}: delib_phase_key={delib_phase_key}, exists={delib_phase_key in st.session_state}")

    pending_exists = pending_decision_key in st.session_state
    delib_not_exists = delib_phase_key not in st.session_state
    delib_not_resolved = st.session_state.get(delib_phase_key) != 'resolved'
    should_enter_delib = pending_exists and (delib_not_exists or delib_not_resolved)

    if should_enter_delib:
        logger.debug(f"Round {state.current_round}: Entering deliberation phase")

        deliberation_complete = display_deliberation_phase(
            llm, data, state, st.session_state[pending_decision_key]
        )

        if not deliberation_complete:
            return

    # Check if deliberation is resolved but evaluation hasn't been done yet
    deliberation_resolved = st.session_state.get(delib_phase_key) == 'resolved'
    needs_evaluation = pending_decision_key in st.session_state and deliberation_resolved and eval_key not in st.session_state

    if needs_evaluation:
        logger.debug("Running evaluation after deliberation")
        with st.spinner("Evaluating your decision and calculating impacts..."):
            stances = st.session_state.get(f"member_stances_{state.current_round}", {})
            debate_history = st.session_state.get(f"debate_history_{state.current_round}", [])
            force_submitted = st.session_state.get(f"force_submitted_{state.current_round}", False)

            consultations = st.session_state.get('conversation_history', [])
            alignment_result = evaluate_consultation_alignment(
                llm, consultations, st.session_state[pending_decision_key], stances
            )

            effectiveness = calculate_board_effectiveness_score(
                state.current_round, stances, debate_history,
                alignment_result.get('alignment_score', 50), force_submitted
            )

            if "board_effectiveness_history" not in st.session_state:
                st.session_state.board_effectiveness_history = []
            st.session_state.board_effectiveness_history.append(effectiveness)
            st.session_state[f"board_effectiveness_{state.current_round}"] = effectiveness

            evaluation = evaluate_decision(
                llm, company_data, module_data,
                scenario, st.session_state[pending_decision_key], round_config, player_role
            )

            evaluation['board_effectiveness'] = effectiveness
            st.session_state[eval_key] = evaluation

            if 'metric_impacts' in evaluation:
                impacts = evaluation['metric_impacts']
                current_metrics = st.session_state.get('current_metrics', company_data['metrics'].copy())
                impact_values = impacts.get('impacts', {})
                if force_submitted:
                    impact_values = {k: v * 0.85 if v > 0 else v for k, v in impact_values.items()}
                updated_metrics = apply_metric_impacts(current_metrics, impact_values)
                st.session_state.current_metrics = updated_metrics
                st.session_state.metric_impact_reasons = impacts.get('reasons', {})
                st.session_state[f"impact_summary_{state.current_round}"] = impacts.get('summary', '')

            st.session_state.round_complete = True
        st.rerun()

    # Only show submit button if evaluation not yet done
    if eval_key not in st.session_state:
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button("Submit Decision", key=f"submit_decision_{state.current_round}", type="primary"):
                if decision:
                    st.session_state[pending_decision_key] = decision
                    st.session_state[delib_phase_key] = 'inactive'
                    st.rerun()
                else:
                    st.warning("Please enter your decision before submitting.")

    # Display evaluation if available
    if eval_key in st.session_state:
        evaluation = st.session_state[eval_key]

        st.markdown("### 📊 Evaluation & Feedback")

        score = evaluation['score']
        score_color = "#28a745" if score >= 70 else "#ffc107" if score >= 50 else "#dc3545"

        st.markdown(f"""
        <div style="text-align: center; padding: 1rem; background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%); border-radius: 10px; margin-bottom: 1rem;">
            <h2 style="color: {score_color}; margin: 0;">Score: {score}/100</h2>
        </div>
        """, unsafe_allow_html=True)

        if evaluation.get('score_reasoning'):
            with st.expander("📋 Score Breakdown & Reasoning", expanded=True):
                st.markdown(evaluation['score_reasoning'])

        col1, col2 = st.columns(2)
        with col1:
            if evaluation.get('strengths'):
                st.markdown("#### ✅ Strengths")
                st.success(evaluation['strengths'])
        with col2:
            if evaluation.get('improvements'):
                st.markdown("#### 🔧 Areas for Improvement")
                st.warning(evaluation['improvements'])

        if evaluation.get('learning_points'):
            st.markdown("#### 📚 Key Learning Points")
            st.info(evaluation['learning_points'])

        if evaluation.get('best_approach'):
            expanded = score < 60
            with st.expander("💡 Recommended Best Approach" + (" - PLEASE REVIEW" if score < 60 else ""), expanded=expanded):
                st.markdown(evaluation['best_approach'])

        if score < 60 and evaluation.get('critical_feedback'):
            st.markdown(f"""
            <div style="background: linear-gradient(135deg, #f8d7da 0%, #f5c6cb 100%); padding: 1rem; border-radius: 10px; margin-top: 1rem; border-left: 4px solid #dc3545;">
                <strong>⚠️ Critical Issues with Your Decision:</strong><br>
                {evaluation['critical_feedback']}
            </div>
            """, unsafe_allow_html=True)

        if score >= 70:
            if evaluation.get('encouragement'):
                st.markdown(f"""
                <div style="background: linear-gradient(135deg, #d4edda 0%, #c3e6cb 100%); padding: 1rem; border-radius: 10px; margin-top: 1rem; border-left: 4px solid #28a745;">
                    <strong>✅ {evaluation['encouragement']}</strong>
                </div>
                """, unsafe_allow_html=True)
        elif score >= 50:
            st.markdown(f"""
            <div style="background: linear-gradient(135deg, #fff3cd 0%, #ffeeba 100%); padding: 1rem; border-radius: 10px; margin-top: 1rem; border-left: 4px solid #ffc107;">
                <strong>📝 Room for Improvement:</strong> Review the best approach above and consider how you could apply these principles in similar scenarios.
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div style="background: linear-gradient(135deg, #f8d7da 0%, #f5c6cb 100%); padding: 1rem; border-radius: 10px; margin-top: 1rem; border-left: 4px solid #dc3545;">
                <strong>📖 Action Required:</strong> This decision did not meet governance standards. Please carefully review the "Recommended Best Approach" section to understand what should have been done differently.
            </div>
            """, unsafe_allow_html=True)

        # Display Metric Impact
        impact_summary_key = f"impact_summary_{state.current_round}"
        if impact_summary_key in st.session_state and st.session_state[impact_summary_key]:
            st.markdown("### 📈 Business Impact")
            st.info(st.session_state[impact_summary_key])

        if 'metric_impacts' in evaluation and evaluation['metric_impacts'].get('impacts'):
            impacts = evaluation['metric_impacts']['impacts']
            reasons = evaluation['metric_impacts'].get('reasons', {})
            changed_metrics = {k: v for k, v in impacts.items() if v != 0}

            if changed_metrics:
                st.markdown("### 📊 Metric Changes from Your Decision")
                positive_impacts = {k: v for k, v in changed_metrics.items() if v > 0}
                negative_impacts = {k: v for k, v in changed_metrics.items() if v < 0}

                col1, col2 = st.columns(2)
                with col1:
                    if positive_impacts:
                        st.markdown("**✅ Positive Impacts:**")
                        for key, change in positive_impacts.items():
                            metric_name = key.replace('_', ' ').title()
                            reason = reasons.get(key, '')
                            st.success(f"**{metric_name}**: +{change}")
                            if reason:
                                st.caption(f"↳ {reason}")
                with col2:
                    if negative_impacts:
                        st.markdown("**⚠️ Negative Impacts:**")
                        for key, change in negative_impacts.items():
                            metric_name = key.replace('_', ' ').title()
                            reason = reasons.get(key, '')
                            st.error(f"**{metric_name}**: {change}")
                            if reason:
                                st.caption(f"↳ {reason}")

        # Next round button
        if st.button("Proceed to Next Round", key=f"next_round_{state.current_round}"):
            st.session_state.current_round += 1
            st.session_state.conversation_history = []
            st.session_state.round_complete = False
            st.session_state.total_score = st.session_state.get('total_score', 0) + score
            st.session_state.metric_impact_reasons = {}
            st.rerun()


def simulation_page():
    """Simulation page — runs the board room simulation for the selected JSON."""

    sim_index = st.session_state.get('selected_sim_index', None)
    simulations = get_available_simulations()

    if sim_index is None or sim_index >= len(simulations):
        st.warning("No simulation selected. Please go back to the Home page.")
        return

    sim = simulations[sim_index]
    st.session_state.selected_file = sim['filepath']

    st.markdown('<h1 class="main-header">🏢 Board Room Simulation</h1>', unsafe_allow_html=True)
    st.markdown('<p style="text-align: center; color: #666;">Corporate Governance Training & Decision Making</p>', unsafe_allow_html=True)

    if "GEMINI_API_KEY" in st.secrets:
        st.session_state.api_key = st.secrets["GEMINI_API_KEY"]

    # Sidebar - Player Information
    with st.sidebar:
        st.header("🎮 Game Info")

        if st.session_state.get('player_role'):
            role = st.session_state.player_role
            st.markdown(f"""
            <div style="background: linear-gradient(135deg, #d4edda 0%, #c3e6cb 100%); padding: 1rem; border-radius: 10px; border-left: 4px solid #28a745;">
                <strong>👤 Your Role</strong><br>
                <span style="font-size: 1.1rem; font-weight: 600;">{role['name']}</span><br>
                <span style="color: #666;">{role['role']}</span>
            </div>
            """, unsafe_allow_html=True)

        with st.expander("⚙️ Options", expanded=False):
            if st.button("🔄 Restart Simulation", use_container_width=True):
                preserve_keys = {'api_key', 'selected_file', 'selected_sim_index', '_sim_pages'}
                for key in list(st.session_state.keys()):
                    if key not in preserve_keys:
                        del st.session_state[key]
                st.rerun()

    # Sidebar metrics display function
    def display_sidebar_metrics(company_data: Dict, impact_reasons: Dict = None):
        """Display company metrics in sidebar during simulation."""
        with st.sidebar:
            st.markdown("---")

            with st.expander("📋 Company & Situation Brief", expanded=False):
                st.markdown(f"**{company_data.get('company_name', 'Company')}**")
                st.caption(f"Industry: {company_data.get('industry', 'N/A')} | Founded: {company_data.get('founded', 'N/A')}")
                st.markdown(company_data.get('company_overview', ''))
                st.markdown("---")
                st.markdown("**⚠️ Key Challenges:**")
                for problem in company_data.get('current_problems', [])[:5]:
                    st.markdown(f"• {problem}")
                st.markdown("---")
                st.markdown("**📌 Initial Situation:**")
                st.markdown(company_data.get('initial_scenario', ''))

            if 'game_goals' in st.session_state:
                st.markdown("---")
                st.header("🎯 Goal Progress")

                current_metrics = st.session_state.get('current_metrics', company_data['metrics'])
                goal_progress = calculate_goal_progress(st.session_state.game_goals, current_metrics)

                achieved_count = sum(1 for g in goal_progress if g.get('achieved', False))
                total_goals = len(goal_progress)
                st.markdown(f"**{achieved_count}/{total_goals}** goals achieved")

                for goal in goal_progress[:4]:
                    progress = goal.get('progress_pct', 0)
                    achieved = goal.get('achieved', False)

                    if achieved:
                        color, status_icon = "#28a745", "✅"
                    elif progress >= 50:
                        color, status_icon = "#ffc107", "🔄"
                    else:
                        color, status_icon = "#dc3545", "⏳"

                    current_val = goal.get('current_value', goal['current'])
                    target_val = goal['target']
                    unit = goal['unit']

                    st.markdown(f"""
                    <div style="margin-bottom: 0.8rem;">
                        <div style="display: flex; justify-content: space-between; font-size: 0.85rem;">
                            <span>{status_icon} {goal['name']}</span>
                            <span>{current_val}{unit} / {target_val}{unit}</span>
                        </div>
                        <div style="background: #e9ecef; border-radius: 4px; height: 8px; margin-top: 4px;">
                            <div style="background: {color}; width: {min(progress, 100)}%; height: 100%; border-radius: 4px;"></div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

            st.markdown("---")

            metrics = st.session_state.get('current_metrics', company_data['metrics'])

            st.header("🔴 High Priority Metrics")
            high_priority_metrics = {k: v for k, v in metrics.items() if v.get('priority') == 'High'}

            if high_priority_metrics:
                for key, metric in high_priority_metrics.items():
                    change = metric.get('change', 0)
                    delta_str = None
                    if change != 0:
                        delta_str = f"{change:+.1f}" if isinstance(change, float) else f"{change:+d}"
                    st.metric(metric['description'], f"{metric['value']} {metric['unit']}",
                             delta=delta_str, delta_color="normal" if change >= 0 else "inverse")
                    if impact_reasons and key in impact_reasons:
                        st.caption(f"📝 {impact_reasons[key]}")
            else:
                st.info("No high priority metrics flagged")

            st.markdown("---")
            st.header("📊 All Metrics")

            if impact_reasons is None:
                impact_reasons = st.session_state.get('metric_impact_reasons', {})

            inverse_metrics = ['customer_churn_rate_annual', 'annual_attrition_rate',
                              'open_high_severity_risks', 'monthly_burn_rate',
                              'data_processing_latency', 'average_incident_resolution_time',
                              'data_privacy_incident_count', 'customer_acquisition_cost']

            def show_metric(key):
                if key in metrics:
                    metric = metrics[key]
                    value = metric['value']
                    unit = metric.get('unit', '')
                    change = metric.get('change', 0)
                    display_val = f"{value} {unit}"
                    delta_str = None
                    if change != 0:
                        delta_str = f"{change:+.2f}" if isinstance(change, float) else f"{change:+d}"
                    delta_color = "inverse" if key in inverse_metrics else "normal"
                    st.metric(metric['description'], display_val, delta=delta_str, delta_color=delta_color)
                    if key in impact_reasons and impact_reasons[key]:
                        st.caption(f"↳ {impact_reasons[key]}")

            metric_categories = {
                '💰 Financial': ['total_revenue_annual', 'annual_recurring_revenue', 'ebitda',
                                'net_profit_margin', 'revenue_growth_yoy', 'monthly_burn_rate'],
                '👥 Customer': ['net_promoter_score', 'customer_churn_rate_annual',
                               'customer_lifetime_value', 'customer_acquisition_cost',
                               'average_contract_value', 'expansion_revenue_rate', 'support_ticket_csat'],
                '⚙️ Operations': ['platform_uptime', 'deployment_frequency',
                                 'average_incident_resolution_time', 'automation_coverage',
                                 'infrastructure_cost_efficiency', 'data_processing_latency',
                                 'project_delivery_on_time_rate'],
                '👔 Human Resources': ['employee_count', 'employee_engagement_score',
                                      'annual_attrition_rate', 'avg_training_hours_per_employee',
                                      'internal_promotion_rate', 'diversity_ratio_women_percentage'],
                '🛡️ Risk & Compliance': ['regulatory_compliance_score', 'open_high_severity_risks',
                                         'data_privacy_incident_count', 'carbon_footprint_yoy_change',
                                         'r_and_d_spend_percentage_of_revenue']
            }

            for category, metric_keys in metric_categories.items():
                present_keys = [k for k in metric_keys if k in metrics]
                if present_keys:
                    with st.expander(category, expanded=(category.startswith('💰'))):
                        for key in present_keys:
                            show_metric(key)

            all_categorized = set()
            for keys in metric_categories.values():
                all_categorized.update(keys)
            uncategorized = [k for k in metrics.keys() if k not in all_categorized]
            if uncategorized:
                with st.expander("📋 Other Metrics", expanded=False):
                    for key in uncategorized:
                        show_metric(key)

    # Check prerequisites
    if not st.session_state.get('api_key'):
        st.error("⚠️ API Key not configured. Please add GEMINI_API_KEY to your Streamlit secrets.")
        return

    if not st.session_state.get('selected_file'):
        st.warning("⚠️ Please select a simulation file.")
        return

    data = load_simulation_data(st.session_state.selected_file)
    if not data:
        st.error("Failed to load simulation data.")
        return

    try:
        llm = initialize_llm(st.session_state.api_key)
    except Exception as e:
        st.error(f"Failed to initialize AI model: {e}")
        return

    if 'current_round' not in st.session_state:
        st.session_state.current_round = 0
    if 'simulation_started' not in st.session_state:
        st.session_state.simulation_started = False

    company_data = data['company_data']
    module_data = data['module_data']
    simulation_config = data['simulation_config']

    # Main content area
    if not st.session_state.get('player_role'):
        # Initial dashboard
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #1E3A5F 0%, #2d5a8a 100%); padding: 1.5rem; border-radius: 12px; margin-bottom: 1.5rem; color: white;">
            <h2 style="margin: 0; color: white;">Welcome to Boardroom Simulation, on "{module_data['module_name']}"</h2>
            <p style="margin: 0.5rem 0 0 0; opacity: 0.9; font-style: italic;">Engineered by Directors' Institute.</p>
        </div>
        """, unsafe_allow_html=True)

        game_goals = generate_game_goals(company_data['metrics'], simulation_config['total_rounds'])
        st.session_state.game_goals = game_goals

        # Company brief
        st.markdown("### 🏢 Company Brief")
        st.markdown(f"""
        <div style="background: #f8f9fa; padding: 1rem; border-radius: 10px; border-left: 4px solid #1E3A5F;">
            <strong>{company_data['company_name']}</strong><br>
            <span style="color: #666;">Industry: {company_data.get('industry', 'Technology')} | Founded: {company_data.get('founded', 'N/A')}</span>
            <p style="margin-top: 0.8rem;">{company_data.get('company_overview', '')}</p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("---")

        # Initial Scenario
        st.markdown("### 📋 Initial Scenario")
        st.markdown(f"""
        <div style="background: #fff3cd; padding: 1rem; border-radius: 10px; border-left: 4px solid #ffc107;">
            {company_data.get('initial_scenario', 'Scenario not available')}
        </div>
        """, unsafe_allow_html=True)

        st.markdown("---")

        # Board of Directors
        st.markdown("### 👥 Board of Directors")
        board_cols = st.columns(3)
        for idx, member in enumerate(company_data['board_members']):
            with board_cols[idx % 3]:
                st.markdown(f"""
                <div style="background: #f8f9fa; padding: 0.8rem; border-radius: 8px; margin: 0.3rem 0; border-left: 3px solid #1E3A5F;">
                    <strong>{member['name']}</strong><br>
                    <span style="color: #666; font-size: 0.85rem;">{member['role']}</span><br>
                    <span style="color: #888; font-size: 0.8rem;">Expertise: {member.get('expertise', 'N/A')}</span>
                </div>
                """, unsafe_allow_html=True)

        st.markdown("---")

        # Challenges
        st.markdown("### ⚠️ Current Challenges")
        challenges_html = ""
        for problem in company_data.get('current_problems', []):
            challenges_html += f'<div style="background: #f8d7da; padding: 0.6rem; border-radius: 6px; margin: 0.3rem 0; border-left: 3px solid #dc3545; font-size: 0.9rem;">• {problem}</div>'
        st.markdown(challenges_html, unsafe_allow_html=True)

        st.markdown("---")

        # Key Metrics
        st.markdown("### 📊 Key Metrics")
        metrics = company_data['metrics']
        key_metrics = {k: v for k, v in metrics.items() if v.get('priority') in ['High', 'high', 'Medium', 'medium']}
        if not key_metrics:
            key_metrics = metrics
        key_metric_items = list(key_metrics.items())
        num_cols = min(len(key_metric_items), 4)
        if num_cols > 0:
            metric_cols = st.columns(num_cols)
            for idx, (key, metric) in enumerate(key_metric_items):
                with metric_cols[idx % num_cols]:
                    st.metric(metric['description'], f"{metric['value']} {metric['unit']}")

        st.markdown("---")

        # Mission Objectives
        st.markdown("### 🎯 Mission Objectives")
        st.markdown(f"*Complete {simulation_config['total_rounds']} rounds of board decisions to achieve these targets:*")
        goal_cols = st.columns(3)
        for idx, goal in enumerate(game_goals[:6]):
            with goal_cols[idx % 3]:
                lower_better = goal.get('lower_is_better', False)
                arrow = "↓" if lower_better else "↑"
                current_display = f"{goal['current']}{goal['unit']}"
                target_display = f"{goal['target']}{goal['unit']}"
                priority_color = "#dc3545" if goal['priority'] == 'high' else "#ffc107"
                st.markdown(f"""
                <div style="background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%); padding: 1rem; border-radius: 10px; border-top: 3px solid {priority_color}; margin-bottom: 0.5rem; text-align: center;">
                    <div style="font-size: 1.5rem;">{goal['icon']}</div>
                    <div style="font-weight: 600; color: #1E3A5F;">{goal['name']}</div>
                    <div style="font-size: 0.85rem; color: #666; margin: 0.3rem 0;">{goal['description']}</div>
                    <div style="margin-top: 0.5rem;">
                        <span style="color: #666;">Current: {current_display}</span>
                        <span style="font-size: 1.2rem; margin: 0 0.5rem;">{arrow}</span>
                        <span style="color: {priority_color}; font-weight: 600;">Target: {target_display}</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)

        st.markdown("---")

        # Learning Objectives
        st.markdown("### 📚 Learning Objectives")
        st.markdown(f"*{module_data.get('overview', '')}*")
        obj_cols = st.columns(3)
        objectives = module_data.get('learning_objectives', [])
        for idx, obj in enumerate(objectives[:6]):
            with obj_cols[idx % 3]:
                st.markdown(f"""
                <div style="background: #d4edda; padding: 0.8rem; border-radius: 8px; margin: 0.3rem 0; border-left: 3px solid #28a745; font-size: 0.85rem;">
                    ✓ {obj}
                </div>
                """, unsafe_allow_html=True)

        st.markdown("---")

        # Choose Your Board Role
        st.markdown("### 👤 Choose Your Board Role")
        st.markdown("Select which board member you want to play as during this simulation:")
        selected_role = display_board_members_for_selection(company_data['board_members'])
        if selected_role:
            st.session_state.player_role = selected_role
            st.rerun()

    elif not st.session_state.simulation_started:
        player_role = st.session_state.player_role
        st.success(f"✅ You are playing as **{player_role['name']}** - {player_role['role']}")

        tab1, tab2, tab3 = st.tabs(["🏢 Company Overview", "👥 Board Members", "📚 Module Info"])

        with tab1:
            display_company_dashboard(company_data)
            st.markdown("---")
            display_current_problems(company_data['current_problems'])
            st.markdown("### 📋 Initial Scenario")
            st.markdown(f'<div class="scenario-box">{company_data["initial_scenario"]}</div>', unsafe_allow_html=True)

        with tab2:
            display_board_members(company_data['board_members'], player_role)
            if company_data.get('committees'):
                st.markdown("### 🏛️ Board Committees")
                for committee in company_data['committees']:
                    with st.expander(committee['name']):
                        st.markdown(f"**Type:** {committee['type']}")
                        st.markdown(f"**Purpose:** {committee['purpose']}")
                        st.markdown(f"**Chairperson:** {committee['chairperson']}")
                        st.markdown(f"**Members:** {', '.join(committee['members'])}")

        with tab3:
            display_module_info(module_data)
            with st.expander("📖 Key Terms & Definitions"):
                for term, definition in list(module_data['key_terms'].items())[:15]:
                    st.markdown(f"**{term}:** {definition}")

        st.markdown("---")

        @st.dialog("📜 Simulation Rules & Guidelines", width="large")
        def show_disclaimer_dialog():
            total_rounds = simulation_config['total_rounds']
            st.markdown(f"""
            ### Welcome to the Boardroom Simulation!

            Please read the following rules and guidelines carefully before proceeding.

            ---

            #### 🎮 How to Play
            In this simulation, you will assume the role of a board member and navigate **{total_rounds} rounds** of
            real-world boardroom scenarios. Each round presents a unique challenge that requires you to analyze the
            situation, consult with fellow board members, and make a strategic decision.

            ---

            #### 📋 Round Structure
            Each round follows this sequence:
            1. **Read the Scenario** - Understand the challenge presented
            2. **Consult** - Seek advice from board members or committees (limited per round)
            3. **Make Your Decision** - Submit your chosen course of action with reasoning
            4. **Board Deliberation** - Board members will react, and you may need to debate with dissenters
            5. **Evaluation** - Your decision is scored and business metrics are updated

            ---

            #### 🔢 Limits Per Round
            | Resource | Limit | Description |
            |----------|-------|-------------|
            | 👥 Director Consultation | **1 per round** | Consult one or more board members together |
            | 🏛️ Committee Consultation | **1 per round** | Consult a board committee for collective advice |
            | ✏️ Decision Revision | **1 per round** | Revise your decision if the board disagrees |
            | 💬 Debate Exchanges | **3 per dissenter** | Convince opposing board members |

            ---

            #### ⏱️ Time Pressure
            Each round has a countdown timer. The time limit varies by round difficulty:
            - **Relaxed:** 15 minutes
            - **Normal:** 10 minutes
            - **Urgent:** 5 minutes

            ---

            #### 📊 Scoring
            Your performance is evaluated on three components:
            - **Decision Quality (50%)** - How well your decision addresses the scenario
            - **Business Impact (30%)** - How your decisions affect company metrics
            - **Board Effectiveness (20%)** - How well you manage board dynamics

            ---

            #### ⚠️ Important Notes
            - **Force Submit** is available if you cannot convince all dissenters, but it carries a scoring penalty
            - Consult strategically - choose members whose expertise is relevant to the scenario
            - Your decisions have cumulative impact on company metrics across all rounds
            """)

            st.markdown("---")

            if st.button("✅ I Understand, Let's Begin!", type="primary", use_container_width=True):
                st.session_state.simulation_started = True
                st.session_state.current_round = 0
                st.session_state.total_score = 0
                st.session_state.conversation_history = []
                st.session_state.initial_metrics = {k: v.copy() for k, v in company_data['metrics'].items()}
                st.session_state.current_metrics = {k: v.copy() for k, v in company_data['metrics'].items()}
                st.session_state.metric_impact_reasons = {}
                st.rerun()

        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            if st.button("🚀 Start Simulation", type="primary", use_container_width=True):
                show_disclaimer_dialog()

    elif st.session_state.current_round >= simulation_config['total_rounds']:
        impact_reasons = st.session_state.get('metric_impact_reasons', {})
        display_sidebar_metrics(company_data, impact_reasons)
        display_final_summary(data)

    else:
        impact_reasons = st.session_state.get('metric_impact_reasons', {})
        display_sidebar_metrics(company_data, impact_reasons)

        state = SimulationState(
            current_round=st.session_state.current_round,
            total_rounds=simulation_config['total_rounds']
        )

        progress = (state.current_round) / state.total_rounds
        st.progress(progress, text=f"Progress: {state.current_round}/{state.total_rounds} rounds")

        run_simulation_round(llm, data, state)
