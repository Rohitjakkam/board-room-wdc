"""
Company dashboard, problems, and module info display components.
"""

import streamlit as st
from typing import Dict, List, Optional


def _fmt_val(v) -> str:
    """Format a metric value: drop unnecessary .0 for whole numbers."""
    try:
        f = float(v)
        return str(int(f)) if f == int(f) else f"{f:.1f}"
    except (TypeError, ValueError):
        return str(v) if v is not None else "0"


def display_company_dashboard(company_data: Dict, player_role: Dict = None):
    """Display company metrics dashboard, optionally highlighting metrics relevant to player_role."""
    st.subheader(f"📊 {company_data['company_name']} Dashboard")

    metrics = company_data['metrics']

    # Determine which metrics are relevant to the player's expertise area
    role_expertise = (player_role or {}).get('expertise', '').lower()
    EXPERTISE_KEYWORDS = {
        'finance': {'revenue', 'profit', 'margin', 'ebitda', 'cost', 'budget', 'debt', 'cash', 'burn'},
        'operations': {'uptime', 'deployment', 'latency', 'automation', 'delivery', 'incident', 'efficiency'},
        'hr': {'employee', 'attrition', 'engagement', 'training', 'diversity', 'retention', 'headcount'},
        'risk': {'risk', 'compliance', 'regulatory', 'audit', 'violation', 'breach', 'incident'},
        'marketing': {'customer', 'churn', 'nps', 'promoter', 'acquisition', 'revenue', 'csat'},
        'technology': {'uptime', 'deployment', 'latency', 'automation', 'platform', 'data', 'cyber'},
        'strategy': {'growth', 'revenue', 'market', 'expansion', 'customer', 'product'},
    }
    relevant_keys = set()
    for domain, kws in EXPERTISE_KEYWORDS.items():
        if any(d in role_expertise for d in (domain, domain[:4])):
            for key in metrics:
                if any(kw in key.lower() for kw in kws):
                    relevant_keys.add(key)

    high_priority = {k: v for k, v in metrics.items() if v.get('priority') in ['High', 'high']}
    other_metrics = {k: v for k, v in metrics.items() if v.get('priority') not in ['High', 'high']}

    if high_priority:
        st.markdown("**High Priority Metrics:**")
        cols = st.columns(min(len(high_priority), 4))
        for idx, (key, metric) in enumerate(high_priority.items()):
            with cols[idx % min(len(high_priority), 4)]:
                change = metric.get('change', 0)
                delta_str = f"{change:+.1f}" if change != 0 else None
                label = metric['description']
                if relevant_keys and key in relevant_keys:
                    label = f"★ {label}"
                st.metric(label, f"{_fmt_val(metric['value'])} {metric['unit']}".rstrip(), delta=delta_str)

    if other_metrics:
        cols = st.columns(4)
        for idx, (key, metric) in enumerate(other_metrics.items()):
            with cols[idx % 4]:
                change = metric.get('change', 0)
                delta_str = f"{change:+.1f}" if change != 0 else None
                label = metric['description']
                if relevant_keys and key in relevant_keys:
                    label = f"★ {label}"
                st.metric(label, f"{_fmt_val(metric['value'])} {metric['unit']}".rstrip(), delta=delta_str)

    if relevant_keys and player_role:
        st.caption(f"★ = relevant to your expertise as {player_role.get('role', 'your role')}")

    with st.expander("📈 View All Metrics"):
        metric_cols = st.columns(3)
        for idx, (key, metric) in enumerate(metrics.items()):
            with metric_cols[idx % 3]:
                priority_badge = "🔴 " if metric.get('priority') in ['High', 'high'] else ""
                role_badge = "★ " if relevant_keys and key in relevant_keys else ""
                st.markdown(f"""
                **{priority_badge}{role_badge}{metric['description']}**
                `{_fmt_val(metric['value'])} {metric['unit']}`
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
