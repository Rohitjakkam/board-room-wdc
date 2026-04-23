"""
Unified data management — load, save, list, delete simulation data via Firestore.
"""

import json
import logging
import os
import streamlit as st
from datetime import datetime
from typing import Dict, List, Optional

from core.firebase_client import get_firestore_client

logger = logging.getLogger(__name__)

_COLLECTION = "simulations"

_ACRONYMS = {
    'Ebitda': 'EBITDA', 'Nps': 'NPS', 'Roi': 'ROI', 'Roe': 'ROE', 'Roa': 'ROA',
    'Yoy': 'YoY', 'Kpi': 'KPI', 'Kpis': 'KPIs', 'Esg': 'ESG',
    'Hr': 'HR', 'It': 'IT', 'Ceo': 'CEO', 'Cfo': 'CFO', 'Coo': 'COO',
    'Cto': 'CTO', 'Ciso': 'CISO', 'Cmo': 'CMO', 'Id': 'ID',
    'Erp': 'ERP', 'Crm': 'CRM', 'Saas': 'SaaS', 'Arr': 'ARR', 'Mrr': 'MRR',
    'Ltv': 'LTV', 'Cac': 'CAC', 'Csat': 'CSAT', 'Ar': 'AR', 'Ap': 'AP',
    'Gdp': 'GDP', 'Ipo': 'IPO',
}


def _title_with_acronyms(text: str) -> str:
    """Like str.title() but preserves known acronyms (e.g. EBITDA, NPS, ROI)."""
    return ' '.join(_ACRONYMS.get(w, w) for w in text.title().split())


def _get_collection():
    """Return Firestore collection reference, or None if unavailable."""
    db = get_firestore_client()
    if db is None:
        return None
    return db.collection(_COLLECTION)


def _make_doc_id(session_name: str) -> str:
    """Generate a safe document ID from session name + timestamp."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in (session_name or "session"))
    if not safe:
        safe = "session"
    return f"{safe[:80]}_{timestamp}"


def _infer_unit(metric_key: str) -> str:
    """Infer a sensible unit for a metric based on its key name."""
    key = metric_key.lower()
    if any(kw in key for kw in ('nps', 'net_promoter', 'promoter_score', 'satisfaction_score',
                                  'sentiment_score', 'happiness_score')):
        return 'score'
    if any(kw in key for kw in ('employees', 'employee_count', 'headcount', 'workforce', 'staff_count')):
        return 'employees'
    if any(kw in key for kw in ('_count', 'count_', 'incident', '_incidents', 'violations',
                                  'defects', '_risks', 'risks_', 'tickets', 'cases')):
        return 'count'
    if any(kw in key for kw in ('status', 'classification', 'tier', 'level', 'phase',
                                  'environment', 'challenges')):
        return 'status'
    if any(kw in key for kw in ('_rate', 'rate_', 'ratio', 'margin', 'percentage', 'pct')):
        return '%'
    if any(kw in key for kw in ('_size', 'size_', 'portfolio_size', 'volume', 'loan_portfolio')):
        return 'count'
    return ''


def _normalize_metrics(data: Dict) -> Dict:
    """Normalize metrics structure: ensure all metrics have valid value, unit, description, priority."""
    if 'company_data' in data and 'metrics' in data['company_data']:
        metrics = data['company_data']['metrics']
        for metric_key, metric_info in list(metrics.items()):
            if not isinstance(metric_info, dict):
                metrics[metric_key] = {
                    'value': 0, 'unit': _infer_unit(metric_key), 'priority': None,
                    'description': _title_with_acronyms(metric_key.replace('_', ' ')),
                }
                continue
            # Ensure value is numeric; flag categorical values
            raw_val = metric_info.get('value')
            try:
                metric_info['value'] = float(raw_val) if raw_val is not None else 0
                metric_info.pop('categorical', None)
            except (TypeError, ValueError):
                # Store original categorical value for reference, set numeric to 0
                metric_info['categorical_value'] = str(raw_val)
                metric_info['value'] = 0
            # Ensure unit and description are strings; infer unit if empty
            metric_info['unit'] = metric_info.get('unit') or _infer_unit(metric_key)
            metric_info['description'] = (
                metric_info.get('description')
                or _title_with_acronyms(metric_key.replace('_', ' '))
            )
            # Normalize priority
            if metric_info.get('priority') not in ("High", "Medium", "Low"):
                metric_info['priority'] = None
    return data


def load_simulation_data(doc_id: str) -> Optional[Dict]:
    """Load simulation data from Firestore by document ID."""
    try:
        col = _get_collection()
        if col is None:
            st.error("Database connection unavailable.")
            return None
        doc = col.document(doc_id).get()
        if not doc.exists:
            st.error(f"Simulation not found: {doc_id}")
            return None
        return doc.to_dict()
    except Exception as e:
        logger.error(f"Error loading simulation data: {e}")
        st.error("Failed to load simulation data. Please try again or contact admin.")
        return None


@st.cache_data(ttl=30)
def get_available_simulations() -> List[Dict]:
    """Return list of available simulations with metadata from Firestore (cached 30s)."""
    try:
        col = _get_collection()
        if col is None:
            return []
        simulations = []
        for doc in col.stream():
            data = doc.to_dict()
            company = data.get('company_data', {})
            module = data.get('module_data', {})
            simulations.append({
                'doc_id': doc.id,
                'session_name': data.get('session_name', doc.id),
                'company_name': company.get('company_name', 'Unknown Company'),
                'company_overview': company.get('company_overview', ''),
                'industry': company.get('industry', 'N/A'),
                'module_name': module.get('module_name', 'N/A'),
                'board_count': len(company.get('board_members', [])),
                'created_at': data.get('created_at', ''),
            })
        return sorted(simulations, key=lambda x: x.get('created_at', ''), reverse=True)
    except Exception as e:
        logger.error(f"Failed to list simulations: {e}")
        return []


def _assign_round_focus_areas(simulation_config: Dict, module_data: Dict) -> None:
    """Populate empty focus_area fields using module topics or learning objectives."""
    topics = [t.get('name', '') for t in module_data.get('topics', []) if t.get('name')]
    objectives = module_data.get('learning_objectives', [])
    fallback = topics + objectives  # prefer topic names, then objectives
    rounds = simulation_config.get('rounds', [])
    fallback_idx = 0
    for round_cfg in rounds:
        if not round_cfg.get('focus_area'):
            if fallback_idx < len(fallback):
                round_cfg['focus_area'] = fallback[fallback_idx][:80]
                fallback_idx += 1
            else:
                round_cfg['focus_area'] = 'Advanced Application'


def save_extracted_data(company_data: Dict, module_data: Dict, session_name: str, simulation_config: Dict = None) -> str:
    """Save extracted data to Firestore. Returns document ID."""
    if simulation_config is None:
        simulation_config = get_default_simulation_config()

    # Auto-populate focus_area from module topics for any rounds that lack one
    _assign_round_focus_areas(simulation_config, module_data)

    # Issue #15: Auto-rename if duplicate simulation name exists
    existing = [s for s in get_available_simulations() if s.get('session_name') == session_name]
    if existing:
        session_name = f"{session_name} ({len(existing) + 1})"
        st.warning(f"A simulation with that name already exists. Renamed to: **{session_name}**")

    doc_id = _make_doc_id(session_name)

    data = {
        "session_name": session_name or f"Session_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "created_at": datetime.now().isoformat(),
        "company_data": company_data,
        "module_data": module_data,
        "simulation_config": simulation_config,
        "status": "ready_for_simulation"
    }

    try:
        col = _get_collection()
        if col is None:
            st.error("Database connection unavailable. Cannot save.")
            return None
        col.document(doc_id).set(data)
        get_available_simulations.clear()
        list_saved_sessions.clear()
        return doc_id
    except Exception as e:
        logger.error(f"Error saving simulation: {e}")
        st.error("Failed to save simulation. Please try again.")
        return None


def load_extracted_data(doc_id: str) -> Optional[Dict]:
    """Load simulation data and normalize metrics structure."""
    data = load_simulation_data(doc_id)
    if data:
        _normalize_metrics(data)
    return data


@st.cache_data(ttl=30)
def list_saved_sessions() -> list:
    """List all saved sessions from Firestore (cached 30s)."""
    try:
        col = _get_collection()
        if col is None:
            return []
        sessions = []
        for doc in col.stream():
            data = doc.to_dict()
            company_data = data.get("company_data") or {}
            module_data = data.get("module_data") or {}
            session_name = data.get("session_name", "Unknown")
            created_at = data.get("created_at", "Unknown")

            sessions.append({
                "doc_id": doc.id,
                "session_name": session_name,
                "created_at": created_at,
                "company_name": company_data.get("company_name", "Unknown"),
                "module_name": module_data.get("module_name", "Unknown"),
                "display_name": f"{session_name} ({doc.id})"
            })
        return sorted(sessions, key=lambda x: x.get("created_at", ""), reverse=True)
    except Exception as e:
        logger.error(f"Failed to list sessions: {e}")
        return []


def delete_session(doc_id: str) -> bool:
    """Delete a simulation document from Firestore."""
    try:
        col = _get_collection()
        if col is None:
            st.error("Database connection unavailable.")
            return False
        col.document(doc_id).delete()
        get_available_simulations.clear()
        list_saved_sessions.clear()
        return True
    except Exception as e:
        logger.error(f"Error deleting session: {e}")
        st.error("Failed to delete session. Please try again.")
        return False


def update_simulation(doc_id: str, data: Dict) -> bool:
    """Update an existing simulation document in Firestore."""
    try:
        col = _get_collection()
        if col is None:
            st.error("Database connection unavailable.")
            return False
        # Issue #16: Check doc still exists before overwriting
        doc = col.document(doc_id).get()
        if not doc.exists:
            st.warning("This simulation was deleted by another admin. Save cancelled.")
            return False
        data['modified_at'] = datetime.now().isoformat()
        col.document(doc_id).set(data, merge=True)
        get_available_simulations.clear()
        list_saved_sessions.clear()
        return True
    except Exception as e:
        logger.error(f"Error updating simulation: {e}")
        st.error("Failed to update simulation. Please try again.")
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


def migrate_local_to_firestore():
    """One-time migration: upload all data/*.json files to Firestore."""
    local_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    if not os.path.isdir(local_dir):
        print("No data/ directory found. Nothing to migrate.")
        return

    col = _get_collection()
    if col is None:
        print("Firestore unavailable. Cannot migrate.")
        return

    count = 0
    for filename in os.listdir(local_dir):
        if not filename.endswith('.json'):
            continue
        filepath = os.path.join(local_dir, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            doc_id = filename.replace('.json', '')
            col.document(doc_id).set(data)
            count += 1
            print(f"  Migrated: {filename} → {doc_id}")
        except Exception as e:
            print(f"  FAILED: {filename} → {e}")

    print(f"\nMigration complete. {count} files uploaded to Firestore.")
