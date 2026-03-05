"""
Final summary, board effectiveness, and grade display components.
"""

import urllib.parse

import streamlit as st
from typing import Dict

import logging
from core.scoring import calculate_overall_grade, calculate_goal_progress
from core.activity_tracker import complete_session

_logger = logging.getLogger(__name__)


def display_board_effectiveness_summary(total_rounds: int):
    """Display the board effectiveness score in the final summary."""
    st.markdown("### 🏛️ Board Effectiveness Performance")

    effectiveness_history = st.session_state.get("board_effectiveness_history", [])

    if not effectiveness_history:
        st.info("No board effectiveness data available.")
        return 0

    total_score = sum(r['deliberation_score'] for r in effectiveness_history)
    avg_score = total_score / len(effectiveness_history)

    if avg_score >= 80:
        grade, grade_color, grade_desc = "A", "#28a745", "Excellent Board Management"
    elif avg_score >= 60:
        grade, grade_color, grade_desc = "B", "#5cb85c", "Good Board Management"
    elif avg_score >= 40:
        grade, grade_color, grade_desc = "C", "#ffc107", "Fair Board Management"
    else:
        grade, grade_color, grade_desc = "D", "#dc3545", "Needs Improvement"

    st.markdown(f"""
    <div style="text-align: center; padding: 1.5rem; background: linear-gradient(135deg, #f0f7ff 0%, #e6f0ff 100%); border-radius: 10px; margin-bottom: 1rem;">
        <h2 style="color: {grade_color}; margin: 0;">Board Effectiveness: {grade}</h2>
        <p style="color: #666; font-size: 1.1rem;">{grade_desc}</p>
        <p style="color: #333;">Average Score: {avg_score:.1f}/100</p>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3, col4 = st.columns(4)

    total_convinced = sum(r.get('members_convinced', 0) for r in effectiveness_history)
    total_force_submits = sum(1 for r in effectiveness_history if r.get('force_submitted', False))
    total_debates = sum(r.get('total_debate_exchanges', 0) for r in effectiveness_history)
    total_opposing = sum(r.get('members_initially_opposing', 0) for r in effectiveness_history)

    with col1:
        st.metric("Dissenters Convinced", total_convinced,
                 delta=f"of {total_opposing}" if total_opposing > 0 else None)
    with col2:
        st.metric("Force Submits", total_force_submits,
                 delta_color="inverse" if total_force_submits > 0 else "normal")
    with col3:
        st.metric("Debate Exchanges", total_debates)
    with col4:
        avg_alignment = sum(r.get('consultation_alignment_score', 50) for r in effectiveness_history) / len(effectiveness_history)
        st.metric("Avg Consultation Alignment", f"{avg_alignment:.0f}%")

    with st.expander("📊 Round-by-Round Board Effectiveness", expanded=False):
        for round_data in effectiveness_history:
            score = round_data.get('deliberation_score', 0)
            score_color = "#28a745" if score >= 70 else "#ffc107" if score >= 50 else "#dc3545"

            st.markdown(f"""
            **Round {round_data.get('round_number', 0) + 1}:**
            <span style="color: {score_color}; font-weight: bold;">{score}/100</span>
            """, unsafe_allow_html=True)

            breakdown = round_data.get('score_breakdown', {})
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.caption(f"Initial Approval: {breakdown.get('initial_approval', 0)}/25")
            with col2:
                st.caption(f"Consultation: {breakdown.get('consultation', 0)}/25")
            with col3:
                st.caption(f"Debate: {breakdown.get('debate_effectiveness', 0)}/30")
            with col4:
                st.caption(f"Efficiency: {breakdown.get('efficiency', 0)}/20")

            approving = round_data.get('members_initially_approving', 0)
            opposing = round_data.get('members_initially_opposing', 0)
            convinced = round_data.get('members_convinced', 0)

            st.caption(f"👍 {approving} approved | 👎 {opposing} opposed | 🔄 {convinced} convinced")

            if round_data.get('force_submitted', False):
                st.warning("⚠️ Decision was force-submitted")
            st.markdown("---")

    return avg_score


def display_final_summary(data: Dict):
    """Display final simulation summary."""
    _student_name = st.session_state.get('student_name', '')
    _student_id = st.session_state.get('student_id', '')

    if _student_name:
        st.markdown(f"## 🎉 Well Done, {_student_name.split()[0]}! Simulation Complete!")
    else:
        st.markdown("## 🎉 Simulation Complete!")

    player_role = st.session_state.get('player_role', {})
    st.markdown(f"**You played as:** {player_role.get('name', 'Unknown')} - {player_role.get('role', 'Unknown')}")
    if _student_name:
        st.markdown(f"**Student:** {_student_name} &nbsp;|&nbsp; **ID:** {_student_id}")

    total_score = st.session_state.get('total_score', 0)
    rounds_completed = st.session_state.get('current_round', 0)
    avg_score = total_score / max(rounds_completed, 1)

    initial_metrics = st.session_state.get('initial_metrics', data['company_data']['metrics'])
    final_metrics = st.session_state.get('current_metrics', data['company_data']['metrics'])

    effectiveness_history = st.session_state.get("board_effectiveness_history", [])
    avg_board_effectiveness = None
    if effectiveness_history:
        avg_board_effectiveness = sum(r['deliberation_score'] for r in effectiveness_history) / len(effectiveness_history)

    grade_info = calculate_overall_grade(initial_metrics, final_metrics, avg_score, avg_board_effectiveness)

    # Track completion
    _act_sid = st.session_state.get('activity_session_id')
    if _act_sid and not st.session_state.get('_activity_completed'):
        try:
            complete_session(
                session_id=_act_sid,
                final_score=grade_info['final_score'],
                grade=grade_info['grade'],
                grade_description=grade_info.get('grade_description', ''),
                metrics_improved=grade_info.get('metrics_improved', 0),
                metrics_declined=grade_info.get('metrics_declined', 0),
            )
            st.session_state._activity_completed = True
        except Exception:
            _logger.warning("Failed to log simulation completion")

    grade_color = {
        'A+': '#28a745', 'A': '#28a745', 'A-': '#5cb85c',
        'B+': '#8bc34a', 'B': '#9acd32', 'B-': '#cddc39',
        'C+': '#ffc107', 'C': '#ff9800', 'C-': '#ff5722',
        'D': '#f44336', 'F': '#d32f2f'
    }.get(grade_info['grade'], '#666')

    _name_line = f'<p style="color: #555; font-size: 1rem; margin: 0.3rem 0;">{_student_name} ({_student_id})</p>' if _student_name else ''
    st.markdown(f"""
    <div style="text-align: center; padding: 2rem; background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%); border-radius: 15px; margin-bottom: 2rem;">
        {_name_line}
        <h1 style="color: {grade_color}; font-size: 4rem; margin: 0;">{grade_info['grade']}</h1>
        <h3 style="color: #333; margin: 0.5rem 0;">{grade_info['grade_description']}</h3>
        <p style="color: #666; font-size: 1.2rem;">Overall Score: {grade_info['final_score']:.1f}/100</p>
    </div>
    """, unsafe_allow_html=True)

    # Goal Achievement
    if 'game_goals' in st.session_state:
        st.markdown("### 🎯 Mission Objectives - Final Results")

        goal_progress = calculate_goal_progress(st.session_state.game_goals, final_metrics)
        achieved_count = sum(1 for g in goal_progress if g.get('achieved', False))
        total_goals = len(goal_progress)

        achievement_pct = (achieved_count / total_goals * 100) if total_goals > 0 else 0

        if achievement_pct >= 80:
            achievement_color, achievement_msg = "#28a745", "Outstanding! You exceeded expectations!"
        elif achievement_pct >= 50:
            achievement_color, achievement_msg = "#ffc107", "Good progress! Some goals need more attention."
        else:
            achievement_color, achievement_msg = "#dc3545", "Keep practicing! Many goals were not achieved."

        st.markdown(f"""
        <div style="text-align: center; padding: 1rem; background: linear-gradient(135deg, #e8f5e9 0%, #c8e6c9 100%); border-radius: 10px; margin-bottom: 1rem; border: 2px solid {achievement_color};">
            <h2 style="color: {achievement_color}; margin: 0;">{achieved_count}/{total_goals} Goals Achieved</h2>
            <p style="color: #666; margin: 0.5rem 0 0 0;">{achievement_msg}</p>
        </div>
        """, unsafe_allow_html=True)

        goal_cols = st.columns(3)
        for idx, goal in enumerate(goal_progress):
            with goal_cols[idx % 3]:
                achieved = goal.get('achieved', False)
                progress = goal.get('progress_pct', 0)
                current_val = goal.get('current_value', goal['current'])
                start_val = goal['current']
                target_val = goal['target']
                unit = goal['unit']

                if achieved:
                    status_icon, bg_color, border_color = "✅", "#d4edda", "#28a745"
                elif progress >= 50:
                    status_icon, bg_color, border_color = "🔶", "#fff3cd", "#ffc107"
                else:
                    status_icon, bg_color, border_color = "❌", "#f8d7da", "#dc3545"

                st.markdown(f"""
                <div style="background: {bg_color}; padding: 0.8rem; border-radius: 8px; border-left: 4px solid {border_color}; margin-bottom: 0.5rem;">
                    <div style="font-weight: 600;">{status_icon} {goal['name']}</div>
                    <div style="font-size: 0.85rem; color: #666; margin: 0.3rem 0;">
                        Start: {start_val}{unit} → Final: {current_val}{unit}
                    </div>
                    <div style="font-size: 0.85rem;">
                        Target: <strong>{target_val}{unit}</strong> | Progress: <strong>{progress:.0f}%</strong>
                    </div>
                </div>
                """, unsafe_allow_html=True)

        st.markdown("---")

    # Score breakdown
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Rounds Completed", rounds_completed)
    with col2:
        st.metric("Decision Score", f"{avg_score:.1f}/100")
    with col3:
        st.metric("Metrics Improved", f"{grade_info['metrics_improved']}", delta=f"+{grade_info['metrics_improved']}")
    with col4:
        st.metric("Metrics Declined", f"{grade_info['metrics_declined']}", delta=f"-{grade_info['metrics_declined']}", delta_color="inverse")

    # Score composition
    st.markdown("### 📊 Score Composition")
    if avg_board_effectiveness is not None:
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown(f"**Decision Quality (50%):** {grade_info['decision_score_component']:.1f} pts\n*Based on your choices across {rounds_completed} rounds*")
        with col2:
            st.markdown(f"**Business Impact (30%):** {grade_info['metric_score_component']:.1f} pts\n*Based on metric improvements: {grade_info['normalized_metric_score']:.1f}/100*")
        with col3:
            st.markdown(f"**Board Effectiveness (20%):** {grade_info['board_effectiveness_component']:.1f} pts\n*Based on board management: {avg_board_effectiveness:.1f}/100*")
    else:
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**Decision Quality (60%):** {grade_info['decision_score_component']:.1f} pts\n*Based on your choices across {rounds_completed} rounds*")
        with col2:
            st.markdown(f"**Business Impact (40%):** {grade_info['metric_score_component']:.1f} pts\n*Based on metric improvements: {grade_info['normalized_metric_score']:.1f}/100*")

    # Board Effectiveness Summary
    if effectiveness_history:
        display_board_effectiveness_summary(rounds_completed)

    # Metrics Before vs After
    st.markdown("### 📈 Metrics Comparison: Before vs After Simulation")

    # Dynamically categorize metrics from actual data (not hardcoded keys)
    CATEGORY_MAP = {
        'revenue': '💰 Financial', 'profit': '💰 Financial', 'ebitda': '💰 Financial',
        'margin': '💰 Financial', 'growth': '💰 Financial', 'debt': '💰 Financial',
        'burn': '💰 Financial', 'cost': '💰 Financial',
        'customer': '👥 Customer', 'churn': '👥 Customer', 'promoter': '👥 Customer',
        'satisfaction': '👥 Customer', 'retention': '👥 Customer', 'lifetime': '👥 Customer',
        'acquisition': '👥 Customer',
        'employee': '👔 Human Resources', 'engagement': '👔 Human Resources',
        'attrition': '👔 Human Resources', 'headcount': '👔 Human Resources',
        'training': '👔 Human Resources', 'turnover': '👔 Human Resources',
        'uptime': '⚙️ Operations', 'deployment': '⚙️ Operations',
        'incident': '⚙️ Operations', 'automation': '⚙️ Operations',
        'latency': '⚙️ Operations', 'platform': '⚙️ Operations',
        'risk': '🛡️ Risk & Compliance', 'compliance': '🛡️ Risk & Compliance',
        'regulatory': '🛡️ Risk & Compliance', 'privacy': '🛡️ Risk & Compliance',
        'severity': '🛡️ Risk & Compliance',
    }

    LOWER_IS_BETTER_KEYWORDS = {'churn', 'attrition', 'risk', 'debt', 'turnover',
                                 'cost', 'defect', 'burn', 'incident', 'latency'}

    # Build dynamic categories from actual metric keys
    metric_categories = {}
    for key in initial_metrics:
        if key not in final_metrics:
            continue
        key_lower = key.lower()
        category = '📊 General'
        for kw, cat in CATEGORY_MAP.items():
            if kw in key_lower:
                category = cat
                break
        metric_categories.setdefault(category, []).append(key)

    for category, metric_keys in metric_categories.items():
        with st.expander(category, expanded=True):
            for key in metric_keys:
                if key in initial_metrics and key in final_metrics:
                    initial = initial_metrics[key]
                    final = final_metrics[key]

                    try:
                        initial_val = float(initial.get('value') or 0)
                    except (TypeError, ValueError):
                        initial_val = 0
                    try:
                        final_val = float(final.get('value') or 0)
                    except (TypeError, ValueError):
                        final_val = 0
                    change = final_val - initial_val

                    if initial_val != 0:
                        pct_change = ((final_val - initial_val) / abs(initial_val)) * 100
                    elif final_val != 0:
                        pct_change = 100.0  # Any change from zero = 100%
                    else:
                        pct_change = 0  # 0 → 0 = no change

                    is_inverse = any(kw in key.lower() for kw in LOWER_IS_BETTER_KEYWORDS)
                    is_improvement = (change < 0 if is_inverse else change > 0)
                    is_decline = (change > 0 if is_inverse else change < 0)

                    unit = initial.get('unit', '')

                    col1, col2, col3, col4 = st.columns([3, 2, 2, 2])

                    with col1:
                        priority_badge = "🔴 " if initial.get('priority') == 'High' else ""
                        st.markdown(f"**{priority_badge}{initial.get('description', key)}**")
                    with col2:
                        st.markdown(f"Before: `{initial_val} {unit}`")
                    with col3:
                        st.markdown(f"After: `{final_val} {unit}`")
                    with col4:
                        if change != 0:
                            change_str = f"{change:+.1f}" if isinstance(change, float) else f"{change:+d}"
                            pct_str = f"({pct_change:+.1f}%)"
                            if is_improvement:
                                st.markdown(f"✅ {change_str} {pct_str}")
                            elif is_decline:
                                st.markdown(f"⚠️ {change_str} {pct_str}")
                            else:
                                st.markdown(f"➡️ {change_str} {pct_str}")
                        else:
                            st.markdown("➡️ No change")

    # Performance assessment
    metrics_worse = grade_info['metrics_declined'] > grade_info['metrics_improved']

    if avg_score >= 80 and not metrics_worse:
        performance, assessment_color, assessment_border = "Excellent! You demonstrated strong understanding of corporate governance and made decisions that positively impacted the business.", "#d4edda", "#28a745"
    elif avg_score >= 70 and not metrics_worse:
        performance, assessment_color, assessment_border = "Good performance. You showed solid governance understanding with room for improvement in some areas.", "#d4edda", "#28a745"
    elif avg_score >= 60:
        performance, assessment_color, assessment_border = "Adequate performance. Your decisions showed basic understanding but missed important considerations. Review the best approaches for each round.", "#fff3cd", "#ffc107"
    elif avg_score >= 45:
        performance, assessment_color, assessment_border = "Below average performance. Many of your decisions did not align with governance best practices. Significant improvement is needed.", "#f8d7da", "#dc3545"
    else:
        performance, assessment_color, assessment_border = "Poor performance. Your decisions showed fundamental gaps in governance understanding. You should revisit the module materials.", "#f8d7da", "#dc3545"

    if metrics_worse and avg_score < 70:
        performance += f" Additionally, your decisions resulted in more metrics declining ({grade_info['metrics_declined']}) than improving ({grade_info['metrics_improved']}), indicating negative business impact."

    st.markdown(f"""
    <div style="background: {assessment_color}; padding: 1rem; border-radius: 10px; border-left: 4px solid {assessment_border}; margin: 1rem 0;">
        <h3 style="margin-top: 0;">Performance Assessment</h3>
        <p style="margin-bottom: 0;">{performance}</p>
    </div>
    """, unsafe_allow_html=True)

    # Round-by-Round Summary
    st.markdown("### 🎯 Round-by-Round Performance Review")
    st.markdown("*Review your decisions, scores, and see what the best approach would have been for each scenario.*")

    for round_num in range(rounds_completed):
        eval_key = f"evaluation_{round_num}"
        scenario_key = f"scenario_round_{round_num}"

        if eval_key in st.session_state:
            evaluation = st.session_state[eval_key]
            scenario = st.session_state.get(scenario_key, "Scenario not available")
            rounds_list = data.get('simulation_config', {}).get('rounds', [])
            round_config = rounds_list[round_num] if round_num < len(rounds_list) else {}

            round_score = evaluation.get('score', 0)
            score_color = "#28a745" if round_score >= 70 else "#ffc107" if round_score >= 50 else "#dc3545"
            score_emoji = "🟢" if round_score >= 70 else "🟡" if round_score >= 50 else "🔴"

            with st.expander(f"{score_emoji} Round {round_num + 1}: Score {round_score}/100 | Difficulty: {round_config.get('difficulty', 'N/A').title()}", expanded=False):
                st.markdown(f"""
                <div style="background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%); padding: 1rem; border-radius: 10px; margin-bottom: 1rem;">
                    <strong>Focus Area:</strong> {round_config.get('focus_area', 'General')}<br>
                    <strong>Time Pressure:</strong> {round_config.get('time_pressure', 'normal').title()}<br>
                    <strong>Your Score:</strong> <span style="color: {score_color}; font-weight: bold;">{round_score}/100</span>
                </div>
                """, unsafe_allow_html=True)

                st.markdown("#### 📋 Scenario Presented")
                with st.container():
                    st.markdown(f"""
                    <div style="background: #fff3cd; padding: 1rem; border-radius: 8px; border-left: 4px solid #ffc107; max-height: 400px; overflow-y: auto;">
                        {scenario}
                    </div>
                    """, unsafe_allow_html=True)

                # Time taken for this round
                round_start = st.session_state.get(f"round_start_time_{round_num}")
                decision_time = st.session_state.get(f"decision_submit_time_{round_num}")
                if round_start and decision_time:
                    elapsed = (decision_time - round_start).total_seconds()
                    minutes, seconds = divmod(int(elapsed), 60)
                    st.caption(f"Time taken: {minutes}m {seconds}s")

                st.markdown("#### 🎯 Your Decision")
                decision_text = evaluation.get('decision', 'Decision not recorded')
                st.markdown(f"""
                <div style="background: #e3f2fd; padding: 1rem; border-radius: 8px; border-left: 4px solid #2196f3;">
                    {decision_text}
                </div>
                """, unsafe_allow_html=True)

                if evaluation.get('score_reasoning'):
                    st.markdown("#### 📊 Score Breakdown")
                    st.markdown(evaluation['score_reasoning'])

                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("#### ✅ What You Did Well")
                    if evaluation.get('strengths'):
                        st.success(evaluation['strengths'])
                    else:
                        st.info("No specific strengths recorded")
                with col2:
                    st.markdown("#### 🔧 Areas for Improvement")
                    if evaluation.get('improvements'):
                        st.warning(evaluation['improvements'])
                    else:
                        st.info("No specific improvements recorded")

                if evaluation.get('critical_feedback'):
                    st.markdown("#### ⚠️ Critical Feedback")
                    st.error(evaluation['critical_feedback'])
                elif evaluation.get('encouragement'):
                    st.markdown("#### 🌟 Encouragement")
                    st.success(evaluation['encouragement'])

                st.markdown("#### 💡 Recommended Best Approach")
                if evaluation.get('best_approach'):
                    st.markdown(f"""
                    <div style="background: linear-gradient(135deg, #d4edda 0%, #c3e6cb 100%); padding: 1.5rem; border-radius: 10px; border: 2px solid #28a745;">
                        <strong style="color: #155724;">What would have been the ideal decision:</strong><br><br>
                        {evaluation['best_approach']}
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.info("Best approach recommendation not available")

                if evaluation.get('learning_points'):
                    st.markdown("#### 📚 Key Learning Points")
                    st.info(evaluation['learning_points'])

                impact_summary = st.session_state.get(f"impact_summary_{round_num}", "")
                if impact_summary:
                    st.markdown("#### 📈 Business Impact from This Decision")
                    st.markdown(impact_summary)

                # Activity stats for this round
                board_consults = st.session_state.get(f"board_consultations_round_{round_num}", 0)
                committee_consults = st.session_state.get(f"committee_consultations_round_{round_num}", 0)
                revisions = st.session_state.get(f"revisions_round_{round_num}", 0)
                force_submitted = st.session_state.get(f"force_submitted_{round_num}", False)
                round_effectiveness = st.session_state.get(f"board_effectiveness_{round_num}", {})

                activity_parts = []
                if board_consults:
                    activity_parts.append(f"**{board_consults}** board consultation(s)")
                if committee_consults:
                    activity_parts.append(f"**{committee_consults}** committee consultation(s)")
                if revisions:
                    activity_parts.append(f"**{revisions}** decision revision(s)")
                if round_effectiveness:
                    convinced = round_effectiveness.get('members_convinced', 0)
                    total_d = round_effectiveness.get('members_initially_opposing', 0)
                    debate_ex = round_effectiveness.get('total_debate_exchanges', 0)
                    if total_d:
                        activity_parts.append(f"**{convinced}/{total_d}** dissenters convinced")
                    if debate_ex:
                        activity_parts.append(f"**{debate_ex}** debate exchange(s)")
                if force_submitted:
                    activity_parts.append("decision was **force-submitted**")

                if activity_parts:
                    st.markdown("#### 🗣️ Round Activity")
                    st.markdown(" | ".join(activity_parts))

                # Board member stances summary
                member_stances = st.session_state.get(f"member_stances_{round_num}", {})
                if member_stances:
                    st.markdown("#### 🏛️ Board Member Reactions")
                    stance_lines = []
                    for name, info in member_stances.items():
                        stance = info.get('stance', 'NEUTRAL')
                        icon = {"APPROVE": "👍", "OPPOSE": "👎", "NEUTRAL": "🤔"}.get(stance, "🤔")
                        convinced_note = ""
                        if info.get('convinced_in_round') is not None:
                            convinced_note = " → ✅ Convinced"
                        stance_lines.append(f"- {icon} **{name}** ({info.get('member_role', '')}) — {stance}{convinced_note}")
                    st.markdown("\n".join(stance_lines))

                st.markdown("---")

    # Consultation history summary
    conversation_history = st.session_state.get('conversation_history', [])
    if conversation_history:
        st.markdown("### 💬 Consultation History")
        st.markdown("*All questions you asked board members and committees during the simulation.*")
        user_questions = [msg for msg in conversation_history if msg.get('role') == 'user']
        if user_questions:
            with st.expander(f"View all {len(user_questions)} consultation(s)", expanded=False):
                for msg in conversation_history:
                    if msg.get('role') == 'user':
                        st.markdown(f"**You asked ({msg.get('member', 'Unknown')}):** {msg.get('content', '')}")
                    elif msg.get('role') == 'assistant':
                        st.markdown(f"> {msg.get('content', '')}")
                        st.markdown("---")

    # Key concepts
    module_data = data['module_data']
    st.markdown("### 📚 Key Concepts Covered")

    for topic in module_data['topics'][:5]:
        with st.expander(topic['name']):
            st.markdown(topic['description'])
            if topic.get('key_principles'):
                st.markdown("**Key Principles:**")
                for principle in topic['key_principles']:
                    st.markdown(f"- {principle}")

    # ============ SHARE ACHIEVEMENT ============
    st.markdown("---")
    st.markdown("### 🏆 Share Your Achievement")

    _company = data['company_data'].get('company_name', 'a company')
    _module = data['module_data'].get('module_name', 'Corporate Governance')
    _grade = grade_info['grade']
    _score = f"{grade_info['final_score']:.0f}"
    _name_tag = f"{_student_name} | " if _student_name else ""

    _rounds_done = rounds_completed
    _goals_achieved = 0
    _total_goals = 0
    if 'game_goals' in st.session_state:
        _goal_progress = calculate_goal_progress(
            st.session_state.game_goals, final_metrics
        )
        _total_goals = len(_goal_progress)
        _goals_achieved = sum(1 for g in _goal_progress if g.get('achieved'))

    _share_text = (
        f"I just completed a Board Room Simulation on \"{_module}\" "
        f"for {_company} and earned a Grade {_grade} ({_score}/100)!\n\n"
        f"📊 {_rounds_done} rounds completed"
    )
    if _total_goals:
        _share_text += f" | 🎯 {_goals_achieved}/{_total_goals} goals achieved"
    if avg_board_effectiveness and avg_board_effectiveness > 0:
        _share_text += f" | 🏛️ Board effectiveness: {avg_board_effectiveness:.0f}%"
    _share_text += (
        f"\n\nSharpening my corporate governance & decision-making skills. "
        f"#BoardRoomSimulation #CorporateGovernance #Leadership"
    )

    # Show preview of the message
    st.markdown(f"""
    <div style="background: #f8f9fa; padding: 1rem; border-radius: 8px; border: 1px solid #dee2e6; margin-bottom: 1rem;">
        <p style="margin: 0; color: #495057; white-space: pre-line;">{_share_text}</p>
    </div>
    """, unsafe_allow_html=True)

    _encoded = urllib.parse.quote(_share_text)

    _linkedin_url = f"https://www.linkedin.com/feed/?shareActive=true&text={_encoded}"
    _twitter_url = f"https://twitter.com/intent/tweet?text={_encoded}"
    _whatsapp_url = f"https://wa.me/?text={_encoded}"

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown(f"""
        <a href="{_linkedin_url}" target="_blank" style="text-decoration: none;">
            <div style="background: #0077B5; color: white; padding: 0.7rem 1rem; border-radius: 8px;
                        text-align: center; font-weight: 600; cursor: pointer;">
                🔗 LinkedIn
            </div>
        </a>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown(f"""
        <a href="{_twitter_url}" target="_blank" style="text-decoration: none;">
            <div style="background: #1DA1F2; color: white; padding: 0.7rem 1rem; border-radius: 8px;
                        text-align: center; font-weight: 600; cursor: pointer;">
                𝕏 Twitter
            </div>
        </a>
        """, unsafe_allow_html=True)

    with col3:
        st.markdown(f"""
        <a href="{_whatsapp_url}" target="_blank" style="text-decoration: none;">
            <div style="background: #25D366; color: white; padding: 0.7rem 1rem; border-radius: 8px;
                        text-align: center; font-weight: 600; cursor: pointer;">
                💬 WhatsApp
            </div>
        </a>
        """, unsafe_allow_html=True)

    with col4:
        if st.button("📋 Copy Text", use_container_width=True):
            st.code(_share_text, language=None)
            st.success("Copy the text above!")

    st.markdown("")

    if st.button("Start New Simulation"):
        preserve_keys = {
            'api_key', 'selected_doc_id', '_sim_pages',
            'user_role', 'admin_authenticated',
            'student_name', 'student_id', 'student_identified',
        }
        for key in list(st.session_state.keys()):
            if key not in preserve_keys:
                del st.session_state[key]
        st.rerun()
