"""
Create Simulation page — PDF upload, extraction, parsing, preview, and save.
"""

import copy
import logging
import time

import streamlit as st

from extractors.pdf_extractor import extract_pdf_text
from extractors.content_parser import parse_company_data, parse_module_content
from core.data_manager import save_extracted_data, get_default_simulation_config
from core.admin_agents import (
    run_create_review_agent,
    run_audit_agent,
    run_planning_agent,
)

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

        # Step 2.5 — one-click auto-prepare (primary flow)
        _render_auto_prepare_panel()

        # Advanced: manual per-agent review (fallback for users who want to
        # see Agent 1's diff before applying, or re-run only part of the chain)
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

            # If auto-prepare ran Agent 3, pass the narrative-enriched config through to save
            _prepared_config = st.session_state.get("autoprep_sim_config")
            if _prepared_config:
                st.caption("✨ Save will include the AI-generated narrative plan (5 rounds, focus areas, tension pairs).")

            _save_processing = st.session_state.get("_dc_save_processing", False)
            if st.button("💾 Save Data for Simulation", type="primary", key="dc_save_btn",
                        disabled=_save_processing):
                st.session_state._dc_save_processing = True
                with st.spinner("Saving data..."):
                    doc_id = save_extracted_data(
                        st.session_state.dc_company_data,
                        st.session_state.dc_module_data,
                        session_name,
                        simulation_config=_prepared_config,
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
                        # Clear auto-prepare artifacts so next session starts clean
                        for _k in ("autoprep_sim_config", "autoprep_log", "autoprep_status",
                                   "autoprep_snapshot", "autoprep_failed_at"):
                            st.session_state.pop(_k, None)
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

    with st.expander("🔧 Advanced — Run Agent 1 alone (skip Auto-Prepare)", expanded=False):
        st.markdown(
            "Runs only the AI Review Agent (PDF recovery + enrichment + gap completion). "
            "Use this when you want to review Agent 1's diff before applying, or when "
            "you don't need Agent 2's audit or Agent 3's narrative plan. "
            "Every change is labeled by source (PDF / Enriched / Generated / Manual)."
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


# ==========================================================================
# AUTO-PREPARE PIPELINE — runs Agent 1 → Agent 2 → Agent 3 in sequence
# ==========================================================================

def _render_auto_prepare_panel():
    """Step 2.5 — one-click auto-prepare that runs all 3 agents sequentially.

    Session-state keys:
      autoprep_status    : "idle" | "done" | "failed"
      autoprep_snapshot  : pre-run copy of company/module/config for undo
      autoprep_log       : list of {agent, status, elapsed, summary, result}
      autoprep_sim_config: Agent 3's enriched simulation_config (passed to save)
      autoprep_failed_at : agent number (1/2/3) where chain stopped, if any
    """
    company_data = st.session_state.get("dc_company_data")
    module_data  = st.session_state.get("dc_module_data")

    if not company_data or not module_data:
        return

    status = st.session_state.get("autoprep_status", "idle")

    # Stale-state detection: if a prior session left status=done/failed but
    # no log survived (e.g. page refresh wiped session state partially), reset.
    if status in ("done", "failed") and not st.session_state.get("autoprep_log"):
        st.session_state["autoprep_status"] = "idle"
        status = "idle"

    # ── Completion view (after a successful or partial run) ──────────────
    if status in ("done", "failed"):
        _render_autoprep_summary()
        st.divider()
        return

    # ── Idle view: big primary CTA + options ─────────────────────────────
    st.header("Step 2.5: ✨ Auto-Prepare with AI")
    st.markdown(
        "Runs all three admin agents in sequence — **~2–3 minutes total**:\n\n"
        "1. **Agent 1** — recovers missed PDF data, enriches thin fields, generates what's truly absent\n"
        "2. **Agent 2** — audits coverage, generates missing metrics/members/committees, computes readiness score\n"
        "3. **Agent 3** — designs a 3-act narrative arc with focus areas and board tensions for every round"
    )

    col_opts_a, col_opts_b = st.columns(2)
    with col_opts_a:
        apply_generated = st.checkbox(
            "Auto-apply Agent 1's AI-generated content (not just PDF-recovered)",
            value=True, key="autoprep_apply_generated",
            help="Uncheck to apply ONLY items recovered from the PDF in Agent 1.",
        )
    with col_opts_b:
        run_agent3 = st.checkbox(
            "Include Agent 3 (narrative planning)",
            value=True, key="autoprep_run_agent3",
            help="Uncheck if you just want Agent 1 + Agent 2 and will plan rounds manually later.",
        )

    col_run, col_manual = st.columns([2, 1])
    with col_run:
        run_clicked = st.button(
            "▶ Run All Agents",
            type="primary",
            key="autoprep_run_btn",
            use_container_width=True,
            help="Runs the full pipeline. Don't close this tab until complete.",
        )
    with col_manual:
        st.caption("Or use the Advanced panel below for manual per-agent review.")

    if run_clicked:
        # Concurrency guard — if the previous run somehow left the flag set
        # (e.g. user force-refreshed), clear it and proceed.
        if st.session_state.get("autoprep_running"):
            st.warning("A previous Auto-Prepare run appears to have been interrupted. Starting fresh.")
            st.session_state["autoprep_running"] = False

        # Pre-flight: API key must be present or every agent silently no-ops
        try:
            api_key = st.secrets.get("GEMINI_API_KEY", "") if hasattr(st, "secrets") else ""
        except Exception:
            api_key = ""
        if not api_key:
            st.error(
                "❌ Gemini API key is not configured. "
                "Add `GEMINI_API_KEY` to `.streamlit/secrets.toml` before running Auto-Prepare."
            )
            return

        st.session_state["autoprep_running"] = True
        try:
            _run_auto_prepare_chain(
                company_data=company_data,
                module_data=module_data,
                company_text=st.session_state.get("dc_company_text", ""),
                module_text=st.session_state.get("dc_module_text", ""),
                apply_generated=apply_generated,
                run_agent3=run_agent3,
            )
        except Exception as exc:
            logger.exception("Auto-Prepare chain raised an unhandled exception")
            st.error(f"Auto-Prepare crashed unexpectedly: {exc}")
            st.session_state["autoprep_status"] = "failed"
            st.session_state["autoprep_failed_at"] = st.session_state.get("autoprep_failed_at", 0)
        finally:
            st.session_state["autoprep_running"] = False
        st.rerun()

    st.divider()


# --------------------------------------------------------------------------
# Pipeline executor
# --------------------------------------------------------------------------

def _run_auto_prepare_chain(
    company_data: dict,
    module_data: dict,
    company_text: str,
    module_text: str,
    apply_generated: bool,
    run_agent3: bool,
) -> None:
    """Run A1 → apply → A2 → apply → (optionally A3 → apply) inside one st.status."""
    # Snapshot for undo — deep copy so later mutations don't poison the snapshot
    st.session_state["autoprep_snapshot"] = {
        "company_data":      copy.deepcopy(company_data),
        "module_data":       copy.deepcopy(module_data),
        "simulation_config": copy.deepcopy(st.session_state.get("autoprep_sim_config")),
    }
    log: list = []
    st.session_state["autoprep_log"] = log
    st.session_state["autoprep_status"] = "idle"
    st.session_state.pop("autoprep_failed_at", None)

    status_box = st.status("🤖 Preparing simulation — don't close this tab…", expanded=True)

    # ── Phase 1: Agent 1 (PDF recovery + enrichment + gap completion) ──
    with status_box:
        st.write("**Agent 1 — Review & Enrich** (this is the slowest step)")
        t0 = time.time()
        try:
            a1 = run_create_review_agent(
                company_data=company_data,
                module_data=module_data,
                company_text=company_text,
                module_text=module_text,
            )
        except Exception as exc:
            elapsed = time.time() - t0
            log.append({"agent": 1, "status": "failed", "elapsed": elapsed, "error": str(exc)})
            st.session_state["autoprep_status"] = "failed"
            st.session_state["autoprep_failed_at"] = 1
            status_box.update(label=f"❌ Agent 1 failed ({elapsed:.0f}s)", state="error")
            return

        _apply_agent1_patch(a1.get("patch", {}), apply_generated=apply_generated)
        company_data = st.session_state["dc_company_data"]
        module_data  = st.session_state["dc_module_data"]
        elapsed = time.time() - t0
        s1 = a1.get("summary", {})
        summary_line = (
            f"PDF={s1.get('pdf_recovered', 0)} | "
            f"Enriched={s1.get('enriched', 0)} | "
            f"Generated={s1.get('generated', 0)} | "
            f"Manual={s1.get('manual_required', 0)}"
        )
        items_count = len(a1.get("items", []))
        log.append({
            "agent": 1, "status": "done", "elapsed": elapsed,
            "items_count": items_count,
            "summary": summary_line,
            "zero_output": items_count == 0,
        })
        if items_count == 0:
            st.write(f"⚠️ Agent 1 finished in {elapsed:.0f}s — **no changes** (data may already be complete, or LLM returned empty — check API key)")
        else:
            st.write(f"✅ Agent 1 complete in {elapsed:.0f}s — {summary_line}")

    # ── Phase 2: Agent 2 (audit + readiness score) ──
    with status_box:
        st.write("**Agent 2 — Audit & Score**")
        t0 = time.time()
        try:
            a2 = run_audit_agent(company_data, module_data)
        except Exception as exc:
            elapsed = time.time() - t0
            log.append({"agent": 2, "status": "failed", "elapsed": elapsed, "error": str(exc)})
            st.session_state["autoprep_status"] = "failed"
            st.session_state["autoprep_failed_at"] = 2
            status_box.update(label=f"❌ Agent 2 failed after Agent 1 succeeded ({elapsed:.0f}s)", state="error")
            return

        _apply_a2_patch_to_dc(a2.get("patch", {}))
        company_data = st.session_state["dc_company_data"]
        module_data  = st.session_state["dc_module_data"]
        elapsed = time.time() - t0
        rs = a2.get("readiness_score", {})
        summary_line = (
            f"Readiness {rs.get('overall', 0)}/100 "
            f"(metrics {rs.get('metric_coverage', 0)}, "
            f"board {rs.get('board_coverage', 0)}, "
            f"structural {rs.get('structural_health', 0)}) | "
            f"{len(a2.get('items', []))} items applied"
        )
        log.append({
            "agent": 2, "status": "done", "elapsed": elapsed,
            "readiness_score": rs,
            "items_count": len(a2.get("items", [])),
            "summary": summary_line,
            "flags": a2.get("flags", []),
        })
        # Persist audit snapshot so Manage Simulations can show it later
        st.session_state["autoprep_audit_snapshot"] = {
            "readiness_score": rs,
            "gaps":  a2.get("gaps", {}),
            "flags": a2.get("flags", []),
            "summary": a2.get("summary", {}),
        }
        st.write(f"✅ Agent 2 complete in {elapsed:.0f}s — {summary_line}")

    if not run_agent3:
        status_box.update(label="✅ Prepared (Agent 3 skipped) — ready to save", state="complete")
        st.session_state["autoprep_status"] = "done"
        return

    # ── Phase 3: Agent 3 (narrative planning) ──
    with status_box:
        st.write("**Agent 3 — Plan Narrative Arc**")
        t0 = time.time()
        sim_config = get_default_simulation_config()
        try:
            a3 = run_planning_agent(company_data, module_data, sim_config)
        except Exception as exc:
            elapsed = time.time() - t0
            log.append({"agent": 3, "status": "failed", "elapsed": elapsed, "error": str(exc)})
            st.session_state["autoprep_status"] = "failed"
            st.session_state["autoprep_failed_at"] = 3
            status_box.update(label=f"❌ Agent 3 failed — Agent 1 + Agent 2 changes preserved ({elapsed:.0f}s)", state="error")
            return

        sim_config = _apply_a3_plan_to_config(a3, sim_config)
        st.session_state["autoprep_sim_config"] = sim_config
        elapsed = time.time() - t0
        n_rounds = len(a3.get("rounds", []))
        arc_title = a3.get("narrative_arc_title", "")
        summary_line = f'{n_rounds}-round arc: "{arc_title[:55]}"'
        log.append({
            "agent": 3, "status": "done", "elapsed": elapsed,
            "summary": summary_line,
            "arc_title": arc_title,
            "rounds": a3.get("rounds", []),
            "act_labels": a3.get("act_labels", {}),
            "coverage": a3.get("coverage", {}),
        })
        st.write(f"✅ Agent 3 complete in {elapsed:.0f}s — {summary_line}")

    total = sum(e.get("elapsed", 0) for e in log)
    status_box.update(label=f"✅ All agents complete in {total:.0f}s — ready to save", state="complete")
    st.session_state["autoprep_status"] = "done"


# --------------------------------------------------------------------------
# Inline apply helpers (mirror manage_simulations.py write-backs so the
# pipeline doesn't depend on cross-page imports and session-state juggling)
# --------------------------------------------------------------------------

def _apply_a2_patch_to_dc(patch: dict) -> None:
    """Apply Agent 2's patch directly into dc_company_data (skipping audit_data)."""
    cd = st.session_state.setdefault("dc_company_data", {})
    cp = patch.get("company", {}) if isinstance(patch, dict) else {}

    for key, info in cp.get("metrics_generated", {}).items():
        cd.setdefault("metrics", {})[key] = info
    for key, val in cp.get("metrics_fixed_values", {}).items():
        if key in cd.get("metrics", {}):
            cd["metrics"][key]["value"] = val
    for m in cp.get("board_members_generated", []):
        if isinstance(m, dict):
            cd.setdefault("board_members", []).append(m)
    for c in cp.get("committees_generated", []):
        if isinstance(c, dict):
            cd.setdefault("committees", []).append(c)
    for p in cp.get("problems_generated", []):
        if isinstance(p, str):
            cd.setdefault("current_problems", []).append(p)

    st.session_state["dc_company_data"] = cd


def _apply_a3_plan_to_config(result: dict, cfg: dict) -> dict:
    """Apply Agent 3's plan into the given sim_config. Mirrors manage_simulations._apply_agent3_plan."""
    enriched_rounds = result.get("rounds", [])
    if not enriched_rounds:
        return cfg

    existing_map = {r["round_number"]: r for r in cfg.get("rounds", [])}
    new_rounds = []
    for er in enriched_rounds:
        rnum = er.get("round_number")
        base = existing_map.get(rnum, {"round_number": rnum})
        base["focus_area"]    = er.get("focus_area") or base.get("focus_area")
        base["difficulty"]    = er.get("difficulty") or base.get("difficulty", "medium")
        base["round_type"]    = er.get("round_type") or base.get("round_type", "both")
        base["time_pressure"] = base.get("time_pressure") or (
            "tight" if base["difficulty"] == "hard" else "normal"
        )
        base["_title"]          = er.get("title", "")
        base["_tension_pair"]   = er.get("tension_pair") or ""
        base["_cascade_seed"]   = er.get("cascade_seed") or ""
        base["_act"]            = er.get("act")
        base["_act_label"]      = er.get("act_label", "")
        base["_topics_covered"] = er.get("topics_covered", []) or []
        new_rounds.append(base)

    new_rounds.sort(key=lambda r: r.get("round_number", 0))
    for i, r in enumerate(new_rounds, start=1):
        r["round_number"] = i

    cfg["rounds"] = new_rounds
    cfg["total_rounds"] = len(new_rounds)
    cfg["_narrative_arc_title"] = result.get("narrative_arc_title", "")
    cfg["_act_labels"]          = result.get("act_labels", {})
    cfg["_coverage"]            = result.get("coverage", {})
    cfg["_tension_pairs"]       = result.get("tension_pairs", [])
    cfg["_planning_flags"]      = result.get("flags", [])
    cfg["_planning_summary"]    = result.get("summary", {})
    return cfg


# --------------------------------------------------------------------------
# Completion / summary view
# --------------------------------------------------------------------------

def _render_autoprep_summary() -> None:
    """Show the post-run readiness card, change log, and undo/re-run controls."""
    status = st.session_state.get("autoprep_status", "idle")
    log    = st.session_state.get("autoprep_log", [])
    failed_at = st.session_state.get("autoprep_failed_at")

    if status == "failed":
        st.error(
            f"❌ Auto-prepare stopped at **Agent {failed_at}**. "
            "Earlier agents' changes are preserved in the session — you can "
            "retry below, continue without the failing step, or undo."
        )
    else:
        st.success("✅ **Simulation prepared.** Review below and click **Save Data for Simulation** at Step 3.")

    # ── Readiness score card (from Agent 2) ──────────────────────────────
    a2_log = next((e for e in log if e.get("agent") == 2 and e.get("status") == "done"), None)
    if a2_log:
        rs = a2_log.get("readiness_score", {})
        overall = rs.get("overall", 0)
        color = "🟢" if overall >= 75 else ("🟡" if overall >= 50 else "🔴")
        st.markdown(f"### {color} Readiness Score: **{overall}/100**")
        c1, c2, c3 = st.columns(3)
        c1.metric("Metric Coverage",    f"{rs.get('metric_coverage', 0)}/100")
        c2.metric("Board Coverage",     f"{rs.get('board_coverage', 0)}/100")
        c3.metric("Structural Health",  f"{rs.get('structural_health', 0)}/100")

    # ── Per-agent summary ────────────────────────────────────────────────
    st.markdown("### 📋 What changed")
    for entry in log:
        agent_n = entry.get("agent")
        icon = {"done": "✅", "failed": "❌"}.get(entry.get("status"), "⚪")
        elapsed = entry.get("elapsed", 0)
        label = {1: "Agent 1 (Review)", 2: "Agent 2 (Audit)", 3: "Agent 3 (Planning)"}[agent_n]
        summary = entry.get("summary", entry.get("error", ""))
        st.markdown(f"- {icon} **{label}** ({elapsed:.0f}s): {summary}")

    # ── Agent 3 arc details ──────────────────────────────────────────────
    a3_log = next((e for e in log if e.get("agent") == 3 and e.get("status") == "done"), None)
    if a3_log:
        with st.expander("🎬 Narrative plan details"):
            st.markdown(f"**Arc:** {a3_log.get('arc_title', '')}")
            acts = a3_log.get("act_labels", {})
            for key in ("1", "2", "3"):
                if key in acts:
                    st.markdown(f"- **Act {key}:** {acts[key]}")
            for r in a3_log.get("rounds", []):
                diff_icon = {"easy": "🟢", "medium": "🟡", "hard": "🔴"}.get(r.get("difficulty", ""), "⚪")
                st.markdown(
                    f"**Round {r.get('round_number')}** {diff_icon} "
                    f"_{r.get('difficulty', '')}_ — {r.get('title', '')}"
                )
                st.caption(str(r.get("focus_area", ""))[:220])
                if r.get("tension_pair"):
                    st.caption(f"Tension: {r['tension_pair']}")

    # ── Agent 2 flags (if any) ───────────────────────────────────────────
    if a2_log and a2_log.get("flags"):
        with st.expander(f"⚠️ {len(a2_log['flags'])} structural flags from Agent 2"):
            for f in a2_log["flags"]:
                sev = f.get("severity", "warning")
                sev_icon = {"error": "🔴", "warning": "🟡"}.get(sev, "⚪")
                st.markdown(f"{sev_icon} [{f.get('type')}] {f.get('message', '')}")

    # ── Control buttons ──────────────────────────────────────────────────
    st.markdown("---")
    col_rerun, col_undo, col_dismiss = st.columns(3)
    with col_rerun:
        if st.button("🔄 Re-run All", key="autoprep_rerun_btn", use_container_width=True):
            _restore_autoprep_snapshot()
            st.rerun()
    with col_undo:
        if st.button("↩ Undo", key="autoprep_undo_btn", use_container_width=True,
                     help="Restore data to the state before Auto-Prepare ran"):
            _restore_autoprep_snapshot()
            st.session_state["autoprep_status"] = "idle"
            st.rerun()
    with col_dismiss:
        if st.button("✓ Keep & Dismiss", key="autoprep_dismiss_btn",
                     type="primary", use_container_width=True,
                     help="Keep the changes; hide this panel and proceed to Save."):
            # Keep the applied changes + sim_config, just close this summary
            st.session_state["autoprep_status"] = "dismissed"
            st.session_state.pop("autoprep_log", None)
            st.session_state.pop("autoprep_failed_at", None)
            st.rerun()


def _restore_autoprep_snapshot() -> None:
    """Restore company/module/config from the pre-run snapshot."""
    snap = st.session_state.get("autoprep_snapshot")
    if not snap:
        return
    st.session_state["dc_company_data"] = copy.deepcopy(snap.get("company_data"))
    st.session_state["dc_module_data"]  = copy.deepcopy(snap.get("module_data"))
    prior_cfg = snap.get("simulation_config")
    if prior_cfg is None:
        st.session_state.pop("autoprep_sim_config", None)
    else:
        st.session_state["autoprep_sim_config"] = copy.deepcopy(prior_cfg)
    # Clear log and status so the idle view shows on next render
    for k in ("autoprep_log", "autoprep_failed_at", "autoprep_audit_snapshot"):
        st.session_state.pop(k, None)
