"""
Board room simulation game engine page.
Contains simulation_page() and run_simulation_round().
"""

import logging
import streamlit as st
from datetime import datetime, timedelta
from typing import Dict, List

from core.models import SimulationState
from core.llm import initialize_llm, initialize_scenario_llm
from core.data_manager import load_extracted_data
from core.simulation_engine import (
    generate_scenario, get_board_member_response, get_committee_response,
    evaluate_decision, evaluate_consultation_alignment,
    apply_metric_impacts, parse_scenario_options, parse_scenario_sections,
)
from core.scoring import (
    calculate_board_effectiveness_score, generate_game_goals,
    calculate_goal_progress, get_time_pressure_minutes,
    compute_force_submit_penalty, round_time_limit_minutes,
)
from components.dashboard import display_company_dashboard, display_current_problems, display_module_info
from components.board_members import display_board_members_for_selection, display_board_members
from components.deliberation import display_deliberation_phase
from components.summary import display_final_summary
from components.tts import speak_button, mic_button
from core.activity_tracker import start_session, log_round, save_progress, find_resumable_session, clear_progress

logger = logging.getLogger(__name__)


def _fmt_val(v) -> str:
    """Format a metric value: drop unnecessary .0 for whole numbers."""
    try:
        f = float(v)
        return str(int(f)) if f == int(f) else f"{f:.1f}"
    except (TypeError, ValueError):
        return str(v) if v is not None else "0"


def _save_checkpoint(checkpoint_name: str):
    """Save current simulation state to Firestore for crash recovery."""
    sid = st.session_state.get('activity_session_id')
    if not sid:
        return
    cr = st.session_state.get('current_round', 0)
    progress = {
        'checkpoint': checkpoint_name,
        'current_round': cr,
        'total_score': st.session_state.get('total_score', 0),
        'conversation_history': st.session_state.get('conversation_history', []),
        'current_metrics': st.session_state.get('current_metrics', {}),
        'metric_impact_reasons': st.session_state.get('metric_impact_reasons', {}),
        'board_effectiveness_history': st.session_state.get('board_effectiveness_history', []),
        'player_role': st.session_state.get('player_role'),
        'game_goals': st.session_state.get('game_goals'),
        'round_summaries': st.session_state.get('round_summaries', []),
        'member_stance_histories': st.session_state.get('member_stance_histories', {}),
        'saved_at': datetime.now().isoformat(),
        'round_state': {
            'scenario': st.session_state.get(f'scenario_round_{cr}'),
            'pending_decision': st.session_state.get(f'pending_decision_{cr}'),
            'evaluation': st.session_state.get(f'evaluation_{cr}'),
            'board_consultations': st.session_state.get(f'board_consultations_round_{cr}', 0),
            'committee_consultations': st.session_state.get(f'committee_consultations_round_{cr}', 0),
            'revisions': st.session_state.get(f'revisions_round_{cr}', 0),
            'deliberation_phase': st.session_state.get(f'deliberation_phase_{cr}'),
            'force_submitted': st.session_state.get(f'force_submitted_{cr}', False),
            'selected_option': st.session_state.get(f'selected_option_{cr}'),
        },
    }
    try:
        save_progress(sid, progress)
    except Exception:
        logger.warning("Failed to save checkpoint %s", checkpoint_name)


def _restore_from_progress(session_data: dict, company_data: dict):
    """Restore simulation state from a saved progress checkpoint."""
    progress = session_data['progress']
    cr = progress.get('current_round', 0)

    # Core state
    st.session_state.current_round = cr
    st.session_state.total_score = progress.get('total_score', 0)
    st.session_state.conversation_history = progress.get('conversation_history', [])
    st.session_state.current_metrics = progress.get('current_metrics', {})
    st.session_state.metric_impact_reasons = progress.get('metric_impact_reasons', {})
    st.session_state.board_effectiveness_history = progress.get('board_effectiveness_history', [])
    st.session_state.simulation_started = True
    st.session_state.activity_session_id = session_data['session_id']
    st.session_state.initial_metrics = {k: v.copy() for k, v in company_data['metrics'].items()}

    # Player role
    if progress.get('player_role'):
        st.session_state.player_role = progress['player_role']

    # Game goals
    if progress.get('game_goals'):
        st.session_state.game_goals = progress['game_goals']

    # Cross-round context
    if progress.get('round_summaries'):
        st.session_state.round_summaries = progress['round_summaries']
    if progress.get('member_stance_histories'):
        st.session_state.member_stance_histories = progress['member_stance_histories']

    # Reset timer for current round so it starts fresh on restore
    timer_key = f"round_start_time_{cr}"
    st.session_state[timer_key] = datetime.now()
    # Clear any stale timer expiry flag
    st.session_state.pop(f"timer_expired_{cr}", None)

    # Per-round state
    rs = progress.get('round_state', {})
    if rs.get('scenario'):
        st.session_state[f'scenario_round_{cr}'] = rs['scenario']
    if rs.get('pending_decision'):
        st.session_state[f'pending_decision_{cr}'] = rs['pending_decision']
    if rs.get('evaluation'):
        st.session_state[f'evaluation_{cr}'] = rs['evaluation']
        st.session_state.round_complete = True
    st.session_state[f'board_consultations_round_{cr}'] = rs.get('board_consultations', 0)
    st.session_state[f'committee_consultations_round_{cr}'] = rs.get('committee_consultations', 0)
    st.session_state[f'revisions_round_{cr}'] = rs.get('revisions', 0)
    if rs.get('deliberation_phase'):
        st.session_state[f'deliberation_phase_{cr}'] = rs['deliberation_phase']
    if rs.get('selected_option'):
        st.session_state[f'selected_option_{cr}'] = rs['selected_option']
    st.session_state[f'force_submitted_{cr}'] = rs.get('force_submitted', False)


def run_simulation_round(llm: object, data: Dict,
                         state: SimulationState) -> None:
    """Run a single simulation round."""

    company_data = data['company_data']
    module_data = data['module_data']
    rounds = data['simulation_config']['rounds']
    if state.current_round >= len(rounds):
        st.error(f"Round {state.current_round + 1} configuration not found. Only {len(rounds)} rounds are configured.")
        st.stop()
    round_config = rounds[state.current_round]
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
    # round_time_limit_minutes() encapsulates the Round 1 +5 onboarding bonus
    # (closes feedback A8/F). Pure function — testable.
    time_limit_minutes = round_time_limit_minutes(state.current_round, time_pressure)

    eval_key = f"evaluation_{state.current_round}"
    decision_submitted = eval_key in st.session_state

    # Phase: Briefing
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        st.markdown(f"""
        <div class="round-indicator">
            Round {state.current_round + 1} of {state.total_rounds} |
            Difficulty: {round_config['difficulty'].title()} |
            Focus: {(round_config.get('focus_area', 'General') or 'General')[:30]}
        </div>
        """, unsafe_allow_html=True)

    with col2:
        board_left = max(0, 1 - st.session_state[board_consult_key])
        committee_left = max(0, 1 - st.session_state[committee_consult_key])
        revision_left = max(0, 1 - st.session_state[revision_key])
        st.markdown(f"""
        <div class="consultation-counter" title="One-shot quotas per round. Director: ask one board member privately. Committee: ask one committee for collective input. Revise: rewrite your decision once after submission. Consultation usage feeds your Board Effectiveness score (consultation alignment, 25 pts).">
            👥 Director: {board_left}/1 | 🏛️ Committee: {committee_left}/1 | ✏️ Revise: {revision_left}/1
        </div>
        """, unsafe_allow_html=True)
        st.caption(
            "ℹ️ Each round you can use **1 Director** consult, **1 Committee** consult, "
            "and **1 Revise**. Consultations feed the **Consultation Alignment** sub-score "
            "(25 pts of Board Effectiveness) — using them and following the advice raises this score."
        )

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
                <div class="timer-label" id="{timer_id}_label">Time Limit ({time_pressure.title()})</div>
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
                            labelEl.innerHTML = "⚠️ Time Limit Reached!";
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

            # Auto-rerun fragment: polls every 15s, triggers full rerun when timer expires
            if remaining_seconds > 0:
                @st.fragment(run_every=timedelta(seconds=15))
                def _timer_watchdog():
                    _elapsed = datetime.now() - st.session_state[timer_key]
                    if _elapsed.total_seconds() >= total_seconds:
                        st.session_state[timer_expired_key] = True
                        st.rerun()
                _timer_watchdog()
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
        st.session_state[f"force_submitted_{state.current_round}"] = True
        st.warning(
            "⚠️ **Time has expired!** Consultations are now locked. You can still submit your decision, but it will be recorded as a **late submission** "
            "— positive metric impacts will be reduced by 15% and your Board Effectiveness "
            "efficiency score is capped at 5/20 for this round."
        )

    # Generate or retrieve scenario
    scenario_key = f"scenario_round_{state.current_round}"
    if scenario_key not in st.session_state:
        # Build cross-round context from previous rounds
        previous_rounds = st.session_state.get('round_summaries', [])
        with st.spinner("Generating scenario..."):
            try:
                _s_llm = st.session_state.get('_scenario_llm', llm)
                st.session_state[scenario_key] = generate_scenario(
                    _s_llm, company_data, module_data, round_config, player_role,
                    previous_rounds=previous_rounds if previous_rounds else None
                )
            except Exception as e:
                logger.error(f"Scenario generation failed: {e}")
                st.error("Failed to generate scenario. Please refresh the page to retry.")
                st.stop()
        _save_checkpoint('scenario_generated')

    scenario = st.session_state[scenario_key]

    st.markdown("### 📋 Scenario")
    sections = parse_scenario_sections(scenario)
    options = parse_scenario_options(scenario)

    if sections['title'] or sections['situation']:
        # Structured rendering
        if sections['title']:
            st.markdown(f'<div class="scenario-title">{sections["title"]}</div>', unsafe_allow_html=True)

        if sections['situation']:
            st.markdown(f'<div class="scenario-situation">{sections["situation"]}</div>', unsafe_allow_html=True)

        info_parts = []
        if sections['key_question']:
            info_parts.append(f"""
                <div class="scenario-info-item">
                    <span class="scenario-info-label">Key Question</span>
                    <p>{sections['key_question']}</p>
                </div>""")
        if sections['stakeholders']:
            info_parts.append(f"""
                <div class="scenario-info-item">
                    <span class="scenario-info-label">Stakeholders Affected</span>
                    <p>{sections['stakeholders']}</p>
                </div>""")
        if sections['time_sensitivity']:
            info_parts.append(f"""
                <div class="scenario-info-item">
                    <span class="scenario-info-label">Time Sensitivity</span>
                    <p>{sections['time_sensitivity']}</p>
                </div>""")

        if info_parts:
            st.markdown(f'<div class="scenario-info-grid">{"".join(info_parts)}</div>', unsafe_allow_html=True)
    else:
        # Fallback: raw text with whitespace preserved
        st.markdown(f'<div class="scenario-box" style="white-space: pre-wrap;">{scenario}</div>',
                    unsafe_allow_html=True)

    # Audio: read scenario aloud (includes options if present)
    _scenario_audio = scenario
    _parsed_opts = parse_scenario_options(scenario)
    if _parsed_opts:
        _opts_text = ". ".join(f"Option {o['letter']}: {o['text']}" for o in _parsed_opts)
        _scenario_audio = scenario + " Options: " + _opts_text
    speak_button(_scenario_audio, label="Listen to Scenario", key=f"scenario_{state.current_round}")

    # Consultation Section
    st.markdown("### 💬 Consultation")

    board_consultation_used = st.session_state[board_consult_key] >= 1
    committee_consultation_used = st.session_state[committee_consult_key] >= 1

    if timer_expired and not decision_submitted:
        st.warning("⏱️ Time has expired — consultations are locked. Please submit your decision.")
    elif not decision_submitted and (not board_consultation_used or not committee_consultation_used):
        consult_tab1, consult_tab2 = st.tabs(["👥 Consult Board Members", "🏛️ Consult Committee"])

        with consult_tab1:
            if board_consultation_used:
                st.warning("⚠️ You have already used your director consultation for this round.")
            else:
                available_members = [m for m in company_data['board_members'] if m['name'] != player_role['name']]

                if not available_members:
                    st.info("No other board members are available for consultation.")
                else:
                    member_names = [m['name'] for m in available_members]

                    # Hover-preview chips above the multiselect — lets users see
                    # full profile (expertise, tenure, personality) before picking.
                    from components.board_members import member_chip_html as _mch
                    _chip_row = ' '.join(
                        f'<span style="background:#eef2ff;color:#3730a3;padding:0.18rem 0.55rem;'
                        f'border-radius:12px;font-size:0.78rem;margin:0.12rem;display:inline-block;'
                        f'border:1px solid #c7d2fe;">{_mch(m, label=m["name"])}</span>'
                        for m in available_members
                    )
                    st.markdown(
                        f'<div style="margin: 0.3rem 0 0.55rem 0;">'
                        f'<small style="color:#6b7280;">💡 Hover any name to see their full profile:</small><br>'
                        f'{_chip_row}</div>',
                        unsafe_allow_html=True,
                    )

                    selected_members = st.multiselect(
                        "Select board member(s) to consult:",
                        member_names,
                        key=f"member_select_{state.current_round}",
                        help="You can select multiple members for a group discussion (1 consultation per round)"
                    )

                    _board_q_label = "Your question or topic for discussion:"
                    user_question = st.text_input(
                        _board_q_label,
                        key=f"member_question_{state.current_round}",
                        placeholder="e.g., What are your thoughts on the compliance implications?"
                    )
                    mic_button(target_label=_board_q_label, key=f"mic_board_{state.current_round}")

                    _board_processing = st.session_state.get(f"_processing_board_{state.current_round}", False)
                    _question_too_short = len((user_question or "").strip()) < 10
                    if _question_too_short and user_question:
                        st.caption("⚠️ Question must be at least 10 characters.")
                    if st.button("Ask Board Member(s)", key=f"ask_members_btn_{state.current_round}",
                                disabled=len(selected_members) == 0 or not user_question or _question_too_short or _board_processing):
                        if selected_members and user_question:
                            st.session_state[f"_processing_board_{state.current_round}"] = True
                            selected_member_data = [m for m in available_members if m['name'] in selected_members]

                            with st.spinner(f"{'Board members are' if len(selected_members) > 1 else selected_members[0] + ' is'} responding..."):
                                try:
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
                                    _save_checkpoint('consultation_done')
                                    st.rerun()
                                except Exception as e:
                                    logger.error(f"Board consultation failed: {e}")
                                    st.session_state.pop(f"_processing_board_{state.current_round}", None)
                                    st.error("Board member is temporarily unavailable. Your consultation was not consumed — please try again.")

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

                    _comm_q_label = "Your question for the committee:"
                    committee_question = st.text_input(
                        _comm_q_label,
                        key=f"committee_question_{state.current_round}",
                        placeholder="e.g., What is the committee's recommendation on this matter?"
                    )
                    mic_button(target_label=_comm_q_label, key=f"mic_comm_{state.current_round}")

                    _comm_processing = st.session_state.get(f"_processing_committee_{state.current_round}", False)
                    _cq_too_short = len((committee_question or "").strip()) < 10
                    if _cq_too_short and committee_question:
                        st.caption("⚠️ Question must be at least 10 characters.")
                    if st.button("Consult Committee", key=f"ask_committee_btn_{state.current_round}",
                                disabled=not committee_question or _cq_too_short or _comm_processing):
                        if committee_question:
                            st.session_state[f"_processing_committee_{state.current_round}"] = True
                            selected_committee_data = next(c for c in committees if c['name'] == selected_committee)

                            with st.spinner(f"{selected_committee} is deliberating..."):
                                try:
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
                                    _save_checkpoint('consultation_done')
                                    st.rerun()
                                except Exception as e:
                                    logger.error(f"Committee consultation failed: {e}")
                                    st.session_state.pop(f"_processing_committee_{state.current_round}", None)
                                    st.error("Committee is temporarily unavailable. Your consultation was not consumed — please try again.")
                else:
                    st.info("No committees are available for consultation.")
    elif not decision_submitted:
        st.warning("⚠️ You have used all consultations for this round. Please make your decision.")

    # Display conversation history
    if 'conversation_history' in st.session_state and st.session_state.conversation_history:
        with st.expander("📝 Discussion History", expanded=True):
            for ci, entry in enumerate(st.session_state.conversation_history):
                if entry['role'] == 'user':
                    st.markdown(f"**You asked {entry.get('member', 'Board')}:** {entry['content']}")
                else:
                    st.markdown(f"**{entry.get('member', 'Board Member')}:** {entry['content']}")
                    speak_button(entry['content'], label="Listen", key=f"consult_{state.current_round}_{ci}")
                st.markdown("---")

    # Check deliberation state
    pending_decision_key = f"pending_decision_{state.current_round}"
    delib_phase_key = f"deliberation_phase_{state.current_round}"
    pending_exists = pending_decision_key in st.session_state

    # Decision Phase — only show input controls before submission
    st.markdown("### ✅ Your Decision")

    decision_key = f"decision_input_{state.current_round}"
    if decision_key not in st.session_state:
        st.session_state[decision_key] = ""

    has_selected_option = f"selected_option_{state.current_round}" in st.session_state

    if not pending_exists:
        if options:
            st.markdown("**Select an option or write your own decision below:**")
            # Blur autofocus and remove focus styling so no option appears pre-selected
            st.components.v1.html("""<script>
                document.activeElement&&document.activeElement.blur();
                setTimeout(function(){
                    document.querySelectorAll('button[kind="secondary"]').forEach(function(b){b.blur();});
                }, 100);
            </script>""", height=0)

            option_cols = st.columns(2)
            for idx, opt in enumerate(options):
                with option_cols[idx % 2]:
                    _is_selected = (has_selected_option
                                    and st.session_state[f"selected_option_{state.current_round}"].get('letter') == opt['letter'])
                    # NOTE: option calibration (unanimous / mild_dissent / etc.) and
                    # stance_distribution MUST NOT be displayed here. They are internal
                    # pedagogical metadata used to drive deterministic board stances —
                    # leaking them would let students pick the "safe" option without
                    # reasoning. Card shows only the letter and the option text.
                    border_color = '#198754' if _is_selected else '#dee2e6'
                    bg_color = '#f0f9f4' if _is_selected else '#ffffff'
                    prefix = '✅ ' if _is_selected else ''
                    st.markdown(
                        f'<div style="background:{bg_color};border:2px solid {border_color};'
                        f'border-radius:10px;padding:0.85rem 1rem;margin-bottom:0.4rem;'
                        f'min-height:170px;">'
                        f'<div style="font-weight:600;font-size:0.95rem;color:#1f2937;'
                        f'margin-bottom:0.5rem;">{prefix}Option {opt["letter"]}</div>'
                        f'<div style="color:#374151;font-size:0.88rem;line-height:1.5;">'
                        f'{opt["text"]}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                    if st.button(
                        "✅ Selected" if _is_selected else f"Select Option {opt['letter']}",
                        key=f"option_{opt['letter']}_{state.current_round}",
                        use_container_width=True,
                        type="primary" if _is_selected else "secondary",
                        disabled=_is_selected,
                    ):
                        st.session_state[f"selected_option_{state.current_round}"] = opt
                        st.rerun()

            st.markdown("---")

    if has_selected_option and not pending_exists:
        _selected = st.session_state[f"selected_option_{state.current_round}"]
        _sel_col1, _sel_col2 = st.columns([5, 1])
        with _sel_col1:
            st.success(f"**Your Decision:** Option {_selected['letter']} — {_selected['text']}")
        with _sel_col2:
            if st.button("Clear", key=f"clear_option_{state.current_round}"):
                del st.session_state[f"selected_option_{state.current_round}"]
                st.rerun()
        _decision_label = "Add reasoning (optional — earns bonus points):"
        _decision_placeholder = "Why did you choose this? What are the risks? How would you implement it? (Leave blank to submit with just your option selection)"
    else:
        _decision_label = "Write your own decision:"
        _decision_placeholder = "State your decision clearly, then explain your rationale — why is this the best course of action? How would you implement it?"

    decision = st.text_area(
        _decision_label,
        key=decision_key,
        placeholder=_decision_placeholder,
        height=150,
        disabled=pending_exists,
    )
    if not pending_exists:
        mic_button(target_label=_decision_label, key=f"mic_{state.current_round}")

    logger.debug(f"Round {state.current_round}: delib_phase_key={delib_phase_key}, exists={delib_phase_key in st.session_state}")

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
            try:
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

                # Engagement data drives the Behavioural Governance dimension
                # in the v1.4.9 rubric. Gathered from session state populated
                # by the consultation + deliberation flows.
                _dh = st.session_state.get(f"debate_history_{state.current_round}", []) or []
                _addressed = len({h.get('dissenter_name') for h in _dh if h.get('dissenter_name')})
                _dissenters_total = sum(1 for s in stances.values()
                                        if s.get('stance') in ('OPPOSE', 'CONVINCED'))
                engagement_data = {
                    'board_consultations':     st.session_state.get(f'board_consultations_round_{state.current_round}', 0),
                    'committee_consultations': st.session_state.get(f'committee_consultations_round_{state.current_round}', 0),
                    'debate_exchanges':        sum(int(s.get('debate_exchanges', 0)) for s in stances.values()),
                    'dissenters_addressed':    _addressed,
                    'dissenters_total':        _dissenters_total,
                    'force_submitted':         bool(force_submitted),
                }

                evaluation = evaluate_decision(
                    llm, company_data, module_data,
                    scenario, st.session_state[pending_decision_key],
                    round_config, player_role,
                    engagement_data=engagement_data,
                )

                evaluation['board_effectiveness'] = effectiveness
                evaluation['engagement_data'] = engagement_data
                st.session_state[eval_key] = evaluation

                if 'metric_impacts' in evaluation:
                    impacts = evaluation['metric_impacts']
                    current_metrics = st.session_state.get('current_metrics', company_data['metrics'].copy())
                    impact_values = impacts.get('impacts', {})
                    if force_submitted:
                        # Escalating penalty (TIMER_ISSUES.md #2): 15% at expiry,
                        # ramps to 50% at +10 min overtime. Uses the same Round 1
                        # bonus calc as the timer itself so overtime is measured
                        # relative to the TRUE limit the player saw.
                        _round_start = st.session_state.get(f"round_start_time_{state.current_round}")
                        _total_secs = round_time_limit_minutes(
                            state.current_round, round_config.get('time_pressure', 'normal')
                        ) * 60
                        _overtime = max(0, (datetime.now() - _round_start).total_seconds() - _total_secs) if _round_start else 0
                        _penalty = compute_force_submit_penalty(_overtime)
                        impact_values = {
                            k: v * (1 - _penalty) if v > 0 else v * (1 + _penalty) if v < 0 else 0
                            for k, v in impact_values.items()
                        }
                    updated_metrics = apply_metric_impacts(current_metrics, impact_values)
                    st.session_state.current_metrics = updated_metrics
                    st.session_state.metric_impact_reasons = impacts.get('reasons', {})
                    st.session_state[f"impact_summary_{state.current_round}"] = impacts.get('summary', '')

                    # Compute the composite per-round score (decision + module + business
                    # impact + board effectiveness). Mirrors the final-grade formula but
                    # scoped to one round, so the player sees a score reflecting actual
                    # metric movement and persuasion outcomes — not just LLM rubric.
                    # Closes client claims #3 and #6.
                    try:
                        from core.scoring import compute_composite_round_score
                        composite = compute_composite_round_score(
                            decision_score=evaluation['score'],
                            vocab_score=evaluation.get('vocabulary_score', 50),
                            metrics_before=current_metrics,
                            metrics_after=updated_metrics,
                            board_effectiveness_score=effectiveness.get('deliberation_score', 50),
                        )
                        st.session_state[f"composite_score_{state.current_round}"] = composite
                        # Also store on the evaluation dict so downstream displays can use it
                        evaluation['composite_round_score'] = composite
                    except Exception as _comp_err:
                        logger.warning(f"Composite round score computation failed: {_comp_err}")

                st.session_state.round_complete = True
                _save_checkpoint('evaluated')
            except Exception as e:
                logger.error(f"Decision evaluation failed: {e}")
                st.error("Failed to evaluate your decision. Please click 'Submit Decision' again to retry.")
                del st.session_state[pending_decision_key]
                st.session_state.pop(f"_processing_submit_{state.current_round}", None)
                st.stop()
        st.rerun()

    # Only show submit button before submission
    _min_chars = 20
    _reasoning_text = (decision or "").strip()
    if not pending_exists and eval_key not in st.session_state:
        _submit_processing = st.session_state.get(f"_processing_submit_{state.current_round}", False)

        # If no option selected and text is too short, show progress
        if not has_selected_option and 0 < len(_reasoning_text) < _min_chars:
            st.caption(f"⚠️ {len(_reasoning_text)}/{_min_chars} characters — add more detail to submit.")

        if st.button("Submit Decision", key=f"submit_decision_{state.current_round}", type="primary",
                     disabled=_submit_processing, use_container_width=True):
            if has_selected_option:
                # Option selected — build final decision text
                _opt = st.session_state[f"selected_option_{state.current_round}"]
                _final_decision = f"Option {_opt['letter']}: {_opt['text']}"
                if _reasoning_text:
                    _final_decision += f"\n\nReasoning: {_reasoning_text}"
                st.session_state[f"_processing_submit_{state.current_round}"] = True
                st.session_state[f"decision_submit_time_{state.current_round}"] = datetime.now()
                st.session_state[pending_decision_key] = _final_decision
                st.session_state[delib_phase_key] = 'inactive'
                st.rerun()
            elif len(_reasoning_text) >= _min_chars:
                # Free-form decision with enough detail
                st.session_state[f"_processing_submit_{state.current_round}"] = True
                st.session_state[f"decision_submit_time_{state.current_round}"] = datetime.now()
                st.session_state[pending_decision_key] = _reasoning_text
                st.session_state[delib_phase_key] = 'inactive'
                st.rerun()
            elif len(_reasoning_text) > 0:
                st.warning(f"Please provide more detail — your decision needs at least {_min_chars} characters.")
            else:
                st.warning("Please select an option above or write your own decision.")

    # Display evaluation if available
    if eval_key in st.session_state:
        evaluation = st.session_state[eval_key]

        st.markdown("### 📊 Evaluation & Feedback")

        # Build full feedback text for audio
        _feedback_parts = [f"Your score is {evaluation.get('score', 0)} out of 100."]
        if evaluation.get('score_reasoning'):
            _feedback_parts.append(evaluation['score_reasoning'])
        if evaluation.get('strengths'):
            _feedback_parts.append(f"Strengths: {evaluation['strengths']}")
        if evaluation.get('improvements'):
            _feedback_parts.append(f"Areas for improvement: {evaluation['improvements']}")
        if evaluation.get('learning_points'):
            _feedback_parts.append(f"Key learning points: {evaluation['learning_points']}")
        speak_button(" ".join(_feedback_parts), label="Listen to Feedback", key=f"feedback_{state.current_round}")

        score = evaluation['score']
        # Composite is the headline (decision + business + board_eff + vocab).
        # LLM decision score is shown as a sub-component, not the headline.
        composite_info = (st.session_state.get(f"composite_score_{state.current_round}")
                          or evaluation.get('composite_round_score'))
        if composite_info:
            headline = composite_info['composite']
            score_color = "#28a745" if headline >= 70 else "#ffc107" if headline >= 50 else "#dc3545"
            w = composite_info.get('weights', {})
            mb = composite_info['metric_breakdown']
            be = effectiveness if 'effectiveness' in dir() else st.session_state.get(f"board_effectiveness_{state.current_round}", {})
            be_score = be.get('deliberation_score', 50) if be else 50
            vocab_score = evaluation.get('vocabulary_score', 50)
            st.markdown(f"""
            <div style="padding: 1rem; background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%); border-radius: 10px; margin-bottom: 1rem;">
                <div style="text-align:center;">
                    <h2 style="color: {score_color}; margin: 0;">Round Score: {headline:.0f}/100</h2>
                    <div style="font-size:0.8rem; color:#6b7280; margin-top:0.2rem;">
                        Composite of decision quality, business impact, board effectiveness, and module application.
                    </div>
                </div>
                <div style="display:grid; grid-template-columns:repeat(4, 1fr); gap:0.6rem; margin-top:0.8rem;">
                    <div style="background:#fff; padding:0.5rem; border-radius:8px; text-align:center; border:1px solid #e5e7eb;">
                        <div style="font-size:0.72rem; color:#6b7280;">Decision ({int(w.get('decision', 0.4)*100)}%)</div>
                        <div style="font-size:1.1rem; font-weight:600; color:#1f2937;">{score}/100</div>
                    </div>
                    <div style="background:#fff; padding:0.5rem; border-radius:8px; text-align:center; border:1px solid #e5e7eb;">
                        <div style="font-size:0.72rem; color:#6b7280;">Business Impact ({int(w.get('metric', 0.25)*100)}%)</div>
                        <div style="font-size:1.1rem; font-weight:600; color:#1f2937;">{mb['normalized_score']:.0f}/100</div>
                    </div>
                    <div style="background:#fff; padding:0.5rem; border-radius:8px; text-align:center; border:1px solid #e5e7eb;">
                        <div style="font-size:0.72rem; color:#6b7280;">Board Effectiveness ({int(w.get('board_effectiveness', 0.20)*100)}%)</div>
                        <div style="font-size:1.1rem; font-weight:600; color:#1f2937;">{be_score:.0f}/100</div>
                    </div>
                    <div style="background:#fff; padding:0.5rem; border-radius:8px; text-align:center; border:1px solid #e5e7eb;">
                        <div style="font-size:0.72rem; color:#6b7280;">Module Vocab ({int(w.get('vocab', 0.15)*100)}%)</div>
                        <div style="font-size:1.1rem; font-weight:600; color:#1f2937;">{vocab_score}/100</div>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)
        else:
            # Legacy fallback when composite isn't available (old session data)
            score_color = "#28a745" if score >= 70 else "#ffc107" if score >= 50 else "#dc3545"
            st.markdown(f"""
            <div style="text-align: center; padding: 1rem; background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%); border-radius: 10px; margin-bottom: 1rem;">
                <h2 style="color: {score_color}; margin: 0;">Score: {score}/100</h2>
            </div>
            """, unsafe_allow_html=True)

        if evaluation.get('score_reasoning'):
            with st.expander("📋 Score Breakdown & Reasoning (Total: 100 pts)", expanded=True):
                st.caption(
                    "**Dimensions:** Governance Understanding /25 · "
                    "Legal & Regulatory /25 · Stakeholder Consideration /15 · "
                    "Strategic Thinking /15 · Role Alignment /5 · "
                    "Behavioural Governance /5 · Decision Integrity /5 · "
                    "Ethics & Judgment Under Pressure /5"
                )
                st.markdown(evaluation['score_reasoning'])

        # Module Vocabulary tracker — independent of board-persuasion outcome (P1-5/P1-6)
        vocab_score = evaluation.get('vocabulary_score', 0)
        vocab_invoked = evaluation.get('vocabulary_invoked') or []
        vocab_missed = evaluation.get('vocabulary_missed') or []
        vocab_misused = evaluation.get('vocabulary_misused') or []
        if vocab_score or vocab_invoked or vocab_missed or vocab_misused:
            vocab_color = "#28a745" if vocab_score >= 70 else "#ffc107" if vocab_score >= 40 else "#dc3545"
            with st.expander(
                f"🎓 Module Application: {vocab_score}/100 — vocabulary you invoked vs missed",
                expanded=(vocab_score < 60),
            ):
                st.caption(
                    "Independent of board persuasion. Measures whether your decision invoked the "
                    "module's canonical concepts by name or correct paraphrase."
                )
                st.markdown(
                    f"<div style='font-size:1.4rem;color:{vocab_color};font-weight:600;'>"
                    f"Module Application Score: {vocab_score}/100</div>",
                    unsafe_allow_html=True,
                )
                vc1, vc2, vc3 = st.columns(3)
                with vc1:
                    st.markdown("**✅ Invoked**")
                    if vocab_invoked:
                        for t in vocab_invoked:
                            st.markdown(f"- {t}")
                    else:
                        st.caption("_None invoked_")
                with vc2:
                    st.markdown("**🟡 Missed**")
                    if vocab_missed:
                        for t in vocab_missed:
                            st.markdown(f"- {t}")
                    else:
                        st.caption("_All relevant terms used_")
                with vc3:
                    st.markdown("**🔴 Misused**")
                    if vocab_misused:
                        for t in vocab_misused:
                            st.markdown(f"- {t}")
                    else:
                        st.caption("_None misused_")

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
            # Default-expanded for any score (closes feedback Item #2). The Best Approach
            # is the highest-leverage learning element — hiding it behind a click was
            # defeating its educational purpose. Players who scored well still benefit
            # from comparing their reasoning against the gold-standard answer.
            label = "💡 Recommended Best Approach"
            if score < 60:
                label += " — PLEASE REVIEW"
            elif score < 75:
                label += " — see how a stronger answer would look"
            else:
                label += " — compare with your reasoning"
            with st.expander(label, expanded=True):
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
                LOWER_IS_BETTER = {'churn', 'attrition', 'risk', 'debt', 'turnover',
                                   'cost', 'defect', 'burn', 'incident', 'latency',
                                   'vacancy', 'audit', 'pending',
                                   'liability', 'remediation', 'penalty', 'loss',
                                   'exposure', 'violation', 'complaint', 'breach',
                                   'carbon', 'emission', 'footprint', 'greenhouse'}
                positive_impacts = {}
                negative_impacts = {}
                for k, v in changed_metrics.items():
                    is_lower_better = any(kw in k.lower() for kw in LOWER_IS_BETTER)
                    is_positive = (v < 0 if is_lower_better else v > 0)
                    if is_positive:
                        positive_impacts[k] = v
                    else:
                        negative_impacts[k] = v

                current_metrics = st.session_state.get('current_metrics', company_data.get('metrics', {}))
                col1, col2 = st.columns(2)
                with col1:
                    if positive_impacts:
                        st.markdown("**✅ Positive Impacts:**")
                        for key, change in positive_impacts.items():
                            metric_name = key.replace('_', ' ').title()
                            unit = (current_metrics.get(key) or {}).get('unit') or ''
                            reason = reasons.get(key, '')
                            usep = "" if unit.startswith('%') else " "
                            is_lib = any(kw in key.lower() for kw in LOWER_IS_BETTER)
                            direction = "↓" if (is_lib and change < 0) else "↑" if change > 0 else ""
                            st.success(f"**{metric_name}**: {direction} {change:+.1f}{usep}{unit}".rstrip())
                            if reason:
                                st.caption(f"↳ {reason}")
                with col2:
                    if negative_impacts:
                        st.markdown("**⚠️ Negative Impacts:**")
                        for key, change in negative_impacts.items():
                            metric_name = key.replace('_', ' ').title()
                            unit = (current_metrics.get(key) or {}).get('unit') or ''
                            reason = reasons.get(key, '')
                            usep = "" if unit.startswith('%') else " "
                            is_lib = any(kw in key.lower() for kw in LOWER_IS_BETTER)
                            direction = "↑" if (is_lib and change > 0) else "↓" if change < 0 else ""
                            st.error(f"**{metric_name}**: {direction} {change:+.1f}{usep}{unit}".rstrip())
                            if reason:
                                st.caption(f"↳ {reason}")

        # Next round button
        _next_processing = st.session_state.get(f"_processing_next_{state.current_round}", False)
        if st.button("Proceed to Next Round", key=f"next_round_{state.current_round}",
                     disabled=_next_processing):
            st.session_state[f"_processing_next_{state.current_round}"] = True
            # Track round activity
            try:
                _act_sid = st.session_state.get('activity_session_id')
                if _act_sid:
                    _round_start = st.session_state.get(f"round_start_time_{state.current_round}")
                    _submit_time = st.session_state.get(f"decision_submit_time_{state.current_round}", datetime.now())
                    _time_taken = int((_submit_time - _round_start).total_seconds()) if _round_start else None
                    # Persuasion outcome — drives X.1 cohort analytics for stuck-dissenter detection.
                    _stances = st.session_state.get(f"member_stances_{state.current_round}", {}) or {}
                    _persuaded = [n for n, s in _stances.items() if s.get('convinced_in_round') is not None]
                    _unpersuaded = [
                        n for n, s in _stances.items()
                        if s.get('stance') in ('OPPOSE', 'CONVINCED')
                        and s.get('convinced_in_round') is None
                    ]
                    log_round(
                        session_id=_act_sid,
                        round_number=state.current_round + 1,
                        decision=st.session_state.get(f"pending_decision_{state.current_round}", ""),
                        score=score,
                        board_consultations=st.session_state.get(f"board_consultations_round_{state.current_round}", 0),
                        committee_consultations=st.session_state.get(f"committee_consultations_round_{state.current_round}", 0),
                        force_submitted=st.session_state.get(f"force_submitted_{state.current_round}", False),
                        time_taken_seconds=_time_taken,
                        strengths=evaluation.get('strengths', []),
                        improvements=evaluation.get('improvements', []),
                        # X.1 — feed cohort analytics so Agent 3's next plan can self-calibrate
                        vocabulary_score=evaluation.get('vocabulary_score'),
                        vocabulary_invoked=evaluation.get('vocabulary_invoked', []),
                        vocabulary_missed=evaluation.get('vocabulary_missed', []),
                        vocabulary_misused=evaluation.get('vocabulary_misused', []),
                        dissenters_persuaded=_persuaded,
                        dissenters_unpersuaded=_unpersuaded,
                    )
            except Exception:
                logger.warning("Failed to log round activity")

            # Save round summary for cross-round context
            _scenario_text = st.session_state.get(f"scenario_round_{state.current_round}", "")
            _sections = parse_scenario_sections(_scenario_text)
            _round_summary = {
                'round_number': state.current_round + 1,
                'title': _sections.get('title', f'Round {state.current_round + 1}'),
                'decision_summary': st.session_state.get(f"pending_decision_{state.current_round}", "")[:200],
                'outcome_summary': f"Score: {score}/100. " + (evaluation.get('score_reasoning', '') or '')[:150],
            }
            if 'round_summaries' not in st.session_state:
                st.session_state.round_summaries = []
            st.session_state.round_summaries.append(_round_summary)

            # Save per-member stance history for cross-round conviction tracking
            _stances = st.session_state.get(f"member_stances_{state.current_round}", {})
            if 'member_stance_histories' not in st.session_state:
                st.session_state.member_stance_histories = {}
            for _mname, _mstance in _stances.items():
                if _mname not in st.session_state.member_stance_histories:
                    st.session_state.member_stance_histories[_mname] = []
                st.session_state.member_stance_histories[_mname].append({
                    'round_number': state.current_round + 1,
                    'stance': _mstance.get('stance', 'NEUTRAL'),
                    'conviction': _mstance.get('conviction_level', 5),
                    'was_convinced': _mstance.get('convinced_in_round') is not None,
                    'objection': _mstance.get('counter_opinion', ''),
                })

            st.session_state.current_round += 1
            st.session_state.conversation_history = []
            st.session_state.round_complete = False
            st.session_state.total_score = st.session_state.get('total_score', 0) + score
            st.session_state.metric_impact_reasons = {}
            _save_checkpoint('next_round')
            st.rerun()


def simulation_page():
    """Simulation page — runs the board room simulation for the selected JSON."""

    # doc_id is set by the make_page closure in main.py before this runs
    if not st.session_state.get('selected_doc_id'):
        st.warning("No simulation selected. Please choose one from the sidebar.")
        return

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

        if st.session_state.get("student_identified"):
            st.markdown(f"""
            <div style="background: #e7f3ff; padding: 0.6rem; border-radius: 8px;
                        margin-top: 0.5rem; font-size: 0.85rem;">
                <strong>Student:</strong> {st.session_state.get('student_name', '')}<br>
                <strong>ID:</strong> {st.session_state.get('student_id', '')}
            </div>
            """, unsafe_allow_html=True)

        with st.expander("⚙️ Options", expanded=False):
            if st.button("🔄 Restart Simulation", use_container_width=True):
                preserve_keys = {
                    'api_key', 'selected_doc_id', '_sim_pages',
                    'user_role', 'admin_authenticated',
                    'student_name', 'student_id', 'student_identified',
                    'activity_session_id'
                }
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

                    current_val = round(goal.get('current_value', goal['current']), 1)
                    target_val = round(goal['target'], 1)
                    unit = goal['unit']
                    unit_sep = "" if unit.startswith('%') else " "

                    st.markdown(f"""
                    <div style="margin-bottom: 0.8rem;">
                        <div style="display: flex; justify-content: space-between; font-size: 0.85rem;">
                            <span>{status_icon} {goal['name']}</span>
                            <span>{_fmt_val(current_val)}{unit_sep}{unit} / {_fmt_val(target_val)}{unit_sep}{unit}</span>
                        </div>
                        <div style="background: #e9ecef; border-radius: 4px; height: 8px; margin-top: 4px;">
                            <div style="background: {color}; width: {min(progress, 100):.1f}%; height: 100%; border-radius: 4px;"></div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

            st.markdown("---")

            metrics = st.session_state.get('current_metrics', company_data['metrics'])

            st.header("🔴 High Priority Metrics")
            high_priority_metrics = {
                k: v for k, v in metrics.items()
                if str(v.get('priority') or '').strip().lower() == 'high'
            }

            if high_priority_metrics:
                for key, metric in high_priority_metrics.items():
                    change = metric.get('change', 0)
                    delta_str = None
                    if change != 0:
                        delta_str = f"{change:+.1f}" if isinstance(change, float) else f"{change:+d}"
                    st.metric(metric.get('description', key), f"{metric.get('value', 0)} {metric.get('unit', '')}",
                             delta=delta_str, delta_color="normal" if change >= 0 else "inverse")
                    if impact_reasons and key in impact_reasons:
                        st.caption(f"📝 {impact_reasons[key]}")
            else:
                st.info("No high priority metrics flagged")

            st.markdown("---")

            # Currency mixing detection — warn ONLY if mixed currency units survived normalization.
            # data_manager._normalize_metrics() canonicalizes recognized units to $M; the warning
            # should only fire when extraction produced a unit we couldn't normalize.
            _currency_units = set()
            for _m in metrics.values():
                _u = (_m.get('unit') or '').strip()
                if any(sym in _u for sym in ('$', '₹', '€', '£')) or _u in ('Cr', 'L', 'M', 'K', 'B'):
                    _currency_units.add(_u)
            if len(_currency_units) > 1:
                st.caption(
                    f"⚠️ Mixed currency/scale units detected ({', '.join(sorted(_currency_units))}). "
                    "These units could not be auto-normalized — admin should review the metric definitions."
                )

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
                    value = metric.get('value', 0) or 0
                    unit = metric.get('unit', '')
                    change = metric.get('change', 0) or 0
                    display_val = f"{_fmt_val(value)} {unit}".rstrip()
                    delta_str = None
                    if change != 0:
                        delta_str = f"{change:+.1f}" if isinstance(change, float) else f"{change:+d}"
                    delta_color = "inverse" if key in inverse_metrics else "normal"
                    st.metric(metric.get('description', key), display_val, delta=delta_str, delta_color=delta_color)
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

    if not st.session_state.get('selected_doc_id'):
        st.warning("⚠️ Please select a simulation.")
        return

    data = load_extracted_data(st.session_state.selected_doc_id)
    if not data:
        st.error("Failed to load simulation data.")
        return

    # Validate required top-level fields
    missing = [f for f in ('company_data', 'module_data', 'simulation_config') if f not in data or not data[f]]
    if missing:
        st.error(f"Simulation data is incomplete. Missing: {', '.join(missing)}. Please re-create this simulation.")
        return

    company_data = data['company_data']
    module_data = data['module_data']
    simulation_config = data['simulation_config']

    # Validate required nested fields
    required_company = {'company_name': 'Company Name', 'board_members': 'Board Members', 'metrics': 'Metrics'}
    required_module = {'module_name': 'Module Name', 'learning_objectives': 'Learning Objectives', 'topics': 'Topics'}
    missing_nested = []
    for key, label in required_company.items():
        if not company_data.get(key):
            missing_nested.append(label)
    for key, label in required_module.items():
        if not module_data.get(key):
            missing_nested.append(label)
    if not simulation_config.get('rounds'):
        missing_nested.append('Round Configuration')
    if missing_nested:
        st.error(f"Simulation data is incomplete. Missing: {', '.join(missing_nested)}. Please edit this simulation in Manage Simulations.")
        return

    try:
        llm = initialize_llm(st.session_state.api_key)
        st.session_state._scenario_llm = initialize_scenario_llm(st.session_state.api_key)
    except Exception as e:
        logger.error(f"Failed to initialize AI model: {e}")
        st.error("Failed to initialize AI model. Please check your API key configuration.")
        return

    if 'current_round' not in st.session_state:
        st.session_state.current_round = 0
    if 'simulation_started' not in st.session_state:
        st.session_state.simulation_started = False

    # Student identification gate (skip for admins)
    if not st.session_state.get("admin_authenticated") and not st.session_state.get("student_identified"):
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #1E3A5F 0%, #2d5a8a 100%);
                    padding: 2rem; border-radius: 12px; margin-bottom: 1.5rem; color: white;
                    text-align: center;">
            <h2 style="margin: 0; color: white;">Welcome to the Boardroom Simulation</h2>
            <p style="margin: 0.5rem 0 0 0; opacity: 0.9;">
                {company_data['company_name']} — {module_data['module_name']}
            </p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("### Please identify yourself to begin")

        with st.form("student_id_form"):
            student_name = st.text_input(
                "Full Name",
                placeholder="e.g., Rahul Sharma",
                help="Enter your full name as it appears in your enrollment"
            )
            student_id = st.text_input(
                "Student ID / Roll Number",
                placeholder="e.g., STU-2026-001",
                help="Enter your student ID or roll number"
            )
            submitted = st.form_submit_button(
                "Continue to Simulation", type="primary", use_container_width=True
            )

            if submitted:
                if not student_name.strip() or not student_id.strip():
                    st.error("Please enter both your name and student ID.")
                else:
                    st.session_state.student_name = student_name.strip().title()
                    st.session_state.student_id = student_id.strip()
                    st.session_state.student_identified = True
                    st.rerun()

        return  # Block further rendering until identified

    # Get student name for personalization (empty string for admins)
    _student_first = st.session_state.get('student_name', '').split()[0] if st.session_state.get('student_name') else ''

    # Check for resumable session (only before simulation has started)
    if not st.session_state.get('simulation_started') and not st.session_state.get('player_role'):
        _s_name = st.session_state.get('student_name', '')
        _s_id = st.session_state.get('student_id', '')
        if _s_name and _s_id and not st.session_state.get('_resume_declined'):
            resumable = find_resumable_session(_s_name, _s_id, company_data['company_name'])
            if resumable and resumable.get('progress'):
                _prog = resumable['progress']
                st.info(f"You have an in-progress session (Round {_prog.get('current_round', 0) + 1}, checkpoint: {_prog.get('checkpoint', 'unknown')}). Would you like to resume?")
                _rc1, _rc2 = st.columns(2)
                with _rc1:
                    if st.button("Resume Session", type="primary"):
                        _restore_from_progress(resumable, company_data)
                        st.rerun()
                with _rc2:
                    if st.button("Start Fresh"):
                        clear_progress(resumable['session_id'])
                        st.session_state._resume_declined = True
                        st.rerun()
                return  # Block further rendering until choice is made

    # Validate player_role belongs to this simulation's board (guard against stale state)
    _stored_role = st.session_state.get('player_role')
    if _stored_role and not st.session_state.get('simulation_started'):
        _valid_names = [m['name'] for m in company_data.get('board_members', [])]
        if _stored_role.get('name') not in _valid_names:
            logger.warning(f"Stale player_role '{_stored_role.get('name')}' not in board. Clearing.")
            st.session_state.pop('player_role', None)

    # Main content area
    if not st.session_state.get('player_role'):
        # Initial dashboard
        _greeting = f", {_student_first}" if _student_first else ""
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #1E3A5F 0%, #2d5a8a 100%); padding: 1.5rem; border-radius: 12px; margin-bottom: 1.5rem; color: white;">
            <h2 style="margin: 0; color: white;">Welcome{_greeting}! Boardroom Simulation on "{module_data['module_name']}"</h2>
            <p style="margin: 0.5rem 0 0 0; opacity: 0.9; font-style: italic;">Engineered by Directors' Institute.</p>
        </div>
        """, unsafe_allow_html=True)

        # Module framing banner — tells the player exactly what's being tested before they start.
        # Pulled from module_data (populated by Agent 1's PDF extraction + Agent 2's enrichment).
        _module_subject  = module_data.get('subject_area') or module_data.get('module_name', '')
        _module_overview = (module_data.get('overview') or '').strip()
        _topic_names = [t.get('name', '') for t in module_data.get('topics', []) if t.get('name')][:6]
        _key_terms = list((module_data.get('key_terms') or {}).keys())[:8]
        _topic_chips = " · ".join(f"<span style='background:rgba(255,255,255,0.18); padding:0.2rem 0.55rem; border-radius:12px; font-size:0.82rem; display:inline-block; margin:0.15rem;'>{t}</span>" for t in _topic_names)
        _term_chips = " · ".join(f"<span style='background:rgba(255,255,255,0.10); padding:0.15rem 0.45rem; border-radius:10px; font-size:0.78rem; display:inline-block; margin:0.1rem;'>{t}</span>" for t in _key_terms)
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #2c3e50 0%, #4ca1af 100%); padding: 1.2rem 1.4rem; border-radius: 12px; margin-bottom: 1.5rem; color: white; border-left: 5px solid #ffc107;">
            <div style="font-size: 0.78rem; letter-spacing: 0.12em; opacity: 0.8; text-transform: uppercase;">📘 What this simulation tests</div>
            <div style="font-size: 1.15rem; font-weight: 600; margin-top: 0.3rem;">{module_data.get('module_name', 'Module')} {'— ' + _module_subject if _module_subject and _module_subject != module_data.get('module_name') else ''}</div>
            {f'<p style="margin: 0.6rem 0 0.4rem 0; opacity: 0.92; font-size: 0.9rem;">{_module_overview}</p>' if _module_overview else ''}
            {f'<div style="margin-top: 0.6rem;"><span style="font-size: 0.78rem; opacity: 0.75;">TOPICS:</span><br>{_topic_chips}</div>' if _topic_chips else ''}
            {f'<div style="margin-top: 0.6rem;"><span style="font-size: 0.78rem; opacity: 0.75;">KEY VOCABULARY YOU WILL BE SCORED ON:</span><br>{_term_chips}</div>' if _term_chips else ''}
            <p style="margin: 0.8rem 0 0 0; font-size: 0.82rem; opacity: 0.85;">
                Your score has two independent axes: <b>Decision Quality</b> (governance/legal/stakeholder/strategy/role)
                and <b>Module Application</b> (whether you invoked the vocabulary above by name or correct paraphrase).
            </p>
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
        _initial_scenario = company_data.get('initial_scenario', 'Scenario not available')
        st.markdown(f"""
        <div style="background: #fff3cd; padding: 1rem; border-radius: 10px; border-left: 4px solid #ffc107;">
            {_initial_scenario}
        </div>
        """, unsafe_allow_html=True)
        speak_button(_initial_scenario, label="Listen to Scenario", key="initial_scenario")

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
        key_metrics = {
            k: v for k, v in metrics.items()
            if str(v.get('priority') or '').strip().lower() in ('high', 'medium')
        }
        if not key_metrics:
            key_metrics = metrics
        key_metric_items = list(key_metrics.items())
        num_cols = min(len(key_metric_items), 4)
        if num_cols > 0:
            metric_cols = st.columns(num_cols)
            for idx, (key, metric) in enumerate(key_metric_items):
                with metric_cols[idx % num_cols]:
                    st.metric(metric.get('description', key),
                              f"{_fmt_val(metric.get('value', 0))} {metric.get('unit', '')}".rstrip())

        st.markdown("---")

        # Mission Objectives
        st.markdown("### 🎯 Mission Objectives")
        st.markdown(f"*Complete {simulation_config['total_rounds']} rounds of board decisions to achieve these targets:*")
        goal_cols = st.columns(3)
        for idx, goal in enumerate(game_goals[:6]):
            with goal_cols[idx % 3]:
                lower_better = goal.get('lower_is_better', False)
                arrow = "↓" if lower_better else "↑"
                _unit = goal['unit']
                _usep = "" if _unit.startswith('%') else " "
                current_display = f"{_fmt_val(goal['current'])}{_usep}{_unit}".rstrip()
                target_display = f"{_fmt_val(goal['target'])}{_usep}{_unit}".rstrip()
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
        st.markdown(f"### 👤 {_student_first + ', c' if _student_first else 'C'}hoose Your Board Role")
        st.markdown("Select which board member you want to play as during this simulation:")
        selected_role = display_board_members_for_selection(company_data['board_members'])
        if selected_role:
            # Clear any stale simulation state from previous sessions/roles
            _stale_keys = [k for k in st.session_state.keys()
                           if k.startswith(('scenario_round_', 'evaluation_', 'member_stances_',
                                            'pending_decision_', 'deliberation_phase_',
                                            'debate_history_', 'current_dissenter_',
                                            'round_start_time_', 'timer_expired_',
                                            'force_submitted_', 'selected_option_',
                                            'board_consultations_round_', 'committee_consultations_round_',
                                            'revisions_round_', 'impact_summary_',
                                            'board_effectiveness_'))]
            for k in _stale_keys:
                del st.session_state[k]
            st.session_state.pop('simulation_started', None)
            st.session_state.pop('current_round', None)
            st.session_state.pop('total_score', None)
            st.session_state.pop('round_summaries', None)
            st.session_state.pop('member_stance_histories', None)
            st.session_state.pop('board_effectiveness_history', None)
            st.session_state.pop('conversation_history', None)
            st.session_state.pop('current_metrics', None)
            st.session_state.pop('initial_metrics', None)
            st.session_state.pop('round_complete', None)
            st.session_state.player_role = selected_role
            st.rerun()

    elif not st.session_state.simulation_started:
        player_role = st.session_state.player_role
        _role_msg = f"✅ {_student_first}, you are playing as **{player_role['name']}** - {player_role['role']}" if _student_first else f"✅ You are playing as **{player_role['name']}** - {player_role['role']}"
        st.success(_role_msg)

        tab1, tab2, tab3 = st.tabs(["🏢 Company Overview", "👥 Board Members", "📚 Module Info"])

        with tab1:
            display_company_dashboard(company_data, player_role=player_role)
            st.markdown("---")
            display_current_problems(company_data['current_problems'])
            st.markdown("### 📋 Initial Scenario")
            st.markdown(f'<div class="scenario-box">{company_data["initial_scenario"]}</div>', unsafe_allow_html=True)
            speak_button(company_data["initial_scenario"], label="Listen to Scenario", key="initial_scenario_tab")

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

            _begin_label = f"✅ Let's Begin, {_student_first}!" if _student_first else "✅ I Understand, Let's Begin!"
            if st.button(_begin_label, type="primary", use_container_width=True):
                st.session_state.simulation_started = True
                st.session_state.current_round = 0
                st.session_state.total_score = 0
                st.session_state.conversation_history = []
                st.session_state.initial_metrics = {k: v.copy() for k, v in company_data['metrics'].items()}
                st.session_state.current_metrics = {k: v.copy() for k, v in company_data['metrics'].items()}
                st.session_state.metric_impact_reasons = {}

                # Track activity
                try:
                    sid = start_session(
                        student_name=st.session_state.get('student_name', 'Admin'),
                        student_id=st.session_state.get('student_id', 'admin'),
                        simulation_name=company_data['company_name'],
                        module_name=module_data['module_name'],
                        player_role=player_role.get('name', 'Unknown'),
                        total_rounds=simulation_config['total_rounds'],
                    )
                    st.session_state.activity_session_id = sid
                except Exception:
                    logger.warning("Failed to start activity tracking session")

                st.rerun()

        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            if st.button("🚀 Start Simulation", type="primary", use_container_width=True):
                show_disclaimer_dialog()

    elif st.session_state.current_round >= simulation_config['total_rounds']:
        # Clear saved progress — simulation is complete
        _act_sid = st.session_state.get('activity_session_id')
        if _act_sid and not st.session_state.get('_progress_cleared'):
            clear_progress(_act_sid)
            st.session_state._progress_cleared = True

        impact_reasons = st.session_state.get('metric_impact_reasons', {})
        display_sidebar_metrics(company_data, impact_reasons)
        display_final_summary(data)

    else:
        impact_reasons = st.session_state.get('metric_impact_reasons', {})
        display_sidebar_metrics(company_data, impact_reasons)

        # Inject beforeunload warning (once per session)
        if not st.session_state.get('_beforeunload_injected'):
            st.markdown("""<script>
                window.addEventListener('beforeunload', function(e) {
                    e.preventDefault();
                    e.returnValue = '';
                });
            </script>""", unsafe_allow_html=True)
            st.session_state._beforeunload_injected = True

        # Inject session timeout warning (fires at 25 minutes)
        if not st.session_state.get('_timeout_warning_injected'):
            st.markdown("""<script>
                if (!window._timeoutWarningSet) {
                    window._timeoutWarningSet = true;
                    setTimeout(function() {
                        var el = document.createElement('div');
                        el.style.cssText = 'position:fixed;top:0;left:0;right:0;background:#ff6b6b;color:white;padding:12px;text-align:center;z-index:9999;font-weight:bold;';
                        el.innerHTML = 'Session may expire soon due to inactivity. Please interact with the page to keep it alive.';
                        document.body.prepend(el);
                    }, 25 * 60 * 1000);
                }
            </script>""", unsafe_allow_html=True)
            st.session_state._timeout_warning_injected = True

        state = SimulationState(
            current_round=st.session_state.current_round,
            total_rounds=simulation_config['total_rounds']
        )

        eval_done = f"evaluation_{state.current_round}" in st.session_state
        rounds_done = state.current_round + 1 if eval_done else state.current_round
        progress = rounds_done / state.total_rounds
        st.progress(progress, text=f"Progress: {rounds_done}/{state.total_rounds} rounds completed")

        run_simulation_round(llm, data, state)
