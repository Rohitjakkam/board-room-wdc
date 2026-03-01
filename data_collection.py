import streamlit as st
import google.generativeai as genai
import json
import PyPDF2
import os
from datetime import datetime
from typing import Dict, Optional, List
import hashlib

# Configure Gemini
genai.configure(api_key=st.secrets.get("GEMINI_API_KEY", ""))

# Data storage directory
DATA_DIR = "extracted_data"


def safe_index(options: List[str], value: str, default: int = 0) -> int:
    """Safely get index of value in options list, returning default if not found."""
    try:
        return options.index(value)
    except (ValueError, TypeError):
        return default


def safe_key(prefix: str, value: str) -> str:
    """Generate a safe Streamlit widget key from potentially problematic strings."""
    # Create a hash for strings with special characters
    safe_value = hashlib.md5(str(value).encode()).hexdigest()[:8]
    return f"{prefix}_{safe_value}"


def ensure_dict(data: Optional[Dict], default_keys: List[str] = None) -> Dict:
    """Ensure data is a dict with required keys initialized."""
    if data is None:
        data = {}
    if default_keys:
        for key in default_keys:
            if key not in data:
                data[key] = {} if key.endswith('_data') or key == 'metrics' or key == 'key_terms' else []
    return data


def ensure_list(data) -> List:
    """Ensure data is a list."""
    if data is None:
        return []
    if isinstance(data, list):
        return data
    return []


def safe_float(value, default: float = 0.0) -> float:
    """Safely convert a value to float, returning default if conversion fails.

    Handles cases where data may contain non-numeric strings like '12-18', 'N/A', etc.
    """
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        # Try to extract a number from the string
        value = value.strip()
        if not value:
            return default
        # Handle common non-numeric patterns
        try:
            return float(value)
        except ValueError:
            # Try to extract first number from string (e.g., "12-18" -> 12)
            import re
            match = re.search(r'-?\d+\.?\d*', value)
            if match:
                try:
                    return float(match.group())
                except ValueError:
                    pass
            return default
    return default


def safe_int(value, default: int = 0) -> int:
    """Safely convert a value to int, returning default if conversion fails.

    Handles cases where data may contain non-numeric strings like '12-18', 'N/A', etc.
    """
    if value is None:
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return default
        try:
            return int(float(value))
        except ValueError:
            # Try to extract first number from string
            import re
            match = re.search(r'-?\d+', value)
            if match:
                try:
                    return int(match.group())
                except ValueError:
                    pass
            return default
    return default


def safe_str(value, default: str = '') -> str:
    """Safely convert a value to string, returning default if value is None or empty."""
    if value is None:
        return default
    result = str(value).strip()
    return result if result else default


def ensure_data_dir():
    """Ensure the data directory exists"""
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

def extract_pdf_with_gemini(pdf_file) -> str:
    """Use Gemini's native PDF processing"""
    try:
        pdf_file.seek(0)
        model = genai.GenerativeModel('gemini-2.5-flash-lite')
        pdf_file.seek(0)
        uploaded_file = genai.upload_file(pdf_file, mime_type='application/pdf')

        prompt = """Extract ALL text content from this PDF document.
        Include everything: headers, body text, tables, numbers, charts, footnotes.
        Be extremely thorough."""

        response = model.generate_content([uploaded_file, prompt])
        return response.text
    except Exception as e:
        st.error(f"Gemini extraction error: {e}")
        return extract_pdf_with_pypdf2(pdf_file)

def extract_pdf_with_pypdf2(pdf_file) -> str:
    """Fallback PDF extraction"""
    try:
        pdf_file.seek(0)
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        text = ""
        for i, page in enumerate(pdf_reader.pages):
            page_text = page.extract_text()
            if page_text.strip():
                text += f"\n{'='*50}\nPAGE {i+1}\n{'='*50}\n{page_text}\n"
        return text if text.strip() else ""
    except Exception as e:
        st.error(f"PyPDF2 error: {e}")
        return ""

def parse_module_content(pdf_text: str) -> Dict:
    """Parse module/course content"""
    if not pdf_text or len(pdf_text.strip()) < 100:
        raise ValueError("Module PDF text is empty or too short")

    model = genai.GenerativeModel('gemini-2.5-flash-lite')

    prompt = f"""Analyze this course/module document thoroughly.

DOCUMENT ({len(pdf_text)} chars):
{pdf_text}

Extract ALL educational content:

1. Module name and subject area
2. Learning objectives
3. Key topics (10-30) with descriptions, principles, formulas, examples
4. Frameworks and models with components and applications
5. Key terms (20-50) with definitions
6. Assessment criteria

Return ONLY valid JSON:
{{
    "module_name": "Exact course name",
    "subject_area": "Finance/Marketing/Operations/Strategy/HR/Economics",
    "learning_objectives": ["Objective 1", "Objective 2"],
    "overview": "2-3 sentence overview",
    "topics": [
        {{
            "name": "Topic name",
            "description": "What this covers",
            "key_principles": ["Principle 1", "Principle 2"],
            "formulas": ["Formula 1"],
            "application": "When/how to use",
            "examples": ["Example 1"]
        }}
    ],
    "frameworks": [
        {{
            "name": "Framework name",
            "description": "What it does",
            "components": ["Component 1", "Component 2"],
            "application_scenario": "When to use"
        }}
    ],
    "key_terms": {{"term1": "definition", "term2": "definition"}},
    "assessment_criteria": ["Criterion 1", "Criterion 2"]
}}

Extract minimum 10 topics, 20 terms. Return ONLY JSON, no markdown."""

    try:
        response = model.generate_content(prompt)
        result_text = response.text.strip().replace('```json', '').replace('```', '').strip()

        if not result_text.startswith('{'):
            json_start = result_text.find('{')
            json_end = result_text.rfind('}') + 1
            if json_start != -1 and json_end > json_start:
                result_text = result_text[json_start:json_end]

        return json.loads(result_text)
    except Exception as e:
        st.error(f"Module parsing error: {e}")
        raise

def parse_company_data(pdf_text: str) -> Dict:
    """Parse company data"""
    if not pdf_text or len(pdf_text.strip()) < 100:
        raise ValueError("Company PDF text is empty or too short")

    model = genai.GenerativeModel('gemini-2.5-flash-lite')

    prompt = f"""Analyze this company document thoroughly.

DOCUMENT ({len(pdf_text)} chars):
{pdf_text}

Extract ALL company information:

1. Company name (exact)
2. Company overview (4-5 sentences)
3. Metrics (20-50): financial, operational, employee, market metrics
4. Leadership team (5-15 people with names, roles, personality traits)
5. Current problems/challenges (5-10)
6. Initial business situation

Return ONLY valid JSON:
{{
    "company_name": "Exact company name",
    "company_overview": "Detailed overview",
    "metrics": {{
        "revenue_total": {{"value": 500, "unit": "$M", "description": "Total revenue"}},
        "profit_margin": {{"value": 15, "unit": "%", "description": "Net profit margin"}},
        "employee_count": {{"value": 1200, "unit": "employees", "description": "Total workforce"}}
    }},
    "board_members": [
        {{"name": "Full Name", "role": "Complete Title", "personality": "Detailed personality"}},
        {{"name": "Full Name", "role": "Complete Title", "personality": "Detailed personality"}}
    ],
    "current_problems": ["Specific problem 1", "Specific problem 2"],
    "initial_scenario": "Current business situation"
}}

Extract 20-50 metrics, 5-15 board members, 5-10 problems. Return ONLY JSON."""

    try:
        response = model.generate_content(prompt)
        result_text = response.text.strip().replace('```json', '').replace('```', '').strip()

        if not result_text.startswith('{'):
            json_start = result_text.find('{')
            json_end = result_text.rfind('}') + 1
            if json_start != -1 and json_end > json_start:
                result_text = result_text[json_start:json_end]

        return json.loads(result_text)
    except Exception as e:
        st.error(f"Company parsing error: {e}")
        raise

def get_default_simulation_config() -> Dict:
    """Return default simulation configuration"""
    return {
        "total_rounds": 5,
        "initial_setup": {
            "starting_scenario": "default",  # default, crisis, growth, stable, custom
            "custom_scenario_text": "",  # Used when starting_scenario is "custom"
            "initial_difficulty": "medium"
        },
        "rounds": [
            {
                "round_number": i + 1,
                "round_type": "both",  # business, module, both
                "difficulty": "medium",  # easy, medium, hard
                "focus_area": None,  # Optional: specific topic/problem to focus on
                "time_pressure": "normal"  # relaxed, normal, urgent
            }
            for i in range(5)
        ],
        "difficulty_settings": {
            "easy": {
                "question_complexity": "straightforward",
                "board_pressure": "supportive",
                "time_allocation": "generous",
                "hints_available": True
            },
            "medium": {
                "question_complexity": "moderate",
                "board_pressure": "balanced",
                "time_allocation": "standard",
                "hints_available": False
            },
            "hard": {
                "question_complexity": "challenging",
                "board_pressure": "demanding",
                "time_allocation": "tight",
                "hints_available": False
            }
        },
        "round_type_settings": {
            "business": {
                "description": "Focus on company-specific challenges and decisions",
                "uses_company_data": True,
                "uses_module_data": False
            },
            "module": {
                "description": "Focus on applying theoretical concepts from the module",
                "uses_company_data": False,
                "uses_module_data": True
            },
            "both": {
                "description": "Integrate theoretical concepts with company challenges",
                "uses_company_data": True,
                "uses_module_data": True
            }
        }
    }


def save_extracted_data(company_data: Dict, module_data: Dict, session_name: str, simulation_config: Dict = None) -> str:
    """Save extracted data to JSON file for persistence"""
    ensure_data_dir()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Handle empty or whitespace-only session names
    if not session_name or not session_name.strip():
        session_name = f"Session_{timestamp}"
    safe_session_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_name)
    # Ensure we have at least something for the filename
    if not safe_session_name:
        safe_session_name = "session"
    filename = f"{safe_session_name}_{timestamp}.json"
    filepath = os.path.join(DATA_DIR, filename)

    # Use provided config or default
    if simulation_config is None:
        simulation_config = get_default_simulation_config()

    data = {
        "session_name": session_name,
        "created_at": datetime.now().isoformat(),
        "company_data": company_data,
        "module_data": module_data,
        "simulation_config": simulation_config,
        "status": "ready_for_simulation"
    }

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return filepath

def load_extracted_data(filepath: str) -> Optional[Dict]:
    """Load previously extracted data and normalize structure"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Normalize metrics structure: ensure all metrics have priority field
        if 'company_data' in data and 'metrics' in data['company_data']:
            for metric_key, metric_info in data['company_data']['metrics'].items():
                if isinstance(metric_info, dict):
                    # If priority field is missing or is 'General', set to None
                    if 'priority' not in metric_info:
                        metric_info['priority'] = None
                    elif metric_info['priority'] not in ["High", "Medium"]:
                        metric_info['priority'] = None

        return data
    except Exception as e:
        st.error(f"Error loading data: {e}")
        return None

def list_saved_sessions() -> list:
    """List all saved session files"""
    ensure_data_dir()
    sessions = []
    corrupted_files = []
    for filename in os.listdir(DATA_DIR):
        if filename.endswith('.json'):
            filepath = os.path.join(DATA_DIR, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Ensure nested dicts exist
                    company_data = data.get("company_data") or {}
                    module_data = data.get("module_data") or {}

                    # Use filepath as unique identifier to avoid duplicate session name issues
                    session_name = data.get("session_name", "Unknown")
                    created_at = data.get("created_at", "Unknown")

                    sessions.append({
                        "filename": filename,
                        "filepath": filepath,
                        "session_name": session_name,
                        "created_at": created_at,
                        "company_name": company_data.get("company_name", "Unknown"),
                        "module_name": module_data.get("module_name", "Unknown"),
                        "display_name": f"{session_name} ({filename})"  # Unique display name
                    })
            except json.JSONDecodeError:
                corrupted_files.append(filename)
                continue
            except Exception:
                continue

    # Warn about corrupted files (will be shown in UI if needed)
    if corrupted_files:
        st.session_state._corrupted_session_files = corrupted_files

    return sorted(sessions, key=lambda x: x.get("created_at", ""), reverse=True)

def delete_session(filepath: str) -> bool:
    """Delete a saved session"""
    try:
        os.remove(filepath)
        return True
    except Exception as e:
        st.error(f"Error deleting session: {e}")
        return False

# Streamlit App UI
def main():
    st.set_page_config(
        page_title="Board Meeting Simulation - Data Collection",
        page_icon="📊",
        layout="wide"
    )

    st.title("📊 Board Meeting Simulation - Data Collection")
    st.markdown("Upload your company and module PDFs to prepare for the simulation.")

    # Initialize session state
    if 'company_data' not in st.session_state:
        st.session_state.company_data = None
    if 'module_data' not in st.session_state:
        st.session_state.module_data = None
    if 'company_text' not in st.session_state:
        st.session_state.company_text = None
    if 'module_text' not in st.session_state:
        st.session_state.module_text = None
    if 'extraction_complete' not in st.session_state:
        st.session_state.extraction_complete = False

    # Tabs for different sections
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📤 Upload & Extract", "💾 Saved Sessions", "🔍 Audit Data", "🎮 Simulation Planning", "ℹ️ Help"])

    with tab1:
        st.header("Step 1: Upload PDF Documents")

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("🏢 Company Document")
            company_file = st.file_uploader(
                "Upload company PDF (annual report, case study, etc.)",
                type=['pdf'],
                key="company_upload"
            )

            if company_file:
                st.success(f"Uploaded: {company_file.name}")

                if st.button("Extract Company Data", key="extract_company"):
                    with st.spinner("Extracting company information..."):
                        company_text = extract_pdf_with_gemini(company_file)
                        if company_text:
                            st.session_state.company_text = company_text
                            st.info(f"Extracted {len(company_text)} characters from PDF")

                            with st.spinner("Parsing company data with AI..."):
                                try:
                                    company_data = parse_company_data(company_text)
                                    st.session_state.company_data = company_data
                                    st.success("Company data parsed successfully!")
                                except Exception as e:
                                    st.error(f"Failed to parse company data: {e}")

        with col2:
            st.subheader("📚 Module Document")
            module_file = st.file_uploader(
                "Upload module/course PDF",
                type=['pdf'],
                key="module_upload"
            )

            if module_file:
                st.success(f"Uploaded: {module_file.name}")

                if st.button("Extract Module Data", key="extract_module"):
                    with st.spinner("Extracting module content..."):
                        module_text = extract_pdf_with_gemini(module_file)
                        if module_text:
                            st.session_state.module_text = module_text
                            st.info(f"Extracted {len(module_text)} characters from PDF")

                            with st.spinner("Parsing module content with AI..."):
                                try:
                                    module_data = parse_module_content(module_text)
                                    st.session_state.module_data = module_data
                                    st.success("Module data parsed successfully!")
                                except Exception as e:
                                    st.error(f"Failed to parse module data: {e}")

        st.divider()

        # Preview extracted data
        st.header("Step 2: Review Extracted Data")

        col1, col2 = st.columns(2)

        with col1:
            if st.session_state.company_data:
                st.subheader("🏢 Company Data Preview")
                data = st.session_state.company_data

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
            if st.session_state.module_data:
                st.subheader("📚 Module Data Preview")
                data = st.session_state.module_data

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

        if st.session_state.company_data and st.session_state.module_data:
            session_name = st.text_input(
                "Session Name",
                value=f"{st.session_state.company_data.get('company_name', 'Session')} - {st.session_state.module_data.get('module_name', 'Module')}",
                help="Give your session a memorable name"
            )

            if st.button("💾 Save Data for Simulation", type="primary"):
                with st.spinner("Saving data..."):
                    filepath = save_extracted_data(
                        st.session_state.company_data,
                        st.session_state.module_data,
                        session_name
                    )
                    st.session_state.extraction_complete = True
                    st.success(f"Data saved successfully!")
                    st.info(f"File location: `{filepath}`")
                    st.balloons()

                    st.markdown("---")
                    st.markdown("### Ready for Simulation!")
                    st.markdown("You can now start the simulation using the saved data.")
        else:
            missing = []
            if not st.session_state.company_data:
                missing.append("Company data")
            if not st.session_state.module_data:
                missing.append("Module data")
            st.warning(f"Please extract both documents first. Missing: {', '.join(missing)}")

    with tab2:
        st.header("💾 Saved Sessions")

        sessions = list_saved_sessions()

        # Show warning for corrupted files if any
        if hasattr(st.session_state, '_corrupted_session_files') and st.session_state._corrupted_session_files:
            with st.expander("⚠️ Corrupted Files Detected", expanded=False):
                st.warning(f"The following session files could not be loaded (corrupted JSON):")
                for f in st.session_state._corrupted_session_files:
                    st.write(f"- `{f}`")
                st.info("You may want to delete these files from the `extracted_data/` folder.")

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

                        if st.button("📂 Load", key=f"load_{session['filename']}"):
                            data = load_extracted_data(session['filepath'])
                            if data:
                                st.session_state.company_data = data.get('company_data')
                                st.session_state.module_data = data.get('module_data')
                                st.success("Data loaded! Switch to 'Upload & Extract' tab to view.")
                                st.rerun()
        else:
            st.info("No saved sessions found. Upload and extract documents to create one.")

    with tab3:
        st.header("🔍 Audit Extracted Data")
        st.markdown("Review, edit, add, or remove extracted information before simulation.")

        # Initialize audit session state
        if 'audit_loaded_file' not in st.session_state:
            st.session_state.audit_loaded_file = None
        if 'audit_data' not in st.session_state:
            st.session_state.audit_data = None
        if 'audit_modified' not in st.session_state:
            st.session_state.audit_modified = False

        # Load session for auditing
        st.subheader("📂 Select Session to Audit")
        sessions = list_saved_sessions()

        if not sessions:
            st.warning("No saved sessions found. Please extract and save data first.")
        else:
            # Use display_name (unique) as key to avoid duplicate issues
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
                        # Ensure data structure integrity
                        if 'company_data' not in data or data['company_data'] is None:
                            data['company_data'] = {}
                        if 'module_data' not in data or data['module_data'] is None:
                            data['module_data'] = {}

                        # Ensure required keys exist in company_data
                        company_defaults = ['metrics', 'board_members', 'current_problems', 'committees']
                        for key in company_defaults:
                            if key not in data['company_data'] or data['company_data'][key] is None:
                                data['company_data'][key] = {} if key == 'metrics' else []

                        # Ensure required keys exist in module_data
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

            # Note about session sync
            st.info("💡 Changes made here are independent of the Simulation Planning tab. Remember to save your changes before switching tabs.")

            # Audit sub-tabs
            audit_tab1, audit_tab2 = st.tabs(["🏢 Company Data", "📚 Module Data"])

            # ============ COMPANY DATA AUDIT ============
            with audit_tab1:
                company_data = st.session_state.audit_data.get('company_data', {})

                # Basic Info Section
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

                # Metrics Section
                st.subheader("📊 Metrics")
                metrics = company_data.get('metrics', {})

                # Priority options for metrics
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
                            # Store priority as High/Medium or None for consistent structure
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
                        # Use safe key to handle special characters in metric names
                        metric_safe_key = safe_key("metric", metric_key)

                        if isinstance(metric_info, dict):
                            with col1:
                                new_val = st.number_input(
                                    "Value",
                                    value=safe_float(metric_info.get('value', 0), 0.0),
                                    key=f"val_{metric_safe_key}",
                                    label_visibility="collapsed"
                                )
                                if new_val != metric_info.get('value'):
                                    st.session_state.audit_data['company_data']['metrics'][metric_key]['value'] = new_val
                                    st.session_state.audit_modified = True

                            with col2:
                                new_unit = st.text_input(
                                    "Unit",
                                    value=metric_info.get('unit', '') or '',
                                    key=f"unit_{metric_safe_key}",
                                    label_visibility="collapsed"
                                )
                                if new_unit != metric_info.get('unit'):
                                    st.session_state.audit_data['company_data']['metrics'][metric_key]['unit'] = new_unit
                                    st.session_state.audit_modified = True

                            with col3:
                                new_desc = st.text_input(
                                    "Description",
                                    value=metric_info.get('description', '') or '',
                                    key=f"desc_{metric_safe_key}",
                                    label_visibility="collapsed"
                                )
                                if new_desc != metric_info.get('description'):
                                    st.session_state.audit_data['company_data']['metrics'][metric_key]['description'] = new_desc
                                    st.session_state.audit_modified = True

                            with col4:
                                # Get current priority, default to 'General' if None or missing
                                current_priority_raw = metric_info.get('priority')
                                current_priority = current_priority_raw if current_priority_raw in ["High", "Medium"] else 'General'
                                priority_idx = safe_index(priority_options, current_priority, 0)
                                new_priority = st.selectbox(
                                    "Priority",
                                    options=priority_options,
                                    index=priority_idx,
                                    key=f"priority_{metric_safe_key}",
                                    label_visibility="collapsed"
                                )
                                if new_priority != current_priority:
                                    # Store as High/Medium or None for consistent structure
                                    priority_value = new_priority if new_priority in ["High", "Medium"] else None
                                    st.session_state.audit_data['company_data']['metrics'][metric_key]['priority'] = priority_value
                                    st.session_state.audit_modified = True

                            with col5:
                                if st.button("🗑️", key=f"del_{metric_safe_key}", help="Remove this metric"):
                                    metrics_to_remove.append(metric_key)
                        else:
                            # Handle non-dict metric values (legacy data)
                            with col1:
                                st.write(str(metric_info))
                            with col5:
                                if st.button("🗑️", key=f"del_{metric_safe_key}", help="Remove this metric"):
                                    metrics_to_remove.append(metric_key)

                        st.markdown("---")

                    # Process removals
                    for key in metrics_to_remove:
                        del st.session_state.audit_data['company_data']['metrics'][key]
                        st.session_state.audit_modified = True
                    if metrics_to_remove:
                        st.rerun()

                st.divider()

                # Board Members Section
                st.subheader("👥 Board Members")
                board_members = company_data.get('board_members', [])

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
                # Always read from session state for current data
                current_board_members = st.session_state.audit_data.get('company_data', {}).get('board_members', [])
                with st.expander(f"📝 Edit Board Members ({len(current_board_members)} total)", expanded=True):
                    members_to_remove = []
                    for i, member in enumerate(current_board_members):
                        st.markdown(f"**👤 {member.get('name', f'Member {i+1}')}**")
                        col1, col2, col3 = st.columns([2, 2, 0.5])

                        with col1:
                            # Read from session state to get current value
                            current_name = st.session_state.audit_data['company_data']['board_members'][i].get('name', '')
                            new_name = st.text_input(
                                "Name",
                                value=current_name,
                                key=f"member_name_{i}"
                            )
                            if new_name != current_name:
                                st.session_state.audit_data['company_data']['board_members'][i]['name'] = new_name
                                st.session_state.audit_modified = True

                        with col2:
                            # Read from session state to get current value
                            current_role = st.session_state.audit_data['company_data']['board_members'][i].get('role', '')
                            new_role = st.text_input(
                                "Role",
                                value=current_role,
                                key=f"member_role_{i}"
                            )
                            if new_role != current_role:
                                st.session_state.audit_data['company_data']['board_members'][i]['role'] = new_role
                                st.session_state.audit_modified = True

                        with col3:
                            if st.button("🗑️", key=f"del_member_{i}", help="Remove this member"):
                                members_to_remove.append(i)

                        # Additional fields row
                        col1, col2 = st.columns(2)

                        with col1:
                            # Read from session state to get current value
                            current_expertise = st.session_state.audit_data['company_data']['board_members'][i].get('expertise', '')
                            new_expertise = st.text_input(
                                "Expertise/Domain",
                                value=current_expertise,
                                key=f"member_expertise_{i}",
                                placeholder="e.g., Finance, Technology"
                            )
                            if new_expertise != current_expertise:
                                st.session_state.audit_data['company_data']['board_members'][i]['expertise'] = new_expertise
                                st.session_state.audit_modified = True

                        with col2:
                            # Read from session state to get current value
                            current_tenure = st.session_state.audit_data['company_data']['board_members'][i].get('tenure_years', 0)
                            new_tenure = st.number_input(
                                "Tenure (years)",
                                value=safe_int(current_tenure, 0),
                                min_value=0,
                                max_value=50,
                                key=f"member_tenure_{i}"
                            )
                            if new_tenure != current_tenure:
                                st.session_state.audit_data['company_data']['board_members'][i]['tenure_years'] = new_tenure
                                st.session_state.audit_modified = True

                        # Read from session state to get current value
                        current_personality = st.session_state.audit_data['company_data']['board_members'][i].get('personality', '')
                        new_personality = st.text_area(
                            "Personality",
                            value=current_personality,
                            key=f"member_personality_{i}",
                            height=60
                        )
                        if new_personality != current_personality:
                            st.session_state.audit_data['company_data']['board_members'][i]['personality'] = new_personality
                            st.session_state.audit_modified = True

                        st.markdown("---")

                    # Process removals (in reverse to maintain indices)
                    for idx in sorted(members_to_remove, reverse=True):
                        del st.session_state.audit_data['company_data']['board_members'][idx]
                        st.session_state.audit_modified = True
                    if members_to_remove:
                        st.rerun()

                st.divider()

                # ============ COMMITTEES SECTION ============
                st.subheader("🏛️ Board Committees")

                # Initialize committees if not exists
                if 'committees' not in st.session_state.audit_data['company_data']:
                    st.session_state.audit_data['company_data']['committees'] = []

                committees = st.session_state.audit_data['company_data'].get('committees', [])

                # Get list of board member names for selection
                member_names = [m.get('name', f"Member {i+1}") for i, m in enumerate(board_members)]

                # Predefined committee types
                committee_types = [
                    "Audit Committee",
                    "Risk Management Committee",
                    "Nomination & Remuneration Committee",
                    "Corporate Social Responsibility Committee",
                    "Stakeholders Relationship Committee",
                    "Strategy Committee",
                    "Finance Committee",
                    "Technology Committee",
                    "Compliance Committee",
                    "Executive Committee",
                    "Governance Committee",
                    "Custom"
                ]

                # Add new committee
                with st.expander("➕ Create New Committee", expanded=False):
                    col1, col2 = st.columns(2)

                    with col1:
                        committee_type = st.selectbox(
                            "Committee Type",
                            options=committee_types,
                            key="new_committee_type"
                        )

                    with col2:
                        if committee_type == "Custom":
                            new_committee_name = st.text_input(
                                "Custom Committee Name",
                                key="new_custom_committee_name",
                                placeholder="Enter committee name"
                            )
                        else:
                            new_committee_name = committee_type
                            st.text_input(
                                "Committee Name",
                                value=committee_type,
                                key="new_committee_name_display",
                                disabled=True
                            )

                    new_committee_purpose = st.text_area(
                        "Committee Purpose/Mandate",
                        key="new_committee_purpose",
                        height=60,
                        placeholder="Describe the committee's purpose and responsibilities..."
                    )

                    st.markdown("**Select Committee Members:**")
                    if member_names:
                        selected_members = st.multiselect(
                            "Choose board members for this committee",
                            options=member_names,
                            key="new_committee_members",
                            help="Select one or more board members"
                        )

                        # Select chairperson from selected members
                        if selected_members:
                            committee_chair = st.selectbox(
                                "Committee Chairperson",
                                options=["None"] + selected_members,
                                key="new_committee_chair"
                            )
                        else:
                            committee_chair = "None"
                    else:
                        st.warning("No board members available. Please add board members first.")
                        selected_members = []
                        committee_chair = "None"

                    if st.button("Create Committee", key="create_committee_btn"):
                        final_name = new_committee_name if committee_type != "Custom" else new_committee_name
                        if final_name and selected_members:
                            # Check for duplicate committee names
                            existing_names = [c.get('name', '').lower() for c in committees]
                            if final_name.lower() in existing_names:
                                st.error(f"A committee named '{final_name}' already exists!")
                            else:
                                new_committee = {
                                    "name": final_name,
                                    "type": committee_type if committee_type != "Custom" else "Custom",
                                    "purpose": new_committee_purpose,
                                    "members": selected_members,
                                    "chairperson": committee_chair if committee_chair != "None" else None,
                                    "created_at": datetime.now().isoformat()
                                }
                                st.session_state.audit_data['company_data']['committees'].append(new_committee)
                                st.session_state.audit_modified = True
                                st.success(f"Created committee: {final_name} with {len(selected_members)} members")
                                st.rerun()
                        elif not final_name:
                            st.error("Please enter a committee name")
                        else:
                            st.error("Please select at least one member for the committee")

                # Display and Edit existing committees
                if committees:
                    with st.expander(f"📝 Manage Committees ({len(committees)} total)", expanded=True):
                        committees_to_remove = []

                        for i, committee in enumerate(committees):
                            st.markdown(f"### 🏛️ {committee.get('name', 'Unnamed Committee')}")

                            col1, col2, col3 = st.columns([3, 3, 1])

                            with col1:
                                edited_name = st.text_input(
                                    "Committee Name",
                                    value=committee.get('name', ''),
                                    key=f"committee_name_{i}"
                                )
                                if edited_name != committee.get('name'):
                                    st.session_state.audit_data['company_data']['committees'][i]['name'] = edited_name
                                    st.session_state.audit_modified = True

                            with col2:
                                current_committee_type = committee.get('type', 'Custom')
                                committee_type_index = safe_index(committee_types, current_committee_type, safe_index(committee_types, 'Custom', 0))
                                edited_type = st.selectbox(
                                    "Type",
                                    options=committee_types,
                                    index=committee_type_index,
                                    key=f"committee_type_{i}"
                                )
                                if edited_type != committee.get('type'):
                                    st.session_state.audit_data['company_data']['committees'][i]['type'] = edited_type
                                    st.session_state.audit_modified = True

                            with col3:
                                st.markdown("<br>", unsafe_allow_html=True)
                                if st.button("🗑️ Delete", key=f"del_committee_{i}", help="Delete this committee"):
                                    committees_to_remove.append(i)

                            edited_purpose = st.text_area(
                                "Purpose/Mandate",
                                value=committee.get('purpose', ''),
                                key=f"committee_purpose_{i}",
                                height=60
                            )
                            if edited_purpose != committee.get('purpose'):
                                st.session_state.audit_data['company_data']['committees'][i]['purpose'] = edited_purpose
                                st.session_state.audit_modified = True

                            # Edit committee members
                            current_members = committee.get('members', [])
                            # Filter to only show members that still exist
                            valid_current_members = [m for m in current_members if m in member_names]

                            edited_members = st.multiselect(
                                "Committee Members",
                                options=member_names,
                                default=valid_current_members,
                                key=f"committee_members_{i}"
                            )
                            if set(edited_members) != set(current_members):
                                st.session_state.audit_data['company_data']['committees'][i]['members'] = edited_members
                                st.session_state.audit_modified = True

                            # Edit chairperson
                            current_chair = committee.get('chairperson')
                            chair_options = ["None"] + edited_members
                            current_chair_index = 0
                            if current_chair and current_chair in edited_members:
                                current_chair_index = chair_options.index(current_chair)

                            edited_chair = st.selectbox(
                                "Chairperson",
                                options=chair_options,
                                index=current_chair_index,
                                key=f"committee_chair_{i}"
                            )
                            new_chair_value = edited_chair if edited_chair != "None" else None
                            if new_chair_value != current_chair:
                                st.session_state.audit_data['company_data']['committees'][i]['chairperson'] = new_chair_value
                                st.session_state.audit_modified = True

                            # Display member count and chair
                            col1, col2 = st.columns(2)
                            with col1:
                                st.info(f"👥 {len(edited_members)} member(s)")
                            with col2:
                                if new_chair_value:
                                    st.info(f"👤 Chair: {new_chair_value}")

                            st.markdown("---")

                        # Process committee removals
                        for idx in sorted(committees_to_remove, reverse=True):
                            del st.session_state.audit_data['company_data']['committees'][idx]
                            st.session_state.audit_modified = True
                        if committees_to_remove:
                            st.rerun()
                else:
                    st.info("No committees created yet. Use the form above to create a committee.")

                # Committee Summary View
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

                        # Member participation matrix
                        st.markdown("### Member Participation")
                        member_committees = {}
                        for member in member_names:
                            member_committees[member] = []
                            for committee in committees:
                                if member in committee.get('members', []):
                                    role = "Chair" if committee.get('chairperson') == member else "Member"
                                    member_committees[member].append(f"{committee.get('name')} ({role})")

                        for member, comms in member_committees.items():
                            if comms:
                                st.markdown(f"**{member}:** {', '.join(comms)}")
                            else:
                                st.markdown(f"**{member}:** _No committee assignments_")

                st.divider()

                # Current Problems Section
                st.subheader("⚠️ Current Problems")
                problems = company_data.get('current_problems', [])

                # Add new problem
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

                # Edit/Remove problems
                with st.expander(f"📝 Edit Problems ({len(problems)} total)", expanded=True):
                    problems_to_remove = []
                    for i, problem in enumerate(problems):
                        col1, col2 = st.columns([10, 1])

                        with col1:
                            new_problem_text = st.text_area(
                                f"Problem {i+1}",
                                value=problem,
                                key=f"problem_{i}",
                                height=60,
                                label_visibility="collapsed"
                            )
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

            # ============ MODULE DATA AUDIT ============
            with audit_tab2:
                module_data = st.session_state.audit_data.get('module_data', {})

                # Basic Info Section
                st.subheader("📋 Basic Information")
                col1, col2 = st.columns(2)

                with col1:
                    new_module_name = st.text_input(
                        "Module Name",
                        value=module_data.get('module_name', ''),
                        key="audit_module_name"
                    )
                    if new_module_name != module_data.get('module_name', ''):
                        st.session_state.audit_data['module_data']['module_name'] = new_module_name
                        st.session_state.audit_modified = True

                with col2:
                    new_subject = st.text_input(
                        "Subject Area",
                        value=module_data.get('subject_area', ''),
                        key="audit_subject_area"
                    )
                    if new_subject != module_data.get('subject_area', ''):
                        st.session_state.audit_data['module_data']['subject_area'] = new_subject
                        st.session_state.audit_modified = True

                new_module_overview = st.text_area(
                    "Overview",
                    value=module_data.get('overview', ''),
                    height=80,
                    key="audit_module_overview"
                )
                if new_module_overview != module_data.get('overview', ''):
                    st.session_state.audit_data['module_data']['overview'] = new_module_overview
                    st.session_state.audit_modified = True

                st.divider()

                # Learning Objectives Section
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

                st.divider()

                # Topics Section
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

                st.divider()

                # Key Terms Section
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
                        # Use safe key to handle special characters in term names
                        term_safe_key = safe_key("term", term)

                        with col1:
                            st.markdown(f"**{term}**")
                            new_def = st.text_area(
                                "Definition",
                                value=definition or '',
                                key=f"def_{term_safe_key}",
                                height=60,
                                label_visibility="collapsed"
                            )
                            if new_def != definition:
                                st.session_state.audit_data['module_data']['key_terms'][term] = new_def
                                st.session_state.audit_modified = True

                        with col2:
                            if st.button("🗑️", key=f"del_{term_safe_key}"):
                                terms_to_remove.append(term)

                        st.markdown("---")

                    for term_key in terms_to_remove:
                        del st.session_state.audit_data['module_data']['key_terms'][term_key]
                        st.session_state.audit_modified = True
                    if terms_to_remove:
                        st.rerun()

                st.divider()

                # Frameworks Section
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

                st.divider()

                # Assessment Criteria Section
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

            # Save Changes Section
            st.divider()
            st.subheader("💾 Save Changes")

            col1, col2, col3 = st.columns([2, 2, 2])

            with col1:
                if st.button("💾 Save to Current File", type="primary", disabled=not st.session_state.audit_modified):
                    if st.session_state.audit_loaded_file:
                        # Update modified timestamp
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
            st.divider()
            st.subheader("📄 View & Download JSON")

            # View JSON options
            view_tab1, view_tab2, view_tab3 = st.tabs(["📋 Full Data", "🏢 Company Only", "📚 Module Only"])

            with view_tab1:
                st.markdown("**Complete Session Data**")
                full_json = json.dumps(st.session_state.audit_data, indent=2, ensure_ascii=False)

                # Statistics
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Total Size", f"{len(full_json):,} chars")
                with col2:
                    metrics_count = len(st.session_state.audit_data.get('company_data', {}).get('metrics', {}))
                    st.metric("Metrics", metrics_count)
                with col3:
                    members_count = len(st.session_state.audit_data.get('company_data', {}).get('board_members', []))
                    st.metric("Board Members", members_count)

                # View JSON
                with st.expander("👁️ View Full JSON", expanded=False):
                    st.code(full_json, language="json")

                # Download buttons - use stable filenames to avoid MediaFileStorageError
                # Initialize export data in session state if needed
                if 'audit_export_timestamp' not in st.session_state:
                    st.session_state.audit_export_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

                col1, col2, col3 = st.columns([2, 2, 1])
                with col1:
                    st.download_button(
                        label="⬇️ Download Full JSON",
                        data=full_json,
                        file_name=f"full_export_{st.session_state.audit_export_timestamp}.json",
                        mime="application/json",
                        key="download_full_json"
                    )
                with col2:
                    # Minified version
                    minified_json = json.dumps(st.session_state.audit_data, ensure_ascii=False)
                    st.download_button(
                        label="⬇️ Download Minified JSON",
                        data=minified_json,
                        file_name=f"full_export_minified_{st.session_state.audit_export_timestamp}.json",
                        mime="application/json",
                        key="download_full_minified"
                    )
                with col3:
                    if st.button("🔄", key="refresh_audit_export", help="Refresh export timestamp"):
                        st.session_state.audit_export_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                        st.rerun()

            with view_tab2:
                st.markdown("**Company Data Only**")
                company_json = json.dumps(st.session_state.audit_data.get('company_data', {}), indent=2, ensure_ascii=False)

                # Statistics
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

                # View JSON
                with st.expander("👁️ View Company JSON", expanded=False):
                    st.code(company_json, language="json")

                # Download - use stable timestamp from session state
                st.download_button(
                    label="⬇️ Download Company JSON",
                    data=company_json,
                    file_name=f"company_export_{st.session_state.audit_export_timestamp}.json",
                    mime="application/json",
                    key="download_company_json"
                )

            with view_tab3:
                st.markdown("**Module Data Only**")
                module_json = json.dumps(st.session_state.audit_data.get('module_data', {}), indent=2, ensure_ascii=False)

                # Statistics
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

                # View JSON
                with st.expander("👁️ View Module JSON", expanded=False):
                    st.code(module_json, language="json")

                # Download - use stable timestamp from session state
                st.download_button(
                    label="⬇️ Download Module JSON",
                    data=module_json,
                    file_name=f"module_export_{st.session_state.audit_export_timestamp}.json",
                    mime="application/json",
                    key="download_module_json"
                )

            # Copy to clipboard helper
            st.divider()
            with st.expander("📋 Copy JSON to Clipboard"):
                st.markdown("Select which data to copy:")
                copy_option = st.radio(
                    "Select data",
                    options=["Full Data", "Company Only", "Module Only"],
                    horizontal=True,
                    key="copy_option",
                    label_visibility="collapsed"
                )

                if copy_option == "Full Data":
                    copy_data = json.dumps(st.session_state.audit_data, indent=2, ensure_ascii=False)
                elif copy_option == "Company Only":
                    copy_data = json.dumps(st.session_state.audit_data.get('company_data', {}), indent=2, ensure_ascii=False)
                else:
                    copy_data = json.dumps(st.session_state.audit_data.get('module_data', {}), indent=2, ensure_ascii=False)

                st.text_area(
                    "JSON Data (select all and copy)",
                    value=copy_data,
                    height=200,
                    key="copy_json_area"
                )

    with tab4:
        st.header("🎮 Simulation Planning")
        st.markdown("Configure how the simulation will flow: number of rounds, difficulty progression, and content focus.")

        # Initialize simulation config in session state
        if 'simulation_config' not in st.session_state:
            st.session_state.simulation_config = get_default_simulation_config()

        # ============ LOAD SESSION FOR PLANNING ============
        st.subheader("📂 Select Session to Configure")
        sessions = list_saved_sessions()

        if not sessions:
            st.warning("No saved sessions found. Please extract and save data first in the 'Upload & Extract' tab.")
        else:
            # Use display_name (unique) as key to avoid duplicate issues
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
                    # Load existing config or use default
                    if 'simulation_config' in data and data['simulation_config']:
                        loaded_config = data['simulation_config']
                        default_config = get_default_simulation_config()

                        # Ensure backward compatibility - merge with defaults
                        # Ensure initial_setup exists with all required keys
                        if 'initial_setup' not in loaded_config or loaded_config['initial_setup'] is None:
                            loaded_config['initial_setup'] = default_config['initial_setup']
                        else:
                            # Ensure all keys exist in initial_setup
                            for key, value in default_config['initial_setup'].items():
                                if key not in loaded_config['initial_setup']:
                                    loaded_config['initial_setup'][key] = value

                        # Ensure rounds list exists
                        if 'rounds' not in loaded_config or loaded_config['rounds'] is None:
                            loaded_config['rounds'] = default_config['rounds']
                        else:
                            # Ensure each round has all required keys
                            for i, round_cfg in enumerate(loaded_config['rounds']):
                                if round_cfg is None:
                                    loaded_config['rounds'][i] = default_config['rounds'][0].copy()
                                    loaded_config['rounds'][i]['round_number'] = i + 1
                                else:
                                    for key in ['round_type', 'difficulty', 'focus_area', 'time_pressure']:
                                        if key not in round_cfg:
                                            round_cfg[key] = default_config['rounds'][0].get(key)

                        # Ensure total_rounds matches rounds list length
                        if 'total_rounds' not in loaded_config:
                            loaded_config['total_rounds'] = len(loaded_config['rounds'])

                        # Ensure difficulty_settings and round_type_settings exist
                        if 'difficulty_settings' not in loaded_config:
                            loaded_config['difficulty_settings'] = default_config['difficulty_settings']
                        if 'round_type_settings' not in loaded_config:
                            loaded_config['round_type_settings'] = default_config['round_type_settings']

                        st.session_state.simulation_config = loaded_config
                    else:
                        st.session_state.simulation_config = get_default_simulation_config()

                    # Ensure data structure for planning
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
            if 'planning_session_data' in st.session_state and st.session_state.planning_session_data:
                config = st.session_state.simulation_config

                # ============ SECTION 1: NUMBER OF ROUNDS ============
                st.subheader("1️⃣ Number of Rounds")
                st.markdown("Set how many rounds the simulation will have.")

                col1, col2 = st.columns([1, 2])
                with col1:
                    total_rounds = st.number_input(
                        "Total Rounds",
                        min_value=1,
                        max_value=20,
                        value=safe_int(config.get('total_rounds', 5), 5),
                        key="total_rounds_input",
                        help="Number of decision rounds in the simulation"
                    )

                    if total_rounds != config.get('total_rounds'):
                        # Update total rounds and adjust rounds list
                        st.session_state.simulation_config['total_rounds'] = total_rounds
                        current_rounds = len(config.get('rounds', []))

                        if total_rounds > current_rounds:
                            # Add new rounds
                            for i in range(current_rounds, total_rounds):
                                st.session_state.simulation_config['rounds'].append({
                                    "round_number": i + 1,
                                    "round_type": "both",
                                    "difficulty": "medium",
                                    "focus_area": None,
                                    "time_pressure": "normal"
                                })
                        elif total_rounds < current_rounds:
                            # Remove excess rounds
                            st.session_state.simulation_config['rounds'] = config['rounds'][:total_rounds]

                with col2:
                    st.info(f"📊 The simulation will have **{total_rounds} rounds** of board decisions.")

                st.divider()

                # ============ SECTION 2: INITIAL SETUP (Deterministic Start) ============
                st.subheader("2️⃣ Initial Setup (Deterministic Start)")
                st.markdown("Configure the starting conditions for a consistent simulation experience.")

                initial_setup = config.get('initial_setup', {})

                col1, col2 = st.columns(2)

                with col1:
                    # Starting scenario
                    scenario_options = {
                        "default": "Default - Standard business conditions",
                        "crisis": "Crisis - Company facing immediate challenges",
                        "growth": "Growth - Expansion opportunities available",
                        "stable": "Stable - Steady state operations",
                        "custom": "Custom - Define your own scenario"
                    }

                    # Check if current scenario is custom (not in predefined options except 'custom')
                    current_scenario = initial_setup.get('starting_scenario', 'default')
                    is_custom_scenario = current_scenario not in ['default', 'crisis', 'growth', 'stable'] or current_scenario == 'custom'

                    if is_custom_scenario and current_scenario != 'custom':
                        scenario_idx = list(scenario_options.keys()).index('custom')
                    else:
                        scenario_idx = list(scenario_options.keys()).index(current_scenario) if current_scenario in scenario_options else 0

                    starting_scenario = st.selectbox(
                        "Starting Scenario",
                        options=list(scenario_options.keys()),
                        format_func=lambda x: scenario_options[x],
                        index=scenario_idx,
                        key="starting_scenario_select"
                    )

                    # Show custom input field if "custom" is selected
                    if starting_scenario == "custom":
                        custom_scenario = st.text_area(
                            "Custom Scenario Description",
                            value=initial_setup.get('custom_scenario_text', '') if initial_setup.get('starting_scenario') == 'custom' or is_custom_scenario else '',
                            key="custom_scenario_input",
                            placeholder="Describe the starting scenario for the simulation...",
                            height=100
                        )
                        st.session_state.simulation_config['initial_setup']['starting_scenario'] = 'custom'
                        st.session_state.simulation_config['initial_setup']['custom_scenario_text'] = custom_scenario
                    else:
                        st.session_state.simulation_config['initial_setup']['starting_scenario'] = starting_scenario
                        # Clear custom text if not using custom
                        if 'custom_scenario_text' in st.session_state.simulation_config['initial_setup']:
                            st.session_state.simulation_config['initial_setup']['custom_scenario_text'] = ''

                with col2:
                    # Initial difficulty
                    init_difficulty_options = ["easy", "medium", "hard"]
                    initial_difficulty = st.selectbox(
                        "Initial Difficulty",
                        options=init_difficulty_options,
                        index=safe_index(init_difficulty_options, initial_setup.get('initial_difficulty', 'medium'), 1),
                        key="initial_difficulty_select"
                    )
                    st.session_state.simulation_config['initial_setup']['initial_difficulty'] = initial_difficulty

                # Display what this means
                with st.expander("ℹ️ What do these settings mean?"):
                    st.markdown("""
                    - **Starting Scenario**: Sets the narrative context for the simulation:
                      - *Default*: Balanced starting point with mixed challenges and opportunities
                      - *Crisis*: Urgent problems require immediate attention
                      - *Growth*: Focus on expansion and investment decisions
                      - *Stable*: Maintenance and optimization focus
                      - *Custom*: Define your own unique starting scenario
                    - **Initial Difficulty**: Sets the baseline challenge level for the first round
                    """)

                st.divider()

                # ============ SECTION 3: ROUND TYPE CONFIGURATION ============
                st.subheader("3️⃣ Round Type Configuration")
                st.markdown("Define whether each round focuses on **Business** challenges, **Module** concepts, or **Both**.")

                # Quick setup options
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

                # Round type explanations
                type_info = config.get('round_type_settings', {})
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.markdown("**🏢 Business**")
                    st.caption(type_info.get('business', {}).get('description', 'Focus on company challenges'))
                with col2:
                    st.markdown("**📚 Module**")
                    st.caption(type_info.get('module', {}).get('description', 'Focus on theoretical concepts'))
                with col3:
                    st.markdown("**🔄 Both**")
                    st.caption(type_info.get('both', {}).get('description', 'Integrate theory with practice'))

                st.divider()

                # ============ SECTION 4: DIFFICULTY CONFIGURATION ============
                st.subheader("4️⃣ Difficulty Configuration")
                st.markdown("Set the difficulty level for each round: **Easy**, **Medium**, or **Hard**.")

                # Quick difficulty patterns
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

                # Difficulty explanations
                diff_settings = config.get('difficulty_settings', {})
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.markdown("**🟢 Easy**")
                    easy = diff_settings.get('easy', {})
                    st.caption(f"Questions: {easy.get('question_complexity', 'straightforward')}")
                    st.caption(f"Board: {easy.get('board_pressure', 'supportive')}")
                    st.caption(f"Hints: {'Yes' if easy.get('hints_available') else 'No'}")
                with col2:
                    st.markdown("**🟡 Medium**")
                    medium = diff_settings.get('medium', {})
                    st.caption(f"Questions: {medium.get('question_complexity', 'moderate')}")
                    st.caption(f"Board: {medium.get('board_pressure', 'balanced')}")
                    st.caption(f"Hints: {'Yes' if medium.get('hints_available') else 'No'}")
                with col3:
                    st.markdown("**🔴 Hard**")
                    hard = diff_settings.get('hard', {})
                    st.caption(f"Questions: {hard.get('question_complexity', 'challenging')}")
                    st.caption(f"Board: {hard.get('board_pressure', 'demanding')}")
                    st.caption(f"Hints: {'Yes' if hard.get('hints_available') else 'No'}")

                st.divider()

                # ============ DETAILED ROUND CONFIGURATION ============
                st.subheader("📋 Detailed Round Configuration")
                st.markdown("Fine-tune each individual round.")

                rounds = st.session_state.simulation_config.get('rounds', [])

                # Get available focus areas from loaded data - include ALL problems and topics
                company_problems = st.session_state.planning_session_data.get('company_data', {}).get('current_problems', [])
                module_topics = [t.get('name', '') for t in st.session_state.planning_session_data.get('module_data', {}).get('topics', [])]
                focus_options = ["None (Auto-select)", "Custom (Enter below)"] + company_problems + module_topics

                for i, round_config in enumerate(rounds):
                    with st.expander(f"Round {i + 1}", expanded=(i < 3)):
                        col1, col2, col3, col4 = st.columns(4)

                        with col1:
                            round_type_options = ["business", "module", "both"]
                            round_type = st.selectbox(
                                "Type",
                                options=round_type_options,
                                index=safe_index(round_type_options, round_config.get('round_type', 'both'), 2),
                                key=f"round_type_{i}"
                            )
                            if round_type != round_config.get('round_type'):
                                st.session_state.simulation_config['rounds'][i]['round_type'] = round_type

                        with col2:
                            difficulty_options = ["easy", "medium", "hard"]
                            difficulty = st.selectbox(
                                "Difficulty",
                                options=difficulty_options,
                                index=safe_index(difficulty_options, round_config.get('difficulty', 'medium'), 1),
                                key=f"round_difficulty_{i}"
                            )
                            if difficulty != round_config.get('difficulty'):
                                st.session_state.simulation_config['rounds'][i]['difficulty'] = difficulty

                        with col3:
                            time_pressure_options = ["relaxed", "normal", "urgent"]
                            time_pressure = st.selectbox(
                                "Time Pressure",
                                options=time_pressure_options,
                                index=safe_index(time_pressure_options, round_config.get('time_pressure', 'normal'), 1),
                                key=f"round_time_{i}"
                            )
                            if time_pressure != round_config.get('time_pressure'):
                                st.session_state.simulation_config['rounds'][i]['time_pressure'] = time_pressure

                        with col4:
                            current_focus = round_config.get('focus_area') or "None (Auto-select)"
                            # Check if current focus is a custom value (not in predefined options)
                            is_custom = current_focus not in focus_options and current_focus != "None (Auto-select)"
                            if is_custom:
                                focus_idx = 1  # "Custom (Enter below)"
                            else:
                                focus_idx = focus_options.index(current_focus) if current_focus in focus_options else 0

                            focus_area = st.selectbox(
                                "Focus Area",
                                options=focus_options,
                                index=focus_idx,
                                key=f"round_focus_{i}"
                            )

                        # Show custom input field if "Custom" is selected
                        if focus_area == "Custom (Enter below)":
                            custom_focus = st.text_input(
                                "Custom Focus Area",
                                value=round_config.get('focus_area', '') if round_config.get('focus_area') not in focus_options else '',
                                key=f"round_custom_focus_{i}",
                                placeholder="Enter your custom focus area..."
                            )
                            if custom_focus:
                                if custom_focus != round_config.get('focus_area'):
                                    st.session_state.simulation_config['rounds'][i]['focus_area'] = custom_focus
                            else:
                                # If custom is selected but empty, set to None
                                if round_config.get('focus_area') is not None:
                                    st.session_state.simulation_config['rounds'][i]['focus_area'] = None
                        else:
                            new_focus = None if focus_area == "None (Auto-select)" else focus_area
                            if new_focus != round_config.get('focus_area'):
                                st.session_state.simulation_config['rounds'][i]['focus_area'] = new_focus

                st.divider()

                # ============ VISUAL SUMMARY ============
                st.subheader("📊 Configuration Summary")

                # Create visual summary
                summary_data = []
                for i, r in enumerate(st.session_state.simulation_config.get('rounds', [])):
                    type_emoji = {"business": "🏢", "module": "📚", "both": "🔄"}.get(r.get('round_type', 'both'), "🔄")
                    diff_emoji = {"easy": "🟢", "medium": "🟡", "hard": "🔴"}.get(r.get('difficulty', 'medium'), "🟡")
                    time_emoji = {"relaxed": "🐢", "normal": "⏱️", "urgent": "⚡"}.get(r.get('time_pressure', 'normal'), "⏱️")

                    # Safely handle focus area display
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

                # Display as a simple table
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
                            # Load current data
                            data = load_extracted_data(st.session_state.planning_loaded_file)
                            if data:
                                # Update with new config
                                data['simulation_config'] = st.session_state.simulation_config
                                data['modified_at'] = datetime.now().isoformat()

                                # Save back
                                with open(st.session_state.planning_loaded_file, 'w', encoding='utf-8') as f:
                                    json.dump(data, f, indent=2, ensure_ascii=False)

                                st.success("Configuration saved successfully!")
                                st.balloons()

                with col2:
                    # Export config as JSON - use stable filename
                    config_json = json.dumps(st.session_state.simulation_config, indent=2, ensure_ascii=False)
                    # Store in session state for stable download
                    if 'config_export_json' not in st.session_state or st.session_state.get('config_export_needs_update', True):
                        st.session_state.config_export_json = config_json
                        st.session_state.config_export_filename = f"simulation_config_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                        st.session_state.config_export_needs_update = False

                    st.download_button(
                        label="⬇️ Export Config JSON",
                        data=st.session_state.config_export_json,
                        file_name=st.session_state.config_export_filename,
                        mime="application/json",
                        key="download_config_json"
                    )
                    if st.button("🔄 Refresh Export", key="refresh_config_export", help="Update the export with latest changes"):
                        st.session_state.config_export_needs_update = True
                        st.rerun()

                # Show raw JSON
                with st.expander("👁️ View Configuration JSON"):
                    st.code(json.dumps(st.session_state.simulation_config, indent=2), language="json")

                st.divider()

                # ============ FINAL REVIEW & EXPORT ============
                st.subheader("✅ Final Review & Export")
                st.markdown("Review and download the complete simulation package with all data and configuration.")

                # Load the latest saved data
                if 'planning_loaded_file' in st.session_state:
                    final_data = load_extracted_data(st.session_state.planning_loaded_file)
                    if final_data:
                        # Merge current simulation config with loaded data
                        final_data['simulation_config'] = st.session_state.simulation_config
                        final_data['export_timestamp'] = datetime.now().isoformat()
                        final_data['status'] = 'ready_for_simulation'

                        # ============ DATA SUMMARY ============
                        st.markdown("#### 📊 Data Summary")

                        col1, col2, col3 = st.columns(3)

                        with col1:
                            st.markdown("**🏢 Company Data**")
                            company = final_data.get('company_data', {})
                            st.write(f"• Company: {company.get('company_name', 'N/A')}")
                            st.write(f"• Metrics: {len(company.get('metrics', {}))}")
                            st.write(f"• Board Members: {len(company.get('board_members', []))}")
                            st.write(f"• Committees: {len(company.get('committees', []))}")
                            st.write(f"• Problems: {len(company.get('current_problems', []))}")

                        with col2:
                            st.markdown("**📚 Module Data**")
                            module = final_data.get('module_data', {})
                            st.write(f"• Module: {module.get('module_name', 'N/A')}")
                            st.write(f"• Subject: {module.get('subject_area', 'N/A')}")
                            st.write(f"• Topics: {len(module.get('topics', []))}")
                            st.write(f"• Frameworks: {len(module.get('frameworks', []))}")
                            st.write(f"• Key Terms: {len(module.get('key_terms', {}))}")

                        with col3:
                            st.markdown("**🎮 Simulation Config**")
                            sim_config = final_data.get('simulation_config', {})
                            st.write(f"• Total Rounds: {sim_config.get('total_rounds', 0)}")
                            initial = sim_config.get('initial_setup', {})
                            st.write(f"• Scenario: {safe_str(initial.get('starting_scenario'), 'N/A').title()}")
                            st.write(f"• Initial Difficulty: {safe_str(initial.get('initial_difficulty'), 'N/A').title()}")

                            # Count difficulty distribution
                            rounds = sim_config.get('rounds', [])
                            easy_count = sum(1 for r in rounds if r.get('difficulty') == 'easy')
                            medium_count = sum(1 for r in rounds if r.get('difficulty') == 'medium')
                            hard_count = sum(1 for r in rounds if r.get('difficulty') == 'hard')
                            st.write(f"• Difficulty Mix: 🟢{easy_count} 🟡{medium_count} 🔴{hard_count}")

                        st.divider()

                        # ============ VALIDATION CHECKLIST ============
                        st.markdown("#### ✔️ Validation Checklist")

                        validation_issues = []
                        validation_warnings = []

                        # Check company data
                        if not company.get('company_name'):
                            validation_issues.append("Company name is missing")
                        if len(company.get('metrics', {})) < 5:
                            validation_warnings.append(f"Only {len(company.get('metrics', {}))} metrics - consider adding more for richer simulation")
                        if len(company.get('board_members', [])) < 3:
                            validation_warnings.append(f"Only {len(company.get('board_members', []))} board members - consider adding more")
                        if len(company.get('current_problems', [])) < 2:
                            validation_warnings.append(f"Only {len(company.get('current_problems', []))} problems defined")

                        # Check module data
                        if not module.get('module_name'):
                            validation_issues.append("Module name is missing")
                        if len(module.get('topics', [])) < 3:
                            validation_warnings.append(f"Only {len(module.get('topics', []))} topics - consider adding more")
                        if len(module.get('key_terms', {})) < 5:
                            validation_warnings.append(f"Only {len(module.get('key_terms', {}))} key terms defined")

                        # Check simulation config
                        if sim_config.get('total_rounds', 0) < 1:
                            validation_issues.append("No simulation rounds configured")
                        if initial.get('starting_scenario') == 'custom' and not initial.get('custom_scenario_text', '').strip():
                            validation_warnings.append("Custom scenario selected but no description provided")

                        # Display validation results
                        if validation_issues:
                            st.error("**Issues Found (Must Fix):**")
                            for issue in validation_issues:
                                st.write(f"❌ {issue}")

                        if validation_warnings:
                            st.warning("**Warnings (Optional to Fix):**")
                            for warning in validation_warnings:
                                st.write(f"⚠️ {warning}")

                        if not validation_issues and not validation_warnings:
                            st.success("✅ All validations passed! Your simulation package is ready.")
                        elif not validation_issues:
                            st.info("✅ No critical issues. You can proceed with the export.")

                        st.divider()

                        # ============ FINAL CONFIRMATION & DOWNLOAD ============
                        st.markdown("#### 📦 Export Complete Package")

                        # Confirmation checkbox
                        confirmed = st.checkbox(
                            "I have reviewed the data and simulation configuration and confirm it is ready for export",
                            key="final_confirmation_checkbox"
                        )

                        if confirmed:
                            # Prepare export button
                            if st.button("🔄 Prepare Export Package", key="prepare_export_package", type="secondary"):
                                # Generate export data only when button is clicked
                                session_name = final_data.get('session_name', 'simulation')
                                safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_name)
                                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

                                export_data = {
                                    "session_name": final_data.get('session_name', 'Unnamed Session'),
                                    "created_at": final_data.get('created_at'),
                                    "modified_at": final_data.get('modified_at'),
                                    "export_timestamp": datetime.now().isoformat(),
                                    "status": "confirmed_ready",
                                    "company_data": final_data.get('company_data', {}),
                                    "module_data": final_data.get('module_data', {}),
                                    "simulation_config": st.session_state.simulation_config,
                                    "validation": {
                                        "issues_count": len(validation_issues),
                                        "warnings_count": len(validation_warnings),
                                        "is_valid": len(validation_issues) == 0
                                    }
                                }

                                # Store in session state for stable downloads
                                st.session_state.final_export_data = export_data
                                st.session_state.final_export_full_json = json.dumps(export_data, indent=2, ensure_ascii=False)
                                st.session_state.final_export_minified_json = json.dumps(export_data, ensure_ascii=False)
                                st.session_state.final_export_filename_full = f"{safe_name}_complete_{timestamp}.json"
                                st.session_state.final_export_filename_mini = f"{safe_name}_minified_{timestamp}.json"
                                st.session_state.final_export_ready = True
                                st.success("Export package prepared! Click the download buttons below.")
                                st.rerun()

                            # Show download buttons only if export is prepared
                            if st.session_state.get('final_export_ready', False):
                                st.success("✅ Export package is ready for download!")

                                col1, col2, col3 = st.columns(3)

                                with col1:
                                    st.download_button(
                                        label="📦 Download Full Package",
                                        data=st.session_state.final_export_full_json,
                                        file_name=st.session_state.final_export_filename_full,
                                        mime="application/json",
                                        type="primary",
                                        key="download_full_package"
                                    )
                                    st.caption("Complete data + config (formatted)")

                                with col2:
                                    st.download_button(
                                        label="⚡ Download Minified",
                                        data=st.session_state.final_export_minified_json,
                                        file_name=st.session_state.final_export_filename_mini,
                                        mime="application/json",
                                        key="download_minified_package"
                                    )
                                    st.caption("Smaller file size")

                                with col3:
                                    if st.button("💾 Save Final Version", key="save_final_version"):
                                        # Update the source file with confirmed status
                                        with open(st.session_state.planning_loaded_file, 'w', encoding='utf-8') as f:
                                            json.dump(st.session_state.final_export_data, f, indent=2, ensure_ascii=False)
                                        st.success("Final version saved!")
                                        st.balloons()
                                    st.caption("Save to current session file")

                                st.divider()

                                # Preview of export
                                with st.expander("👁️ Preview Export Data", expanded=False):
                                    preview_tabs = st.tabs(["📋 Summary", "🏢 Company", "📚 Module", "🎮 Config"])
                                    export_data = st.session_state.final_export_data

                                    with preview_tabs[0]:
                                        st.json({
                                            "session_name": export_data['session_name'],
                                            "export_timestamp": export_data['export_timestamp'],
                                            "status": export_data['status'],
                                            "validation": export_data['validation']
                                        })

                                    with preview_tabs[1]:
                                        st.json(export_data['company_data'])

                                    with preview_tabs[2]:
                                        st.json(export_data['module_data'])

                                    with preview_tabs[3]:
                                        st.json(export_data['simulation_config'])
                            else:
                                st.info("👆 Click 'Prepare Export Package' to generate download files.")

                        else:
                            st.info("👆 Check the confirmation box above to enable export options.")

                else:
                    st.warning("Please load a session first to access the final export.")

    with tab5:
        st.header("ℹ️ How to Use")

        st.markdown("""
        ### Overview
        This app helps you prepare data for the Board Meeting Simulation. You'll upload two PDF documents:

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
        4. **Audit**: Use the Audit Data tab to check, edit, add, or remove information
        5. **Plan Simulation**: Configure rounds, difficulty, and content focus
        6. **Save**: Give your session a name and save for later simulation

        ### Simulation Planning

        The **Simulation Planning** tab allows you to configure:

        **1. Number of Rounds**
        - Set how many decision rounds the simulation will have (1-20)

        **2. Initial Setup (Deterministic Start)**
        - **Starting Scenario**: Choose the narrative context (Default, Crisis, Growth, Stable, or Custom)
        - **Custom Scenario**: Define your own unique starting scenario when "Custom" is selected
        - **Initial Difficulty**: Set the baseline challenge level

        **3. Round Types**
        - **Business**: Focus on company-specific challenges
        - **Module**: Focus on applying theoretical concepts
        - **Both**: Integrate theory with company challenges

        **4. Difficulty Levels**
        - **Easy**: Supportive board, straightforward questions, hints available
        - **Medium**: Balanced challenge, standard time allocation
        - **Hard**: Demanding board, complex questions, tight deadlines

        **5. Detailed Round Configuration**
        - Configure each round individually with Type, Difficulty, Time Pressure, and Focus Area
        - Use quick-set buttons to apply patterns (Progressive difficulty, Alternating types, etc.)
        - Set custom focus areas for specific rounds

        **6. Final Review & Export**
        - Review complete data summary (Company, Module, Simulation Config)
        - Validation checklist identifies issues and warnings
        - Confirm and download the complete simulation package
        - Export options: Full Package (formatted), Minified, or Save to file

        ### Audit Features

        The **Audit Data** tab allows you to:
        - **Check**: Review all extracted data in detail
        - **Edit**: Modify existing values (metrics, board members, topics, etc.)
        - **Add**: Add new items (metrics, board members, problems, topics, terms, etc.)
        - **Remove**: Delete items that are incorrect or unnecessary
        - **Committees**: Create and manage board committees with selected members
        - **Save**: Save changes to the current file or as a new session
        - **Export**: Download the data as a JSON file

        ### Board Committees

        You can create multiple committees from your board members:
        - **Predefined Types**: Audit, Risk Management, Nomination & Remuneration, CSR, Strategy, Finance, Technology, Compliance, Executive, Governance
        - **Custom Committees**: Create any custom committee type
        - **Member Assignment**: Select multiple board members for each committee
        - **Chairperson**: Designate a chairperson from committee members
        - **Purpose/Mandate**: Define each committee's responsibilities
        - **Summary View**: See an overview of all committees and member participation

        ### Tips

        - Use clear, text-based PDFs for best results
        - Larger documents may take longer to process
        - You can re-extract if the initial results aren't satisfactory
        - Saved sessions can be loaded later without re-uploading
        - Always audit extracted data before running simulations
        - Use progressive difficulty (Easy→Hard) for learning scenarios

        ### Technical Notes

        - Data is saved as JSON files in the `extracted_data/` folder
        - The simulation app can load these files directly
        - API key for Gemini is required in `.streamlit/secrets.toml`
        - Simulation config is stored within the session JSON file
        """)

if __name__ == "__main__":
    main()