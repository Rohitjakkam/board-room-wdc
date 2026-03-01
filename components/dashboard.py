"""
Company dashboard, problems, and module info display components.
"""

import streamlit as st
from typing import Dict, List, Optional


def display_company_dashboard(company_data: Dict):
    """Display company metrics dashboard."""
    st.subheader(f"📊 {company_data['company_name']} Dashboard")

    metrics = company_data['metrics']

    high_priority = {k: v for k, v in metrics.items() if v.get('priority') in ['High', 'high']}
    other_metrics = {k: v for k, v in metrics.items() if v.get('priority') not in ['High', 'high']}

    if high_priority:
        st.markdown("**High Priority Metrics:**")
        cols = st.columns(min(len(high_priority), 4))
        for idx, (key, metric) in enumerate(high_priority.items()):
            with cols[idx % min(len(high_priority), 4)]:
                change = metric.get('change', 0)
                delta_str = f"{change:+.1f}" if change != 0 else None
                st.metric(metric['description'], f"{metric['value']} {metric['unit']}", delta=delta_str)

    if other_metrics:
        cols = st.columns(4)
        for idx, (key, metric) in enumerate(other_metrics.items()):
            with cols[idx % 4]:
                change = metric.get('change', 0)
                delta_str = f"{change:+.1f}" if change != 0 else None
                st.metric(metric['description'], f"{metric['value']} {metric['unit']}", delta=delta_str)

    with st.expander("📈 View All Metrics"):
        metric_cols = st.columns(3)
        for idx, (key, metric) in enumerate(metrics.items()):
            with metric_cols[idx % 3]:
                priority_badge = "🔴 " if metric.get('priority') in ['High', 'high'] else ""
                st.markdown(f"""
                **{priority_badge}{metric['description']}**
                `{metric['value']} {metric['unit']}`
                """)


def display_current_problems(problems: List[str]):
    """Display current company problems."""
    st.subheader("⚠️ Current Challenges")
    for problem in problems:
        st.markdown(f"- {problem}")


def display_module_info(module_data: Dict):
    """Display module information."""
    st.subheader(f"📚 {module_data['module_name']}")
    st.markdown(module_data['overview'])

    with st.expander("🎯 Learning Objectives"):
        for obj in module_data['learning_objectives']:
            st.markdown(f"- {obj}")

    with st.expander("📖 Key Topics"):
        for topic in module_data['topics']:
            st.markdown(f"**{topic['name']}**")
            st.markdown(f"_{topic['description']}_")
            st.markdown("---")
