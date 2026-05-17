"""
Shared CSS styles for the Board Room Simulation application.
"""

import streamlit as st


def inject_styles():
    """Inject all CSS styles into the Streamlit app."""
    st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1E3A5F;
        text-align: center;
        padding: 1rem 0;
    }
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1rem;
        border-radius: 10px;
        color: white;
        text-align: center;
        margin: 0.5rem 0;
    }
    .board-member-card {
        background: #f8f9fa;
        padding: 1rem;
        border-radius: 10px;
        border-left: 4px solid #667eea;
        margin: 0.5rem 0;
    }
    .selected-role-card {
        background: #d4edda;
        padding: 1rem;
        border-radius: 10px;
        border-left: 4px solid #28a745;
        margin: 0.5rem 0;
    }
    .scenario-box {
        background: #f8f9fa;
        padding: 1.5rem;
        border-radius: 10px;
        border: 1px solid #dee2e6;
        margin: 1rem 0;
    }
    .scenario-title {
        font-size: 1.3rem;
        font-weight: 700;
        color: #1E3A5F;
        background: linear-gradient(135deg, #e8f4f8 0%, #d4e9ed 100%);
        padding: 0.8rem 1.2rem;
        border-radius: 10px 10px 0 0;
        border-left: 5px solid #1E3A5F;
        margin: 0.5rem 0 0 0;
    }
    .scenario-situation {
        background: #ffffff;
        padding: 1.2rem 1.5rem;
        border: 1px solid #dee2e6;
        border-top: none;
        border-radius: 0 0 10px 10px;
        line-height: 1.7;
        color: #333;
        white-space: pre-wrap;
        margin: 0 0 0.8rem 0;
    }
    .scenario-info-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 0.6rem;
        margin: 0 0 1rem 0;
    }
    .scenario-info-item {
        background: #f0f7ff;
        padding: 0.8rem 1rem;
        border-radius: 8px;
        border-left: 4px solid #007bff;
    }
    .scenario-info-item p {
        margin: 0.3rem 0 0 0;
        color: #333;
        font-size: 0.9rem;
        white-space: pre-wrap;
    }
    .scenario-info-label {
        font-weight: 600;
        color: #1E3A5F;
        font-size: 0.8rem;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .decision-box {
        background: #d4edda;
        padding: 1.5rem;
        border-radius: 10px;
        border: 1px solid #28a745;
        margin: 1rem 0;
    }
    .warning-box {
        background: #f8d7da;
        padding: 1rem;
        border-radius: 10px;
        border: 1px solid #dc3545;
    }
    .info-box {
        background: #cce5ff;
        padding: 1rem;
        border-radius: 10px;
        border: 1px solid #007bff;
    }
    .round-indicator {
        font-size: 1.2rem;
        font-weight: bold;
        color: #1E3A5F;
        padding: 0.5rem 1rem;
        background: #e9ecef;
        border-radius: 20px;
        display: inline-block;
        user-select: none;
        -webkit-user-select: none;
    }
    /* Hide Streamlit's default heading anchor link icons */
    [data-testid="stHeadingAnchorLink"] {
        display: none !important;
    }
    .consultation-counter {
        font-size: 1rem;
        padding: 0.5rem 1rem;
        background: #e7f3ff;
        border-radius: 10px;
        border: 1px solid #007bff;
        display: inline-block;
        margin: 0.5rem 0;
    }
    .option-button {
        width: 100%;
        margin: 0.5rem 0;
    }
    .committee-card {
        background: #f0f7ff;
        padding: 1rem;
        border-radius: 10px;
        border-left: 4px solid #007bff;
        margin: 0.5rem 0;
    }
    .timer-container {
        text-align: center;
        padding: 1rem;
        margin: 1rem 0;
        border-radius: 10px;
        font-family: 'Courier New', monospace;
    }
    .timer-relaxed {
        background: linear-gradient(135deg, #d4edda 0%, #c3e6cb 100%);
        border: 2px solid #28a745;
    }
    .timer-normal {
        background: linear-gradient(135deg, #fff3cd 0%, #ffeeba 100%);
        border: 2px solid #ffc107;
    }
    .timer-urgent {
        background: linear-gradient(135deg, #f8d7da 0%, #f5c6cb 100%);
        border: 2px solid #dc3545;
    }
    .timer-expired {
        background: linear-gradient(135deg, #dc3545 0%, #c82333 100%);
        border: 2px solid #bd2130;
        color: white;
    }
    .timer-display {
        font-size: 2.5rem;
        font-weight: bold;
    }
    .timer-label {
        font-size: 0.9rem;
        margin-top: 0.5rem;
    }
    .stance-card {
        padding: 1rem;
        border-radius: 10px;
        margin: 0.5rem 0;
        border-left: 4px solid #666;
    }
    .stance-approve {
        background: #d4edda;
        border-left-color: #28a745;
    }
    .stance-oppose {
        background: #f8d7da;
        border-left-color: #dc3545;
    }
    .stance-neutral {
        background: #fff3cd;
        border-left-color: #ffc107;
    }
    .stance-convinced {
        background: #d1ecf1;
        border-left-color: #17a2b8;
    }
    .deliberation-header {
        background: linear-gradient(135deg, #f0f7ff 0%, #e6f0ff 100%);
        padding: 1rem;
        border-radius: 10px;
        margin: 1rem 0;
    }
    .debate-box {
        background: #ffffff;
        padding: 1rem;
        border-radius: 8px;
        border: 1px solid #dee2e6;
        margin: 0.5rem 0;
    }
    .conviction-bar {
        height: 8px;
        background: #e9ecef;
        border-radius: 4px;
        overflow: hidden;
    }
    .conviction-fill {
        height: 100%;
        background: linear-gradient(90deg, #ffc107 0%, #dc3545 100%);
        border-radius: 4px;
    }
    .company-brief-section {
        background: linear-gradient(135deg, #e8f4f8 0%, #d4e9ed 100%);
        padding: 0.8rem;
        border-radius: 8px;
        border-left: 4px solid #17a2b8;
        margin-bottom: 0.5rem;
    }
    .company-brief-header {
        color: #1E3A5F;
        font-weight: 600;
        margin-bottom: 0.5rem;
    }
    .challenge-item {
        color: #856404;
        font-size: 0.85rem;
        margin: 0.2rem 0;
    }

    /* Board-member hover tooltip — used wherever a member name is displayed.
       Render via components.board_members.member_chip_html(member). The wrapper
       is inline so it slots into existing text flows; the popup is absolutely
       positioned so it doesn't disturb surrounding layout. */
    .member-hover-wrap {
        position: relative;
        display: inline-block;
        cursor: help;
        border-bottom: 1px dotted rgba(100, 116, 139, 0.5);
    }
    .member-hover-wrap .member-hover-popup {
        visibility: hidden;
        opacity: 0;
        position: absolute;
        z-index: 9999;
        bottom: 125%;
        left: 50%;
        transform: translateX(-50%);
        min-width: 280px;
        max-width: 360px;
        background: #ffffff;
        color: #1f2937;
        text-align: left;
        padding: 0.85rem 1rem;
        border-radius: 10px;
        border: 1px solid #e5e7eb;
        box-shadow: 0 10px 25px rgba(0, 0, 0, 0.15), 0 4px 10px rgba(0, 0, 0, 0.08);
        font-size: 0.85rem;
        line-height: 1.45;
        font-weight: normal;
        transition: opacity 0.15s ease-in-out, visibility 0.15s ease-in-out;
        white-space: normal;
        pointer-events: none;  /* avoid flicker when crossing the gap */
    }
    .member-hover-wrap .member-hover-popup::after {
        content: "";
        position: absolute;
        top: 100%;
        left: 50%;
        transform: translateX(-50%);
        border-width: 6px;
        border-style: solid;
        border-color: #ffffff transparent transparent transparent;
        filter: drop-shadow(0 2px 1px rgba(0, 0, 0, 0.08));
    }
    .member-hover-wrap:hover .member-hover-popup,
    .member-hover-wrap:focus-within .member-hover-popup {
        visibility: visible;
        opacity: 1;
    }
    .member-hover-popup h5 {
        margin: 0 0 0.35rem 0;
        font-size: 0.95rem;
        font-weight: 600;
        color: #111827;
    }
    .member-hover-popup .mh-role {
        font-size: 0.8rem;
        color: #6b7280;
        margin-bottom: 0.55rem;
        font-weight: 500;
    }
    .member-hover-popup .mh-row {
        display: flex;
        margin: 0.18rem 0;
        font-size: 0.8rem;
    }
    .member-hover-popup .mh-key {
        color: #6b7280;
        min-width: 86px;
        flex-shrink: 0;
    }
    .member-hover-popup .mh-val {
        color: #1f2937;
    }
    .member-hover-popup .mh-personality {
        margin-top: 0.55rem;
        padding-top: 0.55rem;
        border-top: 1px solid #f3f4f6;
        font-style: italic;
        color: #4b5563;
        font-size: 0.8rem;
    }
    .member-hover-popup .mh-section {
        margin-top: 0.55rem;
        padding-top: 0.55rem;
        border-top: 1px solid #f3f4f6;
    }
    .member-hover-popup .mh-section-title {
        font-size: 0.72rem;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: #6b7280;
        margin-bottom: 0.3rem;
        font-weight: 600;
    }

    /* When the wrapper is near the right edge of the screen, anchor popup left
       to avoid clipping. Apply by adding class .anchor-right to the wrapper. */
    .member-hover-wrap.anchor-right .member-hover-popup {
        left: auto;
        right: 0;
        transform: none;
    }
    .member-hover-wrap.anchor-right .member-hover-popup::after {
        left: auto;
        right: 20px;
        transform: none;
    }
</style>
""", unsafe_allow_html=True)
