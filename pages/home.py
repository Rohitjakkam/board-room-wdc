"""
Home page — lists all available simulations with launch buttons.
"""

import streamlit as st

from core.data_manager import get_available_simulations


def home_page():
    """Home page listing all available simulations."""
    if not st.session_state.get("admin_authenticated"):
        st.warning("Please log in as admin to access this page.")
        return

    st.markdown('<h1 class="main-header">🏢 Board Room Simulations</h1>', unsafe_allow_html=True)
    st.markdown('<p style="text-align: center; color: #666;">Corporate Governance Training & Decision Making</p>', unsafe_allow_html=True)

    simulations = get_available_simulations()

    if not simulations:
        st.warning("No simulation files found. Use **Create Simulation** in the sidebar to create one.")
        return

    st.markdown(f"### Available Simulations ({len(simulations)})")
    st.markdown("---")

    for idx, sim in enumerate(simulations):
        with st.container():
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"""
                <div style="background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%); padding: 1.2rem; border-radius: 12px; border-left: 5px solid #1E3A5F; margin-bottom: 1rem;">
                    <h3 style="margin: 0; color: #1E3A5F;">{sim['company_name']}</h3>
                    <p style="margin: 0.3rem 0; color: #555; font-size: 0.9rem;"><strong>Module:</strong> {sim['module_name']}</p>
                    <p style="margin: 0.3rem 0; color: #555; font-size: 0.9rem;"><strong>Industry:</strong> {sim['industry']} | <strong>Board Members:</strong> {sim['board_count']}</p>
                    <p style="margin: 0.5rem 0 0 0; color: #777; font-size: 0.85rem;">{sim['company_overview'][:200]}...</p>
                </div>
                """, unsafe_allow_html=True)
            with col2:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button(f"▶️ Launch Simulation", key=f"launch_{idx}", use_container_width=True):
                    st.session_state.selected_sim_index = idx
                    st.switch_page(st.session_state._sim_pages[idx])

    st.markdown("---")
    st.caption("Use **Create Simulation** in the sidebar to add new simulations from PDFs.")
