"""
Board Room Simulation — Unified Entry Point.
Single Streamlit app with sidebar navigation and dynamic simulation pages.
"""

import logging
import re
import streamlit as st
import google.generativeai as genai

from core.data_manager import get_available_simulations
from components.styles import inject_styles
from pages.home import home_page
from pages.create_simulation import create_simulation_page
from pages.manage_simulations import manage_simulations_page
from pages.simulation import simulation_page


def _slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'-+', '-', text)
    return text[:60] or "simulation"


def _no_sims_page():
    """Placeholder page when no simulations exist."""
    st.info("No simulations available yet. Use **Create Simulation** to add one.")


def _render_sidebar_auth():
    """Render role-switching controls in the sidebar."""
    with st.sidebar:
        if st.session_state.get("admin_authenticated"):
            st.markdown("""
            <div style="background: linear-gradient(135deg, #d4edda 0%, #c3e6cb 100%);
                        padding: 0.6rem 1rem; border-radius: 8px; margin-bottom: 1rem;
                        border-left: 4px solid #28a745; font-size: 0.9rem;">
                <strong>Admin Mode</strong>
            </div>
            """, unsafe_allow_html=True)
            if st.button("Logout", key="admin_logout_btn"):
                st.session_state.admin_authenticated = False
                st.session_state.user_role = "student"
                st.rerun()
        else:
            # Show student info if identified
            if st.session_state.get("student_identified"):
                st.markdown(f"""
                <div style="background: #e7f3ff; padding: 0.5rem 0.8rem;
                            border-radius: 8px; font-size: 0.85rem;">
                    Student: <strong>{st.session_state.get('student_name', '')}</strong><br>
                    ID: {st.session_state.get('student_id', '')}
                </div>
                """, unsafe_allow_html=True)

            # Subtle admin login at the bottom
            st.markdown("<br>" * 3, unsafe_allow_html=True)
            st.markdown(
                '<p style="text-align:center; font-size:0.75rem; color:#aaa;">Admin?</p>',
                unsafe_allow_html=True
            )
            with st.popover("🔒", use_container_width=True):
                password = st.text_input(
                    "Admin Password", type="password", key="admin_pw_input"
                )
                if st.button("Login", key="admin_login_btn"):
                    if password == st.secrets.get("ADMIN_PASSWORD", ""):
                        st.session_state.admin_authenticated = True
                        st.session_state.user_role = "admin"
                        st.rerun()
                    else:
                        st.error("Incorrect password.")


def main():
    st.set_page_config(
        page_title="Board Room Simulation",
        page_icon="🏢",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    # Configure Gemini API globally (needed by extractors + simulation engine)
    genai.configure(api_key=st.secrets.get("GEMINI_API_KEY", ""))

    inject_styles()

    # Initialize role state
    if "user_role" not in st.session_state:
        st.session_state.user_role = "student"
    if "admin_authenticated" not in st.session_state:
        st.session_state.admin_authenticated = False

    # Render sidebar auth controls
    _render_sidebar_auth()

    # Build dynamic simulation pages (always — needed for URL matching)
    simulations = get_available_simulations()

    sim_pages = []
    for idx, sim in enumerate(simulations):
        url_slug = _slugify(sim['company_name'])
        # Ensure unique slugs
        if any(url_slug == _slugify(s['company_name']) for s in simulations[:idx]):
            url_slug = f"{url_slug}-{idx}"

        def make_page(i=idx):
            st.session_state.selected_sim_index = i
            simulation_page()

        page = st.Page(
            make_page,
            title=sim['company_name'][:30],
            icon="🏢",
            url_path=url_slug
        )
        sim_pages.append(page)

    # Store sim_pages reference for home page launch buttons
    st.session_state._sim_pages = sim_pages

    # Build navigation based on role
    is_admin = st.session_state.get("admin_authenticated", False)

    if is_admin:
        # Admin sees everything
        nav_sections = {
            "Dashboard": [
                st.Page(home_page, title="Home", icon="🏠", url_path="home")
            ],
            "Create & Manage": [
                st.Page(create_simulation_page, title="Create Simulation", icon="📤", url_path="create"),
                st.Page(manage_simulations_page, title="Manage Simulations", icon="⚙️", url_path="manage"),
            ],
        }
        if sim_pages:
            nav_sections["Simulations"] = sim_pages
        else:
            nav_sections["Simulations"] = [
                st.Page(_no_sims_page, title="No Simulations", icon="📭", url_path="no-sims")
            ]
    else:
        # Student sees only simulations
        if sim_pages:
            nav_sections = {"Simulations": sim_pages}
        else:
            nav_sections = {
                "Simulations": [
                    st.Page(_no_sims_page, title="No Simulations", icon="📭", url_path="no-sims")
                ]
            }

    # Admin: full sidebar navigation visible
    # Student: hide page list (URLs still work, sidebar stays clean)
    nav_position = "sidebar" if is_admin else "hidden"
    nav = st.navigation(nav_sections, position=nav_position)
    nav.run()


if __name__ == "__main__":
    main()
