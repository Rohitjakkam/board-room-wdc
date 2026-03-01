"""
Analytics Dashboard — Admin-only page for monitoring student progress and activity.
"""

import streamlit as st
from datetime import datetime

from core.activity_tracker import get_all_records, delete_all_records
from core.data_manager import get_available_simulations


def _parse_dt(iso_str):
    """Parse ISO datetime string safely."""
    if not iso_str:
        return None
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _grade_color(grade: str) -> str:
    if not grade:
        return "#888"
    g = grade.upper().rstrip("+-")
    return {"A": "#28a745", "B": "#17a2b8", "C": "#ffc107", "D": "#fd7e14", "F": "#dc3545"}.get(g, "#888")


def _status_badge(status: str) -> str:
    colors = {"completed": "#28a745", "in_progress": "#ffc107", "abandoned": "#dc3545"}
    color = colors.get(status, "#888")
    label = status.replace("_", " ").title()
    return f'<span style="background:{color}; color:#fff; padding:2px 8px; border-radius:10px; font-size:0.8rem;">{label}</span>'


def analytics_page():
    """Admin analytics dashboard."""
    if not st.session_state.get("admin_authenticated"):
        st.warning("Please log in as admin to access this page.")
        return

    st.markdown('<h1 class="main-header">📊 Student Analytics</h1>', unsafe_allow_html=True)

    records = get_all_records()

    if not records:
        st.info("No student activity recorded yet. Data will appear here once students start playing simulations.")
        return

    # ── Overview Metrics ──
    completed = [r for r in records if r.get("status") == "completed"]
    in_progress = [r for r in records if r.get("status") == "in_progress"]
    unique_students = len(set(r.get("student_id", "") for r in records if r.get("student_id")))
    unique_sims = len(set(r.get("simulation_name", "") for r in records))

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Sessions", len(records))
    col2.metric("Completed", len(completed))
    col3.metric("In Progress", len(in_progress))
    col4.metric("Unique Students", unique_students)

    if completed:
        scores = [r["final_score"] for r in completed if r.get("final_score") is not None]
        if scores:
            avg_score = sum(scores) / len(scores)
            col_a, col_b, col_c, col_d = st.columns(4)
            col_a.metric("Avg Score", f"{avg_score:.1f}/100")
            col_b.metric("Highest Score", f"{max(scores):.1f}")
            col_c.metric("Lowest Score", f"{min(scores):.1f}")
            col_d.metric("Simulations Used", unique_sims)

    st.divider()

    # ── Tabs ──
    tab_overview, tab_students, tab_simulations, tab_details, tab_manage = st.tabs([
        "📋 Activity Log", "👤 By Student", "🏢 By Simulation", "🔍 Session Detail", "🗑️ Manage"
    ])

    # ── TAB 1: Activity Log ──
    with tab_overview:
        st.subheader("All Activity Sessions")

        # Sort by most recent first
        sorted_records = sorted(records, key=lambda r: r.get("started_at", ""), reverse=True)

        for r in sorted_records:
            started = _parse_dt(r.get("started_at"))
            started_str = started.strftime("%b %d, %Y %I:%M %p") if started else "Unknown"
            score_str = f"{r['final_score']:.0f}/100" if r.get("final_score") is not None else "—"
            grade_str = r.get("grade", "—")
            g_color = _grade_color(grade_str)

            st.markdown(f"""
            <div style="background: #1a1a2e; padding: 1rem; border-radius: 10px;
                        margin-bottom: 0.6rem; border-left: 4px solid {g_color};">
                <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.5rem;">
                    <div>
                        <strong style="font-size:1.05rem;">{r.get('student_name', 'Unknown')}</strong>
                        <span style="color:#aaa; margin-left:0.5rem;">ID: {r.get('student_id', '—')}</span>
                    </div>
                    <div>{_status_badge(r.get('status', 'unknown'))}</div>
                </div>
                <div style="color:#ccc; font-size:0.85rem; margin-top:0.4rem;">
                    🏢 {r.get('simulation_name', '—')} &nbsp;|&nbsp;
                    📚 {r.get('module_name', '—')} &nbsp;|&nbsp;
                    🎭 {r.get('player_role', '—')}
                </div>
                <div style="color:#ccc; font-size:0.85rem; margin-top:0.3rem;">
                    📅 {started_str} &nbsp;|&nbsp;
                    🔄 Rounds: {r.get('rounds_completed', 0)}/{r.get('total_rounds', '?')} &nbsp;|&nbsp;
                    📊 Score: <strong style="color:{g_color};">{score_str}</strong> &nbsp;|&nbsp;
                    🏆 Grade: <strong style="color:{g_color};">{grade_str}</strong>
                </div>
            </div>
            """, unsafe_allow_html=True)

    # ── TAB 2: By Student ──
    with tab_students:
        st.subheader("Student Performance")

        # Build student summary
        student_map = {}
        for r in records:
            sid = r.get("student_id", "unknown")
            if sid not in student_map:
                student_map[sid] = {
                    "name": r.get("student_name", "Unknown"),
                    "student_id": sid,
                    "sessions": [],
                }
            student_map[sid]["sessions"].append(r)

        # Student selector
        student_options = [f"{v['name']} ({v['student_id']})" for v in student_map.values()]
        if not student_options:
            st.info("No students found.")
        else:
            selected_student = st.selectbox("Select Student", student_options, key="analytics_student_select")
            idx = student_options.index(selected_student)
            student = list(student_map.values())[idx]

            sessions = student["sessions"]
            completed_sessions = [s for s in sessions if s.get("status") == "completed"]
            scores = [s["final_score"] for s in completed_sessions if s.get("final_score") is not None]

            # Student summary metrics
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total Attempts", len(sessions))
            c2.metric("Completed", len(completed_sessions))
            c3.metric("Avg Score", f"{sum(scores)/len(scores):.1f}" if scores else "—")
            c4.metric("Best Score", f"{max(scores):.1f}" if scores else "—")

            # Grade distribution
            if completed_sessions:
                grades = [s.get("grade", "—") for s in completed_sessions]
                grade_counts = {}
                for g in grades:
                    grade_counts[g] = grade_counts.get(g, 0) + 1

                st.markdown("**Grade Distribution:**")
                grade_cols = st.columns(min(len(grade_counts), 6))
                for i, (grade, count) in enumerate(sorted(grade_counts.items())):
                    grade_cols[i % len(grade_cols)].markdown(
                        f'<div style="text-align:center; padding:0.5rem; background:#1a1a2e; '
                        f'border-radius:8px; border:2px solid {_grade_color(grade)};">'
                        f'<div style="font-size:1.5rem; font-weight:bold; color:{_grade_color(grade)};">{grade}</div>'
                        f'<div style="font-size:0.8rem; color:#aaa;">{count}x</div></div>',
                        unsafe_allow_html=True
                    )

            # Session history for this student
            st.markdown("---")
            st.markdown("**Session History:**")
            for s in sorted(sessions, key=lambda x: x.get("started_at", ""), reverse=True):
                started = _parse_dt(s.get("started_at"))
                started_str = started.strftime("%b %d, %Y") if started else "Unknown"
                score_val = f"{s['final_score']:.0f}" if s.get("final_score") is not None else "—"
                grade_val = s.get("grade", "—")

                with st.expander(
                    f"{s.get('simulation_name', '—')} — {started_str} — "
                    f"Grade: {grade_val} | Score: {score_val}"
                ):
                    st.markdown(f"**Role:** {s.get('player_role', '—')}")
                    st.markdown(f"**Module:** {s.get('module_name', '—')}")
                    st.markdown(f"**Rounds:** {s.get('rounds_completed', 0)}/{s.get('total_rounds', '?')}")

                    if s.get("rounds"):
                        for rd in s["rounds"]:
                            st.markdown(f"**Round {rd['round_number']}** — Score: {rd.get('score', '—')}")
                            if rd.get("decision"):
                                st.markdown(f"> {rd['decision'][:200]}...")
                            cols = st.columns(2)
                            if rd.get("strengths"):
                                with cols[0]:
                                    st.markdown("✅ **Strengths:**")
                                    for item in rd["strengths"]:
                                        st.markdown(f"- {item}")
                            if rd.get("improvements"):
                                with cols[1]:
                                    st.markdown("⚠️ **Improvements:**")
                                    for item in rd["improvements"]:
                                        st.markdown(f"- {item}")
                            st.markdown("---")

    # ── TAB 3: By Simulation ──
    with tab_simulations:
        st.subheader("Simulation Performance")

        sim_map = {}
        for r in records:
            sim_name = r.get("simulation_name", "Unknown")
            if sim_name not in sim_map:
                sim_map[sim_name] = []
            sim_map[sim_name].append(r)

        if not sim_map:
            st.info("No simulation data yet.")
        else:
            selected_sim = st.selectbox("Select Simulation", list(sim_map.keys()), key="analytics_sim_select")
            sim_records = sim_map[selected_sim]
            sim_completed = [r for r in sim_records if r.get("status") == "completed"]
            sim_scores = [r["final_score"] for r in sim_completed if r.get("final_score") is not None]

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total Attempts", len(sim_records))
            c2.metric("Completed", len(sim_completed))
            c3.metric("Completion Rate", f"{len(sim_completed)/len(sim_records)*100:.0f}%" if sim_records else "—")
            c4.metric("Avg Score", f"{sum(sim_scores)/len(sim_scores):.1f}" if sim_scores else "—")

            if sim_completed:
                # Round-by-round average scores
                st.markdown("**Average Score by Round:**")
                max_rounds = max(r.get("total_rounds", 5) for r in sim_completed)
                round_scores = {}
                for r in sim_completed:
                    for rd in (r.get("rounds") or []):
                        rn = rd["round_number"]
                        if rn not in round_scores:
                            round_scores[rn] = []
                        if rd.get("score") is not None:
                            round_scores[rn].append(rd["score"])

                if round_scores:
                    round_cols = st.columns(min(len(round_scores), 6))
                    for i, rn in enumerate(sorted(round_scores.keys())):
                        if not round_scores[rn]:
                            continue
                        avg = sum(round_scores[rn]) / len(round_scores[rn])
                        color = "#28a745" if avg >= 70 else "#ffc107" if avg >= 50 else "#dc3545"
                        round_cols[i % len(round_cols)].markdown(
                            f'<div style="text-align:center; padding:0.5rem; background:#1a1a2e; '
                            f'border-radius:8px; margin-bottom:0.5rem;">'
                            f'<div style="font-size:0.8rem; color:#aaa;">Round {rn}</div>'
                            f'<div style="font-size:1.3rem; font-weight:bold; color:{color};">{avg:.0f}</div>'
                            f'</div>',
                            unsafe_allow_html=True
                        )

                # Student leaderboard
                st.markdown("---")
                st.markdown("**Leaderboard:**")
                sorted_completed = sorted(sim_completed, key=lambda r: r.get("final_score", 0), reverse=True)
                for rank, r in enumerate(sorted_completed, 1):
                    medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"#{rank}")
                    score_val = f"{r['final_score']:.0f}" if r.get("final_score") is not None else "—"
                    st.markdown(
                        f"{medal} **{r.get('student_name', 'Unknown')}** "
                        f"(ID: {r.get('student_id', '—')}) — "
                        f"Score: **{score_val}** | Grade: **{r.get('grade', '—')}** | "
                        f"Role: {r.get('player_role', '—')}"
                    )

            # Consultation patterns
            if sim_completed:
                st.markdown("---")
                st.markdown("**Consultation Usage:**")
                total_board = sum(
                    sum(rd.get("board_consultations", 0) for rd in (r.get("rounds") or []))
                    for r in sim_completed
                )
                total_committee = sum(
                    sum(rd.get("committee_consultations", 0) for rd in (r.get("rounds") or []))
                    for r in sim_completed
                )
                total_rounds_all = sum(r.get("rounds_completed", 0) for r in sim_completed)

                cc1, cc2, cc3 = st.columns(3)
                cc1.metric("Board Consultations", total_board)
                cc2.metric("Committee Consultations", total_committee)
                cc3.metric(
                    "Avg Consultations/Round",
                    f"{(total_board + total_committee) / total_rounds_all:.1f}" if total_rounds_all else "—"
                )

    # ── TAB 4: Session Detail ──
    with tab_details:
        st.subheader("Session Detail Viewer")

        detail_options = [
            f"{r.get('student_name', '?')} — {r.get('simulation_name', '?')} "
            f"({_parse_dt(r.get('started_at')).strftime('%b %d') if _parse_dt(r.get('started_at')) else '?'})"
            for r in sorted(records, key=lambda x: x.get("started_at", ""), reverse=True)
        ]

        if detail_options:
            selected_detail = st.selectbox("Select Session", detail_options, key="analytics_detail_select")
            detail_idx = detail_options.index(selected_detail)
            detail_record = sorted(records, key=lambda x: x.get("started_at", ""), reverse=True)[detail_idx]

            # Session info
            st.markdown(f"""
            <div style="background:#1a1a2e; padding:1.2rem; border-radius:10px; margin-bottom:1rem;">
                <h3 style="margin:0;">{detail_record.get('student_name', 'Unknown')}</h3>
                <p style="color:#aaa; margin:0.3rem 0;">Student ID: {detail_record.get('student_id', '—')}</p>
                <div style="display:flex; gap:2rem; flex-wrap:wrap; margin-top:0.8rem;">
                    <div>🏢 <strong>{detail_record.get('simulation_name', '—')}</strong></div>
                    <div>📚 {detail_record.get('module_name', '—')}</div>
                    <div>🎭 {detail_record.get('player_role', '—')}</div>
                    <div>{_status_badge(detail_record.get('status', 'unknown'))}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # Timing
            started = _parse_dt(detail_record.get("started_at"))
            completed = _parse_dt(detail_record.get("completed_at"))
            if started:
                st.markdown(f"**Started:** {started.strftime('%B %d, %Y at %I:%M %p UTC')}")
            if completed:
                st.markdown(f"**Completed:** {completed.strftime('%B %d, %Y at %I:%M %p UTC')}")
                if started:
                    duration = completed - started
                    mins = int(duration.total_seconds() // 60)
                    st.markdown(f"**Duration:** {mins} minutes")

            # Final results
            if detail_record.get("status") == "completed":
                gc1, gc2, gc3, gc4 = st.columns(4)
                gc1.metric("Final Score", f"{detail_record.get('final_score', 0):.0f}/100")
                gc2.metric("Grade", detail_record.get("grade", "—"))
                gc3.metric("Metrics Improved", detail_record.get("metrics_improved", "—"))
                gc4.metric("Metrics Declined", detail_record.get("metrics_declined", "—"))

            # Round-by-round details
            rounds = detail_record.get("rounds") or []
            if rounds:
                st.markdown("---")
                st.markdown("### Round-by-Round Breakdown")
                for rd in rounds:
                    score = rd.get("score", 0)
                    color = "#28a745" if score >= 70 else "#ffc107" if score >= 50 else "#dc3545"
                    force_tag = " ⚠️ Force-submitted" if rd.get("force_submitted") else ""
                    time_str = f" | ⏱️ {rd.get('time_taken_seconds', 0)//60}m {rd.get('time_taken_seconds', 0)%60}s" if rd.get("time_taken_seconds") else ""

                    with st.expander(f"Round {rd['round_number']} — Score: {score:.0f}{force_tag}{time_str}"):
                        st.markdown(f"**Score:** <span style='color:{color}; font-size:1.2rem;'>{score:.0f}/100</span>", unsafe_allow_html=True)
                        st.markdown(f"**Consultations:** Board: {rd.get('board_consultations', 0)} | Committee: {rd.get('committee_consultations', 0)}")

                        if rd.get("decision"):
                            st.markdown("**Decision:**")
                            st.markdown(f"> {rd['decision']}")

                        cols = st.columns(2)
                        if rd.get("strengths"):
                            with cols[0]:
                                st.markdown("✅ **Strengths:**")
                                for s in rd["strengths"]:
                                    st.markdown(f"- {s}")
                        if rd.get("improvements"):
                            with cols[1]:
                                st.markdown("⚠️ **Areas for Improvement:**")
                                for imp in rd["improvements"]:
                                    st.markdown(f"- {imp}")
            else:
                st.info("No round data available yet for this session.")
        else:
            st.info("No sessions to display.")

    # ── TAB 5: Manage ──
    with tab_manage:
        st.subheader("Manage Activity Data")
        st.markdown(f"**Total records:** {len(records)}")

        st.warning("Deleting activity data is irreversible.")
        if st.button("🗑️ Clear All Activity Data", type="secondary", key="analytics_clear_btn"):
            st.session_state._confirm_clear_analytics = True

        if st.session_state.get("_confirm_clear_analytics"):
            st.error("Are you sure? This will delete ALL student activity records.")
            c1, c2 = st.columns(2)
            if c1.button("Yes, delete everything", key="analytics_confirm_delete"):
                delete_all_records()
                st.session_state._confirm_clear_analytics = False
                st.success("All activity data cleared.")
                st.rerun()
            if c2.button("Cancel", key="analytics_cancel_delete"):
                st.session_state._confirm_clear_analytics = False
                st.rerun()
