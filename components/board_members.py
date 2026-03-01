"""
Board member selection and display components.
"""

import streamlit as st
from typing import Dict, List, Optional


def display_board_members_for_selection(board_members: List[Dict]) -> Optional[Dict]:
    """Display board members as clickable selection cards."""
    st.subheader("👤 Select Your Role")
    st.markdown("Choose which board member you want to play as:")

    cols = st.columns(2)

    for idx, member in enumerate(board_members):
        with cols[idx % 2]:
            with st.container():
                st.markdown(f"""
                <div class="board-member-card">
                    <h4>{member['name']}</h4>
                    <p><strong>{member['role']}</strong></p>
                    <p><em>Expertise: {member['expertise']} | Tenure: {member['tenure_years']} years</em></p>
                    <p style="font-size: 0.9rem;">{member['personality']}</p>
                </div>
                """, unsafe_allow_html=True)

                if st.button(f"Play as {member['name']}", key=f"select_role_{idx}", use_container_width=True):
                    return member

    return None


def display_board_members(board_members: List[Dict], player_role: Optional[Dict] = None):
    """Display board member cards."""
    st.subheader("👥 Board of Directors")

    cols = st.columns(2)

    for idx, member in enumerate(board_members):
        with cols[idx % 2]:
            is_player = player_role and member['name'] == player_role['name']
            card_class = "selected-role-card" if is_player else "board-member-card"
            player_badge = " (YOU)" if is_player else ""

            with st.container():
                st.markdown(f"""
                <div class="{card_class}">
                    <h4>{member['name']}{player_badge}</h4>
                    <p><strong>{member['role']}</strong></p>
                    <p><em>Expertise: {member['expertise']} | Tenure: {member['tenure_years']} years</em></p>
                    <p style="font-size: 0.9rem;">{member['personality']}</p>
                </div>
                """, unsafe_allow_html=True)
