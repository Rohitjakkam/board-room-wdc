"""
Unified data management — load, save, list, delete simulation JSON files.
All operations use the single `data/` directory.
"""

import json
import os
import streamlit as st
from datetime import datetime
from typing import Dict, List, Optional


def get_data_dir() -> str:
    """Get the unified data directory path."""
    # Always resolve relative to the project root (parent of core/)
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def ensure_data_dir():
    """Ensure the data directory exists."""
    data_dir = get_data_dir()
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)


def load_simulation_data(file_path: str) -> Optional[Dict]:
    """Load simulation data from JSON file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        st.error(f"Error loading simulation data: {e}")
        return None


def get_available_simulations() -> List[Dict]:
    """Scan data/ folder and return list of available simulations with metadata."""
    data_dir = get_data_dir()
    simulations = []
    if not os.path.isdir(data_dir):
        return simulations
    for filename in sorted(os.listdir(data_dir)):
        if not filename.endswith('.json'):
            continue
        filepath = os.path.join(data_dir, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            company = data.get('company_data', {})
            module = data.get('module_data', {})
            simulations.append({
                'filename': filename,
                'filepath': filepath,
                'session_name': data.get('session_name', filename),
                'company_name': company.get('company_name', 'Unknown Company'),
                'company_overview': company.get('company_overview', ''),
                'industry': company.get('industry', 'N/A'),
                'module_name': module.get('module_name', 'N/A'),
                'board_count': len(company.get('board_members', [])),
                'created_at': data.get('created_at', ''),
            })
        except Exception:
            continue
    return simulations


def save_extracted_data(company_data: Dict, module_data: Dict, session_name: str, simulation_config: Dict = None) -> str:
    """Save extracted data to JSON file in the unified data/ directory."""
    ensure_data_dir()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if not session_name or not session_name.strip():
        session_name = f"Session_{timestamp}"
    safe_session_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_name)
    if not safe_session_name:
        safe_session_name = "session"
    filename = f"{safe_session_name}_complete_{timestamp}.json"
    filepath = os.path.join(get_data_dir(), filename)

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
    """Load previously extracted data and normalize structure."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Normalize metrics structure: ensure all metrics have priority field
        if 'company_data' in data and 'metrics' in data['company_data']:
            for metric_key, metric_info in data['company_data']['metrics'].items():
                if isinstance(metric_info, dict):
                    if 'priority' not in metric_info:
                        metric_info['priority'] = None
                    elif metric_info['priority'] not in ["High", "Medium"]:
                        metric_info['priority'] = None

        return data
    except Exception as e:
        st.error(f"Error loading data: {e}")
        return None


def list_saved_sessions() -> list:
    """List all saved session files from the unified data/ directory."""
    ensure_data_dir()
    data_dir = get_data_dir()
    sessions = []
    corrupted_files = []
    for filename in os.listdir(data_dir):
        if filename.endswith('.json'):
            filepath = os.path.join(data_dir, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    company_data = data.get("company_data") or {}
                    module_data = data.get("module_data") or {}

                    session_name = data.get("session_name", "Unknown")
                    created_at = data.get("created_at", "Unknown")

                    sessions.append({
                        "filename": filename,
                        "filepath": filepath,
                        "session_name": session_name,
                        "created_at": created_at,
                        "company_name": company_data.get("company_name", "Unknown"),
                        "module_name": module_data.get("module_name", "Unknown"),
                        "display_name": f"{session_name} ({filename})"
                    })
            except json.JSONDecodeError:
                corrupted_files.append(filename)
                continue
            except Exception:
                continue

    if corrupted_files:
        st.session_state._corrupted_session_files = corrupted_files

    return sorted(sessions, key=lambda x: x.get("created_at", ""), reverse=True)


def delete_session(filepath: str) -> bool:
    """Delete a saved session file."""
    try:
        os.remove(filepath)
        return True
    except Exception as e:
        st.error(f"Error deleting session: {e}")
        return False


def get_default_simulation_config() -> Dict:
    """Return default simulation configuration."""
    return {
        "total_rounds": 5,
        "initial_setup": {
            "starting_scenario": "default",
            "custom_scenario_text": "",
            "initial_difficulty": "medium"
        },
        "rounds": [
            {
                "round_number": i + 1,
                "round_type": "both",
                "difficulty": "medium",
                "focus_area": None,
                "time_pressure": "normal"
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
