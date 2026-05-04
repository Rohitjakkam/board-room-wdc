"""
Board deliberation phase UI — debate exchanges, stance tracking, force submit, revision.
"""

import logging
import streamlit as st
from typing import Dict, List

from core.models import SimulationState
from core.simulation_engine import generate_member_stances, evaluate_debate_response

logger = logging.getLogger(__name__)


def display_deliberation_phase(llm: object, data: Dict,
                                state: SimulationState, player_decision: str) -> bool:
    """
    Display and manage the board deliberation phase.
    Returns True if deliberation is complete, False if still in progress.
    """
    logger.debug(f"display_deliberation_phase called for round {state.current_round}")

    company_data = data['company_data']
    module_data = data['module_data']
    player_role = st.session_state.get('player_role')
    round_num = state.current_round

    if not player_role:
        logger.error("player_role not found in session state!")
        st.error("Error: Player role not found. Please restart the simulation.")
        return False

    # Session state keys for this round
    delib_phase_key = f"deliberation_phase_{round_num}"
    stances_key = f"member_stances_{round_num}"
    current_dissenter_key = f"current_dissenter_{round_num}"
    debate_history_key = f"debate_history_{round_num}"
    force_key = f"force_submitted_{round_num}"
    pending_decision_key = f"pending_decision_{round_num}"
    revision_key = f"revisions_round_{round_num}"

    if revision_key not in st.session_state:
        st.session_state[revision_key] = 0

    if delib_phase_key not in st.session_state:
        st.session_state[delib_phase_key] = 'inactive'
        logger.debug(f"Initialized delib_phase to 'inactive'")

    logger.debug(f"Current delib_phase: {st.session_state[delib_phase_key]}")

    # PHASE 1: Generate member stances (on first entry)
    if st.session_state[delib_phase_key] == 'inactive':
        logger.debug("Starting stance generation (phase: inactive -> generating)")
        st.session_state[delib_phase_key] = 'generating'
        st.session_state[debate_history_key] = []
        # Preserve force_submitted if already set True by timer expiry
        if force_key not in st.session_state:
            st.session_state[force_key] = False
        st.session_state[current_dissenter_key] = 0

        with st.spinner("Board members are reviewing your decision..."):
            scenario = st.session_state.get(f"scenario_round_{round_num}", "")
            all_member_histories = st.session_state.get('member_stance_histories', {})
            logger.debug(f"Generating stances for scenario length: {len(scenario)}, decision length: {len(player_decision)}")
            try:
                stances = generate_member_stances(llm, company_data, module_data,
                                                  scenario, player_decision, player_role,
                                                  all_member_histories=all_member_histories if all_member_histories else None)
                st.session_state[stances_key] = stances
                logger.debug(f"Generated {len(stances)} member stances")
            except Exception as e:
                logger.error(f"Error generating stances: {e}")
                st.error("Failed to generate board member stances. Please try again.")
                st.session_state[delib_phase_key] = 'inactive'
                return False

        st.session_state[delib_phase_key] = 'review'
        logger.debug("Stance generation complete, transitioning to review phase")
        st.rerun()

    # Get current state
    member_stances = st.session_state.get(stances_key, {})

    # Display section header — names the player as the proposer (closes feedback Issue 5)
    st.markdown("### 🏛️ Board Deliberation")
    st.markdown(f"""
    <div class="deliberation-header">
        <strong>You proposed this decision as {player_role.get('name', '')}
        ({player_role.get('role', '')}).</strong> The board is reviewing it now.
        Members will share their perspectives based on their expertise — engage the dissenters
        to either persuade them or move forward with their objections noted.
    </div>
    """, unsafe_allow_html=True)

    # Categorize members by stance
    approving = [(n, s) for n, s in member_stances.items() if s['stance'] == 'APPROVE']
    # Include CONVINCED so index-based current_dissenter tracking stays stable after stance flip.
    # IMPORTANT: this list is the canonical dissenter queue, computed deterministically once at
    # generate_member_stances time. Preserves insertion order (Python 3.7+) so dissenters
    # never "appear" mid-deliberation — they're always visible in the queue panel below.
    all_oppose = [(n, s) for n, s in member_stances.items() if s['stance'] in ('OPPOSE', 'CONVINCED')]
    opposing = [(n, s) for n, s in all_oppose if s.get('convinced_in_round') is None]
    neutral = [(n, s) for n, s in member_stances.items() if s['stance'] == 'NEUTRAL']
    convinced = [(n, s) for n, s in member_stances.items() if s.get('convinced_in_round') is not None]

    # Display summary counts
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Supporting", len(approving), delta_color="normal",
                  help="Board members who support your decision from the start.")
    with col2:
        st.metric("Opposing", len(opposing), delta_color="inverse",
                  help="Board members still opposing — engage them in debate to reduce their conviction or convert them.")
    with col3:
        st.metric("Neutral", len(neutral),
                  help="Board members without a strong stance either way.")
    with col4:
        st.metric("Convinced", len(convinced), delta_color="normal",
                  help="Initially-opposing members you fully turned to support. "
                       "Increments only when a member's stance flips (not just when their conviction drops). "
                       "Watch the per-member conviction bars below to see partial persuasion.")

    # Dissenter queue panel — addresses feedback E / Agent-W2 by surfacing the FULL
    # dissenter list from deliberation start. Previously, waiting dissenters were buried
    # in collapsed expanders, creating the illusion that a "third dissenter appeared
    # mid-deliberation" when the queue advanced past the second.
    if all_oppose:
        current_idx = st.session_state.get(current_dissenter_key, 0)
        total_d = len(all_oppose)
        queue_chips = []
        for idx, (name, stance) in enumerate(all_oppose):
            if stance.get('convinced_in_round') is not None:
                # Done — converted
                bg, fg, mark = "#d4edda", "#155724", "✓ "
            elif idx < current_idx:
                # Done — addressed (max exchanges or skipped)
                bg, fg, mark = "#e2e3e5", "#383d41", "◾ "
            elif idx == current_idx:
                # In progress
                bg, fg, mark = "#fff3cd", "#856404", "▶ "
            else:
                # Upcoming
                bg, fg, mark = "#f8d7da", "#721c24", ""
            queue_chips.append(
                f'<span style="background:{bg};color:{fg};padding:0.25rem 0.6rem;'
                f'border-radius:14px;font-size:0.82rem;margin:0.15rem;display:inline-block;">'
                f'{mark}[{idx + 1}/{total_d}] {name}</span>'
            )
        st.markdown(
            f'<div style="margin: 0.6rem 0;">'
            f'<small style="color:#666;">📋 <strong>Dissenter queue ({total_d} total)</strong> — '
            f'addressed in order. ▶ = current · ✓ = convinced · ◾ = previously addressed:</small><br>'
            f'{"".join(queue_chips)}'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # Display approving members
    if approving:
        st.markdown("**✅ Supporting your decision:**")
        for name, stance in approving:
            with st.expander(f"✅ {name} ({stance['member_role']}) - APPROVES"):
                st.markdown(f"*\"{stance['initial_reaction']}\"*")
                st.caption(f"**Expertise:** {stance['member_expertise']} | **Relevance:** {stance['expertise_relevance']}")

    # Display neutral members
    if neutral:
        st.markdown("**➖ Neutral:**")
        for name, stance in neutral:
            with st.expander(f"➖ {name} ({stance['member_role']}) - NEUTRAL"):
                st.markdown(f"*\"{stance['initial_reaction']}\"*")
                st.caption(f"**Expertise:** {stance['member_expertise']}")

    # Display convinced members
    if convinced:
        st.markdown("**🔄 Convinced during debate:**")
        for name, stance in convinced:
            with st.expander(f"🔄 {name} ({stance['member_role']}) - CONVINCED"):
                st.success(f"Convinced in debate round {stance['convinced_in_round']}")
                st.markdown(f"*Original objection:* {stance.get('original_counter_opinion', stance.get('counter_opinion', 'N/A'))}")

    # Display opposing members with debate interface
    if opposing:
        st.markdown("**⚠️ Opposing your decision:**")

        current_idx = st.session_state.get(current_dissenter_key, 0)

        for idx, (name, stance) in enumerate(all_oppose):
            conviction_pct = stance['conviction_level'] * 10
            is_current = (idx == current_idx)

            if is_current:
                st.markdown(f"""
                <div class="stance-card stance-oppose">
                    <h4>⚠️ {name} ({stance['member_role']}) - OPPOSES</h4>
                    <p><strong>Expertise:</strong> {stance['member_expertise']}</p>
                    <p><em>"{stance['initial_reaction']}"</em></p>
                    <div class="conviction-bar">
                        <div class="conviction-fill" style="width: {conviction_pct}%;"></div>
                    </div>
                    <small>Conviction Level: {stance['conviction_level']}/10</small>
                </div>
                """, unsafe_allow_html=True)

                exchanges = stance.get('debate_exchanges', 0)
                max_exchanges = 3

                if exchanges > 0:
                    st.markdown("##### 📜 Debate History")
                    member_history = [
                        h for h in st.session_state.get(debate_history_key, [])
                        if h.get('dissenter_name') == name
                    ]
                    for i, hist in enumerate(member_history, 1):
                        with st.container():
                            st.markdown(f"**Exchange {i}:**")
                            st.info(f"🎯 **{name}:** {hist.get('dissenter_argument', '')}")
                            st.success(f"💬 **Your response:** {hist.get('player_response', '')}")
                            if hist.get('llm_evaluation'):
                                st.caption(f"📊 Evaluation: {hist.get('llm_evaluation', '')}")
                    st.markdown("---")

                if exchanges > 0:
                    st.warning(f"**{name}'s Response:** {stance['counter_opinion']}")
                else:
                    st.warning(f"**Counter-opinion:** {stance['counter_opinion']}")

                if exchanges < max_exchanges:
                    st.markdown(f"#### 💬 Debate with {name} (Exchange {exchanges + 1} of {max_exchanges})")

                    response_key = f"debate_response_{round_num}_{name}_{exchanges}"

                    player_response = st.text_area(
                        f"Your response to {name}'s objection:",
                        key=response_key,
                        placeholder="Address their specific concerns and provide your reasoning...",
                        height=120
                    )

                    col1, col2 = st.columns([1, 2])
                    with col1:
                        _debate_processing = st.session_state.get(f"_processing_debate_{round_num}_{name}_{exchanges}", False)
                        _response_too_short = len((player_response or "").strip()) < 20
                        if _response_too_short and player_response:
                            st.caption("⚠️ Response must be at least 20 characters.")
                        if st.button(f"Submit Response", key=f"submit_debate_{round_num}_{name}_{exchanges}",
                                    type="primary", disabled=not player_response or _response_too_short or _debate_processing):
                            if player_response:
                                st.session_state[f"_processing_debate_{round_num}_{name}_{exchanges}"] = True
                                with st.spinner(f"{name} is considering your response..."):
                                    member_data = next(m for m in company_data['board_members']
                                                     if m['name'] == name)

                                    member_debate_history = [
                                        h for h in st.session_state.get(debate_history_key, [])
                                        if h.get('dissenter_name') == name
                                    ]

                                    try:
                                        result = evaluate_debate_response(
                                            llm, member_data, company_data,
                                            stance['counter_opinion'],
                                            player_response,
                                            member_debate_history,
                                            player_role
                                        )
                                    except Exception as e:
                                        logger.error(f"Debate evaluation failed for {name}: {e}")
                                        st.error("Failed to evaluate your response. Please try submitting again.")
                                        st.session_state.pop(f"_processing_debate_{round_num}_{name}_{exchanges}", None)
                                        return False

                                    exchange_record = {
                                        'dissenter_name': name,
                                        'dissenter_argument': stance['counter_opinion'],
                                        'player_response': player_response,
                                        'llm_evaluation': result['evaluation'],
                                        'response_score': result['score'],
                                        'stance_changed': result['stance_changed']
                                    }
                                    st.session_state[debate_history_key].append(exchange_record)

                                    st.session_state[stances_key][name]['debate_exchanges'] = exchanges + 1

                                    # Update conviction level dynamically
                                    if result.get('updated_conviction') is not None:
                                        st.session_state[stances_key][name]['conviction_level'] = result['updated_conviction']

                                    if result['stance_changed']:
                                        st.session_state[stances_key][name]['original_counter_opinion'] = stance['counter_opinion']
                                        st.session_state[stances_key][name]['convinced_in_round'] = exchanges + 1
                                        st.session_state[stances_key][name]['conviction_level'] = 0
                                        st.session_state[stances_key][name]['stance'] = 'CONVINCED'
                                        st.session_state[current_dissenter_key] = current_idx + 1
                                    else:
                                        st.session_state[stances_key][name]['counter_opinion'] = result['follow_up']

                                st.session_state.pop(f"_processing_debate_{round_num}_{name}_{exchanges}", None)
                                st.rerun()

                    with col2:
                        if st.button(f"Skip to Next Dissenter", key=f"skip_{round_num}_{name}"):
                            st.session_state[current_dissenter_key] = current_idx + 1
                            st.rerun()
                else:
                    st.warning(f"Maximum debate exchanges ({max_exchanges}) reached with {name}.")
                    if st.button(f"Move to Next Dissenter", key=f"move_next_{round_num}_{name}"):
                        st.session_state[current_dissenter_key] = current_idx + 1
                        st.rerun()
            elif stance.get('convinced_in_round') is None:
                with st.expander(f"⚠️ {name} ({stance['member_role']}) - OPPOSES (waiting)"):
                    st.markdown(f"*\"{stance['initial_reaction']}\"*")
                    st.caption(f"Conviction: {stance['conviction_level']}/10")

    # Check if all dissenters have been addressed (use all_oppose so convinced members don't shrink the target)
    all_addressed = (st.session_state.get(current_dissenter_key, 0) >= len(all_oppose))

    st.markdown("---")

    # Resolution options
    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        if len(opposing) == 0 or all_addressed:
            if len(opposing) == 0:
                st.success("✅ All board members support your decision!")
                if st.button("✓ Proceed with Decision", key=f"proceed_{round_num}", type="primary",
                            use_container_width=True):
                    logger.debug("Proceed with Decision clicked - no opposition")
                    st.session_state[delib_phase_key] = 'resolved'
                    st.rerun()
            else:
                remaining_opposed = sum(1 for n, s in member_stances.items()
                                       if s['stance'] == 'OPPOSE' and s.get('convinced_in_round') is None)
                if remaining_opposed > 0:
                    st.warning(f"⚠️ {remaining_opposed} board member(s) still oppose after debate.")

                    revision_used = st.session_state.get(revision_key, 0) >= 1

                    col_proceed, col_revise = st.columns(2)
                    with col_proceed:
                        if st.button("✓ Proceed Anyway", key=f"proceed_{round_num}", type="primary",
                                    use_container_width=True):
                            logger.debug("Proceed with Decision clicked despite opposition")
                            st.session_state[delib_phase_key] = 'resolved'
                            st.rerun()
                    with col_revise:
                        if revision_used:
                            st.warning("✏️ Revision already used this round")
                        else:
                            if st.button("✏️ Revise Decision", key=f"revise_{round_num}",
                                        help="Go back and modify your decision (1 revision per round)",
                                        use_container_width=True):
                                logger.debug("Revise Decision clicked")
                                st.session_state[revision_key] = st.session_state.get(revision_key, 0) + 1
                                for k in [pending_decision_key, delib_phase_key, stances_key,
                                          current_dissenter_key, debate_history_key]:
                                    if k in st.session_state:
                                        del st.session_state[k]
                                st.session_state.pop(f"_processing_submit_{round_num}", None)
                                st.session_state.pop(f"_force_confirm_{round_num}", None)
                                st.session_state.pop(f"_processing_force_{round_num}", None)
                                st.rerun()
                else:
                    st.success("✅ All dissenters have been convinced!")
                    if st.button("✓ Proceed with Decision", key=f"proceed_{round_num}", type="primary",
                                use_container_width=True):
                        logger.debug("Proceed with Decision clicked")
                        st.session_state[delib_phase_key] = 'resolved'
                        st.rerun()
        else:
            remaining = len(all_oppose) - st.session_state.get(current_dissenter_key, 0)
            st.info(f"📋 {remaining} dissenter(s) remaining to address.")

        remaining_opposed_check = sum(1 for n, s in member_stances.items()
                                      if s['stance'] == 'OPPOSE' and s.get('convinced_in_round') is None)

        has_opposition = remaining_opposed_check > 0 or not all_addressed

        if has_opposition:
            st.markdown("---")
            show_revise_here = not (all_addressed and remaining_opposed_check > 0)

            if show_revise_here:
                col_force, col_revise_alt = st.columns(2)
            else:
                col_force = st.container()
                col_revise_alt = None

            with col_force:
                _force_confirm_key = f"_force_confirm_{round_num}"
                _force_confirmed = st.session_state.get(_force_confirm_key, False)
                _force_processing = st.session_state.get(f"_processing_force_{round_num}", False)

                if not _force_confirmed:
                    if st.button("⚡ Force Submit", key=f"force_submit_{round_num}",
                                help="Submit without full board approval (scoring penalty applies)",
                                use_container_width=True):
                        st.session_state[_force_confirm_key] = True
                        st.rerun()
                else:
                    st.warning("⚠️ Force submitting will apply a scoring penalty. Are you sure?")
                    col_yes, col_no = st.columns(2)
                    with col_yes:
                        if st.button("Yes, Force Submit", key=f"force_confirm_yes_{round_num}",
                                    type="primary", use_container_width=True, disabled=_force_processing):
                            st.session_state[f"_processing_force_{round_num}"] = True
                            logger.debug("Force Submit confirmed")
                            st.session_state[force_key] = True
                            st.session_state[delib_phase_key] = 'resolved'
                            st.rerun()
                    with col_no:
                        if st.button("Cancel", key=f"force_confirm_no_{round_num}",
                                    use_container_width=True):
                            st.session_state[_force_confirm_key] = False
                            st.rerun()

            if show_revise_here and col_revise_alt:
                with col_revise_alt:
                    revision_used_alt = st.session_state.get(revision_key, 0) >= 1
                    if revision_used_alt:
                        st.warning("✏️ Revision already used")
                    else:
                        if st.button("✏️ Revise Decision", key=f"revise_alt_{round_num}",
                                    help="Go back and modify your decision (1 revision per round)",
                                    use_container_width=True):
                            logger.debug("Revise Decision (alt) clicked")
                            st.session_state[revision_key] = st.session_state.get(revision_key, 0) + 1
                            for k in [pending_decision_key, delib_phase_key, stances_key,
                                      current_dissenter_key, debate_history_key]:
                                if k in st.session_state:
                                    del st.session_state[k]
                            st.session_state.pop(f"_processing_submit_{round_num}", None)
                            st.session_state.pop(f"_force_confirm_{round_num}", None)
                            st.session_state.pop(f"_processing_force_{round_num}", None)
                            st.rerun()

    is_resolved = st.session_state.get(delib_phase_key) == 'resolved'
    logger.debug(f"Deliberation phase returning: {is_resolved}")
    return is_resolved
