"""
Create Simulation page — PDF upload, extraction, parsing, preview, and save.
"""

import logging
import streamlit as st

from extractors.pdf_extractor import extract_pdf_text
from extractors.content_parser import parse_company_data, parse_module_content
from core.data_manager import save_extracted_data

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
