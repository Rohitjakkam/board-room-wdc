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

    # Build dynamic simulation pages
    simulations = get_available_simulations()

    # Section 1: Dashboard
    dashboard_pages = [
        st.Page(home_page, title="Home", icon="🏠", url_path="home")
    ]

    # Section 2: Create & Manage
    create_pages = [
        st.Page(create_simulation_page, title="Create Simulation", icon="📤", url_path="create"),
        st.Page(manage_simulations_page, title="Manage Simulations", icon="⚙️", url_path="manage"),
    ]

    # Section 3: Dynamic simulation pages
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

    # Build navigation
    nav_sections = {
        "Dashboard": dashboard_pages,
        "Create & Manage": create_pages,
    }

    if sim_pages:
        nav_sections["Simulations"] = sim_pages
    else:
        nav_sections["Simulations"] = [
            st.Page(_no_sims_page, title="No Simulations", icon="📭", url_path="no-sims")
        ]

    nav = st.navigation(nav_sections)
    nav.run()


if __name__ == "__main__":
    main()
