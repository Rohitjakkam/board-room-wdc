"""
AI-powered content parsing for company data and module content.
"""

import json
import logging
import streamlit as st
import google.generativeai as genai
from typing import Dict, List, Any

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> str:
    """Strip markdown fences and extract JSON object from LLM response."""
    text = text.strip().replace('```json', '').replace('```', '').strip()
    if not text.startswith('{'):
        json_start = text.find('{')
        json_end = text.rfind('}') + 1
        if json_start != -1 and json_end > json_start:
            text = text[json_start:json_end]
    return text


# ---------------------------------------------------------------------------
# Post-parse validation helpers
# ---------------------------------------------------------------------------

def _ensure_list(data: Dict, key: str, item_defaults: Dict = None) -> List:
    """Ensure key exists as a list; fill missing item fields with defaults."""
    val = data.get(key)
    if not isinstance(val, list):
        data[key] = []
        return data[key]
    if item_defaults:
        for item in val:
            if isinstance(item, dict):
                for dk, dv in item_defaults.items():
                    item.setdefault(dk, dv)
    return val


def _ensure_dict(data: Dict, key: str) -> Dict:
    """Ensure key exists as a dict."""
    val = data.get(key)
    if not isinstance(val, dict):
        data[key] = {}
    return data[key]


def _validate_company_data(data: Dict) -> Dict:
    """Validate and fill defaults for parsed company data."""
    # Top-level strings
    data.setdefault('company_name', 'Unknown Company')
    data.setdefault('company_overview', '')
    data.setdefault('initial_scenario', '')
    data.setdefault('industry', 'Unknown')
    data.setdefault('founded', '')

    # Metrics — ensure dict, each metric has value/unit/description
    metrics = _ensure_dict(data, 'metrics')
    for key, info in list(metrics.items()):
        if not isinstance(info, dict):
            metrics[key] = {'value': info, 'unit': '', 'description': key.replace('_', ' ').title()}
        else:
            info.setdefault('value', 0)
            info.setdefault('unit', '')
            info.setdefault('description', key.replace('_', ' ').title())

    # Board members — ensure list, each member has all required fields
    _ensure_list(data, 'board_members', {
        'name': 'Unknown',
        'role': 'Board Member',
        'expertise': 'General Management',
        'tenure_years': 0,
        'personality': 'Professional and analytical',
    })

    # Committees — ensure list, each has required fields
    _ensure_list(data, 'committees', {
        'name': 'Unknown Committee',
        'type': 'Advisory',
        'purpose': '',
        'chairperson': '',
        'members': [],
    })
    # Ensure committee members is always a list of strings
    for committee in data['committees']:
        if not isinstance(committee.get('members'), list):
            committee['members'] = []

    # Current problems — ensure list of strings
    problems = data.get('current_problems')
    if not isinstance(problems, list):
        data['current_problems'] = []

    return data


def _validate_module_data(data: Dict) -> Dict:
    """Validate and fill defaults for parsed module data."""
    # Top-level strings
    data.setdefault('module_name', 'Unknown Module')
    data.setdefault('subject_area', 'General')
    data.setdefault('overview', '')

    # Lists
    _ensure_list(data, 'learning_objectives')
    _ensure_list(data, 'assessment_criteria')

    # Topics — ensure list, each topic has required fields
    _ensure_list(data, 'topics', {
        'name': 'Unknown Topic',
        'description': '',
        'key_principles': [],
        'formulas': [],
        'application': '',
        'examples': [],
    })
    # Ensure nested lists are actually lists
    for topic in data['topics']:
        for list_key in ('key_principles', 'formulas', 'examples'):
            if not isinstance(topic.get(list_key), list):
                topic[list_key] = [topic[list_key]] if topic.get(list_key) else []

    # Frameworks — ensure list, each has required fields
    _ensure_list(data, 'frameworks', {
        'name': 'Unknown Framework',
        'description': '',
        'components': [],
        'application_scenario': '',
    })

    # Key terms — ensure dict
    _ensure_dict(data, 'key_terms')

    return data


# ---------------------------------------------------------------------------
# Module parser
# ---------------------------------------------------------------------------

def parse_module_content(pdf_text: str) -> Dict:
    """Parse module/course content from extracted PDF text."""
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
        result_text = _extract_json(response.text)
        data = json.loads(result_text)
        return _validate_module_data(data)
    except Exception as e:
        logger.error(f"Module parsing error: {e}")
        st.error("Failed to parse module content. The PDF may not contain the expected format.")
        raise


# ---------------------------------------------------------------------------
# Company parser
# ---------------------------------------------------------------------------

def parse_company_data(pdf_text: str) -> Dict:
    """Parse company data from extracted PDF text."""
    if not pdf_text or len(pdf_text.strip()) < 100:
        raise ValueError("Company PDF text is empty or too short")

    model = genai.GenerativeModel('gemini-2.5-flash-lite')

    prompt = f"""Analyze this company document thoroughly.

DOCUMENT ({len(pdf_text)} chars):
{pdf_text}

Extract ALL company information:

1. Company name (exact), industry, year founded
2. Company overview (4-5 sentences)
3. Metrics (20-50): financial, operational, employee, market metrics
   Use snake_case keys. Include metrics like: total_revenue_annual, ebitda, net_profit_margin,
   revenue_growth_yoy, net_promoter_score, customer_churn_rate_annual, employee_engagement_score,
   annual_attrition_rate, regulatory_compliance_score, employee_count, customer_acquisition_cost,
   customer_lifetime_value, platform_uptime, deployment_frequency, etc.
4. Leadership/board team (5-15 people) with: name, role, expertise area, tenure years, personality
5. Committees (e.g., Audit, Risk, Compensation) with: name, type, purpose, chairperson, member names
6. Current problems/challenges (5-10)
7. Initial business situation

Return ONLY valid JSON:
{{
    "company_name": "Exact company name",
    "industry": "Industry sector",
    "founded": "Year founded or N/A",
    "company_overview": "Detailed 4-5 sentence overview",
    "metrics": {{
        "total_revenue_annual": {{"value": 500, "unit": "$M", "description": "Total annual revenue"}},
        "net_profit_margin": {{"value": 15, "unit": "%", "description": "Net profit margin"}},
        "revenue_growth_yoy": {{"value": 8, "unit": "%", "description": "Year-over-year revenue growth"}},
        "employee_count": {{"value": 1200, "unit": "employees", "description": "Total workforce"}},
        "ebitda": {{"value": 120, "unit": "$M", "description": "EBITDA"}},
        "net_promoter_score": {{"value": 45, "unit": "score", "description": "Net Promoter Score"}},
        "customer_churn_rate_annual": {{"value": 12, "unit": "%", "description": "Annual customer churn rate"}},
        "employee_engagement_score": {{"value": 72, "unit": "%", "description": "Employee engagement score"}},
        "annual_attrition_rate": {{"value": 15, "unit": "%", "description": "Annual employee attrition"}},
        "regulatory_compliance_score": {{"value": 88, "unit": "%", "description": "Regulatory compliance score"}}
    }},
    "board_members": [
        {{
            "name": "Full Name",
            "role": "Complete Title (e.g. CEO, CFO, COO)",
            "expertise": "Area of expertise (e.g. Finance, Operations, Technology)",
            "tenure_years": 5,
            "personality": "Detailed personality description"
        }}
    ],
    "committees": [
        {{
            "name": "Committee Name",
            "type": "Audit/Risk/Compensation/Governance/Strategy",
            "purpose": "Committee's purpose",
            "chairperson": "Name of chair (must match a board_members name)",
            "members": ["Member Name 1", "Member Name 2"]
        }}
    ],
    "current_problems": ["Specific problem 1", "Specific problem 2"],
    "initial_scenario": "Current business situation summary"
}}

Extract 20-50 metrics (use snake_case keys), 5-15 board members, 2-6 committees, 5-10 problems. Return ONLY JSON."""

    try:
        response = model.generate_content(prompt)
        result_text = _extract_json(response.text)
        data = json.loads(result_text)
        return _validate_company_data(data)
    except Exception as e:
        logger.error(f"Company parsing error: {e}")
        st.error("Failed to parse company data. The PDF may not contain the expected format.")
        raise
