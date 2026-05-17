"""
Board member selection and display components.

The `member_chip_html` helper is the single source of truth for rendering a
board member's name with a hover popup. Every call site that displays a member
name (deliberation cards, dissenter queue, summary panels, consultation chat)
should use it so that adding a new field to the member dict surfaces in the
tooltip automatically.
"""

import html as _html
import streamlit as st
from typing import Dict, List, Optional


# Fields that get a row in the tooltip body. Order matters — first-listed
# appears first. Adding a key here automatically surfaces it in every hover
# popup, application-wide. Keep this list small and stable.
_TOOLTIP_FIELDS = [
    ('expertise',     'Expertise'),
    ('tenure_years',  'Tenure'),
    ('industry',      'Industry'),
    ('background',    'Background'),
    ('education',     'Education'),
    ('committees',    'Committees'),  # may be a list — handled below
]


def _fmt_field_value(key: str, value) -> str:
    """Format a member-dict value for tooltip display. Returns escaped HTML."""
    if value is None or value == '':
        return ''
    if key == 'tenure_years':
        try:
            n = int(value)
            return f"{n} year{'s' if n != 1 else ''}"
        except (TypeError, ValueError):
            return _html.escape(str(value))
    if isinstance(value, list):
        return _html.escape(', '.join(str(v) for v in value if v))
    return _html.escape(str(value))


def member_chip_html(member: Dict,
                     label: Optional[str] = None,
                     stance: Optional[Dict] = None,
                     anchor: str = 'center') -> str:
    """Return an HTML string with a member-name chip + hover popup.

    Embed the return value directly inside any st.markdown(..., unsafe_allow_html=True)
    block. The popup contents are built from the member dict — adding a key to
    `_TOOLTIP_FIELDS` makes it appear in every popup application-wide.

    Args:
        member: A board-member dict (must have 'name'; everything else is optional).
        label:  Optional display text. Defaults to member['name'].
        stance: Optional stance dict for this round (adds stance/conviction info).
        anchor: 'center' (default) or 'right' — use 'right' near page edges to
                prevent the popup from being clipped.

    Returns:
        An HTML string. Caller is responsible for using unsafe_allow_html=True.
    """
    name = member.get('name', 'Unknown')
    # The label slot is trusted to allow callers to wrap the name in styled
    # markup (e.g. <h4>, <strong>). Member-dict fields are always escaped
    # below — the only XSS surface is the label, and callers control it
    # entirely (no user input flows through it).
    display = label if label is not None else _html.escape(name)
    role = _html.escape(member.get('role', '') or '')

    # Build the field rows
    rows = []
    for key, header in _TOOLTIP_FIELDS:
        val = _fmt_field_value(key, member.get(key))
        if val:
            rows.append(
                f'<div class="mh-row"><span class="mh-key">{header}:</span>'
                f'<span class="mh-val">{val}</span></div>'
            )
    rows_html = ''.join(rows)

    # Personality gets its own emphasized block at the bottom
    personality = member.get('personality')
    personality_block = ''
    if personality:
        personality_block = (
            f'<div class="mh-personality">{_html.escape(str(personality))}</div>'
        )

    # Optional stance-aware block — only renders when stance info is supplied
    stance_block = ''
    if stance:
        stance_label = stance.get('stance', '')
        conviction = stance.get('conviction_level')
        counter = stance.get('counter_opinion') or stance.get('initial_reaction', '')
        bits = []
        if stance_label:
            bits.append(f'<div class="mh-row"><span class="mh-key">Stance:</span>'
                        f'<span class="mh-val">{_html.escape(str(stance_label))}</span></div>')
        if conviction is not None:
            bits.append(f'<div class="mh-row"><span class="mh-key">Conviction:</span>'
                        f'<span class="mh-val">{int(conviction)}/10</span></div>')
        if counter:
            short = _html.escape(str(counter))[:180]
            if len(str(counter)) > 180:
                short += '…'
            bits.append(f'<div class="mh-row"><span class="mh-key">Note:</span>'
                        f'<span class="mh-val">{short}</span></div>')
        if bits:
            stance_block = (
                '<div class="mh-section">'
                '<div class="mh-section-title">This round</div>'
                + ''.join(bits)
                + '</div>'
            )

    anchor_class = ' anchor-right' if anchor == 'right' else ''
    role_html = f'<div class="mh-role">{role}</div>' if role else ''

    return (
        f'<span class="member-hover-wrap{anchor_class}" tabindex="0">'
        f'{display}'
        f'<span class="member-hover-popup">'
        f'<h5>{_html.escape(name)}</h5>'
        f'{role_html}'
        f'{rows_html}'
        f'{personality_block}'
        f'{stance_block}'
        f'</span>'
        f'</span>'
    )


def display_board_members_for_selection(board_members: List[Dict]) -> Optional[Dict]:
    """Display board members as clickable selection cards."""
    st.subheader("👤 Select Your Role")
    st.markdown("Choose which board member you want to play as:")

    cols = st.columns(2)

    for idx, member in enumerate(board_members):
        with cols[idx % 2]:
            with st.container():
                tenure = f"{member['tenure_years']} years" if member.get('tenure_years') is not None else "Not specified"
                # Name is wrapped with hover popup so all fields are discoverable
                # via tooltip, even fields not shown on the card itself.
                name_html = member_chip_html(member, label=f"<h4 style='display:inline'>{member['name']}</h4>")
                st.markdown(f"""
                <div class="board-member-card">
                    {name_html}
                    <p><strong>{member['role']}</strong></p>
                    <p><em>Expertise: {member['expertise']} | Tenure: {tenure}</em></p>
                    <p style="font-size: 0.9rem;">{member['personality']}</p>
                </div>
                """, unsafe_allow_html=True)

                safe_key = member['name'].replace(' ', '_').replace("'", "").lower()
                if st.button(f"Play as {member['name']}", key=f"select_role_{safe_key}", use_container_width=True):
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
                tenure = f"{member['tenure_years']} years" if member.get('tenure_years') is not None else "Not specified"
                st.markdown(f"""
                <div class="{card_class}">
                    <h4>{member['name']}{player_badge}</h4>
                    <p><strong>{member['role']}</strong></p>
                    <p><em>Expertise: {member['expertise']} | Tenure: {tenure}</em></p>
                    <p style="font-size: 0.9rem;">{member['personality']}</p>
                </div>
                """, unsafe_allow_html=True)
