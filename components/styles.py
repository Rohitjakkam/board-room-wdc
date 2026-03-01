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
        background: #fff3cd;
        padding: 1.5rem;
        border-radius: 10px;
        border: 1px solid #ffc107;
        margin: 1rem 0;
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
</style>
""", unsafe_allow_html=True)
