"""
Admin AI Agents — Create Simulation Review, Audit Data, and Simulation Planning.

Three agents that help admin produce high-quality simulation data:
  Agent 1: run_create_review_agent  — recover lost PDF data + enrich thin fields
  Agent 2: run_audit_agent          — module-guided gap detection + generation
  Agent 3: run_planning_agent       — narrative 3-act simulation design
"""

import json
import logging
import re
import streamlit as st
from google import genai
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MODEL = "gemini-2.5-flash"

_DEFAULT_PERSONALITY = "Professional and analytical"
_DEFAULT_EXPERTISE   = "General Management"

# Allowed board member roles (from content_parser.py)
_ALLOWED_ROLES = {
    "CEO", "MD", "CFO", "COO", "CTO", "CMO", "CHRO", "CRO", "CLO",
    "Board Director", "Independent Director", "Non-Executive Director",
    "Chairperson", "Vice Chairperson", "Executive Director",
    "Company Secretary", "General Counsel",
}

# Case-insensitive lookup map for role normalization (" cfo " → "CFO")
_ALLOWED_ROLES_LOOKUP = {r.lower(): r for r in _ALLOWED_ROLES}


def _normalize_role(role: str) -> str:
    """Strip whitespace and case-normalize against _ALLOWED_ROLES; return original if unknown."""
    if not isinstance(role, str):
        return role
    stripped = role.strip()
    canonical = _ALLOWED_ROLES_LOOKUP.get(stripped.lower())
    return canonical if canonical else stripped

# Expertise → role mapping for gap completion
_EXPERTISE_TO_ROLE = {
    "Finance":     "CFO",
    "Technology":  "CTO",
    "HR":          "CHRO",
    "Risk":        "CRO",
    "Legal":       "CLO",
    "Marketing":   "CMO",
    "Operations":  "COO",
    "Strategy":    "Board Director",
}

# CATEGORY_MAP keywords (mirrors scoring.py) — used to validate generated metric keys
_CATEGORY_KEYWORDS = {
    "Financial":   {"revenue", "profit", "ebitda", "margin", "growth", "debt", "roe", "roa", "roi"},
    "Customer":    {"customer", "churn", "promoter", "satisfaction", "retention", "nps", "csat"},
    "HR":          {"employee", "engagement", "attrition", "headcount", "workforce", "training"},
    "Operations":  {"uptime", "deployment", "platform", "delivery", "efficiency", "supply"},
    "Risk":        {"risk", "compliance", "regulatory", "audit", "incident", "violation"},
}

# Acronyms (mirrors content_parser.py)
_ACRONYMS = {
    'Ebitda': 'EBITDA', 'Nps': 'NPS', 'Roi': 'ROI', 'Roe': 'ROE', 'Roa': 'ROA',
    'Yoy': 'YoY', 'Kpi': 'KPI', 'Kpis': 'KPIs', 'Esg': 'ESG',
    'Hr': 'HR', 'It': 'IT', 'Ceo': 'CEO', 'Cfo': 'CFO', 'Coo': 'COO',
    'Cto': 'CTO', 'Ciso': 'CISO', 'Cmo': 'CMO', 'Id': 'ID',
    'Erp': 'ERP', 'Crm': 'CRM', 'Saas': 'SaaS', 'Arr': 'ARR', 'Mrr': 'MRR',
    'Ltv': 'LTV', 'Cac': 'CAC', 'Csat': 'CSAT',
}

# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

def _get_api_key() -> str:
    try:
        return st.secrets.get("GEMINI_API_KEY", "")
    except Exception:
        return ""


def _call_admin_llm(prompt: str, temperature: float = 0.5, max_tokens: int = 4096) -> str:
    """Call Gemini with the given prompt. Returns raw text or empty string on error."""
    api_key = _get_api_key()
    if not api_key:
        logger.error("GEMINI_API_KEY not set in secrets")
        return ""
    try:
        client = genai.Client(api_key=api_key)
        from google.genai import types
        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        response = client.models.generate_content(
            model=_MODEL,
            contents=prompt,
            config=config,
        )
        return response.text or ""
    except Exception as e:
        logger.error(f"Admin LLM call failed: {e}")
        return ""


def _salvage_truncated_json(text: str) -> str:
    """Given likely-truncated JSON, trim back to the last complete element and auto-close.

    Strategy: walk forward tracking brace/bracket depth and string state. Every
    time we see a closing `}` or `]` OUTSIDE a string AND there's still at least
    one open container, record position+1 as a safe truncation point. Then
    truncate there and auto-close the remaining open containers.
    """
    if not text or text[0] != "{":
        return text

    in_str = False
    escape = False
    stack: list = []
    last_safe = -1
    safe_stack_snapshot: list = []

    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_str:
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
            # We just closed a container. If there are still open containers,
            # this position is a safe place to truncate and auto-close.
            if stack:
                last_safe = i + 1
                safe_stack_snapshot = stack[:]

    if last_safe <= 0:
        return text

    salvaged = text[:last_safe].rstrip().rstrip(",").rstrip()
    closers = "".join("}" if c == "{" else "]" for c in reversed(safe_stack_snapshot))
    return salvaged + closers


def _extract_json(text: str) -> Dict:
    """Strip markdown fences and parse JSON. Auto-salvages truncated responses."""
    if not text:
        return {}
    try:
        text = text.strip().replace("```json", "").replace("```", "").strip()
        if not text.startswith("{"):
            start = text.find("{")
            end   = text.rfind("}") + 1
            if start != -1 and end > start:
                text = text[start:end]
        return json.loads(text)
    except json.JSONDecodeError as e:
        # Token-limit truncation — try salvaging the last complete element
        logger.warning(f"JSON parse failed ({e}); attempting salvage of truncated response")
        try:
            salvaged = _salvage_truncated_json(text)
            result = json.loads(salvaged)
            logger.info(f"Salvage succeeded — recovered {len(result)} top-level keys")
            return result
        except Exception as e2:
            logger.error(f"JSON salvage also failed: {e2}\nRaw text: {text[:300]}")
            return {}
    except Exception as e:
        logger.error(f"JSON extraction failed: {e}\nRaw text: {text[:300]}")
        return {}


def _title_with_acronyms(text: str) -> str:
    """Title-case a string while preserving known acronyms."""
    return " ".join(_ACRONYMS.get(w, w) for w in text.title().split())


def _infer_unit(metric_key: str) -> str:
    """Infer a sensible unit for a metric key (mirrors content_parser._infer_unit)."""
    key = metric_key.lower()
    if any(k in key for k in ("nps", "net_promoter", "satisfaction_score", "sentiment")):
        return "score"
    if any(k in key for k in ("employees", "headcount", "workforce", "staff_count")):
        return "employees"
    if any(k in key for k in ("_count", "incidents", "violations", "tickets")):
        return "count"
    if any(k in key for k in ("_rate", "ratio", "margin", "percentage", "pct", "growth")):
        return "%"
    return ""


def _snake_to_label(key: str) -> str:
    """Convert snake_case metric key to a human-readable label."""
    return _title_with_acronyms(key.replace("_", " "))


def _board_names_set(company_data: Dict) -> set:
    return {m.get("name", "") for m in company_data.get("board_members", [])}


def _text_similarity(a: str, b: str) -> float:
    """Rough word-overlap similarity between two strings (0.0–1.0)."""
    if not a or not b:
        return 0.0
    wa = set(a.lower().split())
    wb = set(b.lower().split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / max(len(wa), len(wb))


# ---------------------------------------------------------------------------
# Agent 1 — Create Simulation Review
# ---------------------------------------------------------------------------

def run_create_review_agent(
    company_data: Dict,
    module_data: Dict,
    company_text: str = "",
    module_text: str = "",
) -> Dict:
    """
    Agent 1 entry point.

    Returns a result dict:
    {
      "patch": {
        "company": { ...fields to update in company_data... },
        "module":  { ...fields to update in module_data... },
      },
      "items": [
        {
          "field": str,           # e.g. "board_members[2].personality"
          "source": str,          # "pdf" | "enriched" | "generated"
          "label": str,           # human-readable label
          "before": Any,          # current value
          "after": Any,           # proposed value
          "reason": str,          # why this change is needed
        }
      ],
      "phase1_skipped": bool,     # True if no raw text available
      "summary": {
        "pdf_recovered": int,
        "enriched": int,
        "generated": int,
        "manual_required": int,
      }
    }
    """
    items: List[Dict] = []
    patch: Dict = {"company": {}, "module": {}}

    has_company_text = bool(company_text and len(company_text.strip()) >= 200)
    has_module_text  = bool(module_text  and len(module_text.strip())  >= 200)

    # Phase 1 — PDF recovery
    if has_company_text or has_module_text:
        _agent1_phase1_recovery(
            company_data, module_data,
            company_text if has_company_text else "",
            module_text  if has_module_text  else "",
            patch, items,
        )
    phase1_skipped = not (has_company_text or has_module_text)

    # Apply Phase 1 patch to working copies so Phase 2 sees updated data
    working_company = _apply_patch(company_data, patch["company"])
    working_module  = _apply_patch(module_data,  patch["module"])

    # Phase 2+3 — enrichment and gap completion
    _agent1_phase2_enrichment(working_company, working_module, patch, items)

    # Build summary counts
    summary = {
        "pdf_recovered":  sum(1 for i in items if i["source"] == "pdf"),
        "enriched":       sum(1 for i in items if i["source"] == "enriched"),
        "generated":      sum(1 for i in items if i["source"] == "generated"),
        "manual_required":sum(1 for i in items if i["source"] == "manual"),
    }

    return {
        "patch": patch,
        "items": items,
        "phase1_skipped": phase1_skipped,
        "summary": summary,
    }


def _agent1_phase1_recovery(
    company_data: Dict, module_data: Dict,
    company_text: str, module_text: str,
    patch: Dict, items: List[Dict],
) -> None:
    """Phase 1: send raw text to LLM, parse delta patch, add to items."""

    if company_text:
        truncated = _smart_truncate_text(company_text, company_data)
        prompt    = _build_recovery_prompt(truncated, company_data)
        raw       = _call_admin_llm(prompt, temperature=0.3, max_tokens=8192)
        delta     = _extract_json(raw)
        if delta:
            _apply_company_recovery_delta(delta, company_data, patch, items)

    if module_text:
        truncated = _smart_truncate_module_text(module_text, module_data)
        prompt    = _build_module_recovery_prompt(truncated, module_data)
        raw       = _call_admin_llm(prompt, temperature=0.3, max_tokens=8192)
        delta     = _extract_json(raw)
        if delta:
            _apply_module_recovery_delta(delta, module_data, patch, items)


def _agent1_phase2_enrichment(
    company_data: Dict, module_data: Dict,
    patch: Dict, items: List[Dict],
) -> None:
    """Phase 2+3: enrich thin fields and generate truly absent ones."""
    gaps = _detect_enrichment_gaps(company_data, module_data)
    if not gaps:
        return
    prompt = _build_enrichment_prompt(company_data, module_data, gaps)
    raw    = _call_admin_llm(prompt, temperature=0.6, max_tokens=8192)
    delta  = _extract_json(raw)
    if delta:
        _apply_enrichment_delta(delta, company_data, module_data, gaps, patch, items)


def _smart_truncate_text(raw_text: str, company_data: Dict, target: int = 80_000) -> str:
    """
    Keep first 35% + last 30% of raw text, plus any page containing a
    name not already in board_members, capped at target chars.
    """
    if len(raw_text) <= target:
        return raw_text

    known_names = {m.get("name", "").lower() for m in company_data.get("board_members", [])}

    # Split into page blocks (pdf_extractor marks pages with PAGE N headers)
    page_blocks = re.split(r"={20,}\nPAGE \d+\n={20,}", raw_text)

    # Always include first 35% and last 30%
    front_target = int(target * 0.35)
    back_target  = int(target * 0.30)
    extra_target = target - front_target - back_target

    front = raw_text[:front_target]
    back  = raw_text[-back_target:]

    # Extra: pages containing names not in board_members
    extra_pages = []
    extra_chars = 0
    for block in page_blocks[1:-1]:  # skip first/last already included
        block_lower = block.lower()
        has_unknown_name = any(
            word.istitle() and len(word) > 3
            and word.lower() not in known_names
            and word.lower() not in {"the", "and", "for", "with", "from"}
            for word in block.split()
        )
        if has_unknown_name and extra_chars + len(block) <= extra_target:
            extra_pages.append(block)
            extra_chars += len(block)

    extra = "\n".join(extra_pages)
    return f"{front}\n[...]\n{extra}\n[...]\n{back}"


def _smart_truncate_module_text(raw_text: str, module_data: Dict, target: int = 60_000) -> str:
    """Keep first 30% + last 40% of module text (glossaries are at the end)."""
    if len(raw_text) <= target:
        return raw_text
    front = raw_text[:int(target * 0.30)]
    back  = raw_text[-int(target * 0.40):]
    return f"{front}\n[...]\n{back}"


def _build_recovery_prompt(truncated_text: str, company_data: Dict) -> str:
    existing_members  = [f"{m.get('name')} ({m.get('role')})" for m in company_data.get("board_members", [])]
    existing_metrics  = list(company_data.get("metrics", {}).keys())[:20]
    existing_problems = company_data.get("current_problems", [])
    existing_committees = [c.get("name") for c in company_data.get("committees", [])]

    return f"""You are extracting data missed in a first-pass AI parsing of a company PDF.

ALREADY EXTRACTED (do NOT repeat these):
Board members: {existing_members}
Metric keys:   {existing_metrics}
Committees:    {existing_committees}
Problems:      {existing_problems[:5]}

RAW DOCUMENT TEXT:
{truncated_text}

Find ONLY what was MISSED. Look specifically for:
- Additional board members (names, roles, tenure years, personality clues from quotes/bios)
- Metrics with actual numeric values not yet captured (use snake_case keys)
- Committee member names listed in governance sections
- Board tenure from "appointed in YYYY" or "serving since YYYY" mentions
- Additional company challenges framed as "strategic priorities" or "key risks"
- Corrections to existing data (wrong tenure, wrong role title)

Return ONLY valid JSON matching this schema exactly:
{{
  "board_members_add": [
    {{"name": "", "role": "", "expertise": "", "tenure_years": 0, "personality": ""}}
  ],
  "board_members_update": [
    {{"name": "", "fields": {{"tenure_years": 0, "personality": ""}}}}
  ],
  "metrics_add": {{
    "metric_key": {{"value": 0, "unit": "", "description": ""}}
  }},
  "metrics_update": {{
    "metric_key": {{"value": 0}}
  }},
  "committees_add": [
    {{"name": "", "type": "", "purpose": "", "chairperson": "", "members": []}}
  ],
  "committees_member_corrections": {{
    "CommitteeName": ["Member Name 1", "Member Name 2"]
  }},
  "problems_add": [],
  "initial_scenario_candidate": "",
  "company_overview_supplement": ""
}}

Return ONLY JSON. If nothing was missed, return an empty object {{}}."""


def _build_module_recovery_prompt(truncated_text: str, module_data: Dict) -> str:
    existing_topics    = [t.get("name") for t in module_data.get("topics", [])]
    existing_terms     = list(module_data.get("key_terms", {}).keys())[:20]
    existing_frameworks = [f.get("name") for f in module_data.get("frameworks", [])]

    return f"""You are extracting data missed in a first-pass AI parsing of a course/module PDF.

ALREADY EXTRACTED (do NOT repeat these):
Topics:     {existing_topics}
Key terms:  {existing_terms}
Frameworks: {existing_frameworks}

RAW DOCUMENT TEXT:
{truncated_text}

Find ONLY what was MISSED. Look specifically for:
- Additional topics not in the list above
- Key terms from glossary sections at the end of the document
- Additional frameworks from appendix or case study sections
- Formulas or worked examples for existing topics
- Additional learning objectives or assessment criteria

Return ONLY valid JSON:
{{
  "topics_add": [
    {{"name": "", "description": "", "key_principles": [], "formulas": [], "application": "", "examples": []}}
  ],
  "key_terms_add": {{"term": "definition"}},
  "frameworks_add": [
    {{"name": "", "description": "", "components": [], "application_scenario": ""}}
  ],
  "learning_objectives_add": [],
  "assessment_criteria_add": [],
  "topics_formula_update": {{
    "TopicName": {{"formulas": [], "examples": []}}
  }}
}}

Return ONLY JSON. If nothing was missed, return {{}}."""


def _apply_company_recovery_delta(delta: Dict, company_data: Dict, patch: Dict, items: List[Dict]) -> None:
    """Merge company recovery delta into patch and record items."""
    board_names = _board_names_set(company_data)

    # New board members
    for m in delta.get("board_members_add", []):
        name = m.get("name", "").strip()
        if name and name not in board_names:
            existing = patch["company"].setdefault("board_members_add", [])
            existing.append(m)
            items.append({
                "field": f"board_members[new].{name}",
                "source": "pdf",
                "label": f"Board member recovered: {name} ({m.get('role', '')})",
                "before": None,
                "after": m,
                "reason": "Found in document but missed in first extraction pass",
            })

    # Board member updates (tenure, personality corrections)
    for upd in delta.get("board_members_update", []):
        name   = upd.get("name", "")
        fields = upd.get("fields", {})
        if name and fields:
            existing = patch["company"].setdefault("board_members_update", [])
            existing.append(upd)
            for field, val in fields.items():
                items.append({
                    "field": f"board_members[{name}].{field}",
                    "source": "pdf",
                    "label": f"{name} — {field} corrected from document",
                    "before": None,
                    "after": val,
                    "reason": "Found in document text (e.g. appointment date, bio quote)",
                })

    # New metrics
    for key, info in delta.get("metrics_add", {}).items():
        if key and key not in company_data.get("metrics", {}):
            patch["company"].setdefault("metrics_add", {})[key] = info
            items.append({
                "field": f"metrics.{key}",
                "source": "pdf",
                "label": f"Metric recovered: {_snake_to_label(key)} = {info.get('value')} {info.get('unit', '')}",
                "before": None,
                "after": info,
                "reason": "Found in financial table or footnote in document",
            })

    # Metric value corrections
    for key, info in delta.get("metrics_update", {}).items():
        if key in company_data.get("metrics", {}):
            patch["company"].setdefault("metrics_update", {})[key] = info
            items.append({
                "field": f"metrics.{key}.value",
                "source": "pdf",
                "label": f"Metric value corrected: {_snake_to_label(key)} → {info.get('value')}",
                "before": company_data["metrics"][key].get("value"),
                "after": info.get("value"),
                "reason": "Actual value found in document (was 0 or incorrect)",
            })

    # New committees
    for c in delta.get("committees_add", []):
        patch["company"].setdefault("committees_add", []).append(c)
        items.append({
            "field": f"committees[new].{c.get('name')}",
            "source": "pdf",
            "label": f"Committee recovered: {c.get('name')}",
            "before": None,
            "after": c,
            "reason": "Found in governance section of document",
        })

    # Committee member corrections
    for comm_name, members in delta.get("committees_member_corrections", {}).items():
        patch["company"].setdefault("committees_member_corrections", {})[comm_name] = members
        items.append({
            "field": f"committees[{comm_name}].members",
            "source": "pdf",
            "label": f"{comm_name} members recovered from document",
            "before": [],
            "after": members,
            "reason": "Member names found in committee charter / governance section",
        })

    # Additional problems
    existing_problems = set(company_data.get("current_problems", []))
    for p in delta.get("problems_add", []):
        if p and p not in existing_problems:
            patch["company"].setdefault("problems_add", []).append(p)
            items.append({
                "field": "current_problems[new]",
                "source": "pdf",
                "label": f"Problem recovered: {p[:80]}",
                "before": None,
                "after": p,
                "reason": "Found in document as strategic risk or challenge",
            })

    # Better initial scenario
    candidate = delta.get("initial_scenario_candidate", "").strip()
    current   = company_data.get("initial_scenario", "")
    if candidate and len(candidate) > len(current) + 50:
        patch["company"]["initial_scenario"] = candidate
        items.append({
            "field": "initial_scenario",
            "source": "pdf",
            "label": "Initial scenario recovered from document",
            "before": current[:100] if current else "",
            "after": candidate[:100],
            "reason": "A better opening scenario found in document text",
        })

    # Company overview supplement (append to existing overview if materially new)
    supplement = delta.get("company_overview_supplement", "").strip()
    current_overview = company_data.get("company_overview", "")
    if supplement and len(supplement) > 40 and supplement not in current_overview:
        patch["company"]["company_overview_append"] = supplement
        items.append({
            "field": "company_overview",
            "source": "pdf",
            "label": "Additional company context recovered from document",
            "before": (current_overview[:80] + "…") if current_overview else "",
            "after": supplement[:150],
            "reason": "New background details found in document that supplement the overview",
        })


def _apply_module_recovery_delta(delta: Dict, module_data: Dict, patch: Dict, items: List[Dict]) -> None:
    """Merge module recovery delta into patch and record items."""
    existing_topic_names     = {t.get("name", "") for t in module_data.get("topics", [])}
    existing_framework_names = {f.get("name", "") for f in module_data.get("frameworks", [])}
    existing_terms           = set(module_data.get("key_terms", {}).keys())

    for t in delta.get("topics_add", []):
        if t.get("name") and t["name"] not in existing_topic_names:
            patch["module"].setdefault("topics_add", []).append(t)
            items.append({
                "field": f"module.topics[new].{t['name']}",
                "source": "pdf",
                "label": f"Topic recovered: {t['name']}",
                "before": None, "after": t,
                "reason": "Found in document appendix or secondary section",
            })

    new_terms = {k: v for k, v in delta.get("key_terms_add", {}).items() if k not in existing_terms}
    if new_terms:
        patch["module"].setdefault("key_terms_add", {}).update(new_terms)
        items.append({
            "field": "module.key_terms",
            "source": "pdf",
            "label": f"{len(new_terms)} key terms recovered from document glossary",
            "before": len(existing_terms),
            "after": len(existing_terms) + len(new_terms),
            "reason": "Glossary section found in document",
        })

    for f in delta.get("frameworks_add", []):
        if f.get("name") and f["name"] not in existing_framework_names:
            patch["module"].setdefault("frameworks_add", []).append(f)
            items.append({
                "field": f"module.frameworks[new].{f['name']}",
                "source": "pdf",
                "label": f"Framework recovered: {f['name']}",
                "before": None, "after": f,
                "reason": "Found in appendix or case study section of document",
            })

    for lo in delta.get("learning_objectives_add", []):
        patch["module"].setdefault("learning_objectives_add", []).append(lo)
        items.append({
            "field": "module.learning_objectives[new]",
            "source": "pdf",
            "label": f"Learning objective recovered: {lo[:80]}",
            "before": None, "after": lo,
            "reason": "Found in document but missed in first extraction",
        })

    for ac in delta.get("assessment_criteria_add", []):
        patch["module"].setdefault("assessment_criteria_add", []).append(ac)
        items.append({
            "field": "module.assessment_criteria[new]",
            "source": "pdf",
            "label": f"Assessment criterion recovered: {str(ac)[:80]}",
            "before": None, "after": ac,
            "reason": "Found in document but missed in first extraction",
        })

    # Topic formula/example updates
    for topic_name, upd in delta.get("topics_formula_update", {}).items():
        patch["module"].setdefault("topics_formula_update", {})[topic_name] = upd
        items.append({
            "field": f"module.topics[{topic_name}].formulas+examples",
            "source": "pdf",
            "label": f"{topic_name} — formulas/examples recovered",
            "before": None,
            "after": upd,
            "reason": "Found in worked examples or appendix of document",
        })


def _detect_enrichment_gaps(company_data: Dict, module_data: Dict) -> Dict:
    """
    Detect fields that need Phase 2 enrichment or Phase 3 generation.
    Returns a structured gaps dict consumed by the enrichment prompt.
    """
    gaps: Dict = {
        "board_default_personality": [],
        "board_default_expertise":   [],
        "board_zero_tenure":         [],
        "problems_thin":             [],
        "problems_missing":          False,
        "initial_scenario_thin":     False,
        "committee_empty_purpose":   [],
        "committee_empty_members":   [],
        "metrics_empty_description": [],
        "metrics_empty_unit":        [],
        "topics_no_principles":      [],
        "topics_no_examples":        [],
        "frameworks_no_components":  [],
        "learning_objectives_missing": False,
        "assessment_criteria_missing": False,
        "module_overview_thin":      False,
        "board_missing_entirely":    False,
        "committees_missing_entirely": False,
        "all_metrics_zero":          False,
    }

    members = company_data.get("board_members", [])

    if not members:
        gaps["board_missing_entirely"] = True
    else:
        for m in members:
            if m.get("personality", "").strip() == _DEFAULT_PERSONALITY:
                gaps["board_default_personality"].append(m.get("name", ""))
            if m.get("expertise", "").strip() == _DEFAULT_EXPERTISE:
                gaps["board_default_expertise"].append(m.get("name", ""))
            if not m.get("tenure_years"):
                gaps["board_zero_tenure"].append(m.get("name", ""))

    problems = company_data.get("current_problems", [])
    if len(problems) < 3:
        gaps["problems_missing"] = True
    for p in problems:
        if len(str(p)) < 50:
            gaps["problems_thin"].append(p)

    scenario  = company_data.get("initial_scenario", "")
    overview  = company_data.get("company_overview", "")
    if not scenario or len(scenario) < 100 or _text_similarity(scenario, overview) > 0.70:
        gaps["initial_scenario_thin"] = True

    committees = company_data.get("committees", [])
    if not committees:
        gaps["committees_missing_entirely"] = True
    else:
        for c in committees:
            if not c.get("purpose"):
                gaps["committee_empty_purpose"].append(c.get("name", ""))
            if not c.get("members"):
                gaps["committee_empty_members"].append(c.get("name", ""))

    metrics = company_data.get("metrics", {})
    all_zero = metrics and all(
        v.get("value", 0) == 0 for v in metrics.values() if isinstance(v, dict)
    )
    if all_zero:
        gaps["all_metrics_zero"] = True
    else:
        for key, info in metrics.items():
            if isinstance(info, dict):
                if not info.get("description") or info.get("description") == key:
                    gaps["metrics_empty_description"].append(key)
                if not info.get("unit"):
                    gaps["metrics_empty_unit"].append(key)

    for t in module_data.get("topics", []):
        if not t.get("key_principles"):
            gaps["topics_no_principles"].append(t.get("name", ""))
        if not t.get("examples"):
            gaps["topics_no_examples"].append(t.get("name", ""))

    for f in module_data.get("frameworks", []):
        if isinstance(f, dict):
            if not f.get("components"):
                gaps["frameworks_no_components"].append(f.get("name", ""))

    if not module_data.get("learning_objectives"):
        gaps["learning_objectives_missing"] = True
    if not module_data.get("assessment_criteria"):
        gaps["assessment_criteria_missing"] = True
    if len(module_data.get("overview", "")) < 80:
        gaps["module_overview_thin"] = True

    return gaps


def _build_enrichment_prompt(company_data: Dict, module_data: Dict, gaps: Dict) -> str:
    members    = company_data.get("board_members", [])
    board_summary = "\n".join(
        f"  - {m.get('name')} | {m.get('role')} | {m.get('expertise')} | {m.get('tenure_years')}yrs"
        for m in members
    ) or "  (none)"
    committee_summary = "\n".join(
        f"  - {c.get('name')} ({c.get('type')})"
        for c in company_data.get("committees", [])
    ) or "  (none)"
    metrics_summary = ", ".join(list(company_data.get("metrics", {}).keys())[:15]) or "(none)"

    tasks = []
    if gaps["board_default_personality"]:
        tasks.append(f"Rewrite personality for board members with default text: {gaps['board_default_personality']}. "
                     "2–3 sentences each: communication style, decision-making biases, boardroom behaviour.")
    if gaps["board_default_expertise"]:
        tasks.append(f"Infer expertise for members where expertise is 'General Management': "
                     f"{gaps['board_default_expertise']}. Map from their role (CFO→Finance, CTO→Technology, etc.)")
    if gaps["board_zero_tenure"]:
        tasks.append(f"Suggest realistic tenure_years for: {gaps['board_zero_tenure']}. "
                     "CEO 4–8 yrs, CFO 3–7, COO 3–6, Independent Director 2–5.")
    if gaps["problems_thin"]:
        tasks.append(f"Expand these thin problems to 50+ chars with metric quantification: {gaps['problems_thin']}")
    if gaps["problems_missing"]:
        tasks.append(f"Generate 5 industry-appropriate problems for {company_data.get('company_name')} "
                     f"({company_data.get('industry')}) using available metrics as evidence.")
    if gaps["initial_scenario_thin"]:
        tasks.append("Rewrite initial_scenario as a boardroom opening briefing (100+ chars, present-tense, "
                     "references top 3 problems and 2 metric values). Must differ from company_overview.")
    if gaps["committee_empty_purpose"]:
        tasks.append(f"Infer purpose for committees: {gaps['committee_empty_purpose']} (from their type).")
    if gaps["committee_empty_members"]:
        tasks.append(f"Assign members to empty committees: {gaps['committee_empty_members']}. "
                     "Use existing board members by expertise match.")
    if gaps["committees_missing_entirely"]:
        tasks.append("Generate 3 standard committees (Audit, Risk, Remuneration) assigned from board members.")
    if gaps["board_missing_entirely"]:
        tasks.append(f"Generate 6 board members for {company_data.get('company_name')} "
                     f"({company_data.get('industry')}): CEO, CFO, COO, CTO, CHRO, Independent Director.")
    if gaps["metrics_empty_description"]:
        tasks.append(f"Generate human-readable descriptions for metric keys: {gaps['metrics_empty_description'][:10]}")
    if gaps["metrics_empty_unit"]:
        tasks.append(f"Infer units for metric keys: {gaps['metrics_empty_unit'][:10]}")
    if gaps["topics_no_principles"]:
        tasks.append(f"Generate 2–3 key_principles for module topics: {gaps['topics_no_principles'][:8]}")
    if gaps["topics_no_examples"]:
        tasks.append(f"Generate 1 concrete business example for module topics: {gaps['topics_no_examples'][:8]}")
    if gaps["frameworks_no_components"]:
        tasks.append(f"Generate components list for frameworks: {gaps['frameworks_no_components']}")
    if gaps["learning_objectives_missing"]:
        tasks.append(f"Generate 5 learning objectives for module '{module_data.get('module_name')}' "
                     f"({module_data.get('subject_area')}) using Bloom's taxonomy verbs.")
    if gaps["assessment_criteria_missing"]:
        tasks.append("Generate assessment criteria from learning_objectives using Bloom's verbs "
                     "(Analyze, Evaluate, Apply, Synthesize).")
    if gaps["all_metrics_zero"]:
        # Don't generate fake financials — flag instead
        tasks.append("NOTE: all metrics have value=0. Do NOT generate fake values. "
                     "Set 'metrics_unreadable': true in output.")

    if not tasks:
        return ""

    return f"""You are enriching extracted simulation data to make it simulation-ready.

COMPANY: {company_data.get('company_name')} | Industry: {company_data.get('industry')}
Overview: {company_data.get('company_overview', '')[:300]}

MODULE: {module_data.get('module_name')} | Subject: {module_data.get('subject_area')}

CURRENT BOARD:
{board_summary}

CURRENT COMMITTEES:
{committee_summary}

CURRENT METRICS (keys): {metrics_summary}

TASKS TO COMPLETE:
{chr(10).join(f"{i+1}. {t}" for i, t in enumerate(tasks))}

Return ONLY valid JSON:
{{
  "board_members_personality": {{"MemberName": "2–3 sentence personality text"}},
  "board_members_expertise":   {{"MemberName": "Expertise area"}},
  "board_members_tenure":      {{"MemberName": 5}},
  "problems_expanded":         {{"original problem text": "expanded version with quantification"}},
  "problems_generated":        [],
  "initial_scenario":          "",
  "committee_purposes":        {{"CommitteeName": "purpose text"}},
  "committee_members":         {{"CommitteeName": ["Member Name 1", "Member Name 2"]}},
  "committees_generated":      [],
  "board_members_generated":   [],
  "metric_descriptions":       {{"metric_key": "Human Readable Description"}},
  "metric_units":              {{"metric_key": "unit"}},
  "topic_principles":          {{"TopicName": ["principle 1", "principle 2"]}},
  "topic_examples":            {{"TopicName": ["example"]}},
  "framework_components":      {{"FrameworkName": ["component 1", "component 2"]}},
  "learning_objectives":       [],
  "assessment_criteria":       [],
  "module_overview":           "",
  "metrics_unreadable":        false
}}

Only include keys relevant to the tasks above. Return ONLY JSON."""


def _apply_enrichment_delta(
    delta: Dict,
    company_data: Dict,
    module_data: Dict,
    gaps: Dict,
    patch: Dict,
    items: List[Dict],
) -> None:
    """Apply Phase 2+3 enrichment delta to patch and record items."""

    source_for = lambda field: "generated" if _is_generated_gap(field, gaps) else "enriched"

    # Board personalities
    for name, personality in delta.get("board_members_personality", {}).items():
        patch["company"].setdefault("board_members_personality", {})[name] = personality
        items.append({
            "field": f"board_members[{name}].personality",
            "source": "enriched",
            "label": f"{name} — personality rewritten",
            "before": _DEFAULT_PERSONALITY,
            "after": personality[:120] + "..." if len(personality) > 120 else personality,
            "reason": "Default personality replaced with role-specific behaviour profile",
        })

    # Board expertise
    for name, expertise in delta.get("board_members_expertise", {}).items():
        patch["company"].setdefault("board_members_expertise", {})[name] = expertise
        items.append({
            "field": f"board_members[{name}].expertise",
            "source": "enriched",
            "label": f"{name} — expertise inferred: {expertise}",
            "before": _DEFAULT_EXPERTISE,
            "after": expertise,
            "reason": "Inferred from role title",
        })

    # Board tenure
    for name, tenure in delta.get("board_members_tenure", {}).items():
        patch["company"].setdefault("board_members_tenure", {})[name] = tenure
        items.append({
            "field": f"board_members[{name}].tenure_years",
            "source": "enriched",
            "label": f"{name} — tenure set to {tenure} years",
            "before": 0,
            "after": tenure,
            "reason": "Realistic tenure assigned by role seniority",
        })

    # Expanded problems
    for original, expanded in delta.get("problems_expanded", {}).items():
        patch["company"].setdefault("problems_expanded", {})[original] = expanded
        items.append({
            "field": "current_problems[existing]",
            "source": "enriched",
            "label": f"Problem expanded: {original[:60]}",
            "before": original,
            "after": expanded[:120] + "..." if len(expanded) > 120 else expanded,
            "reason": "Expanded with metric quantification for simulation specificity",
        })

    # Generated problems
    for p in delta.get("problems_generated", []):
        patch["company"].setdefault("problems_generated", []).append(p)
        items.append({
            "field": "current_problems[new]",
            "source": "generated",
            "label": f"Problem generated: {str(p)[:80]}",
            "before": None, "after": p,
            "reason": "Fewer than 3 problems found — generated from industry + metrics context",
        })

    # Initial scenario
    scenario = delta.get("initial_scenario", "").strip()
    if scenario:
        patch["company"]["initial_scenario"] = scenario
        items.append({
            "field": "initial_scenario",
            "source": "enriched",
            "label": "Initial scenario rewritten as boardroom briefing",
            "before": company_data.get("initial_scenario", "")[:80],
            "after": scenario[:120] + "..." if len(scenario) > 120 else scenario,
            "reason": "Was too short or mirrored company_overview",
        })

    # Committee purposes
    for name, purpose in delta.get("committee_purposes", {}).items():
        patch["company"].setdefault("committee_purposes", {})[name] = purpose
        items.append({
            "field": f"committees[{name}].purpose",
            "source": "enriched",
            "label": f"{name} — purpose inferred",
            "before": "", "after": purpose,
            "reason": "Purpose inferred from committee type",
        })

    # Committee members
    for name, members in delta.get("committee_members", {}).items():
        patch["company"].setdefault("committee_members_assigned", {})[name] = members
        items.append({
            "field": f"committees[{name}].members",
            "source": "enriched",
            "label": f"{name} — {len(members)} members assigned",
            "before": [], "after": members,
            "reason": "Members assigned from board by expertise match",
        })

    # Generated committees
    for c in delta.get("committees_generated", []):
        if not isinstance(c, dict):
            continue
        patch["company"].setdefault("committees_generated", []).append(c)
        items.append({
            "field": f"committees[new].{c.get('name')}",
            "source": "generated",
            "label": f"Committee generated: {c.get('name')}",
            "before": None, "after": c,
            "reason": "No committees found in PDF — standard committees created",
        })

    # Generated board members
    for m in delta.get("board_members_generated", []):
        if not isinstance(m, dict):
            continue
        patch["company"].setdefault("board_members_generated", []).append(m)
        items.append({
            "field": f"board_members[new].{m.get('name')}",
            "source": "generated",
            "label": f"Board member generated: {m.get('name')} ({m.get('role')})",
            "before": None, "after": m,
            "reason": "No board members found in PDF — standard board created",
        })

    # Metric descriptions
    for key, desc in delta.get("metric_descriptions", {}).items():
        patch["company"].setdefault("metric_descriptions", {})[key] = desc
        items.append({
            "field": f"metrics.{key}.description",
            "source": "enriched",
            "label": f"Metric description: {_snake_to_label(key)}",
            "before": key, "after": desc,
            "reason": "Description inferred from metric key name",
        })

    # Metric units
    for key, unit in delta.get("metric_units", {}).items():
        patch["company"].setdefault("metric_units", {})[key] = unit
        items.append({
            "field": f"metrics.{key}.unit",
            "source": "enriched",
            "label": f"Metric unit: {_snake_to_label(key)} → {unit}",
            "before": "", "after": unit,
            "reason": "Unit inferred from metric key pattern",
        })

    # Module: topic principles
    for topic_name, principles in delta.get("topic_principles", {}).items():
        patch["module"].setdefault("topic_principles", {})[topic_name] = principles
        items.append({
            "field": f"module.topics[{topic_name}].key_principles",
            "source": "enriched",
            "label": f"{topic_name} — {len(principles)} key principles generated",
            "before": [], "after": principles,
            "reason": "Topic had no key principles — generated from topic name and subject area",
        })

    # Module: topic examples
    for topic_name, examples in delta.get("topic_examples", {}).items():
        patch["module"].setdefault("topic_examples", {})[topic_name] = examples
        items.append({
            "field": f"module.topics[{topic_name}].examples",
            "source": "enriched",
            "label": f"{topic_name} — example generated",
            "before": [], "after": examples,
            "reason": "Topic had no examples — generated from subject area context",
        })

    # Module: framework components
    for fw_name, components in delta.get("framework_components", {}).items():
        patch["module"].setdefault("framework_components", {})[fw_name] = components
        items.append({
            "field": f"module.frameworks[{fw_name}].components",
            "source": "enriched",
            "label": f"{fw_name} — components filled",
            "before": [], "after": components,
            "reason": "Standard components inferred from framework name",
        })

    # Module: learning objectives
    los = delta.get("learning_objectives", [])
    if los and not module_data.get("learning_objectives"):
        patch["module"]["learning_objectives"] = los
        items.append({
            "field": "module.learning_objectives",
            "source": "generated",
            "label": f"{len(los)} learning objectives generated",
            "before": [], "after": los,
            "reason": "Module had no learning objectives",
        })

    # Module: assessment criteria
    criteria = delta.get("assessment_criteria", [])
    if criteria and not module_data.get("assessment_criteria"):
        patch["module"]["assessment_criteria"] = criteria
        items.append({
            "field": "module.assessment_criteria",
            "source": "generated",
            "label": f"{len(criteria)} assessment criteria generated",
            "before": [], "after": criteria,
            "reason": "Generated from learning objectives using Bloom's taxonomy",
        })

    # Unreadable metrics flag
    if delta.get("metrics_unreadable"):
        items.append({
            "field": "metrics (all)",
            "source": "manual",
            "label": "All metrics show value=0 — PDF appears image-based",
            "before": None, "after": None,
            "reason": "Cannot generate fake financial data. Enter values manually in Audit tab.",
        })


def _is_generated_gap(field: str, gaps: Dict) -> bool:
    """Return True if this field falls under a Phase 3 (truly absent) gap."""
    if "board_members_generated" in field:
        return gaps.get("board_missing_entirely", False)
    if "committees_generated" in field:
        return gaps.get("committees_missing_entirely", False)
    if "problems_generated" in field:
        return gaps.get("problems_missing", False)
    if "learning_objectives" in field:
        return gaps.get("learning_objectives_missing", False)
    if "assessment_criteria" in field:
        return gaps.get("assessment_criteria_missing", False)
    return False


def _apply_patch(original: Dict, patch_section: Dict) -> Dict:
    """Return a shallow merged copy of original with patch_section overlaid (non-destructive)."""
    import copy
    result = copy.deepcopy(original)
    for key, val in patch_section.items():
        if key not in ("board_members_add", "metrics_add", "committees_add",
                       "problems_add", "topics_add", "key_terms_add", "frameworks_add"):
            result[key] = val
    return result


# ---------------------------------------------------------------------------
# Agent 2 — Audit Data
# ---------------------------------------------------------------------------

# Maps subject_area keyword → list of required CATEGORY_MAP categories
_SUBJECT_TO_CATEGORIES: Dict[str, List[str]] = {
    "finance":     ["Financial"],
    "financial":   ["Financial"],
    "hr":          ["HR"],
    "human":       ["HR"],
    "people":      ["HR"],
    "workforce":   ["HR"],
    "risk":        ["Risk", "Financial"],
    "compliance":  ["Risk"],
    "governance":  ["Financial", "Risk"],
    "esg":         ["Risk", "HR"],
    "sustainability": ["Risk", "Operations"],
    "operations":  ["Operations"],
    "supply":      ["Operations"],
    "customer":    ["Customer"],
    "marketing":   ["Customer", "Financial"],
    "technology":  ["Operations", "Financial"],
    "digital":     ["Operations", "Customer"],
    "strategy":    ["Financial", "Customer"],
    "audit":       ["Risk", "Financial"],
}

# Maps objective/topic keywords → expertise domain needed in board
_KEYWORD_TO_EXPERTISE: Dict[str, str] = {
    "financial":   "Finance",
    "revenue":     "Finance",
    "budget":      "Finance",
    "audit":       "Finance",
    "risk":        "Risk",
    "compliance":  "Risk",
    "regulatory":  "Risk",
    "technology":  "Technology",
    "digital":     "Technology",
    "cyber":       "Technology",
    "hr":          "HR",
    "people":      "HR",
    "talent":      "HR",
    "workforce":   "HR",
    "customer":    "Marketing",
    "marketing":   "Marketing",
    "brand":       "Marketing",
    "operations":  "Operations",
    "supply":      "Operations",
    "legal":       "Legal",
    "governance":  "Strategy",
    "strategy":    "Strategy",
    "esg":         "Risk",
}

# Maps frameworks → expected committee types
_FRAMEWORK_TO_COMMITTEES: Dict[str, List[str]] = {
    "king iv":     ["Audit Committee", "Risk Committee", "Remuneration Committee", "Social and Ethics Committee"],
    "king iii":    ["Audit Committee", "Risk Committee", "Remuneration Committee"],
    "coso":        ["Audit Committee", "Risk Committee"],
    "sox":         ["Audit Committee"],
    "iso 31000":   ["Risk Committee"],
    "basel":       ["Risk Committee", "Audit Committee"],
    "oecd":        ["Audit Committee", "Remuneration Committee"],
    "cadbury":     ["Audit Committee", "Remuneration Committee"],
    "sarbanes":    ["Audit Committee"],
    "ifrs":        ["Audit Committee"],
}

# Default committees for any governance module
_DEFAULT_GOVERNANCE_COMMITTEES = ["Audit Committee", "Risk Committee"]


def _audit_phase1_gap_analysis(company_data: Dict, module_data: Dict) -> Dict:
    """Phase 1: deterministic cross-document gap analysis — 5 mappings."""

    gaps: Dict[str, Any] = {
        "missing_metric_categories": [],
        "missing_expertise_roles": [],
        "missing_committee_types": [],
        "missing_problem_themes": [],
        "zero_value_metrics": [],
    }

    # --- Mapping 1: subject_area → metric categories ---
    subject = (module_data.get("subject_area") or "").lower()
    required_categories: set = set()
    for kw, cats in _SUBJECT_TO_CATEGORIES.items():
        if kw in subject:
            required_categories.update(cats)
    # Fallback: always need Financial
    required_categories.add("Financial")

    existing_metrics = company_data.get("metrics", {})
    covered_categories: set = set()
    for metric_key in existing_metrics:
        key_lower = metric_key.lower()
        for cat, keywords in _CATEGORY_KEYWORDS.items():
            if any(kw in key_lower for kw in keywords):
                covered_categories.add(cat)
                break

    for cat in sorted(required_categories):
        if cat not in covered_categories:
            gaps["missing_metric_categories"].append(cat)

    # --- Mapping 2: learning_objectives → board expertise ---
    all_text = " ".join([
        " ".join(module_data.get("learning_objectives", [])),
        " ".join(module_data.get("key_topics", [])),
        module_data.get("overview", ""),
    ]).lower()

    required_expertise: set = set()
    for kw, domain in _KEYWORD_TO_EXPERTISE.items():
        if kw in all_text:
            required_expertise.add(domain)

    existing_expertise = {
        m.get("expertise", "").strip()
        for m in company_data.get("board_members", [])
        if isinstance(m, dict)
    }
    for domain in sorted(required_expertise):
        if domain not in existing_expertise:
            gaps["missing_expertise_roles"].append(domain)

    # --- Mapping 3: frameworks → committee types ---
    # Normalize both sides: lowercase + strip non-alphanumeric so "ISO 31000",
    # "iso31000", "ISO-31000" all match the same key.
    def _norm_fw(s: str) -> str:
        return "".join(ch for ch in s.lower() if ch.isalnum())

    raw_frameworks = module_data.get("frameworks", [])
    framework_names = [
        _norm_fw(f.get("name", "") if isinstance(f, dict) else str(f))
        for f in raw_frameworks
    ]
    required_committees: set = set()
    for fname_norm in framework_names:
        for fkey, ctypes in _FRAMEWORK_TO_COMMITTEES.items():
            if _norm_fw(fkey) in fname_norm:
                required_committees.update(ctypes)
    if not required_committees and (
        "governance" in subject or "audit" in subject or "risk" in subject
    ):
        required_committees.update(_DEFAULT_GOVERNANCE_COMMITTEES)

    existing_committee_names = {
        (c.get("name", "") if isinstance(c, dict) else str(c)).strip().lower()
        for c in company_data.get("committees", [])
    }
    for ctype in sorted(required_committees):
        if ctype.lower() not in existing_committee_names:
            gaps["missing_committee_types"].append(ctype)

    # --- Mapping 4: key_topics → problem themes ---
    topics_text = [
        (t.get("name", "") if isinstance(t, dict) else str(t)).lower()
        for t in module_data.get("topics", [])
    ] + [
        (t if isinstance(t, str) else "").lower()
        for t in module_data.get("key_topics", [])
    ]
    problems_text = " ".join(company_data.get("current_problems", [])).lower()

    for topic in topics_text:
        if not topic:
            continue
        # Check if any word from the topic appears in problems
        topic_words = [w for w in topic.split() if len(w) > 4]
        if topic_words and not any(w in problems_text for w in topic_words):
            gaps["missing_problem_themes"].append(topic)

    # --- Mapping 5: metric zero-values (skipped by scoring engine) ---
    for key, info in existing_metrics.items():
        if isinstance(info, dict):
            val = info.get("value")
            if val == 0 or val == "0":
                gaps["zero_value_metrics"].append(key)

    # Stash required-set sizes so readiness scorer uses correct denominators
    gaps["_required_categories_count"] = len(required_categories)
    gaps["_required_expertise_count"]  = len(required_expertise)

    return gaps


def _audit_phase2_structural_checks(company_data: Dict, module_data: Dict) -> List[Dict]:
    """Phase 2: deterministic structural integrity checks."""
    flags = []
    members = company_data.get("board_members", [])
    member_names = {m.get("name", "") for m in members if isinstance(m, dict)}

    # Check 1: committee members exist on board
    for c in company_data.get("committees", []):
        if not isinstance(c, dict):
            continue
        for cm in c.get("members", []):
            if cm and cm not in member_names:
                flags.append({
                    "type": "committee_member_missing",
                    "severity": "error",
                    "message": f"Committee '{c.get('name')}' lists '{cm}' who is not on the board",
                    "field": f"committees.{c.get('name')}.members",
                })
        chairperson = c.get("chairperson", "")
        if chairperson and chairperson not in member_names:
            flags.append({
                "type": "committee_chair_missing",
                "severity": "error",
                "message": f"Committee '{c.get('name')}' chairperson '{chairperson}' not on board",
                "field": f"committees.{c.get('name')}.chairperson",
            })

    # Check 2: board member role validation (normalize first — "CFO ", "cfo" should pass)
    for m in members:
        if not isinstance(m, dict):
            continue
        raw_role = m.get("role", "")
        normalized = _normalize_role(raw_role)
        # If normalization recovered a valid role, rewrite in place
        if normalized != raw_role and normalized in _ALLOWED_ROLES:
            m["role"] = normalized
            continue
        if normalized not in _ALLOWED_ROLES:
            flags.append({
                "type": "invalid_role",
                "severity": "warning",
                "message": f"'{m.get('name')}' has non-standard role '{raw_role}'",
                "field": f"board_members.{m.get('name')}.role",
            })

    # Check 3: board member missing required fields
    for m in members:
        if not isinstance(m, dict):
            continue
        for field in ("name", "role", "personality", "expertise", "tenure_years"):
            val = m.get(field)
            if not val or (isinstance(val, str) and val.strip() == ""):
                flags.append({
                    "type": "member_field_missing",
                    "severity": "warning",
                    "message": f"'{m.get('name', '?')}' is missing field '{field}'",
                    "field": f"board_members.{m.get('name', '?')}.{field}",
                })

    # Check 4: duplicate metric keys with different casing
    metric_keys_lower = {}
    for k in company_data.get("metrics", {}):
        lower_k = k.lower()
        if lower_k in metric_keys_lower:
            flags.append({
                "type": "duplicate_metric_key",
                "severity": "warning",
                "message": f"Duplicate metric keys (case): '{k}' vs '{metric_keys_lower[lower_k]}'",
                "field": f"metrics.{k}",
            })
        else:
            metric_keys_lower[lower_k] = k

    # Check 5: fewer than 3 board members
    if len(members) < 3:
        flags.append({
            "type": "board_too_small",
            "severity": "error",
            "message": f"Only {len(members)} board member(s) — minimum 3 needed for debate",
            "field": "board_members",
        })

    # Check 6: fewer than 2 current problems
    if len(company_data.get("current_problems", [])) < 2:
        flags.append({
            "type": "problems_too_few",
            "severity": "warning",
            "message": "Fewer than 2 current problems — scenarios will lack tension",
            "field": "current_problems",
        })

    # Check 7: module learning objectives < 2
    if len(module_data.get("learning_objectives", [])) < 2:
        flags.append({
            "type": "objectives_too_few",
            "severity": "warning",
            "message": "Fewer than 2 learning objectives — Bloom sequencing will be shallow",
            "field": "module.learning_objectives",
        })

    return flags


def _build_audit_generation_prompt(
    company_data: Dict, module_data: Dict,
    gaps: Dict, flags: List[Dict],
) -> str:
    """Build the LLM prompt for Agent 2 Phase 3 generation."""
    member_list = "\n".join(
        f"  - {m.get('name')} | {m.get('role')} | expertise: {m.get('expertise')}"
        for m in company_data.get("board_members", [])
        if isinstance(m, dict)
    ) or "  (none)"
    committee_list = "\n".join(
        f"  - {c.get('name') if isinstance(c, dict) else c}"
        for c in company_data.get("committees", [])
    ) or "  (none)"
    problem_list = "\n".join(
        f"  - {p}" for p in company_data.get("current_problems", [])
    ) or "  (none)"
    metric_list = "\n".join(
        f"  - {k}: {v.get('value')} {v.get('unit', '')} ({v.get('description', '')})"
        for k, v in list(company_data.get("metrics", {}).items())[:10]
        if isinstance(v, dict)
    ) or "  (none)"

    gaps_text = ""
    if gaps["missing_metric_categories"]:
        gaps_text += f"\nMISSING METRIC CATEGORIES: {', '.join(gaps['missing_metric_categories'])}"
    if gaps["missing_expertise_roles"]:
        gaps_text += f"\nMISSING BOARD EXPERTISE: {', '.join(gaps['missing_expertise_roles'])}"
    if gaps["missing_committee_types"]:
        gaps_text += f"\nMISSING COMMITTEES: {', '.join(gaps['missing_committee_types'])}"
    if gaps["missing_problem_themes"]:
        gaps_text += f"\nMISSING PROBLEM THEMES: {', '.join(gaps['missing_problem_themes'][:5])}"
    if gaps["zero_value_metrics"]:
        gaps_text += f"\nZERO-VALUE METRICS (need realistic values): {', '.join(gaps['zero_value_metrics'])}"

    error_flags = [f for f in flags if f["severity"] == "error"]
    flags_text = "\n".join(f"  - [{f['type']}] {f['message']}" for f in error_flags) or "  (none)"

    return f"""You are an expert corporate governance data generator.

COMPANY: {company_data.get('company_name', 'Unknown')}
{company_data.get('company_overview', '')}

MODULE: {module_data.get('module_name', '')}
Subject Area: {module_data.get('subject_area', '')}

Learning Objectives:
{chr(10).join(f"  - {o}" for o in module_data.get('learning_objectives', []))}

EXISTING BOARD MEMBERS:
{member_list}

EXISTING COMMITTEES:
{committee_list}

EXISTING PROBLEMS:
{problem_list}

EXISTING METRICS (sample):
{metric_list}

IDENTIFIED GAPS:{gaps_text if gaps_text else " None"}

STRUCTURAL ERRORS:
{flags_text}

Generate ONLY what is missing. Do not repeat what already exists.

Rules for metrics:
- Keys must use snake_case and contain at least one of these words (so the scoring engine can categorize them):
  Financial: revenue, profit, ebitda, margin, growth, debt, roe, roa, roi
  Customer:  customer, churn, promoter, satisfaction, retention, nps, csat
  HR:        employee, engagement, attrition, headcount, workforce, training
  Operations: uptime, deployment, platform, delivery, efficiency, supply
  Risk:      risk, compliance, regulatory, audit, incident, violation
- Use realistic non-zero values with appropriate units

Rules for board members:
- Only generate if expertise domain is truly missing from current board
- Use these valid roles only: {', '.join(sorted(_ALLOWED_ROLES))}
- Personality: 2-3 sentences describing communication style and priorities
- Tenure: integer years (1-20)

Rules for committees:
- Each must include: name, type, purpose, chairperson (existing board member name), members (list of existing member names)

Rules for problems:
- 1-2 sentences, specific to the company and module topic

Respond in JSON:
{{
  "metrics_generated": {{
    "<snake_case_key>": {{"value": <number>, "unit": "<unit>", "description": "<label>"}}
  }},
  "metrics_fixed_values": {{
    "<existing_key>": <realistic_non_zero_number>
  }},
  "board_members_generated": [
    {{"name": "<Full Name>", "role": "<valid role>", "expertise": "<domain>", "personality": "<2-3 sentences>", "tenure_years": <int>}}
  ],
  "committees_generated": [
    {{"name": "<Committee Name>", "type": "<type>", "purpose": "<purpose>", "chairperson": "<existing member>", "members": ["<name1>", "<name2>"]}}
  ],
  "problems_generated": ["<problem statement>"],
  "reasoning": "<1-2 sentences on what was generated and why>"
}}"""


def _compute_readiness_score(
    company_data: Dict, module_data: Dict,
    gaps: Dict, flags: List[Dict],
) -> Dict:
    """Compute 3 sub-scores and overall readiness (0-100 each)."""

    # Sub-score 1: Metric coverage
    # Use the actual required-category count for THIS module (stashed during gap detection)
    missing_cats = len(gaps.get("missing_metric_categories", []))
    total_cats = max(gaps.get("_required_categories_count", 1), 1)
    metric_score = max(0, int(100 * (1 - missing_cats / total_cats)))

    # Penalise zero-value metrics
    zero_count = len(gaps.get("zero_value_metrics", []))
    metric_score = max(0, metric_score - zero_count * 5)

    # Sub-score 2: Board coverage
    # Denominator is the expertise THIS module requires, not the full keyword dict
    missing_expertise = len(gaps.get("missing_expertise_roles", []))
    required_expertise_count = gaps.get("_required_expertise_count", 0)
    if required_expertise_count == 0:
        # Module doesn't need specific expertise — score is full if we have a board at all
        board_score = 100
    else:
        board_score = max(0, int(100 * (1 - missing_expertise / required_expertise_count)))
    missing_committees = len(gaps.get("missing_committee_types", []))
    board_score = max(0, board_score - missing_committees * 10)

    # Sub-score 3: Structural health
    error_flags = sum(1 for f in flags if f["severity"] == "error")
    warn_flags  = sum(1 for f in flags if f["severity"] == "warning")
    structural_score = max(0, 100 - error_flags * 20 - warn_flags * 5)

    overall = int((metric_score + board_score + structural_score) / 3)

    return {
        "overall": overall,
        "metric_coverage": metric_score,
        "board_coverage": board_score,
        "structural_health": structural_score,
    }


def _audit_phase3_generate_and_score(
    company_data: Dict, module_data: Dict,
    gaps: Dict, flags: List[Dict],
    patch: Dict, items: List[Dict],
) -> Dict:
    """Phase 3: LLM generation for detected gaps + compute readiness score."""

    # Always compute readiness (even without LLM)
    readiness = _compute_readiness_score(company_data, module_data, gaps, flags)

    has_gaps = any(gaps.get(k) for k in (
        "missing_metric_categories", "missing_expertise_roles",
        "missing_committee_types", "missing_problem_themes", "zero_value_metrics",
    ))
    has_errors = any(f["severity"] == "error" for f in flags)

    if not has_gaps and not has_errors:
        return readiness

    prompt = _build_audit_generation_prompt(company_data, module_data, gaps, flags)
    raw = _call_admin_llm(prompt, temperature=0.5, max_tokens=8192)
    delta = _extract_json(raw)
    if not delta:
        return readiness

    # Apply generated metrics
    for key, info in delta.get("metrics_generated", {}).items():
        if not isinstance(info, dict):
            continue
        patch["company"].setdefault("metrics_generated", {})[key] = info
        items.append({
            "field": f"metrics.{key}",
            "source": "generated",
            "label": f"Metric added: {key}",
            "before": None,
            "after": info,
            "reason": f"Required for {module_data.get('subject_area', 'module')} coverage",
        })

    # Apply fixed zero-value metrics
    for key, val in delta.get("metrics_fixed_values", {}).items():
        patch["company"].setdefault("metrics_fixed_values", {})[key] = val
        items.append({
            "field": f"metrics.{key}.value",
            "source": "generated",
            "label": f"Metric value fixed: {key}",
            "before": 0,
            "after": val,
            "reason": "Zero value would be skipped by scoring engine",
        })

    # Apply generated board members
    for m in delta.get("board_members_generated", []):
        if not isinstance(m, dict):
            continue
        patch["company"].setdefault("board_members_generated", []).append(m)
        items.append({
            "field": f"board_members[new].{m.get('name')}",
            "source": "generated",
            "label": f"Board member added: {m.get('name')} ({m.get('role')}) — {m.get('expertise')} expertise",
            "before": None,
            "after": m,
            "reason": f"Missing expertise domain: {m.get('expertise')}",
        })

    # Apply generated committees
    for c in delta.get("committees_generated", []):
        if not isinstance(c, dict):
            continue
        patch["company"].setdefault("committees_generated", []).append(c)
        items.append({
            "field": f"committees[new].{c.get('name')}",
            "source": "generated",
            "label": f"Committee added: {c.get('name')}",
            "before": None,
            "after": c,
            "reason": f"Required by {module_data.get('subject_area', 'module')} frameworks",
        })

    # Apply generated problems
    for p in delta.get("problems_generated", []):
        if not isinstance(p, str):
            continue
        patch["company"].setdefault("problems_generated", []).append(p)
        items.append({
            "field": "current_problems[new]",
            "source": "generated",
            "label": f"Problem added: {p[:80]}...",
            "before": None,
            "after": p,
            "reason": "Missing problem theme aligned to module topic",
        })

    # Re-compute readiness after generation intent
    readiness = _compute_readiness_score(company_data, module_data, gaps, flags)
    readiness["reasoning"] = delta.get("reasoning", "")

    return readiness


def run_audit_agent(company_data: Dict, module_data: Dict) -> Dict:
    """
    Agent 2 entry point.
    Returns: {items, patch, readiness_score, gaps, flags, summary}
    """
    items: List[Dict] = []
    patch: Dict = {"company": {}, "module": {}}

    gaps  = _audit_phase1_gap_analysis(company_data, module_data)
    flags = _audit_phase2_structural_checks(company_data, module_data)
    readiness = _audit_phase3_generate_and_score(
        company_data, module_data, gaps, flags, patch, items,
    )

    summary = {
        "metrics_missing":   len(gaps.get("missing_metric_categories", [])),
        "roles_missing":     len(gaps.get("missing_expertise_roles", [])),
        "committees_missing": len(gaps.get("missing_committee_types", [])),
        "problems_missing":  len(gaps.get("missing_problem_themes", [])),
        "structural_flags":  len(flags),
        "items_generated":   len(items),
    }

    return {
        "items":          items,
        "patch":          patch,
        "readiness_score": readiness,
        "gaps":           gaps,
        "flags":          flags,
        "summary":        summary,
    }


# ---------------------------------------------------------------------------
# Agent 3 — Simulation Planning
# ---------------------------------------------------------------------------

_BLOOM_LEVELS = {1: "Remember", 2: "Understand", 3: "Apply",
                  4: "Analyze", 5: "Evaluate", 6: "Create"}

_BLOOM_KEYWORDS: Dict[int, set] = {
    6: {"create", "design", "develop", "formulate", "propose", "construct"},
    5: {"evaluate", "judge", "assess", "justify", "recommend", "critique", "defend"},
    4: {"analyze", "compare", "examine", "distinguish", "investigate", "differentiate"},
    3: {"apply", "implement", "use", "execute", "solve", "demonstrate"},
    2: {"understand", "explain", "describe", "interpret", "classify", "summarize"},
    1: {"remember", "recall", "identify", "list", "define", "name"},
}

# (role_a, role_b, tension_theme)
_TENSION_PAIRS: List[Tuple[str, str, str]] = [
    ("CFO",  "CHRO", "cost discipline vs. talent investment"),
    ("CRO",  "CEO",  "risk appetite vs. growth ambition"),
    ("CTO",  "CFO",  "digital investment vs. budget constraints"),
    ("COO",  "CMO",  "operational efficiency vs. market expansion"),
    ("CLO",  "CEO",  "compliance conservatism vs. strategic boldness"),
    ("CRO",  "CTO",  "security constraints vs. innovation speed"),
    ("CHRO", "COO",  "people-first culture vs. process-first efficiency"),
]

# Per-act config: (act_num, label, difficulty_sequence, round_type_sequence)
_ACT_CONFIGS = [
    (1, "Orientation",  ["easy",   "easy"],   ["both", "both"]),
    (2, "Complication", ["medium", "hard"],   ["both", "business"]),
    (3, "Resolution",   ["hard",   "hard"],   ["both", "both"]),
]


def _classify_topic_bloom_level(topic: str) -> int:
    """Return a Bloom level (1-6) for a topic string based on keyword match."""
    topic_lower = topic.lower()
    for level in range(6, 0, -1):
        if any(kw in topic_lower for kw in _BLOOM_KEYWORDS[level]):
            return level
    return 2  # default: Understand


def _identify_tension_pairs(board_members: List[Dict]) -> List[Dict]:
    """Return tension pairs that are actually present on this board."""
    roles_present = {
        m.get("role", "").upper()
        for m in board_members if isinstance(m, dict)
    }
    found = []
    for role_a, role_b, theme in _TENSION_PAIRS:
        if role_a in roles_present and role_b in roles_present:
            found.append({"role_a": role_a, "role_b": role_b, "theme": theme})
    return found


def _compute_act_structure(num_rounds: int) -> List[Dict]:
    """
    Divide num_rounds into 3 acts with appropriate difficulty and round_type.
    Returns list of per-round act metadata.
    """
    acts = []
    # Assign rounds to acts proportionally: ~40% Act1, ~40% Act2, ~20% Act3
    act1_end = max(1, round(num_rounds * 0.4))
    act2_end = max(act1_end + 1, round(num_rounds * 0.8))

    difficulty_ramp = {
        "easy":   ["easy"]   * act1_end,
        "medium": ["medium"] * (act2_end - act1_end),
        "hard":   ["hard"]   * (num_rounds - act2_end),
    }
    all_difficulties = (
        difficulty_ramp["easy"] + difficulty_ramp["medium"] + difficulty_ramp["hard"]
    )

    for i in range(num_rounds):
        rnum = i + 1
        if rnum <= act1_end:
            act_num, act_label = 1, "Orientation"
        elif rnum <= act2_end:
            act_num, act_label = 2, "Complication"
        else:
            act_num, act_label = 3, "Resolution"

        acts.append({
            "round_number": rnum,
            "act":          act_num,
            "act_label":    act_label,
            "difficulty":   all_difficulties[i],
        })
    return acts


def _check_coverage_requirements(module_data: Dict, num_rounds: int) -> Dict:
    """
    Returns a map of topics/objectives that must be covered at least once,
    with their recommended Bloom level and act.
    """
    requirements: Dict[str, Dict] = {}

    topics = module_data.get("key_topics", [])
    if not topics:
        topics = [
            (t.get("name", "") if isinstance(t, dict) else str(t))
            for t in module_data.get("topics", [])
        ]

    objectives = module_data.get("learning_objectives", [])

    all_items = topics + objectives
    total = len(all_items) or 1

    for idx, item in enumerate(all_items):
        item_str = (item.get("name", "") if isinstance(item, dict) else str(item)).strip()
        if not item_str:
            continue
        bloom = _classify_topic_bloom_level(item_str)
        # Assign to act based on Bloom level
        if bloom <= 2:
            recommended_act = 1
        elif bloom <= 4:
            recommended_act = 2
        else:
            recommended_act = 3

        requirements[item_str] = {
            "bloom_level":      bloom,
            "bloom_label":      _BLOOM_LEVELS[bloom],
            "recommended_act":  recommended_act,
        }
    return requirements


def _run_pre_planning_flags(
    company_data: Dict, module_data: Dict, simulation_config: Dict,
) -> List[str]:
    """Return warnings that the planner should address."""
    flags = []
    num_rounds = simulation_config.get("total_rounds", 5)

    topics = module_data.get("key_topics", []) + [
        (t.get("name", "") if isinstance(t, dict) else str(t))
        for t in module_data.get("topics", [])
    ]
    objectives = module_data.get("learning_objectives", [])
    total_items = len(topics) + len(objectives)

    if total_items > num_rounds * 2:
        flags.append(
            f"Module has {total_items} topics/objectives but only {num_rounds} rounds — "
            "some topics will need to share a round."
        )
    if len(company_data.get("board_members", [])) < 3:
        flags.append("Fewer than 3 board members — tension dynamics will be limited.")
    if not _identify_tension_pairs(company_data.get("board_members", [])):
        flags.append("No matching tension pairs found — consider adding CRO, CFO, or CHRO.")
    if num_rounds < 3:
        flags.append("Fewer than 3 rounds — 3-act structure will be compressed.")

    return flags


def _build_narrative_planning_prompt(
    company_data: Dict,
    module_data: Dict,
    simulation_config: Dict,
    act_structure: List[Dict],
    tension_pairs: List[Dict],
    coverage_requirements: Dict,
) -> str:
    """Build the LLM prompt for Agent 3 Phase 2 narrative arc design."""
    num_rounds = simulation_config.get("total_rounds", 5)

    # Summarise act structure
    act_lines = []
    for r in act_structure:
        act_lines.append(
            f"  Round {r['round_number']}: Act {r['act']} ({r['act_label']}) — "
            f"difficulty: {r['difficulty']}"
        )

    # Top tension pairs (max 3)
    tension_lines = "\n".join(
        f"  - {t['role_a']} ↔ {t['role_b']}: {t['theme']}"
        for t in tension_pairs[:3]
    ) or "  (none detected)"

    # Coverage requirements (top 8)
    cov_items = list(coverage_requirements.items())[:8]
    cov_lines = "\n".join(
        f"  - [{v['bloom_label']}] {topic} → Act {v['recommended_act']}"
        for topic, v in cov_items
    ) or "  (none)"

    board_list = "\n".join(
        f"  - {m.get('name')} | {m.get('role')} | {m.get('expertise')}"
        for m in company_data.get("board_members", [])
        if isinstance(m, dict)
    ) or "  (none)"

    problems_list = "\n".join(
        f"  - {p}" for p in company_data.get("current_problems", [])
    ) or "  (none)"

    return f"""You are a corporate governance simulation narrative designer.

COMPANY: {company_data.get('company_name', 'Unknown')}
{company_data.get('company_overview', '')}

CURRENT PROBLEMS:
{problems_list}

MODULE: {module_data.get('module_name', '')}
Subject Area: {module_data.get('subject_area', '')}
Overview: {module_data.get('overview', '')}

BOARD MEMBERS:
{board_list}

ACT STRUCTURE (fixed — do not change difficulty or act):
{chr(10).join(act_lines)}

TENSION PAIRS AVAILABLE:
{tension_lines}

COVERAGE REQUIREMENTS (Bloom sequenced — must appear in the stated act):
{cov_lines}

DESIGN TASK:
Create a 3-act simulation narrative that:
1. Tells a connected story — each round's decision causes the next round's crisis
2. Escalates naturally from orientation → complication → resolution
3. Assigns a tension pair to each Act 2 and Act 3 round
4. Teaches every coverage requirement in approximately the right act
5. Makes focus_area RICH (2-3 sentences) — this text feeds directly into the scenario generator
   and must name: (a) the specific challenge, (b) which board member's domain is tested,
   (c) the decision frame the player faces

Respond in JSON:
{{
  "narrative_arc_title": "<10-15 word title for the full simulation arc>",
  "act_labels": {{
    "1": "<Act 1 subtitle>",
    "2": "<Act 2 subtitle>",
    "3": "<Act 3 subtitle>"
  }},
  "rounds": [
    {{
      "round_number": <int>,
      "title": "<8-12 word round title>",
      "focus_area": "<2-3 sentences: specific challenge + board domain tested + decision frame>",
      "round_type": "<both|business|module>",
      "tension_pair": "<ROLE_A and ROLE_B — theme>" or null,
      "cascade_seed": "<1 sentence: what decision from this round seeds the next round's crisis>",
      "topics_covered": ["<topic1>", "<topic2>"]
    }}
  ]
}}

Generate exactly {num_rounds} rounds. Each focus_area must be specific, vivid, and different."""


def _verify_coverage(rounds: List[Dict], coverage_requirements: Dict) -> Dict:
    """Check which required topics are covered by the generated rounds."""
    covered: Dict[str, int] = {}  # topic → round_number
    uncovered = []

    all_covered_text = " ".join(
        " ".join(r.get("topics_covered", [])) + " " + r.get("focus_area", "") + " " + r.get("title", "")
        for r in rounds
    ).lower()

    for topic in coverage_requirements:
        # Check if any significant word from the topic appears in round text
        topic_words = [w for w in topic.lower().split() if len(w) > 4]
        if topic_words and any(w in all_covered_text for w in topic_words):
            # Find which round covers it first
            for r in rounds:
                r_text = (
                    " ".join(r.get("topics_covered", [])) + " " +
                    r.get("focus_area", "") + " " + r.get("title", "")
                ).lower()
                r_words = [w for w in topic.lower().split() if len(w) > 4]
                if r_words and any(w in r_text for w in r_words):
                    covered[topic] = r["round_number"]
                    break
        else:
            uncovered.append(topic)

    return {"covered": covered, "uncovered": uncovered}


def _agent3_phase1_pre_planning(
    company_data: Dict, module_data: Dict, simulation_config: Dict,
) -> Tuple[List[Dict], List[Dict], Dict, List[str]]:
    """Phase 1: compute act structure, tensions, coverage requirements, pre-flags."""
    num_rounds   = simulation_config.get("total_rounds", 5)
    act_structure = _compute_act_structure(num_rounds)
    tension_pairs = _identify_tension_pairs(company_data.get("board_members", []))
    coverage_req  = _check_coverage_requirements(module_data, num_rounds)
    flags         = _run_pre_planning_flags(company_data, module_data, simulation_config)
    return act_structure, tension_pairs, coverage_req, flags


def _agent3_phase2_narrative_design(
    company_data: Dict,
    module_data: Dict,
    simulation_config: Dict,
    act_structure: List[Dict],
    tension_pairs: List[Dict],
    coverage_requirements: Dict,
) -> Tuple[str, Dict, List[Dict]]:
    """Phase 2: LLM generates narrative arc title + enriched round configs."""
    prompt = _build_narrative_planning_prompt(
        company_data, module_data, simulation_config,
        act_structure, tension_pairs, coverage_requirements,
    )
    raw   = _call_admin_llm(prompt, temperature=0.7, max_tokens=6000)
    delta = _extract_json(raw)

    if not delta or "rounds" not in delta:
        # Fallback: use act structure with basic focus areas
        return (
            f"{module_data.get('module_name', 'Simulation')} — 3-Act Governance Journey",
            {"1": "Orientation", "2": "Complication", "3": "Resolution"},
            [
                {
                    "round_number": r["round_number"],
                    "title": f"Round {r['round_number']}: {r['act_label']}",
                    "focus_area": f"Apply {module_data.get('module_name', 'governance')} "
                                  f"principles to a {r['difficulty']} challenge.",
                    "round_type": "both",
                    "tension_pair": None,
                    "cascade_seed": None,
                    "topics_covered": [],
                }
                for r in act_structure
            ],
        )

    narrative_title = delta.get("narrative_arc_title", "Simulation Arc")
    act_labels      = delta.get("act_labels", {"1": "Orientation", "2": "Complication", "3": "Resolution"})
    llm_rounds      = delta.get("rounds", [])

    # Merge LLM round data with act structure (difficulty comes from act structure)
    merged_rounds = []
    act_map = {r["round_number"]: r for r in act_structure}

    for llm_round in llm_rounds:
        if not isinstance(llm_round, dict):
            continue
        rnum = llm_round.get("round_number")
        base = act_map.get(rnum, {})
        merged_rounds.append({
            "round_number":  rnum,
            "act":           base.get("act", 1),
            "act_label":     base.get("act_label", ""),
            "title":         llm_round.get("title", f"Round {rnum}"),
            "focus_area":    llm_round.get("focus_area", ""),
            "difficulty":    base.get("difficulty", "medium"),
            "round_type":    llm_round.get("round_type", "both"),
            "tension_pair":  llm_round.get("tension_pair"),
            "cascade_seed":  llm_round.get("cascade_seed"),
            "topics_covered": llm_round.get("topics_covered", []),
            "time_pressure": "tight" if base.get("difficulty") == "hard" else "normal",
        })

    # Sort by round_number
    merged_rounds.sort(key=lambda r: r.get("round_number", 0))
    return narrative_title, act_labels, merged_rounds


def run_planning_agent(
    company_data: Dict,
    module_data: Dict,
    simulation_config: Dict,
) -> Dict:
    """
    Agent 3 entry point.
    Returns: {narrative_arc_title, act_labels, rounds, coverage, flags, summary}
    """
    # Phase 1: deterministic pre-planning analysis
    act_structure, tension_pairs, coverage_req, pre_flags = _agent3_phase1_pre_planning(
        company_data, module_data, simulation_config,
    )

    # Phase 2: LLM narrative arc design
    narrative_title, act_labels, enriched_rounds = _agent3_phase2_narrative_design(
        company_data, module_data, simulation_config,
        act_structure, tension_pairs, coverage_req,
    )

    # Phase 3: coverage verification
    coverage = _verify_coverage(enriched_rounds, coverage_req)
    post_flags = [f"Topic not covered: '{t}'" for t in coverage.get("uncovered", [])]

    all_flags = pre_flags + post_flags

    summary = {
        "total_rounds":       len(enriched_rounds),
        "tension_pairs_used": len([r for r in enriched_rounds if r.get("tension_pair")]),
        "topics_covered":     len(coverage.get("covered", {})),
        "topics_uncovered":   len(coverage.get("uncovered", [])),
        "flags":              len(all_flags),
    }

    return {
        "narrative_arc_title": narrative_title,
        "act_labels":          act_labels,
        "rounds":              enriched_rounds,
        "coverage":            coverage,
        "tension_pairs":       tension_pairs,
        "flags":               all_flags,
        "summary":             summary,
    }
