"""
Create Simulation page — PDF upload, extraction, parsing, preview, and save.
"""

import logging
import streamlit as st

from extractors.pdf_extractor import extract_pdf_text
from extractors.content_parser import parse_company_data, parse_module_content
from core.data_manager import save_extracted_data
from core.admin_agents import run_create_review_agent

logger = logging.getLogger(__name__)


def create_simulation_page():
    """Page for uploading PDFs, extracting data, and saving new simulations."""
    if not st.session_state.get("admin_authenticated"):
        st.warning("Please log in as admin to access this page.")
        return

    # Issue #31: Validate API key before allowing extraction
    if not st.secrets.get("GEMINI_API_KEY"):
        st.error("Gemini API key not configured. Add GEMINI_API_KEY to .streamlit/secrets.toml.")
        return

    st.markdown('<h1 class="main-header">📤 Create Simulation</h1>', unsafe_allow_html=True)
    st.markdown("Upload your company and module PDFs to prepare a new simulation.")

    # Initialize session state
    if 'dc_company_data' not in st.session_state:
        st.session_state.dc_company_data = None
    if 'dc_module_data' not in st.session_state:
        st.session_state.dc_module_data = None
    if 'dc_company_text' not in st.session_state:
        st.session_state.dc_company_text = None
    if 'dc_module_text' not in st.session_state:
        st.session_state.dc_module_text = None

    tab_upload, tab_help = st.tabs(["📤 Upload & Extract", "ℹ️ Help"])

    # ==================== TAB 1: UPLOAD & EXTRACT ====================
    with tab_upload:
        st.header("Step 1: Upload PDF Documents")

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("🏢 Company Document")
            company_file = st.file_uploader(
                "Upload company PDF (annual report, case study, etc.)",
                type=['pdf'],
                key="dc_company_upload"
            )

            if company_file:
                file_size_mb = len(company_file.getvalue()) / (1024 * 1024)
                st.success(f"Uploaded: {company_file.name} ({file_size_mb:.1f} MB)")

                if file_size_mb > 20:
                    st.error("File exceeds 20 MB limit. Please upload a smaller PDF.")
                elif st.button("Extract Company Data", key="dc_extract_company"):
                    with st.spinner("Extracting company information..."):
                        company_text = extract_pdf_text(company_file)
                        if company_text:
                            st.session_state.dc_company_text = company_text
                            st.info(f"Extracted {len(company_text)} characters from PDF")
                            # Issue #23: Warn if extraction seems incomplete
                            file_size_kb = len(company_file.getvalue()) / 1024
                            if len(company_text) < 500 and file_size_kb > 100:
                                st.warning("Extraction produced very little text relative to PDF size. Results may be incomplete.")

                            with st.spinner("Parsing company data with AI..."):
                                try:
                                    company_data = parse_company_data(company_text)
                                    st.session_state.dc_company_data = company_data
                                    st.success("Company data parsed successfully!")
                                except Exception as e:
                                    logger.error(f"Failed to parse company data: {e}")
                                    st.session_state.dc_company_data = None
                                    st.error("Failed to parse company data. Please check the PDF format.")
                        else:
                            st.session_state.dc_company_data = None
                            st.error("No text could be extracted from this PDF. Please try a different file.")

        with col2:
            st.subheader("📚 Module Document")
            module_file = st.file_uploader(
                "Upload module/course PDF",
                type=['pdf'],
                key="dc_module_upload"
            )

            if module_file:
                file_size_mb = len(module_file.getvalue()) / (1024 * 1024)
                st.success(f"Uploaded: {module_file.name} ({file_size_mb:.1f} MB)")

                if file_size_mb > 20:
                    st.error("File exceeds 20 MB limit. Please upload a smaller PDF.")
                elif st.button("Extract Module Data", key="dc_extract_module"):
                    with st.spinner("Extracting module content..."):
                        module_text = extract_pdf_text(module_file)
                        if module_text:
                            st.session_state.dc_module_text = module_text
                            st.info(f"Extracted {len(module_text)} characters from PDF")
                            # Issue #23: Warn if extraction seems incomplete
                            file_size_kb = len(module_file.getvalue()) / 1024
                            if len(module_text) < 500 and file_size_kb > 100:
                                st.warning("Extraction produced very little text relative to PDF size. Results may be incomplete.")

                            with st.spinner("Parsing module content with AI..."):
                                try:
                                    module_data = parse_module_content(module_text)
                                    st.session_state.dc_module_data = module_data
                                    st.success("Module data parsed successfully!")
                                except Exception as e:
                                    logger.error(f"Failed to parse module data: {e}")
                                    st.session_state.dc_module_data = None
                                    st.error("Failed to parse module data. Please check the PDF format.")
                        else:
                            st.session_state.dc_module_data = None
                            st.error("No text could be extracted from this PDF. Please try a different file.")

        st.divider()

        # Preview extracted data
        st.header("Step 2: Review Extracted Data")

        col1, col2 = st.columns(2)

        with col1:
            if st.session_state.dc_company_data:
                st.subheader("🏢 Company Data Preview")
                data = st.session_state.dc_company_data

                st.markdown(f"**Company Name:** {data.get('company_name', 'N/A')}")
                st.markdown(f"**Overview:** {data.get('company_overview', 'N/A')[:200]}...")

                with st.expander("View Metrics"):
                    metrics = data.get('metrics', {})
                    for name, info in list(metrics.items())[:10]:
                        if isinstance(info, dict):
                            st.write(f"- {name}: {info.get('value', 'N/A')} {info.get('unit', '')}")
                        else:
                            st.write(f"- {name}: {info}")
                    if len(metrics) > 10:
                        st.info(f"... and {len(metrics) - 10} more metrics")

                with st.expander("View Board Members"):
                    for member in data.get('board_members', [])[:5]:
                        st.write(f"- **{member.get('name', 'N/A')}**: {member.get('role', 'N/A')}")
                    if len(data.get('board_members', [])) > 5:
                        st.info(f"... and {len(data.get('board_members', [])) - 5} more members")

                with st.expander("View Current Problems"):
                    for problem in data.get('current_problems', []):
                        st.write(f"- {problem}")
            else:
                st.info("Upload and extract company PDF to see preview")

        with col2:
            if st.session_state.dc_module_data:
                st.subheader("📚 Module Data Preview")
                data = st.session_state.dc_module_data

                st.markdown(f"**Module Name:** {data.get('module_name', 'N/A')}")
                st.markdown(f"**Subject Area:** {data.get('subject_area', 'N/A')}")
                st.markdown(f"**Overview:** {data.get('overview', 'N/A')[:200]}...")

                with st.expander("View Topics"):
                    for topic in data.get('topics', [])[:5]:
                        st.write(f"- **{topic.get('name', 'N/A')}**: {topic.get('description', 'N/A')[:100]}...")
                    if len(data.get('topics', [])) > 5:
                        st.info(f"... and {len(data.get('topics', [])) - 5} more topics")

                with st.expander("View Frameworks"):
                    for framework in data.get('frameworks', [])[:5]:
                        st.write(f"- **{framework.get('name', 'N/A')}**: {framework.get('description', 'N/A')[:100]}...")

                with st.expander("View Key Terms"):
                    terms = data.get('key_terms', {})
                    for term, definition in list(terms.items())[:10]:
                        st.write(f"- **{term}**: {definition[:80]}...")
                    if len(terms) > 10:
                        st.info(f"... and {len(terms) - 10} more terms")
            else:
                st.info("Upload and extract module PDF to see preview")

        st.divider()

        # Agent 1 — AI Review panel
        _render_agent1_panel()

        st.divider()

        # Save data
        st.header("Step 3: Save Data for Simulation")

        if st.session_state.dc_company_data and st.session_state.dc_module_data:
            session_name = st.text_input(
                "Session Name",
                value=f"{st.session_state.dc_company_data.get('company_name', 'Session')} - {st.session_state.dc_module_data.get('module_name', 'Module')}",
                help="Give your session a memorable name",
                key="dc_session_name"
            )

            _save_processing = st.session_state.get("_dc_save_processing", False)
            if st.button("💾 Save Data for Simulation", type="primary", key="dc_save_btn",
                        disabled=_save_processing):
                st.session_state._dc_save_processing = True
                with st.spinner("Saving data..."):
                    doc_id = save_extracted_data(
                        st.session_state.dc_company_data,
                        st.session_state.dc_module_data,
                        session_name
                    )
                    if doc_id:
                        st.success("Simulation saved! It's now available in the Simulations section.")
                        st.info(f"Simulation ID: `{doc_id}`")
                        st.balloons()
                        # Clear state to prevent duplicate saves
                        st.session_state.dc_company_data = None
                        st.session_state.dc_module_data = None
                        st.session_state.dc_company_text = None
                        st.session_state.dc_module_text = None
                        st.session_state.pop("_dc_save_processing", None)
                        st.rerun()
                    else:
                        st.session_state.pop("_dc_save_processing", None)
        else:
            missing = []
            if not st.session_state.dc_company_data:
                missing.append("Company data")
            if not st.session_state.dc_module_data:
                missing.append("Module data")
            st.warning(f"Please extract both documents first. Missing: {', '.join(missing)}")

    # ==================== TAB 2: HELP ====================
    with tab_help:
        st.header("ℹ️ How to Use")

        st.markdown("""
        ### Overview
        This page helps you prepare data for a new Board Meeting Simulation. You'll upload two PDF documents:

        1. **Company Document**: An annual report, case study, or company profile containing:
           - Company overview and background
           - Financial and operational metrics
           - Leadership team information
           - Current business challenges

        2. **Module Document**: A course or training material containing:
           - Learning objectives
           - Key topics and concepts
           - Frameworks and models
           - Assessment criteria

        ### Steps

        1. **Upload PDFs**: Upload both company and module PDF files
        2. **Extract Data**: Click the extract buttons to process each PDF with AI
        3. **Review**: Check the extracted data preview to ensure accuracy
        4. **Save**: Give your session a name and save for simulation
        5. **Manage**: Use the Manage Simulations page to audit, edit, or configure rounds

        ### Tips

        - Use clear, text-based PDFs for best results
        - Larger documents may take longer to process
        - You can re-extract if the initial results aren't satisfactory
        - After saving, the simulation instantly appears in the sidebar
        - API key for Gemini is required in `.streamlit/secrets.toml`
        """)


# ==================== AGENT 1 UI ====================

_SOURCE_COLOR = {"pdf": "green", "enriched": "orange", "generated": "red", "manual": "red"}
_SOURCE_ICON  = {"pdf": "✅", "enriched": "✏️", "generated": "⚡", "manual": "⛔"}
_SOURCE_LABEL = {
    "pdf":       "Recovered from PDF",
    "enriched":  "Enriched from context",
    "generated": "AI-Generated (not from PDF)",
    "manual":    "Requires manual input",
}


def _render_agent1_panel():
    """Render the Agent 1 AI Review expander between Step 2 and Step 3."""
    company_data = st.session_state.get("dc_company_data")
    module_data  = st.session_state.get("dc_module_data")

    if not company_data or not module_data:
        return

    with st.expander("🤖 Step 2.5 — AI Review Agent: Recover & Enrich Extracted Data", expanded=False):
        st.markdown(
            "The AI Review Agent scans the raw PDF text for data missed in the first extraction, "
            "enriches thin fields, and generates only what's truly absent. "
            "Every change is labeled by source so you know what came from the PDF vs what was generated."
        )

        has_text = bool(
            st.session_state.get("dc_company_text") or
            st.session_state.get("dc_module_text")
        )
        if not has_text:
            st.warning(
                "Raw PDF text is not available — PDF recovery will be skipped. "
                "Only quality enrichment and gap completion will run."
            )

        col_run, col_clear = st.columns([2, 1])
        with col_run:
            run_btn = st.button(
                "Run Full Review",
                key="agent1_run",
                type="primary",
                help="Runs in ~15–20 seconds",
            )
        with col_clear:
            if st.session_state.get("agent1_result"):
                if st.button("Clear Results", key="agent1_clear"):
                    st.session_state.pop("agent1_result", None)
                    st.rerun()

        if run_btn:
            with st.spinner("Running AI review — recovering from PDF and enriching data..."):
                result = run_create_review_agent(
                    company_data=company_data,
                    module_data=module_data,
                    company_text=st.session_state.get("dc_company_text", ""),
                    module_text=st.session_state.get("dc_module_text", ""),
                )
            st.session_state["agent1_result"] = result
            st.rerun()

        # Show persistent apply banner (survives the rerun that clears agent1_result)
        if st.session_state.get("agent1_apply_banner"):
            banner_msg = st.session_state.pop("agent1_apply_banner")
            st.success(
                f"✅ {banner_msg} — scroll down to **Step 3** and click "
                "**💾 Save Data for Simulation** to persist to the database."
            )

        result = st.session_state.get("agent1_result")
        if not result:
            return

        _render_agent1_summary(result)
        _render_agent1_items(result)
        _render_agent1_apply_buttons(result, company_data, module_data)


def _render_agent1_summary(result: dict):
    """Render the summary counts bar."""
    s = result.get("summary", {})
    total = sum(s.values())
    if total == 0:
        st.success("No issues found — data looks complete.")
        return

    st.markdown("---")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("From PDF",       s.get("pdf_recovered", 0),  help="Data found in the PDF but missed in first extraction")
    c2.metric("Enriched",       s.get("enriched", 0),        help="Thin fields improved from existing context")
    c3.metric("AI-Generated",   s.get("generated", 0),       help="Content not in PDF — AI generated, review before saving")
    c4.metric("Manual needed",  s.get("manual_required", 0), help="Cannot be recovered or generated — needs admin input")

    if result.get("phase1_skipped"):
        st.info("PDF recovery skipped — raw text unavailable. Only enrichment and gap completion ran.")


def _render_agent1_items(result: dict):
    """Render the source-coded item list grouped by source."""
    items = result.get("items", [])
    if not items:
        return

    for source in ("pdf", "enriched", "generated", "manual"):
        group = [i for i in items if i.get("source") == source]
        if not group:
            continue

        icon  = _SOURCE_ICON[source]
        label = _SOURCE_LABEL[source]
        color = _SOURCE_COLOR[source]

        st.markdown(f"**{icon} {label}** ({len(group)} changes)")
        with st.expander(f"View {label} changes", expanded=(source == "pdf")):
            for item in group:
                before = item.get("before")
                after  = item.get("after")
                reason = item.get("reason", "")

                st.markdown(f"**{item.get('label', item.get('field', ''))}**")
                if before is not None and source != "pdf":
                    col_b, col_a = st.columns(2)
                    col_b.caption("Before")
                    col_b.text(str(before)[:200] if before else "(empty)")
                    col_a.caption("After")
                    col_a.text(str(after)[:200] if after else "(none)")
                elif after is not None:
                    st.caption(f"Value: {str(after)[:200]}")
                if reason:
                    st.caption(f"Reason: {reason}")
                st.markdown("---")


def _render_agent1_apply_buttons(result: dict, company_data: dict, module_data: dict):
    """Render apply buttons and handle write-back to session state."""
    items = result.get("items", [])
    patch = result.get("patch", {})

    if not items:
        return

    pdf_count  = sum(1 for i in items if i["source"] == "pdf")
    all_count  = sum(1 for i in items if i["source"] in ("pdf", "enriched", "generated"))

    st.markdown("---")
    c1, c2, c3 = st.columns(3)

    with c1:
        if st.button(f"Apply All ({all_count} changes)", key="agent1_apply_all", type="primary"):
            _apply_agent1_patch(patch, apply_generated=True)
            st.session_state.pop("agent1_result", None)
            st.session_state["agent1_apply_banner"] = f"Applied {all_count} changes to session data"
            st.rerun()

    with c2:
        if pdf_count > 0:
            if st.button(f"Apply PDF-Recovered Only ({pdf_count})", key="agent1_apply_pdf"):
                _apply_agent1_patch(patch, apply_generated=False)
                st.session_state.pop("agent1_result", None)
                st.session_state["agent1_apply_banner"] = f"Applied {pdf_count} PDF-recovered changes to session data"
                st.rerun()

    with c3:
        if st.button("Discard", key="agent1_discard"):
            st.session_state.pop("agent1_result", None)
            st.rerun()


def _apply_agent1_patch(patch: dict, apply_generated: bool = True):
    """Write agent patch back into dc_company_data and dc_module_data session state."""
    import copy

    company = st.session_state.get("dc_company_data", {})
    module  = st.session_state.get("dc_module_data", {})

    cp = patch.get("company", {})
    mp = patch.get("module", {})

    # ── Company patches ──────────────────────────────────────────────

    # New board members (PDF-recovered)
    for m in cp.get("board_members_add", []):
        company.setdefault("board_members", []).append(m)

    # Board member updates (tenure / personality from PDF)
    for upd in cp.get("board_members_update", []):
        name   = upd.get("name", "")
        fields = upd.get("fields", {})
        for m in company.get("board_members", []):
            if m.get("name") == name:
                m.update(fields)
                break

    # New metrics (PDF-recovered)
    for key, info in cp.get("metrics_add", {}).items():
        company.setdefault("metrics", {})[key] = info

    # Metric value corrections (PDF)
    for key, info in cp.get("metrics_update", {}).items():
        if key in company.get("metrics", {}):
            company["metrics"][key].update(info)

    # New committees (PDF-recovered)
    for c in cp.get("committees_add", []):
        company.setdefault("committees", []).append(c)

    # Committee member corrections (PDF)
    for comm_name, members in cp.get("committees_member_corrections", {}).items():
        for c in company.get("committees", []):
            if c.get("name") == comm_name:
                c["members"] = members
                break

    # New problems (PDF-recovered)
    existing = set(company.get("current_problems", []))
    for p in cp.get("problems_add", []):
        if p not in existing:
            company.setdefault("current_problems", []).append(p)

    # Better initial scenario (PDF)
    if "initial_scenario" in cp:
        company["initial_scenario"] = cp["initial_scenario"]

    # Company overview supplement (PDF) — append to existing
    if cp.get("company_overview_append"):
        existing_overview = company.get("company_overview", "")
        supplement = cp["company_overview_append"]
        if supplement not in existing_overview:
            company["company_overview"] = (existing_overview + " " + supplement).strip()

    # ── Enrichment + Generated patches — gated by apply_generated flag ──
    # When user clicks "Apply PDF-Only", these are SKIPPED (only PDF-recovered items above stay)
    if apply_generated:

        # Board personalities
        for name, personality in cp.get("board_members_personality", {}).items():
            for m in company.get("board_members", []):
                if m.get("name") == name:
                    m["personality"] = personality
                    break

        # Board expertise
        for name, expertise in cp.get("board_members_expertise", {}).items():
            for m in company.get("board_members", []):
                if m.get("name") == name:
                    m["expertise"] = expertise
                    break

        # Board tenure
        for name, tenure in cp.get("board_members_tenure", {}).items():
            for m in company.get("board_members", []):
                if m.get("name") == name:
                    m["tenure_years"] = tenure
                    break

        # Expanded problems
        problems = company.get("current_problems", [])
        expanded_map = cp.get("problems_expanded", {})
        for i, p in enumerate(problems):
            if p in expanded_map:
                problems[i] = expanded_map[p]

        # Committee purposes
        for name, purpose in cp.get("committee_purposes", {}).items():
            for c in company.get("committees", []):
                if c.get("name") == name:
                    c["purpose"] = purpose
                    break

        # Committee members assigned
        for name, members in cp.get("committee_members_assigned", {}).items():
            for c in company.get("committees", []):
                if c.get("name") == name:
                    c["members"] = members
                    break

        # Metric descriptions and units
        for key, desc in cp.get("metric_descriptions", {}).items():
            if key in company.get("metrics", {}):
                company["metrics"][key]["description"] = desc

        for key, unit in cp.get("metric_units", {}).items():
            if key in company.get("metrics", {}):
                company["metrics"][key]["unit"] = unit

        # Generated items (new board members / committees / problems)
        for p in cp.get("problems_generated", []):
            company.setdefault("current_problems", []).append(p)
        for m in cp.get("board_members_generated", []):
            company.setdefault("board_members", []).append(m)
        for c in cp.get("committees_generated", []):
            company.setdefault("committees", []).append(c)

    # ── Module patches ──────────────────────────────────────────────

    for t in mp.get("topics_add", []):
        module.setdefault("topics", []).append(t)

    if mp.get("key_terms_add"):
        module.setdefault("key_terms", {}).update(mp["key_terms_add"])

    for f in mp.get("frameworks_add", []):
        module.setdefault("frameworks", []).append(f)

    existing_los = set(module.get("learning_objectives", []))
    for lo in mp.get("learning_objectives_add", []):
        if lo and lo not in existing_los:
            module.setdefault("learning_objectives", []).append(lo)
            existing_los.add(lo)

    existing_ac = set(module.get("assessment_criteria", []))
    for ac in mp.get("assessment_criteria_add", []):
        if ac and ac not in existing_ac:
            module.setdefault("assessment_criteria", []).append(ac)
            existing_ac.add(ac)

    # Topics formula/example updates are PDF-recovered — always apply
    for topic_name, upd in mp.get("topics_formula_update", {}).items():
        for t in module.get("topics", []):
            if t.get("name") == topic_name:
                if upd.get("formulas"):
                    t["formulas"] = upd["formulas"]
                if upd.get("examples"):
                    t["examples"] = upd["examples"]
                break

    # Module enrichment keys — gated by apply_generated flag
    if apply_generated:
        # Topic principles and examples (enriched)
        for topic_name, principles in mp.get("topic_principles", {}).items():
            for t in module.get("topics", []):
                if t.get("name") == topic_name:
                    t["key_principles"] = principles
                    break

        for topic_name, examples in mp.get("topic_examples", {}).items():
            for t in module.get("topics", []):
                if t.get("name") == topic_name:
                    t["examples"] = examples
                    break

        for fw_name, components in mp.get("framework_components", {}).items():
            for f in module.get("frameworks", []):
                if f.get("name") == fw_name:
                    f["components"] = components
                    break

        if mp.get("learning_objectives"):
            module["learning_objectives"] = mp["learning_objectives"]
        if mp.get("assessment_criteria"):
            module["assessment_criteria"] = mp["assessment_criteria"]

        if mp.get("module_overview"):
            module["overview"] = mp["module_overview"]

    st.session_state["dc_company_data"] = company
    st.session_state["dc_module_data"]  = module
