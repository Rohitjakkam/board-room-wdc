"""
AI-powered content parsing for company data and module content.
"""

import json
import streamlit as st
import google.generativeai as genai
from typing import Dict


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
    """Parse company data from extracted PDF text."""
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
