"""
Student Home — simulation picker for student users.
Lists available simulations and lets students navigate to one.
"""

import streamlit as st
from core.data_manager import get_available_simulations


def student_home_page():
    """Landing page for students — identify yourself and pick a simulation."""

    st.markdown(
        '<h1 style="text-align:center; color:#1E3A5F;">Board Room Simulation</h1>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p style="text-align:center; color:#666;">Corporate Governance Training & Decision Making</p>',
        unsafe_allow_html=True,
    )
    st.markdown("---")

    # Student identification gate
    if not st.session_state.get("student_identified"):
        st.subheader("Welcome! Please identify yourself to begin.")
        with st.form("student_home_id_form"):
            col_a, col_b = st.columns(2)
            with col_a:
                name = st.text_input("Full Name", placeholder="e.g. Rahul Sharma")
            with col_b:
                student_id = st.text_input("Student ID", placeholder="e.g. STU-2026-001")
            submitted = st.form_submit_button(
                "Continue", type="primary", use_container_width=True
            )
            if submitted:
                if name.strip() and student_id.strip():
                    st.session_state.student_name = name.strip()
                    st.session_state.student_id = student_id.strip()
                    st.session_state.student_identified = True
                    st.rerun()
                else:
                    st.error("Please enter both your name and student ID.")
        return

    # Greeting
    st.markdown(
        f"Welcome, **{st.session_state.get('student_name', '')}** "
        f"(ID: {st.session_state.get('student_id', '')})"
    )
    st.markdown("### Choose a Simulation")

    simulations = get_available_simulations()
    sim_pages_dict = st.session_state.get("_sim_pages", {})

    if not simulations:
        st.info("No simulations are available yet. Please ask your instructor.")
        return

    for sim in simulations:
        doc_id = sim["doc_id"]
        with st.container():
            col1, col2 = st.columns([4, 1])
            with col1:
                st.markdown(f"""
                <div style="background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
                            padding: 1rem; border-radius: 10px;
                            border-left: 5px solid #1E3A5F; margin-bottom: 0.8rem;">
                    <h4 style="margin: 0; color: #1E3A5F;">{sim['company_name']}</h4>
                    <p style="margin: 0.2rem 0; color: #555; font-size: 0.88rem;">
                        <strong>Module:</strong> {sim['module_name']} &nbsp;|&nbsp;
                        <strong>Industry:</strong> {sim['industry']}
                    </p>
                    <p style="margin: 0.3rem 0 0 0; color: #777; font-size: 0.83rem;">
                        {sim.get('company_overview', '')[:180]}...
                    </p>
                </div>
                """, unsafe_allow_html=True)
            with col2:
                st.markdown("<br>", unsafe_allow_html=True)
                target_page = sim_pages_dict.get(doc_id)
                if target_page:
                    if st.button(
                        "Join", key=f"student_join_{doc_id}",
                        use_container_width=True, type="primary",
                    ):
                        st.switch_page(target_page)
                else:
                    st.button(
                        "Join", key=f"student_join_{doc_id}",
                        disabled=True, use_container_width=True,
                    )

    st.markdown("---")
    st.caption("Contact your instructor if your simulation is not listed.")
