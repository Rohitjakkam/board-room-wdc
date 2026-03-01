"""
Manage Simulations page — saved sessions, audit data, simulation planning.
Combines Tabs 2, 3, 4 from the original data_collection.py.
"""

import json
import streamlit as st
from datetime import datetime

from core.utils import safe_index, safe_key, safe_float, safe_int, safe_str
from core.data_manager import (
    list_saved_sessions, load_extracted_data, delete_session,
    save_extracted_data, get_default_simulation_config
)


def manage_simulations_page():
    """Page for managing saved sessions, auditing data, and configuring simulation rounds."""
    st.markdown('<h1 class="main-header">⚙️ Manage Simulations</h1>', unsafe_allow_html=True)
    st.markdown("Manage saved sessions, audit extracted data, and configure simulation rounds.")

    # Initialize audit session state
    if 'audit_loaded_file' not in st.session_state:
        st.session_state.audit_loaded_file = None
    if 'audit_data' not in st.session_state:
        st.session_state.audit_data = None
    if 'audit_modified' not in st.session_state:
        st.session_state.audit_modified = False

    tab_sessions, tab_audit, tab_planning = st.tabs([
        "💾 Saved Sessions", "🔍 Audit Data", "🎮 Simulation Planning"
    ])

    # ==================== TAB 1: SAVED SESSIONS ====================
    with tab_sessions:
        st.header("💾 Saved Sessions")

        sessions = list_saved_sessions()

        if sessions:
            for session in sessions:
                with st.expander(f"📁 {session['session_name']}", expanded=False):
                    col1, col2, col3 = st.columns([2, 2, 1])

                    with col1:
                        st.markdown(f"**Company:** {session['company_name']}")
                        st.markdown(f"**Module:** {session['module_name']}")

                    with col2:
                        st.markdown(f"**Created:** {session['created_at'][:19].replace('T', ' ')}")
                        st.markdown(f"**File:** `{session['filename']}`")

                    with col3:
                        if st.button("🗑️ Delete", key=f"del_{session['filename']}"):
                            if delete_session(session['filepath']):
                                st.success("Deleted!")
                                st.rerun()

                        if st.button("📂 Load for Audit", key=f"load_{session['filename']}"):
                            data = load_extracted_data(session['filepath'])
                            if data:
                                # Ensure data structure integrity
                                if 'company_data' not in data or data['company_data'] is None:
                                    data['company_data'] = {}
                                if 'module_data' not in data or data['module_data'] is None:
                                    data['module_data'] = {}

                                company_defaults = ['metrics', 'board_members', 'current_problems', 'committees']
                                for key in company_defaults:
                                    if key not in data['company_data'] or data['company_data'][key] is None:
                                        data['company_data'][key] = {} if key == 'metrics' else []

                                module_defaults = ['topics', 'frameworks', 'learning_objectives', 'assessment_criteria', 'key_terms']
                                for key in module_defaults:
                                    if key not in data['module_data'] or data['module_data'][key] is None:
                                        data['module_data'][key] = {} if key == 'key_terms' else []

                                st.session_state.audit_data = data
                                st.session_state.audit_loaded_file = session['filepath']
                                st.session_state.audit_modified = False
                                st.success("Data loaded! Switch to 'Audit Data' tab to review and edit.")
                                st.rerun()
        else:
            st.info("No saved sessions found. Use **Create Simulation** to add new simulations.")

    # ==================== TAB 2: AUDIT DATA ====================
    with tab_audit:
        st.header("🔍 Audit Extracted Data")
        st.markdown("Review, edit, add, or remove extracted information before simulation.")

        # Load session for auditing
        if not st.session_state.audit_data:
            st.subheader("📂 Select Session to Audit")
            sessions = list_saved_sessions()

            if not sessions:
                st.warning("No saved sessions found. Please create a simulation first.")
            else:
                session_options = {s['display_name']: s['filepath'] for s in sessions}
                selected_session = st.selectbox(
                    "Choose a session to audit",
                    options=list(session_options.keys()),
                    key="audit_session_select"
                )

                col1, col2 = st.columns([1, 4])
                with col1:
                    if st.button("🔄 Load for Audit", type="primary"):
                        filepath = session_options[selected_session]
                        data = load_extracted_data(filepath)
                        if data:
                            if 'company_data' not in data or data['company_data'] is None:
                                data['company_data'] = {}
                            if 'module_data' not in data or data['module_data'] is None:
                                data['module_data'] = {}

                            company_defaults = ['metrics', 'board_members', 'current_problems', 'committees']
                            for key in company_defaults:
                                if key not in data['company_data'] or data['company_data'][key] is None:
                                    data['company_data'][key] = {} if key == 'metrics' else []

                            module_defaults = ['topics', 'frameworks', 'learning_objectives', 'assessment_criteria', 'key_terms']
                            for key in module_defaults:
                                if key not in data['module_data'] or data['module_data'][key] is None:
                                    data['module_data'][key] = {} if key == 'key_terms' else []

                            st.session_state.audit_data = data
                            st.session_state.audit_loaded_file = filepath
                            st.session_state.audit_modified = False
                            st.success("Session loaded for auditing!")
                            st.rerun()

                with col2:
                    if st.session_state.audit_modified:
                        st.warning("⚠️ You have unsaved changes!")

        if st.session_state.audit_data:
            st.divider()
            st.info("💡 Changes made here are independent of the Simulation Planning tab. Remember to save your changes before switching tabs.")

            audit_tab1, audit_tab2 = st.tabs(["🏢 Company Data", "📚 Module Data"])

            # ============ COMPANY DATA AUDIT ============
            with audit_tab1:
                _render_company_audit()

            # ============ MODULE DATA AUDIT ============
            with audit_tab2:
                _render_module_audit()

            # Save Changes Section
            st.divider()
            st.subheader("💾 Save Changes")

            col1, col2, col3 = st.columns([2, 2, 2])

            with col1:
                if st.button("💾 Save to Current File", type="primary", disabled=not st.session_state.audit_modified):
                    if st.session_state.audit_loaded_file:
                        st.session_state.audit_data['modified_at'] = datetime.now().isoformat()
                        with open(st.session_state.audit_loaded_file, 'w', encoding='utf-8') as f:
                            json.dump(st.session_state.audit_data, f, indent=2, ensure_ascii=False)
                        st.session_state.audit_modified = False
                        st.success("Changes saved successfully!")
                        st.rerun()

            with col2:
                new_session_name = st.text_input("New Session Name", key="audit_new_session_name", placeholder="Enter name to save as new")

            with col3:
                if st.button("💾 Save as New Session"):
                    if new_session_name:
                        st.session_state.audit_data['session_name'] = new_session_name
                        st.session_state.audit_data['created_at'] = datetime.now().isoformat()
                        filepath = save_extracted_data(
                            st.session_state.audit_data.get('company_data', {}),
                            st.session_state.audit_data.get('module_data', {}),
                            new_session_name
                        )
                        st.session_state.audit_modified = False
                        st.success(f"Saved as new session: {filepath}")
                    else:
                        st.error("Please enter a session name")

            # View and Export JSON
            _render_json_export()

    # ==================== TAB 3: SIMULATION PLANNING ====================
    with tab_planning:
        st.header("🎮 Simulation Planning")
        st.markdown("Configure how the simulation will flow: number of rounds, difficulty progression, and content focus.")

        if 'simulation_config' not in st.session_state:
            st.session_state.simulation_config = get_default_simulation_config()

        _render_simulation_planning()


# ==================== COMPANY AUDIT HELPERS ====================

def _render_company_audit():
    """Render the company data audit UI."""
    company_data = st.session_state.audit_data.get('company_data', {})

    # Basic Info
    st.subheader("📋 Basic Information")
    col1, col2 = st.columns(2)

    with col1:
        new_company_name = st.text_input(
            "Company Name",
            value=company_data.get('company_name', ''),
            key="audit_company_name"
        )
        if new_company_name != company_data.get('company_name', ''):
            st.session_state.audit_data['company_data']['company_name'] = new_company_name
            st.session_state.audit_modified = True

    with col2:
        new_scenario = st.text_input(
            "Initial Scenario",
            value=company_data.get('initial_scenario', ''),
            key="audit_initial_scenario"
        )
        if new_scenario != company_data.get('initial_scenario', ''):
            st.session_state.audit_data['company_data']['initial_scenario'] = new_scenario
            st.session_state.audit_modified = True

    new_overview = st.text_area(
        "Company Overview",
        value=company_data.get('company_overview', ''),
        height=100,
        key="audit_company_overview"
    )
    if new_overview != company_data.get('company_overview', ''):
        st.session_state.audit_data['company_data']['company_overview'] = new_overview
        st.session_state.audit_modified = True

    st.divider()

    # Metrics
    _render_metrics_audit(company_data)
    st.divider()

    # Board Members
    _render_board_members_audit(company_data)
    st.divider()

    # Committees
    _render_committees_audit(company_data)
    st.divider()

    # Current Problems
    _render_problems_audit(company_data)


def _render_metrics_audit(company_data):
    """Render metrics audit section."""
    st.subheader("📊 Metrics")
    metrics = company_data.get('metrics', {})
    priority_options = ["General", "High", "Medium"]

    # Add new metric
    with st.expander("➕ Add New Metric", expanded=False):
        col1, col2, col3, col4, col5 = st.columns([2, 1, 1, 1, 1])
        with col1:
            new_metric_name = st.text_input("Metric Name (key)", key="new_metric_name", placeholder="e.g., market_share")
        with col2:
            new_metric_value = st.number_input("Value", key="new_metric_value", value=0.0)
        with col3:
            new_metric_unit = st.text_input("Unit", key="new_metric_unit", placeholder="e.g., %")
        with col4:
            new_metric_desc = st.text_input("Description", key="new_metric_desc", placeholder="e.g., Market Share")
        with col5:
            new_metric_priority = st.selectbox("Priority", options=priority_options, key="new_metric_priority", index=0)

        if st.button("Add Metric", key="add_metric_btn"):
            if new_metric_name and new_metric_name not in metrics:
                priority_value = new_metric_priority if new_metric_priority in ["High", "Medium"] else None
                st.session_state.audit_data['company_data']['metrics'][new_metric_name] = {
                    "value": new_metric_value,
                    "unit": new_metric_unit,
                    "description": new_metric_desc,
                    "priority": priority_value
                }
                st.session_state.audit_modified = True
                st.success(f"Added metric: {new_metric_name}")
                st.rerun()
            elif new_metric_name in metrics:
                st.error("Metric with this name already exists!")
            else:
                st.error("Please enter a metric name")

    # Edit/Remove existing metrics
    with st.expander(f"📝 Edit Metrics ({len(metrics)} total)", expanded=True):
        metrics_to_remove = []
        for metric_key, metric_info in metrics.items():
            st.markdown(f"**{metric_key}**")
            col1, col2, col3, col4, col5 = st.columns([1, 1, 2, 1, 0.5])
            metric_safe = safe_key("metric", metric_key)

            if isinstance(metric_info, dict):
                with col1:
                    new_val = st.number_input(
                        "Value",
                        value=safe_float(metric_info.get('value', 0), 0.0),
                        key=f"val_{metric_safe}",
                        label_visibility="collapsed"
                    )
                    if new_val != metric_info.get('value'):
                        st.session_state.audit_data['company_data']['metrics'][metric_key]['value'] = new_val
                        st.session_state.audit_modified = True

                with col2:
                    new_unit = st.text_input(
                        "Unit",
                        value=metric_info.get('unit', '') or '',
                        key=f"unit_{metric_safe}",
                        label_visibility="collapsed"
                    )
                    if new_unit != metric_info.get('unit'):
                        st.session_state.audit_data['company_data']['metrics'][metric_key]['unit'] = new_unit
                        st.session_state.audit_modified = True

                with col3:
                    new_desc = st.text_input(
                        "Description",
                        value=metric_info.get('description', '') or '',
                        key=f"desc_{metric_safe}",
                        label_visibility="collapsed"
                    )
                    if new_desc != metric_info.get('description'):
                        st.session_state.audit_data['company_data']['metrics'][metric_key]['description'] = new_desc
                        st.session_state.audit_modified = True

                with col4:
                    current_priority_raw = metric_info.get('priority')
                    current_priority = current_priority_raw if current_priority_raw in ["High", "Medium"] else 'General'
                    priority_idx = safe_index(priority_options, current_priority, 0)
                    new_priority = st.selectbox(
                        "Priority",
                        options=priority_options,
                        index=priority_idx,
                        key=f"priority_{metric_safe}",
                        label_visibility="collapsed"
                    )
                    if new_priority != current_priority:
                        priority_value = new_priority if new_priority in ["High", "Medium"] else None
                        st.session_state.audit_data['company_data']['metrics'][metric_key]['priority'] = priority_value
                        st.session_state.audit_modified = True

                with col5:
                    if st.button("🗑️", key=f"del_{metric_safe}", help="Remove this metric"):
                        metrics_to_remove.append(metric_key)
            else:
                with col1:
                    st.write(str(metric_info))
                with col5:
                    if st.button("🗑️", key=f"del_{metric_safe}", help="Remove this metric"):
                        metrics_to_remove.append(metric_key)

            st.markdown("---")

        for key in metrics_to_remove:
            del st.session_state.audit_data['company_data']['metrics'][key]
            st.session_state.audit_modified = True
        if metrics_to_remove:
            st.rerun()


def _render_board_members_audit(company_data):
    """Render board members audit section."""
    st.subheader("👥 Board Members")

    # Add new board member
    with st.expander("➕ Add New Board Member", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            new_member_name = st.text_input("Name", key="new_member_name")
        with col2:
            new_member_role = st.text_input("Role/Title", key="new_member_role")

        col1, col2 = st.columns(2)
        with col1:
            new_member_expertise = st.text_input("Expertise/Domain", key="new_member_expertise", placeholder="e.g., Finance, Technology, Legal")
        with col2:
            new_member_tenure = st.number_input("Tenure (years)", key="new_member_tenure", min_value=0, max_value=50, value=0)

        new_member_personality = st.text_area("Personality Description", key="new_member_personality", height=80)

        if st.button("Add Board Member", key="add_member_btn"):
            if new_member_name and new_member_role:
                st.session_state.audit_data['company_data']['board_members'].append({
                    "name": new_member_name,
                    "role": new_member_role,
                    "expertise": new_member_expertise,
                    "tenure_years": new_member_tenure,
                    "personality": new_member_personality
                })
                st.session_state.audit_modified = True
                st.success(f"Added board member: {new_member_name}")
                st.rerun()
            else:
                st.error("Please enter name and role")

    # Edit/Remove board members
    current_board_members = st.session_state.audit_data.get('company_data', {}).get('board_members', [])
    with st.expander(f"📝 Edit Board Members ({len(current_board_members)} total)", expanded=True):
        members_to_remove = []
        for i, member in enumerate(current_board_members):
            st.markdown(f"**👤 {member.get('name', f'Member {i+1}')}**")
            col1, col2, col3 = st.columns([2, 2, 0.5])

            with col1:
                current_name = st.session_state.audit_data['company_data']['board_members'][i].get('name', '')
                new_name = st.text_input("Name", value=current_name, key=f"member_name_{i}")
                if new_name != current_name:
                    st.session_state.audit_data['company_data']['board_members'][i]['name'] = new_name
                    st.session_state.audit_modified = True

            with col2:
                current_role = st.session_state.audit_data['company_data']['board_members'][i].get('role', '')
                new_role = st.text_input("Role", value=current_role, key=f"member_role_{i}")
                if new_role != current_role:
                    st.session_state.audit_data['company_data']['board_members'][i]['role'] = new_role
                    st.session_state.audit_modified = True

            with col3:
                if st.button("🗑️", key=f"del_member_{i}", help="Remove this member"):
                    members_to_remove.append(i)

            col1, col2 = st.columns(2)
            with col1:
                current_expertise = st.session_state.audit_data['company_data']['board_members'][i].get('expertise', '')
                new_expertise = st.text_input("Expertise/Domain", value=current_expertise, key=f"member_expertise_{i}", placeholder="e.g., Finance, Technology")
                if new_expertise != current_expertise:
                    st.session_state.audit_data['company_data']['board_members'][i]['expertise'] = new_expertise
                    st.session_state.audit_modified = True

            with col2:
                current_tenure = st.session_state.audit_data['company_data']['board_members'][i].get('tenure_years', 0)
                new_tenure = st.number_input("Tenure (years)", value=safe_int(current_tenure, 0), min_value=0, max_value=50, key=f"member_tenure_{i}")
                if new_tenure != current_tenure:
                    st.session_state.audit_data['company_data']['board_members'][i]['tenure_years'] = new_tenure
                    st.session_state.audit_modified = True

            current_personality = st.session_state.audit_data['company_data']['board_members'][i].get('personality', '')
            new_personality = st.text_area("Personality", value=current_personality, key=f"member_personality_{i}", height=60)
            if new_personality != current_personality:
                st.session_state.audit_data['company_data']['board_members'][i]['personality'] = new_personality
                st.session_state.audit_modified = True

            st.markdown("---")

        for idx in sorted(members_to_remove, reverse=True):
            del st.session_state.audit_data['company_data']['board_members'][idx]
            st.session_state.audit_modified = True
        if members_to_remove:
            st.rerun()


def _render_committees_audit(company_data):
    """Render committees audit section."""
    st.subheader("🏛️ Board Committees")

    if 'committees' not in st.session_state.audit_data['company_data']:
        st.session_state.audit_data['company_data']['committees'] = []

    committees = st.session_state.audit_data['company_data'].get('committees', [])
    board_members = company_data.get('board_members', [])
    member_names = [m.get('name', f"Member {i+1}") for i, m in enumerate(board_members)]

    committee_types = [
        "Audit Committee", "Risk Management Committee",
        "Nomination & Remuneration Committee", "Corporate Social Responsibility Committee",
        "Stakeholders Relationship Committee", "Strategy Committee",
        "Finance Committee", "Technology Committee",
        "Compliance Committee", "Executive Committee",
        "Governance Committee", "Custom"
    ]

    # Add new committee
    with st.expander("➕ Create New Committee", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            committee_type = st.selectbox("Committee Type", options=committee_types, key="new_committee_type")
        with col2:
            if committee_type == "Custom":
                new_committee_name = st.text_input("Custom Committee Name", key="new_custom_committee_name", placeholder="Enter committee name")
            else:
                new_committee_name = committee_type
                st.text_input("Committee Name", value=committee_type, key="new_committee_name_display", disabled=True)

        new_committee_purpose = st.text_area("Committee Purpose/Mandate", key="new_committee_purpose", height=60, placeholder="Describe the committee's purpose...")

        st.markdown("**Select Committee Members:**")
        if member_names:
            selected_members = st.multiselect("Choose board members for this committee", options=member_names, key="new_committee_members")
            if selected_members:
                committee_chair = st.selectbox("Committee Chairperson", options=["None"] + selected_members, key="new_committee_chair")
            else:
                committee_chair = "None"
        else:
            st.warning("No board members available. Please add board members first.")
            selected_members = []
            committee_chair = "None"

        if st.button("Create Committee", key="create_committee_btn"):
            if new_committee_name and selected_members:
                existing_names = [c.get('name', '').lower() for c in committees]
                if new_committee_name.lower() in existing_names:
                    st.error(f"A committee named '{new_committee_name}' already exists!")
                else:
                    new_committee = {
                        "name": new_committee_name,
                        "type": committee_type if committee_type != "Custom" else "Custom",
                        "purpose": new_committee_purpose,
                        "members": selected_members,
                        "chairperson": committee_chair if committee_chair != "None" else None,
                        "created_at": datetime.now().isoformat()
                    }
                    st.session_state.audit_data['company_data']['committees'].append(new_committee)
                    st.session_state.audit_modified = True
                    st.success(f"Created committee: {new_committee_name} with {len(selected_members)} members")
                    st.rerun()
            elif not new_committee_name:
                st.error("Please enter a committee name")
            else:
                st.error("Please select at least one member for the committee")

    # Edit existing committees
    if committees:
        with st.expander(f"📝 Manage Committees ({len(committees)} total)", expanded=True):
            committees_to_remove = []
            for i, committee in enumerate(committees):
                st.markdown(f"### 🏛️ {committee.get('name', 'Unnamed Committee')}")
                col1, col2, col3 = st.columns([3, 3, 1])

                with col1:
                    edited_name = st.text_input("Committee Name", value=committee.get('name', ''), key=f"committee_name_{i}")
                    if edited_name != committee.get('name'):
                        st.session_state.audit_data['company_data']['committees'][i]['name'] = edited_name
                        st.session_state.audit_modified = True

                with col2:
                    current_committee_type = committee.get('type', 'Custom')
                    committee_type_index = safe_index(committee_types, current_committee_type, safe_index(committee_types, 'Custom', 0))
                    edited_type = st.selectbox("Type", options=committee_types, index=committee_type_index, key=f"committee_type_{i}")
                    if edited_type != committee.get('type'):
                        st.session_state.audit_data['company_data']['committees'][i]['type'] = edited_type
                        st.session_state.audit_modified = True

                with col3:
                    st.markdown("<br>", unsafe_allow_html=True)
                    if st.button("🗑️ Delete", key=f"del_committee_{i}", help="Delete this committee"):
                        committees_to_remove.append(i)

                edited_purpose = st.text_area("Purpose/Mandate", value=committee.get('purpose', ''), key=f"committee_purpose_{i}", height=60)
                if edited_purpose != committee.get('purpose'):
                    st.session_state.audit_data['company_data']['committees'][i]['purpose'] = edited_purpose
                    st.session_state.audit_modified = True

                current_members = committee.get('members', [])
                valid_current_members = [m for m in current_members if m in member_names]
                edited_members = st.multiselect("Committee Members", options=member_names, default=valid_current_members, key=f"committee_members_{i}")
                if set(edited_members) != set(current_members):
                    st.session_state.audit_data['company_data']['committees'][i]['members'] = edited_members
                    st.session_state.audit_modified = True

                current_chair = committee.get('chairperson')
                chair_options = ["None"] + edited_members
                current_chair_index = 0
                if current_chair and current_chair in edited_members:
                    current_chair_index = chair_options.index(current_chair)

                edited_chair = st.selectbox("Chairperson", options=chair_options, index=current_chair_index, key=f"committee_chair_{i}")
                new_chair_value = edited_chair if edited_chair != "None" else None
                if new_chair_value != current_chair:
                    st.session_state.audit_data['company_data']['committees'][i]['chairperson'] = new_chair_value
                    st.session_state.audit_modified = True

                col1, col2 = st.columns(2)
                with col1:
                    st.info(f"👥 {len(edited_members)} member(s)")
                with col2:
                    if new_chair_value:
                        st.info(f"👤 Chair: {new_chair_value}")

                st.markdown("---")

            for idx in sorted(committees_to_remove, reverse=True):
                del st.session_state.audit_data['company_data']['committees'][idx]
                st.session_state.audit_modified = True
            if committees_to_remove:
                st.rerun()
    else:
        st.info("No committees created yet. Use the form above to create a committee.")

    # Committee Summary
    if committees:
        with st.expander("📊 Committee Summary", expanded=False):
            st.markdown("### Committee Overview")
            for committee in committees:
                st.markdown(f"**{committee.get('name', 'Unnamed')}**")
                chair = committee.get('chairperson', 'Not assigned')
                members = committee.get('members', [])
                st.markdown(f"- **Chairperson:** {chair if chair else 'Not assigned'}")
                st.markdown(f"- **Members ({len(members)}):** {', '.join(members) if members else 'None'}")
                if committee.get('purpose'):
                    st.markdown(f"- **Purpose:** {committee.get('purpose')[:100]}{'...' if len(committee.get('purpose', '')) > 100 else ''}")
                st.markdown("")

            st.markdown("### Member Participation")
            for member in member_names:
                comms = []
                for committee in committees:
                    if member in committee.get('members', []):
                        role = "Chair" if committee.get('chairperson') == member else "Member"
                        comms.append(f"{committee.get('name')} ({role})")
                if comms:
                    st.markdown(f"**{member}:** {', '.join(comms)}")
                else:
                    st.markdown(f"**{member}:** _No committee assignments_")


def _render_problems_audit(company_data):
    """Render current problems audit section."""
    st.subheader("⚠️ Current Problems")
    problems = company_data.get('current_problems', [])

    with st.expander("➕ Add New Problem", expanded=False):
        new_problem = st.text_area("Problem Description", key="new_problem_text", height=60)
        if st.button("Add Problem", key="add_problem_btn"):
            if new_problem:
                st.session_state.audit_data['company_data']['current_problems'].append(new_problem)
                st.session_state.audit_modified = True
                st.success("Added new problem!")
                st.rerun()
            else:
                st.error("Please enter a problem description")

    with st.expander(f"📝 Edit Problems ({len(problems)} total)", expanded=True):
        problems_to_remove = []
        for i, problem in enumerate(problems):
            col1, col2 = st.columns([10, 1])
            with col1:
                new_problem_text = st.text_area(f"Problem {i+1}", value=problem, key=f"problem_{i}", height=60, label_visibility="collapsed")
                if new_problem_text != problem:
                    st.session_state.audit_data['company_data']['current_problems'][i] = new_problem_text
                    st.session_state.audit_modified = True
            with col2:
                if st.button("🗑️", key=f"del_problem_{i}", help="Remove this problem"):
                    problems_to_remove.append(i)
            st.markdown("---")

        for idx in sorted(problems_to_remove, reverse=True):
            del st.session_state.audit_data['company_data']['current_problems'][idx]
            st.session_state.audit_modified = True
        if problems_to_remove:
            st.rerun()


# ==================== MODULE AUDIT HELPERS ====================

def _render_module_audit():
    """Render the module data audit UI."""
    module_data = st.session_state.audit_data.get('module_data', {})

    # Basic Info
    st.subheader("📋 Basic Information")
    col1, col2 = st.columns(2)

    with col1:
        new_module_name = st.text_input("Module Name", value=module_data.get('module_name', ''), key="audit_module_name")
        if new_module_name != module_data.get('module_name', ''):
            st.session_state.audit_data['module_data']['module_name'] = new_module_name
            st.session_state.audit_modified = True

    with col2:
        new_subject = st.text_input("Subject Area", value=module_data.get('subject_area', ''), key="audit_subject_area")
        if new_subject != module_data.get('subject_area', ''):
            st.session_state.audit_data['module_data']['subject_area'] = new_subject
            st.session_state.audit_modified = True

    new_module_overview = st.text_area("Overview", value=module_data.get('overview', ''), height=80, key="audit_module_overview")
    if new_module_overview != module_data.get('overview', ''):
        st.session_state.audit_data['module_data']['overview'] = new_module_overview
        st.session_state.audit_modified = True

    st.divider()

    # Learning Objectives
    _render_objectives_audit(module_data)
    st.divider()

    # Topics
    _render_topics_audit(module_data)
    st.divider()

    # Key Terms
    _render_terms_audit(module_data)
    st.divider()

    # Frameworks
    _render_frameworks_audit(module_data)
    st.divider()

    # Assessment Criteria
    _render_criteria_audit(module_data)


def _render_objectives_audit(module_data):
    """Render learning objectives audit section."""
    st.subheader("🎯 Learning Objectives")
    objectives = module_data.get('learning_objectives', [])

    with st.expander("➕ Add New Objective", expanded=False):
        new_objective = st.text_input("Objective", key="new_objective_text")
        if st.button("Add Objective", key="add_objective_btn"):
            if new_objective:
                if 'learning_objectives' not in st.session_state.audit_data['module_data']:
                    st.session_state.audit_data['module_data']['learning_objectives'] = []
                st.session_state.audit_data['module_data']['learning_objectives'].append(new_objective)
                st.session_state.audit_modified = True
                st.success("Added objective!")
                st.rerun()

    with st.expander(f"📝 Edit Objectives ({len(objectives)} total)", expanded=True):
        obj_to_remove = []
        for i, obj in enumerate(objectives):
            col1, col2 = st.columns([10, 1])
            with col1:
                new_obj = st.text_input(f"Objective {i+1}", value=obj, key=f"obj_{i}", label_visibility="collapsed")
                if new_obj != obj:
                    st.session_state.audit_data['module_data']['learning_objectives'][i] = new_obj
                    st.session_state.audit_modified = True
            with col2:
                if st.button("🗑️", key=f"del_obj_{i}"):
                    obj_to_remove.append(i)

        for idx in sorted(obj_to_remove, reverse=True):
            del st.session_state.audit_data['module_data']['learning_objectives'][idx]
            st.session_state.audit_modified = True
        if obj_to_remove:
            st.rerun()


def _render_topics_audit(module_data):
    """Render topics audit section."""
    st.subheader("📚 Topics")
    topics = module_data.get('topics', [])

    with st.expander("➕ Add New Topic", expanded=False):
        new_topic_name = st.text_input("Topic Name", key="new_topic_name")
        new_topic_desc = st.text_area("Description", key="new_topic_desc", height=60)
        new_topic_principles = st.text_input("Key Principles (comma-separated)", key="new_topic_principles")
        new_topic_application = st.text_input("Application", key="new_topic_application")

        if st.button("Add Topic", key="add_topic_btn"):
            if new_topic_name:
                if 'topics' not in st.session_state.audit_data['module_data']:
                    st.session_state.audit_data['module_data']['topics'] = []
                st.session_state.audit_data['module_data']['topics'].append({
                    "name": new_topic_name,
                    "description": new_topic_desc,
                    "key_principles": [p.strip() for p in new_topic_principles.split(',') if p.strip()],
                    "formulas": [],
                    "application": new_topic_application,
                    "examples": []
                })
                st.session_state.audit_modified = True
                st.success(f"Added topic: {new_topic_name}")
                st.rerun()

    with st.expander(f"📝 Edit Topics ({len(topics)} total)", expanded=True):
        topics_to_remove = []
        for i, topic in enumerate(topics):
            st.markdown(f"**Topic {i+1}: {topic.get('name', 'Unnamed')}**")
            col1, col2 = st.columns([10, 1])

            with col1:
                new_name = st.text_input("Name", value=topic.get('name', ''), key=f"topic_name_{i}")
                if new_name != topic.get('name'):
                    st.session_state.audit_data['module_data']['topics'][i]['name'] = new_name
                    st.session_state.audit_modified = True

                new_desc = st.text_area("Description", value=topic.get('description', ''), key=f"topic_desc_{i}", height=60)
                if new_desc != topic.get('description'):
                    st.session_state.audit_data['module_data']['topics'][i]['description'] = new_desc
                    st.session_state.audit_modified = True

                new_app = st.text_input("Application", value=topic.get('application', ''), key=f"topic_app_{i}")
                if new_app != topic.get('application'):
                    st.session_state.audit_data['module_data']['topics'][i]['application'] = new_app
                    st.session_state.audit_modified = True

            with col2:
                if st.button("🗑️", key=f"del_topic_{i}"):
                    topics_to_remove.append(i)

            st.markdown("---")

        for idx in sorted(topics_to_remove, reverse=True):
            del st.session_state.audit_data['module_data']['topics'][idx]
            st.session_state.audit_modified = True
        if topics_to_remove:
            st.rerun()


def _render_terms_audit(module_data):
    """Render key terms audit section."""
    st.subheader("📖 Key Terms")
    terms = module_data.get('key_terms', {})

    with st.expander("➕ Add New Term", expanded=False):
        new_term = st.text_input("Term", key="new_term_name")
        new_definition = st.text_area("Definition", key="new_term_def", height=60)
        if st.button("Add Term", key="add_term_btn"):
            if new_term and new_term not in terms:
                if 'key_terms' not in st.session_state.audit_data['module_data']:
                    st.session_state.audit_data['module_data']['key_terms'] = {}
                st.session_state.audit_data['module_data']['key_terms'][new_term] = new_definition
                st.session_state.audit_modified = True
                st.success(f"Added term: {new_term}")
                st.rerun()
            elif new_term in terms:
                st.error("Term already exists!")

    with st.expander(f"📝 Edit Terms ({len(terms)} total)", expanded=True):
        terms_to_remove = []
        for term, definition in terms.items():
            col1, col2 = st.columns([10, 1])
            term_safe = safe_key("term", term)

            with col1:
                st.markdown(f"**{term}**")
                new_def = st.text_area("Definition", value=definition or '', key=f"def_{term_safe}", height=60, label_visibility="collapsed")
                if new_def != definition:
                    st.session_state.audit_data['module_data']['key_terms'][term] = new_def
                    st.session_state.audit_modified = True

            with col2:
                if st.button("🗑️", key=f"del_{term_safe}"):
                    terms_to_remove.append(term)

            st.markdown("---")

        for term_key in terms_to_remove:
            del st.session_state.audit_data['module_data']['key_terms'][term_key]
            st.session_state.audit_modified = True
        if terms_to_remove:
            st.rerun()


def _render_frameworks_audit(module_data):
    """Render frameworks audit section."""
    st.subheader("🔧 Frameworks")
    frameworks = module_data.get('frameworks', [])

    with st.expander("➕ Add New Framework", expanded=False):
        new_fw_name = st.text_input("Framework Name", key="new_fw_name")
        new_fw_desc = st.text_area("Description", key="new_fw_desc", height=60)
        new_fw_components = st.text_input("Components (comma-separated)", key="new_fw_components")
        new_fw_scenario = st.text_input("Application Scenario", key="new_fw_scenario")

        if st.button("Add Framework", key="add_fw_btn"):
            if new_fw_name:
                if 'frameworks' not in st.session_state.audit_data['module_data']:
                    st.session_state.audit_data['module_data']['frameworks'] = []
                st.session_state.audit_data['module_data']['frameworks'].append({
                    "name": new_fw_name,
                    "description": new_fw_desc,
                    "components": [c.strip() for c in new_fw_components.split(',') if c.strip()],
                    "application_scenario": new_fw_scenario
                })
                st.session_state.audit_modified = True
                st.success(f"Added framework: {new_fw_name}")
                st.rerun()

    with st.expander(f"📝 Edit Frameworks ({len(frameworks)} total)", expanded=True):
        fw_to_remove = []
        for i, fw in enumerate(frameworks):
            st.markdown(f"**Framework {i+1}: {fw.get('name', 'Unnamed')}**")
            col1, col2 = st.columns([10, 1])

            with col1:
                new_name = st.text_input("Name", value=fw.get('name', ''), key=f"fw_name_{i}")
                if new_name != fw.get('name'):
                    st.session_state.audit_data['module_data']['frameworks'][i]['name'] = new_name
                    st.session_state.audit_modified = True

                new_desc = st.text_area("Description", value=fw.get('description', ''), key=f"fw_desc_{i}", height=60)
                if new_desc != fw.get('description'):
                    st.session_state.audit_data['module_data']['frameworks'][i]['description'] = new_desc
                    st.session_state.audit_modified = True

                new_scenario = st.text_input("Application Scenario", value=fw.get('application_scenario', ''), key=f"fw_scenario_{i}")
                if new_scenario != fw.get('application_scenario'):
                    st.session_state.audit_data['module_data']['frameworks'][i]['application_scenario'] = new_scenario
                    st.session_state.audit_modified = True

            with col2:
                if st.button("🗑️", key=f"del_fw_{i}"):
                    fw_to_remove.append(i)

            st.markdown("---")

        for idx in sorted(fw_to_remove, reverse=True):
            del st.session_state.audit_data['module_data']['frameworks'][idx]
            st.session_state.audit_modified = True
        if fw_to_remove:
            st.rerun()


def _render_criteria_audit(module_data):
    """Render assessment criteria audit section."""
    st.subheader("✅ Assessment Criteria")
    criteria = module_data.get('assessment_criteria', [])

    with st.expander("➕ Add New Criterion", expanded=False):
        new_criterion = st.text_input("Criterion", key="new_criterion_text")
        if st.button("Add Criterion", key="add_criterion_btn"):
            if new_criterion:
                if 'assessment_criteria' not in st.session_state.audit_data['module_data']:
                    st.session_state.audit_data['module_data']['assessment_criteria'] = []
                st.session_state.audit_data['module_data']['assessment_criteria'].append(new_criterion)
                st.session_state.audit_modified = True
                st.success("Added criterion!")
                st.rerun()

    with st.expander(f"📝 Edit Criteria ({len(criteria)} total)", expanded=True):
        criteria_to_remove = []
        for i, criterion in enumerate(criteria):
            col1, col2 = st.columns([10, 1])
            with col1:
                new_crit = st.text_input(f"Criterion {i+1}", value=criterion, key=f"crit_{i}", label_visibility="collapsed")
                if new_crit != criterion:
                    st.session_state.audit_data['module_data']['assessment_criteria'][i] = new_crit
                    st.session_state.audit_modified = True
            with col2:
                if st.button("🗑️", key=f"del_crit_{i}"):
                    criteria_to_remove.append(i)

        for idx in sorted(criteria_to_remove, reverse=True):
            del st.session_state.audit_data['module_data']['assessment_criteria'][idx]
            st.session_state.audit_modified = True
        if criteria_to_remove:
            st.rerun()


# ==================== JSON EXPORT HELPER ====================

def _render_json_export():
    """Render JSON view and export section."""
    if not st.session_state.audit_data:
        return

    st.divider()
    st.subheader("📄 View & Download JSON")

    if 'audit_export_timestamp' not in st.session_state:
        st.session_state.audit_export_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    view_tab1, view_tab2, view_tab3 = st.tabs(["📋 Full Data", "🏢 Company Only", "📚 Module Only"])

    with view_tab1:
        st.markdown("**Complete Session Data**")
        full_json = json.dumps(st.session_state.audit_data, indent=2, ensure_ascii=False)

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Size", f"{len(full_json):,} chars")
        with col2:
            st.metric("Metrics", len(st.session_state.audit_data.get('company_data', {}).get('metrics', {})))
        with col3:
            st.metric("Board Members", len(st.session_state.audit_data.get('company_data', {}).get('board_members', [])))

        with st.expander("👁️ View Full JSON", expanded=False):
            st.code(full_json, language="json")

        col1, col2, col3 = st.columns([2, 2, 1])
        with col1:
            st.download_button(
                label="⬇️ Download Full JSON", data=full_json,
                file_name=f"full_export_{st.session_state.audit_export_timestamp}.json",
                mime="application/json", key="download_full_json"
            )
        with col2:
            minified_json = json.dumps(st.session_state.audit_data, ensure_ascii=False)
            st.download_button(
                label="⬇️ Download Minified JSON", data=minified_json,
                file_name=f"full_export_minified_{st.session_state.audit_export_timestamp}.json",
                mime="application/json", key="download_full_minified"
            )
        with col3:
            if st.button("🔄", key="refresh_audit_export", help="Refresh export timestamp"):
                st.session_state.audit_export_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                st.rerun()

    with view_tab2:
        st.markdown("**Company Data Only**")
        company_json = json.dumps(st.session_state.audit_data.get('company_data', {}), indent=2, ensure_ascii=False)
        company_data_view = st.session_state.audit_data.get('company_data', {})

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Size", f"{len(company_json):,} chars")
        with col2:
            st.metric("Metrics", len(company_data_view.get('metrics', {})))
        with col3:
            st.metric("Board Members", len(company_data_view.get('board_members', [])))
        with col4:
            st.metric("Committees", len(company_data_view.get('committees', [])))

        with st.expander("👁️ View Company JSON", expanded=False):
            st.code(company_json, language="json")

        st.download_button(
            label="⬇️ Download Company JSON", data=company_json,
            file_name=f"company_export_{st.session_state.audit_export_timestamp}.json",
            mime="application/json", key="download_company_json"
        )

    with view_tab3:
        st.markdown("**Module Data Only**")
        module_json = json.dumps(st.session_state.audit_data.get('module_data', {}), indent=2, ensure_ascii=False)
        module_data_view = st.session_state.audit_data.get('module_data', {})

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Size", f"{len(module_json):,} chars")
        with col2:
            st.metric("Topics", len(module_data_view.get('topics', [])))
        with col3:
            st.metric("Key Terms", len(module_data_view.get('key_terms', {})))
        with col4:
            st.metric("Frameworks", len(module_data_view.get('frameworks', [])))

        with st.expander("👁️ View Module JSON", expanded=False):
            st.code(module_json, language="json")

        st.download_button(
            label="⬇️ Download Module JSON", data=module_json,
            file_name=f"module_export_{st.session_state.audit_export_timestamp}.json",
            mime="application/json", key="download_module_json"
        )


# ==================== SIMULATION PLANNING HELPER ====================

def _render_simulation_planning():
    """Render the simulation planning configuration UI."""
    st.subheader("📂 Select Session to Configure")
    sessions = list_saved_sessions()

    if not sessions:
        st.warning("No saved sessions found. Please create a simulation first.")
        return

    session_options = {s['display_name']: s['filepath'] for s in sessions}
    selected_planning_session = st.selectbox(
        "Choose a session to configure simulation",
        options=list(session_options.keys()),
        key="planning_session_select"
    )

    if st.button("🔄 Load Session Config", type="primary", key="load_planning_session"):
        filepath = session_options[selected_planning_session]
        data = load_extracted_data(filepath)
        if data:
            if 'simulation_config' in data and data['simulation_config']:
                loaded_config = data['simulation_config']
                default_config = get_default_simulation_config()

                if 'initial_setup' not in loaded_config or loaded_config['initial_setup'] is None:
                    loaded_config['initial_setup'] = default_config['initial_setup']
                else:
                    for key, value in default_config['initial_setup'].items():
                        if key not in loaded_config['initial_setup']:
                            loaded_config['initial_setup'][key] = value

                if 'rounds' not in loaded_config or loaded_config['rounds'] is None:
                    loaded_config['rounds'] = default_config['rounds']
                else:
                    for i, round_cfg in enumerate(loaded_config['rounds']):
                        if round_cfg is None:
                            loaded_config['rounds'][i] = default_config['rounds'][0].copy()
                            loaded_config['rounds'][i]['round_number'] = i + 1
                        else:
                            for key in ['round_type', 'difficulty', 'focus_area', 'time_pressure']:
                                if key not in round_cfg:
                                    round_cfg[key] = default_config['rounds'][0].get(key)

                if 'total_rounds' not in loaded_config:
                    loaded_config['total_rounds'] = len(loaded_config['rounds'])
                if 'difficulty_settings' not in loaded_config:
                    loaded_config['difficulty_settings'] = default_config['difficulty_settings']
                if 'round_type_settings' not in loaded_config:
                    loaded_config['round_type_settings'] = default_config['round_type_settings']

                st.session_state.simulation_config = loaded_config
            else:
                st.session_state.simulation_config = get_default_simulation_config()

            if 'company_data' not in data or data['company_data'] is None:
                data['company_data'] = {}
            if 'module_data' not in data or data['module_data'] is None:
                data['module_data'] = {}

            st.session_state.planning_loaded_file = filepath
            st.session_state.planning_session_data = data
            st.success("Session loaded! Configure the simulation below.")
            st.rerun()

    st.divider()

    # Only show config if a session is loaded
    if 'planning_session_data' not in st.session_state or not st.session_state.planning_session_data:
        st.info("Load a session above to configure simulation rounds.")
        return

    config = st.session_state.simulation_config

    # ============ SECTION 1: NUMBER OF ROUNDS ============
    st.subheader("1️⃣ Number of Rounds")
    col1, col2 = st.columns([1, 2])
    with col1:
        total_rounds = st.number_input(
            "Total Rounds", min_value=1, max_value=20,
            value=safe_int(config.get('total_rounds', 5), 5),
            key="total_rounds_input"
        )
        if total_rounds != config.get('total_rounds'):
            st.session_state.simulation_config['total_rounds'] = total_rounds
            current_rounds = len(config.get('rounds', []))
            if total_rounds > current_rounds:
                for i in range(current_rounds, total_rounds):
                    st.session_state.simulation_config['rounds'].append({
                        "round_number": i + 1, "round_type": "both",
                        "difficulty": "medium", "focus_area": None, "time_pressure": "normal"
                    })
            elif total_rounds < current_rounds:
                st.session_state.simulation_config['rounds'] = config['rounds'][:total_rounds]

    with col2:
        st.info(f"📊 The simulation will have **{total_rounds} rounds** of board decisions.")

    st.divider()

    # ============ SECTION 2: INITIAL SETUP ============
    st.subheader("2️⃣ Initial Setup (Deterministic Start)")
    initial_setup = config.get('initial_setup', {})

    col1, col2 = st.columns(2)
    with col1:
        scenario_options = {
            "default": "Default - Standard business conditions",
            "crisis": "Crisis - Company facing immediate challenges",
            "growth": "Growth - Expansion opportunities available",
            "stable": "Stable - Steady state operations",
            "custom": "Custom - Define your own scenario"
        }
        current_scenario = initial_setup.get('starting_scenario', 'default')
        is_custom_scenario = current_scenario not in ['default', 'crisis', 'growth', 'stable'] or current_scenario == 'custom'

        if is_custom_scenario and current_scenario != 'custom':
            scenario_idx = list(scenario_options.keys()).index('custom')
        else:
            scenario_idx = list(scenario_options.keys()).index(current_scenario) if current_scenario in scenario_options else 0

        starting_scenario = st.selectbox(
            "Starting Scenario", options=list(scenario_options.keys()),
            format_func=lambda x: scenario_options[x],
            index=scenario_idx, key="starting_scenario_select"
        )

        if starting_scenario == "custom":
            custom_scenario = st.text_area(
                "Custom Scenario Description",
                value=initial_setup.get('custom_scenario_text', '') if initial_setup.get('starting_scenario') == 'custom' or is_custom_scenario else '',
                key="custom_scenario_input", placeholder="Describe the starting scenario...", height=100
            )
            st.session_state.simulation_config['initial_setup']['starting_scenario'] = 'custom'
            st.session_state.simulation_config['initial_setup']['custom_scenario_text'] = custom_scenario
        else:
            st.session_state.simulation_config['initial_setup']['starting_scenario'] = starting_scenario
            if 'custom_scenario_text' in st.session_state.simulation_config['initial_setup']:
                st.session_state.simulation_config['initial_setup']['custom_scenario_text'] = ''

    with col2:
        init_difficulty_options = ["easy", "medium", "hard"]
        initial_difficulty = st.selectbox(
            "Initial Difficulty", options=init_difficulty_options,
            index=safe_index(init_difficulty_options, initial_setup.get('initial_difficulty', 'medium'), 1),
            key="initial_difficulty_select"
        )
        st.session_state.simulation_config['initial_setup']['initial_difficulty'] = initial_difficulty

    st.divider()

    # ============ SECTION 3: ROUND TYPE CONFIGURATION ============
    st.subheader("3️⃣ Round Type Configuration")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if st.button("Set All: Business", key="set_all_business"):
            for r in st.session_state.simulation_config['rounds']:
                r['round_type'] = 'business'
            st.rerun()
    with col2:
        if st.button("Set All: Module", key="set_all_module"):
            for r in st.session_state.simulation_config['rounds']:
                r['round_type'] = 'module'
            st.rerun()
    with col3:
        if st.button("Set All: Both", key="set_all_both"):
            for r in st.session_state.simulation_config['rounds']:
                r['round_type'] = 'both'
            st.rerun()
    with col4:
        if st.button("Alternate Pattern", key="set_alternate"):
            types = ['business', 'module', 'both']
            for i, r in enumerate(st.session_state.simulation_config['rounds']):
                r['round_type'] = types[i % 3]
            st.rerun()

    st.divider()

    # ============ SECTION 4: DIFFICULTY CONFIGURATION ============
    st.subheader("4️⃣ Difficulty Configuration")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if st.button("Set All: Easy", key="set_all_easy"):
            for r in st.session_state.simulation_config['rounds']:
                r['difficulty'] = 'easy'
            st.rerun()
    with col2:
        if st.button("Set All: Medium", key="set_all_medium"):
            for r in st.session_state.simulation_config['rounds']:
                r['difficulty'] = 'medium'
            st.rerun()
    with col3:
        if st.button("Set All: Hard", key="set_all_hard"):
            for r in st.session_state.simulation_config['rounds']:
                r['difficulty'] = 'hard'
            st.rerun()
    with col4:
        if st.button("Progressive (Easy→Hard)", key="set_progressive"):
            rounds = st.session_state.simulation_config['rounds']
            n = len(rounds)
            for i, r in enumerate(rounds):
                if i < n // 3:
                    r['difficulty'] = 'easy'
                elif i < 2 * n // 3:
                    r['difficulty'] = 'medium'
                else:
                    r['difficulty'] = 'hard'
            st.rerun()

    st.divider()

    # ============ DETAILED ROUND CONFIGURATION ============
    st.subheader("📋 Detailed Round Configuration")

    rounds = st.session_state.simulation_config.get('rounds', [])
    company_problems = st.session_state.planning_session_data.get('company_data', {}).get('current_problems', [])
    module_topics = [t.get('name', '') for t in st.session_state.planning_session_data.get('module_data', {}).get('topics', [])]
    focus_options = ["None (Auto-select)", "Custom (Enter below)"] + company_problems + module_topics

    for i, round_config in enumerate(rounds):
        with st.expander(f"Round {i + 1}", expanded=(i < 3)):
            col1, col2, col3, col4 = st.columns(4)

            with col1:
                round_type_options = ["business", "module", "both"]
                round_type = st.selectbox(
                    "Type", options=round_type_options,
                    index=safe_index(round_type_options, round_config.get('round_type', 'both'), 2),
                    key=f"round_type_{i}"
                )
                if round_type != round_config.get('round_type'):
                    st.session_state.simulation_config['rounds'][i]['round_type'] = round_type

            with col2:
                difficulty_options = ["easy", "medium", "hard"]
                difficulty = st.selectbox(
                    "Difficulty", options=difficulty_options,
                    index=safe_index(difficulty_options, round_config.get('difficulty', 'medium'), 1),
                    key=f"round_difficulty_{i}"
                )
                if difficulty != round_config.get('difficulty'):
                    st.session_state.simulation_config['rounds'][i]['difficulty'] = difficulty

            with col3:
                time_pressure_options = ["relaxed", "normal", "urgent"]
                time_pressure = st.selectbox(
                    "Time Pressure", options=time_pressure_options,
                    index=safe_index(time_pressure_options, round_config.get('time_pressure', 'normal'), 1),
                    key=f"round_time_{i}"
                )
                if time_pressure != round_config.get('time_pressure'):
                    st.session_state.simulation_config['rounds'][i]['time_pressure'] = time_pressure

            with col4:
                current_focus = round_config.get('focus_area') or "None (Auto-select)"
                is_custom = current_focus not in focus_options and current_focus != "None (Auto-select)"
                if is_custom:
                    focus_idx = 1
                else:
                    focus_idx = focus_options.index(current_focus) if current_focus in focus_options else 0

                focus_area = st.selectbox(
                    "Focus Area", options=focus_options, index=focus_idx, key=f"round_focus_{i}"
                )

            if focus_area == "Custom (Enter below)":
                custom_focus = st.text_input(
                    "Custom Focus Area",
                    value=round_config.get('focus_area', '') if round_config.get('focus_area') not in focus_options else '',
                    key=f"round_custom_focus_{i}", placeholder="Enter your custom focus area..."
                )
                if custom_focus:
                    if custom_focus != round_config.get('focus_area'):
                        st.session_state.simulation_config['rounds'][i]['focus_area'] = custom_focus
                else:
                    if round_config.get('focus_area') is not None:
                        st.session_state.simulation_config['rounds'][i]['focus_area'] = None
            else:
                new_focus = None if focus_area == "None (Auto-select)" else focus_area
                if new_focus != round_config.get('focus_area'):
                    st.session_state.simulation_config['rounds'][i]['focus_area'] = new_focus

    st.divider()

    # ============ VISUAL SUMMARY ============
    st.subheader("📊 Configuration Summary")

    summary_data = []
    for i, r in enumerate(st.session_state.simulation_config.get('rounds', [])):
        type_emoji = {"business": "🏢", "module": "📚", "both": "🔄"}.get(r.get('round_type', 'both'), "🔄")
        diff_emoji = {"easy": "🟢", "medium": "🟡", "hard": "🔴"}.get(r.get('difficulty', 'medium'), "🟡")
        time_emoji = {"relaxed": "🐢", "normal": "⏱️", "urgent": "⚡"}.get(r.get('time_pressure', 'normal'), "⏱️")

        focus_area_value = r.get('focus_area')
        if focus_area_value and len(str(focus_area_value)) > 20:
            focus_display = str(focus_area_value)[:20] + '...'
        elif focus_area_value:
            focus_display = str(focus_area_value)
        else:
            focus_display = 'Auto'

        summary_data.append({
            "Round": i + 1,
            "Type": f"{type_emoji} {safe_str(r.get('round_type'), 'both').title()}",
            "Difficulty": f"{diff_emoji} {safe_str(r.get('difficulty'), 'medium').title()}",
            "Time": f"{time_emoji} {safe_str(r.get('time_pressure'), 'normal').title()}",
            "Focus": focus_display
        })

    col_headers = st.columns(5)
    col_headers[0].markdown("**Round**")
    col_headers[1].markdown("**Type**")
    col_headers[2].markdown("**Difficulty**")
    col_headers[3].markdown("**Time**")
    col_headers[4].markdown("**Focus**")

    for row in summary_data:
        cols = st.columns(5)
        cols[0].write(row["Round"])
        cols[1].write(row["Type"])
        cols[2].write(row["Difficulty"])
        cols[3].write(row["Time"])
        cols[4].write(row["Focus"])

    st.divider()

    # ============ SAVE CONFIGURATION ============
    st.subheader("💾 Save Configuration")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("💾 Save to Current Session", type="primary", key="save_planning_config"):
            if 'planning_loaded_file' in st.session_state:
                data = load_extracted_data(st.session_state.planning_loaded_file)
                if data:
                    data['simulation_config'] = st.session_state.simulation_config
                    data['modified_at'] = datetime.now().isoformat()
                    with open(st.session_state.planning_loaded_file, 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                    st.success("Configuration saved successfully!")
                    st.balloons()

    with col2:
        config_json = json.dumps(st.session_state.simulation_config, indent=2, ensure_ascii=False)
        if 'config_export_json' not in st.session_state or st.session_state.get('config_export_needs_update', True):
            st.session_state.config_export_json = config_json
            st.session_state.config_export_filename = f"simulation_config_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            st.session_state.config_export_needs_update = False

        st.download_button(
            label="⬇️ Export Config JSON",
            data=st.session_state.config_export_json,
            file_name=st.session_state.config_export_filename,
            mime="application/json", key="download_config_json"
        )

    with st.expander("👁️ View Configuration JSON"):
        st.code(json.dumps(st.session_state.simulation_config, indent=2), language="json")
