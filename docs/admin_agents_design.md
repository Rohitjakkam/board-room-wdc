# Admin AI Agents — Design Document

**Project:** Board Room WDC  
**Date:** 2026-04-23  
**Scope:** Three AI agents to assist admin across Create Simulation, Audit Data, and Simulation Planning stages  
**Model:** `gemini-2.5-flash` (existing API, no new dependency)

---

## Why These Agents Exist

PDF extraction via Gemini is a **compression step**. It takes N characters of raw text and produces a structured JSON. That compression always loses something — board members buried in appendix pages, metrics locked in financial tables, committee details in governance footnotes, personality clues scattered across executive bios.

The current pipeline (`extractors/content_parser.py`) produces a JSON document that passes structural validation but is often **semantically hollow**:

- Board members say generic things because `personality` defaulted to `"Professional and analytical"`
- The scenario generator has nothing to escalate from because `current_problems` are one-line vague strings
- Committees list names that don't match any board member — `get_committee_prompt()` silently returns empty `member_details`
- Round focus areas point to topics that no board member has expertise in

The raw PDF text (`dc_company_text`, `dc_module_text`) is stored in session state after extraction and **never used again**. Agent 1 fixes this. Agents 2 and 3 operate downstream on the saved Firestore data and work from the structured JSON alone.

---

## Agent 1 — Create Simulation Review Agent

### Core principle: No data lost from the PDF

Agent 1 operates with a strict priority order:

```
Priority 1 — Recover from raw PDF text
  The raw text is in session state. Use it. Find what the first parse missed.
  Source label: "Recovered from PDF"  →  shown in green

Priority 2 — Enrich from existing structured data
  Data exists in the JSON but is thin (default values, vague strings).
  Improve it using what IS in the JSON (name + role + metrics + industry).
  Source label: "Enriched from context"  →  shown in yellow

Priority 3 — Generate as last resort
  Truly absent from both the PDF and the structured JSON.
  Only runs after Phase 1 and 2 have nothing to work with.
  Source label: "AI-Generated (not from PDF)"  →  shown in orange, flagged for admin review
```

**The agent never generates what can be recovered. It never generates what can be inferred. Generation is the last resort, clearly labeled.**

---

### Where it lives

`pages/create_simulation.py` — a new **"AI Review"** expander panel inserted between Step 2 (Review Extracted Data) and Step 3 (Save). Visible only when both `dc_company_data` and `dc_module_data` exist in session state.

### Trigger

Admin clicks **"Run Full Review"** inside the expander. The button is disabled until both company and module data are extracted. Admin can re-run after re-extracting.

### What it receives

```python
# Session state available at trigger time
company_data  = st.session_state.dc_company_data    # structured JSON from parser
module_data   = st.session_state.dc_module_data     # structured JSON from parser
company_text  = st.session_state.dc_company_text    # raw PDF text — may be empty
module_text   = st.session_state.dc_module_text     # raw PDF text — may be empty
```

---

### Phase 1 — PDF Recovery (raw text → missing data)

**Runs only when raw text is available.** Skipped with a warning if `dc_company_text` is empty.

#### Why the first parse misses data

The first extraction pass (`parse_company_data`) focuses on the main document body. These are the common miss patterns:

| What gets missed | Where it hides in PDFs |
|---|---|
| Board members #6–12 | Footer bios, appendix "About Our Directors" sections, governance reports |
| Exact metric values | Financial tables, footnotes, chart captions with embedded numbers |
| Committee member names | Corporate governance chapters, committee charters at document end |
| Board member tenure | "Appointed in 2019" / "Serving since 2021" mentions in individual bios |
| Personality clues | CEO quotes in foreword, individual writing style in letters to shareholders |
| Problems framed as "priorities" | Strategic review sections that reframe problems as forward-looking initiatives |
| Founded year / HQ location | Often in a "Company at a Glance" sidebar parsed out of order |
| Module: formulas and worked examples | Appendices, end-of-chapter practice problems |
| Module: full glossary | End-of-document glossary sections systematically skipped by structured extraction |
| Module: additional frameworks | Case study sections that reference frameworks not in the main body |

#### Smart text truncation for large PDFs

Raw text can exceed 200K characters. The LLM context window cannot hold it all alongside the structured JSON. The agent applies a **smart truncation strategy** to keep the most information-dense sections:

```
Slice 1: First 35% of text
  Reason: Company profile, CEO letter, overview — usually in opening pages

Slice 2: Last 30% of text
  Reason: Appendices, governance sections, committee charters, glossaries —
          the sections the parser most commonly misses

Slice 3: Any page segment containing a personal name NOT already in board_members
  Reason: Targeted recovery — if a name appears in raw text but not in the JSON,
          that page likely contains a board member bio that was missed

Combined target: ~80K chars maximum passed to the LLM
```

#### Recovery LLM call — delta extraction

This is a **targeted delta extraction**, not a full re-parse. The LLM is told what was already extracted and asked only for what was missed.

```
Model: gemini-2.5-flash
Temperature: 0.3  (factual recovery — minimal creativity)
Max tokens: 4096

Prompt structure:
  "The following data has already been extracted from this PDF document.
   Do not repeat what is already here.

   ALREADY EXTRACTED:
   [compact summary of current_json — names, roles, metric keys, problem list]

   RAW DOCUMENT TEXT:
   [smart-truncated text]

   Your task: Find ONLY what was missed. Look specifically for:
   - Additional board members not in the list above
   - Metrics with actual numeric values not captured
   - Committee member names referenced in governance sections
   - Board tenure mentioned as appointment years
   - Leadership quotes or personality signals not captured
   - Additional company challenges framed as 'strategic priorities'
   - Module: glossary terms, additional frameworks, worked examples

   Return a JSON patch — only additions and corrections, nothing already present."

Output schema:
{
  "board_members_add": [
    {"name": "", "role": "", "expertise": "", "tenure_years": 0, "personality": ""}
  ],
  "board_members_update": [
    {"name": "", "fields": {"tenure_years": 5, "personality": "..."}}
  ],
  "metrics_add": {
    "metric_key": {"value": 0, "unit": "", "description": ""}
  },
  "metrics_update": {
    "metric_key": {"value": 0}
  },
  "committees_add": [
    {"name": "", "type": "", "purpose": "", "chairperson": "", "members": []}
  ],
  "committees_member_corrections": {
    "CommitteeName": ["Member Name 1", "Member Name 2"]
  },
  "problems_add": ["Problem found in text but not captured"],
  "initial_scenario_candidate": "",
  "company_overview_supplement": "",
  "topics_add": [
    {"name": "", "description": "", "key_principles": [], "formulas": [], "application": "", "examples": []}
  ],
  "key_terms_add": {"term": "definition"},
  "frameworks_add": [
    {"name": "", "description": "", "components": [], "application_scenario": ""}
  ],
  "learning_objectives_add": [],
  "assessment_criteria_add": []
}
```

All items returned in this patch are labeled **"Recovered from PDF"** in the UI.

#### When raw text is unavailable

If `dc_company_text == ""` (scanned PDF that Gemini also failed on, or extraction produced no text):

- Phase 1 is skipped entirely
- A warning banner is shown: `"Raw PDF text unavailable — PDF recovery skipped. Running quality enrichment and gap completion only."`
- All fixes in Phase 2 and Phase 3 are labeled "Inferred" or "AI-Generated" accordingly

---

### Phase 2 — Quality Enrichment (thin fields → improved content)

Runs on the JSON **after Phase 1 additions are applied**. Targets fields that exist but are too thin to produce good simulation output.

Does NOT create new records. Only improves what is already there.

#### Company enrichment targets

| Field | Thin condition | Enrichment rule |
|---|---|---|
| `personality` | Exactly `"Professional and analytical"` (parser default) | Generate 2–3 sentences using `name` + `role` + `expertise` + `tenure_years` + any personality clues recovered in Phase 1. CFO → data-driven, cost-conscious, skeptical of unquantified proposals. CTO → future-focused, impatient with legacy constraints. Independent Director → governance-first, asks probing questions. |
| `expertise` | Exactly `"General Management"` (parser default) | Map from `role`: CFO → Finance, CTO → Technology, CHRO → HR, CRO → Risk, CLO → Legal, CMO → Marketing |
| `tenure_years` | `== 0` | Infer realistic range by role: CEO 4–8, CFO 3–7, COO 3–6, Independent Director 2–5, Company Secretary 2–4 |
| Problem string | < 50 chars or no quantification | Expand using available metrics: `"High attrition"` + `annual_attrition_rate: 22%` → `"Annual employee attrition at 22% — 7 points above sector average — driving critical skill loss in engineering and customer success teams"` |
| `initial_scenario` | < 100 chars OR cosine similarity > 0.75 with `company_overview` | Rewrite as a boardroom opening briefing: present-tense, first-person framing of the situation, referencing the top 3 problems and 2 key metric values |
| Committee `purpose` | Empty string | Infer from `type`: Audit → "Oversight of financial reporting integrity and external audit process"; Risk → "Enterprise risk governance and risk appetite framework oversight" |
| Committee `members` | Empty list | Assign appropriate board members by role: Audit → CFO + Independent Directors; Risk → CRO + CFO; Remuneration → Independent Directors + CHRO |
| Metric `description` | Empty or equals snake_case key verbatim | Convert snake_case to human label: `annual_attrition_rate` → `"Annual Employee Attrition Rate"` |
| Metric `unit` | Empty string | Re-apply `_infer_unit()` logic: revenue keys → `$M`, rate/ratio/margin/pct → `%`, NPS/score → `score`, headcount → `employees` |

#### Module enrichment targets

| Field | Thin condition | Enrichment rule |
|---|---|---|
| `key_principles` | Empty list on any topic | Generate 2–3 key principles from topic `name` + `subject_area` + `description` |
| `examples` | Empty list on any topic | Generate 1–2 concrete business examples grounded in the `subject_area` and company `industry` |
| `assessment_criteria` | Empty list | Generate from `learning_objectives` using Bloom's taxonomy action verbs (Analyze, Evaluate, Apply, Synthesize) |
| Framework `components` | Empty list | Infer standard components from framework `name`: SWOT → Strengths/Weaknesses/Opportunities/Threats; Porter's Five Forces → Rivalry/New Entrants/Substitutes/Buyer Power/Supplier Power |
| `overview` | < 80 chars | Expand from `module_name` + `subject_area` + first 3 topic names |
| `learning_objectives` | Empty list | Generate 5 objectives from `module_name` + `subject_area` using Bloom's verbs |

#### Phase 2 LLM call

```
Model: gemini-2.5-flash
Temperature: 0.6  (needs some creativity for personality writing)
Max tokens: 4096

Input: post-Phase-1 JSON with only the thin fields sent (not the full document)
Output: JSON patch targeting only the enrichment fields above
```

All items from this call are labeled **"Enriched from context"** in the UI.

---

### Phase 3 — Gap Completion (truly absent, AI-generated)

Runs only when Phase 1 found nothing AND the field has no basis for Phase 2 enrichment. Clearly flagged. Admin should review all Phase 3 outputs before saving.

| Gap | Condition | Generation rule |
|---|---|---|
| `board_members` count == 0 after Phase 1 | No board members found anywhere | Generate 6 standard roles for the `industry`: Healthcare → CEO, CMO, CFO, CRO, CHRO, Independent Director |
| `committees` count == 0 after Phase 1 | No committees found in PDF | Generate 3 standard committees: Audit, Risk, Remuneration — assign existing board members by role |
| `current_problems` count < 3 after Phase 1 | Fewer than 3 problems total | Generate from low-value metrics and industry-specific common challenges |
| `key_terms` count < 5 after Phase 1 | Module glossary appears absent | Generate from topic names and framework component names |
| All metrics `value == 0` | PDF likely scanned / image-only | **Do not generate fake financial data.** Flag to admin with `"⛔ Metrics appear unreadable — manual entry required"` |

Phase 3 is folded into the Phase 2 LLM call to avoid a third API round trip.

All Phase 3 outputs are labeled **"AI-Generated (not from PDF)"** in orange.

---

### Output UI — source-coded report

```
COMPANY DATA REVIEW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ✅ Recovered from PDF
  ─────────────────────────────────
  • Found 4 additional board members (pages 18–22 appendix)
      James Osei | Independent Director | Risk expertise | Tenure: 4 yrs
      Priya Nair  | Company Secretary   | Legal expertise | Tenure: 2 yrs
      ...
  • Recovered 12 metrics from financial tables (pages 34–36)
      loan_portfolio_size: 4.2B, cost_to_income_ratio: 58%, ...
  • Recovered Audit Committee members: Sarah Kim, David Osei, Linda Tan
  • Recovered board tenure from appointment dates:
      CEO appointed 2019 → tenure_years: 6
      CFO appointed 2021 → tenure_years: 3

  ✏️  Enriched from context
  ─────────────────────────────────
  • 7 board member personalities rewritten from default
      Before: "Professional and analytical"
      After:  "David Kim is methodical and data-driven, consistently
               challenging assumptions with quantitative evidence..."
  • 3 problems expanded with metric quantification
      Before: "High attrition"
      After:  "Annual attrition at 22% — 7pts above sector average —
               causing critical skill gaps in engineering..."
  • initial_scenario rewritten as boardroom briefing (was copy of overview)

  ⚡ AI-Generated (not from PDF) — review before saving
  ─────────────────────────────────
  • Risk Committee members assigned by role (not found in PDF)
  • CTO personality generated — no bio found in document
  • 2 assessment criteria generated from learning objectives

  ⛔ Requires manual input
  ─────────────────────────────────
  • All revenue metrics show value=0 — PDF may be image-based
    → Open Audit Data tab after saving to enter values manually

MODULE DATA REVIEW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ✅ Recovered from PDF
  • 11 key terms recovered from end-of-document glossary
  • 2 additional frameworks found in appendix case study

  ✏️  Enriched from context
  • 4 topics enriched with key principles
  • Assessment criteria generated from learning objectives

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  [Apply All]   [Apply PDF-Recovered Only]   [Review Each Change]
```

**"Apply PDF-Recovered Only"** applies Phase 1 results only — for admins who trust the PDF but want to manually review enriched/generated content.

**"Review Each Change"** opens an expandable diff view per field — before/after — with the source label and reasoning for each change.

### Auto-fix write-back

All applied fixes write directly to:
- `st.session_state.dc_company_data`
- `st.session_state.dc_module_data`

The `audit_modified` flag is not involved here — that belongs to the Audit tab. The admin proceeds to Step 3 (Save) as normal. No new Firestore writes from the agent.

### LLM call summary

| Call | Phase | Model | Temp | Input | Output |
|---|---|---|---|---|---|
| Call 1 — Recovery | Phase 1 | `gemini-2.5-flash` | 0.3 | Smart-truncated raw text + current JSON summary | Delta patch JSON |
| Call 2 — Enrichment + Gaps | Phase 2 + 3 | `gemini-2.5-flash` | 0.6 | Post-Phase-1 JSON (thin fields only) | Enrichment patch JSON |

Total: 2 LLM calls. Combined latency target: under 20 seconds.

---

## Agent 2 — Audit Data Agent

### Core principle: module_data is the blueprint for company_data

Agent 2 treats `module_data` as the **semantic contract** that `company_data` must fulfill. The module defines what the simulation needs to teach. The company data must have enough content — the right metrics, the right board expertise, the right problems, the right committees — for those teaching goals to work. A missing metric isn't just a data gap; it's a broken simulation goal. A missing board expertise area isn't cosmetic; it means a whole class of module topics has no one on the board to speak to them.

**The agent answers one question per gap: "Which module requirement made this necessary?"** Every generated item carries that reasoning so admin understands why it was added.

---

### Where it lives

`pages/manage_simulations.py` — a collapsible **"AI Audit Assistant"** expander at the top of **Tab 2: Audit Data**, visible only when `st.session_state.audit_data` is not None.

### Trigger

Admin loads a saved session, then clicks **"Run Module Alignment Audit"** inside the expander. The agent runs its deterministic analysis instantly, then makes one LLM call to generate missing content. Admin reviews and applies.

### What it receives

```python
audit_data   = st.session_state.audit_data
company_data = audit_data.get('company_data', {})
module_data  = audit_data.get('module_data', {})
```

Raw PDF text is no longer available at this stage. Agent 2 works entirely from the two structured JSON documents.

---

### Phase 1 — Cross-Document Gap Analysis (deterministic, no LLM)

This is the core new capability. The agent builds a **requirement map** from `module_data` and checks every requirement against `company_data`.

#### Mapping 1: Module subject_area → Required metric categories

`core/scoring.py:generate_game_goals()` uses `CATEGORY_MAP` to group metrics. The module's `subject_area` directly predicts which metric categories must be present for game goals to be meaningful:

| subject_area | Required metric categories | Example metric keys |
|---|---|---|
| Finance / Accounting | Financial | `total_revenue_annual`, `ebitda`, `net_profit_margin`, `revenue_growth_yoy`, `debt_to_equity_ratio` |
| HR / People Management | HR | `annual_attrition_rate`, `employee_engagement_score`, `employee_count`, `training_hours_per_employee` |
| Technology / IT | Operations | `platform_uptime`, `deployment_frequency`, `security_incidents`, `it_spend_percentage` |
| Marketing / Sales | Customer | `net_promoter_score`, `customer_churn_rate_annual`, `customer_acquisition_cost`, `customer_lifetime_value` |
| Risk / Compliance | Risk | `regulatory_compliance_score`, `risk_incidents_count`, `audit_findings_open` |
| Strategy | Financial + Customer | Revenue + market share metrics |
| Operations / Supply Chain | Operations | `operational_efficiency_ratio`, `on_time_delivery_rate`, `supply_chain_disruption_count` |

**Gap detection:** For each required category, the agent checks if at least 3 metrics exist with non-zero values. Fewer than 3 = gap flagged. Zero metrics for a required category = blocker.

#### Mapping 2: Module topics → Board expertise required

Each topic implies a board member must exist with matching expertise to speak credibly during consultation:

| Topic keyword | Required board expertise | Allowed roles |
|---|---|---|
| Financial analysis / statements / capital | Finance | CFO, Executive Director |
| Risk / governance / compliance | Risk | CRO, Independent Director |
| Human capital / talent / workforce / HR | HR | CHRO |
| Digital / technology / cyber / data | Technology | CTO, CISO |
| Legal / regulatory / contract | Legal | CLO, General Counsel |
| Marketing / brand / customer | Marketing | CMO |
| Operations / supply chain / logistics | Operations | COO |
| Strategy / corporate / M&A | Strategy | CEO, Board Director |

**Gap detection:** For each module topic, find the required expertise. If no board member has that expertise → orphaned topic. Orphaned topics produce hollow consultation responses during simulation.

#### Mapping 3: Module learning_objectives → Company problems required

Learning objectives describe what students must practice. Each objective implies a class of boardroom problem that must exist in `current_problems`:

| Learning objective verb / keyword | Problem type needed |
|---|---|
| "Analyze financial distress / performance" | Financial performance problems (margin pressure, revenue decline) |
| "Evaluate talent / retention / workforce" | HR problems (attrition, engagement, skill gaps) |
| "Apply risk framework / assess risk" | Risk / compliance problems (regulatory exposure, operational risk) |
| "Develop market strategy / expansion" | Growth or market problems (competition, market share loss) |
| "Assess governance / board oversight" | Governance problems (board accountability, committee effectiveness) |
| "Manage digital / technology transformation" | Technology problems (legacy systems, cyber threats) |
| "Optimize operations / supply chain" | Operational problems (efficiency, disruption, capacity) |

**Gap detection:** For each learning objective, determine its problem type. Check if at least 1 current_problem covers that type. If not → missing problem flagged, with the objective as the reason.

#### Mapping 4: Module frameworks → Committees required

Frameworks that students must apply imply governance structures that should exist in the company:

| Framework type | Committee needed |
|---|---|
| Audit / financial reporting / internal control | Audit Committee |
| Risk management / enterprise risk | Risk Committee |
| Executive compensation / remuneration | Remuneration Committee |
| Governance / board effectiveness | Governance / Nominations Committee |
| ESG / sustainability | ESG Committee or Risk Committee |

**Gap detection:** For each framework in `module_data.frameworks`, determine if it implies a committee. Check if that committee type exists in `company_data.committees`. Missing → flagged with framework name as reason.

#### Mapping 5: Module key_terms → Metrics must exist

If a key term is a known financial/operational metric, that metric should exist in company data so students can see it in action:

| Key term | Expected metric key pattern |
|---|---|
| EBITDA | `ebitda` |
| NPS / Net Promoter Score | `net_promoter_score` |
| Attrition Rate | `annual_attrition_rate` |
| Compliance Score | `regulatory_compliance_score` |
| Churn Rate | `customer_churn_rate_annual` |
| ROE / Return on Equity | `return_on_equity` |
| Debt-to-Equity | `debt_to_equity_ratio` |

**Gap detection:** Scan key_terms for known metric names. Check if a matching metric exists in company metrics. Missing → flagged.

---

### Phase 2 — Structural Integrity Checks (deterministic, no LLM)

These checks catch issues that silently break the simulation engine regardless of module alignment:

| Check | Engine impact if ignored |
|---|---|
| Committee `chairperson` not in `board_members` names | `get_committee_prompt()` in `llm.py:83` — `member_details` returns empty list, committee prompt has no personnel |
| Committee `members` list contains names not in `board_members` | Same — phantom members are skipped; committee appears to have no one |
| Board member `role` not in allowed list (`content_parser.py:306`) | Scenario generator references invalid role; options mapping breaks |
| Board has fewer than 4 members | Not enough voices for APPROVE / OPPOSE / NEUTRAL spread — simulation feels unanimous |
| 0 committees defined | `get_committee_response()` called but nothing to render |
| Any committee has 0 members | Committee prompt has no `member_details` — generic non-personalized response |
| All board members have identical `expertise` | Every board member echoes the same view — no deliberation tension |
| `metrics` dict is empty | `generate_game_goals()` in `scoring.py:96` returns empty list — simulation has no performance targets |
| Any metric `value == 0` with non-empty unit | `generate_game_goals()` skips zero-value metrics — that metric produces no game goal |
| Board member `personality` == default string | Board member speaks generically in every consultation and evaluation |
| Board member `tenure_years == 0` | Tenure context missing from `get_board_member_prompt()` — member loses seniority weight |

---

### Phase 3 — Module-Guided Generation (LLM call)

After Phases 1 and 2 identify all gaps, one LLM call generates everything that's missing. The prompt passes:
- The full gap list with the module reason for each item
- `company_name`, `industry`, `company_overview` as generation context
- `module_name`, `subject_area`, all topics, learning objectives, frameworks as the semantic guide
- Existing board members list (so generated content doesn't duplicate or contradict what's there)

#### What gets generated and how

**Missing metrics (module-guided):**
Generated metric keys must use words from `CATEGORY_MAP` in `scoring.py` so the scoring engine categorizes them correctly. The agent is instructed to name metrics with the category keywords:
```
Finance gap → keys must contain: revenue, profit, ebitda, margin, growth, or debt
HR gap     → keys must contain: employee, engagement, attrition, or headcount
Customer   → keys must contain: customer, churn, promoter, satisfaction, or retention
Operations → keys must contain: uptime, deployment, or platform
Risk       → keys must contain: risk, compliance, or regulatory
```
Values are calibrated to the `industry` (e.g. SaaS company: `platform_uptime: 99.2%`, Manufacturing: `on_time_delivery_rate: 87%`). Units follow `_infer_unit()` logic from `content_parser.py`.

**Missing board members (topic-guided):**
One new member is generated per orphaned topic expertise area. The member receives:
- A role appropriate for that expertise (Risk → CRO; Technology → CTO)
- A personality grounded in the expertise area and the module context
- A realistic `tenure_years` for the role

**Missing committees (framework-guided):**
Generated with the framework name as the `purpose`. Members are assigned from existing board members whose `expertise` matches the committee type. Chairperson is set to the most senior relevant member.

**Missing problems (objective-guided):**
Each generated problem is phrased so it is directly solvable using the module topic that triggered it. Problems reference a specific metric value where possible:
```
Trigger: learning objective "Evaluate talent retention strategies"
Metric available: annual_attrition_rate: 22%
Generated problem: "Annual employee attrition running at 22% — significantly above the 14% industry
benchmark — is causing critical skill gaps in engineering and customer success, with projected
replacement costs of $3.2M in the coming fiscal year. Board intervention on retention strategy is required."
```

**Thin field enrichment (non-module-specific):**
The same call also handles:
- Default `personality` strings → role-specific 2–3 sentence personality
- `tenure_years == 0` → realistic value by role
- Committee `purpose` empty → infer from type
- Committee `members` empty → assign from board by expertise
- Problem strings < 50 chars → expand with metric quantification
- Metric `description` empty → human-readable label from snake_case key
- Module topic `key_principles` empty → generate from topic name + subject_area
- Module `assessment_criteria` empty → generate from learning_objectives using Bloom's verbs

```
Model: gemini-2.5-flash
Temperature: 0.55
Max tokens: 6144  (higher than other agents — generating multiple new records)

Output: complete patch JSON
{
  "metrics_add": { ... },
  "board_members_add": [ ... ],
  "board_members_update": [ ... ],
  "committees_add": [ ... ],
  "committees_update": { ... },
  "problems_add": [ ... ],
  "problems_update": [ ... ],
  "initial_scenario": "",
  "company_overview_expanded": "",
  "topics_update": { ... },
  "assessment_criteria": [ ... ],
  "generation_reasons": {
    "metrics_add": "Finance metrics needed — module topic 'Capital Allocation' requires Financial category metrics for game goals",
    "board_members_add[0]": "CRO added — module topic 'Risk Governance' has no board expert with Risk expertise",
    ...
  }
}
```

Every generated item includes a `generation_reasons` entry. This is displayed in the UI so admin knows exactly why each item was created.

---

### Readiness Score — updated with module alignment component

```
Score = 100

MODULE ALIGNMENT DEDUCTIONS
  Each orphaned module topic (no board expert):      -8 pts each  (max -24)
  Each uncovered learning objective type:            -5 pts each  (max -20)
  Required metric category missing entirely:         -10 pts each (max -20)
  Framework with no matching committee:              -5 pts each  (max -10)

STRUCTURAL DEDUCTIONS
  Committee chairperson mismatch:                    -8 pts each
  Committee members not in board:                    -5 pts each  (max -10)
  Board < 4 members:                                 -15 pts
  0 committees:                                      -12 pts
  Any committee with 0 members:                      -10 pts each (max -20)
  All board members identical expertise:             -10 pts

COMPLETENESS DEDUCTIONS
  Empty metrics dict:                                -15 pts
  Metrics with value=0 (non-zero unit):              -3 pts each  (max -9)
  Default personality on member:                     -2 pts each  (max -10)
  Fewer than 5 problems:                             -6 pts
  Problem strings < 50 chars:                        -2 pts each  (max -8)
  Overview < 150 chars:                              -5 pts
  Module topics with no key_principles:              -1 pt each   (max -5)
```

Score sections displayed separately: Module Alignment (X/40), Structural (X/35), Completeness (X/25). Overall color: Red (0–49), Orange (50–74), Green (75–100).

---

### Output UI

```
MODULE ALIGNMENT AUDIT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DATA READINESS:  Module Alignment 28/40 · Structural 27/35 · Completeness 12/25 = 67/100

SIMULATION BLOCKERS — fix before running
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ⛔ No Financial metrics found
     Reason: module topic "Capital Allocation Frameworks" requires Financial metrics
             for game goals — scoring.py will produce 0 financial goals
     Fix: 5 financial metrics generated → [ebitda, net_profit_margin, revenue_growth_yoy,
          total_revenue_annual, debt_to_equity_ratio] with calibrated values for Banking industry

  ⛔ Module topic "Risk Governance" has no board expert (Risk expertise)
     Reason: students consulting the board on risk topics get no credible response
     Fix: CRO generated → Marcus Webb | CRO | Risk expertise | Tenure 5 yrs

  ⛔ Committee "Audit Committee" chairperson "Sarah K." not found in board
     Reason: get_committee_prompt() returns empty member_details — committee is unusable
     Fix: closest match → "Sarah Kim" (CFO)

MODULE ALIGNMENT GAPS — will reduce learning outcomes
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ⚠️  Learning objective "Evaluate talent retention strategies" has no matching problem
      Fix: HR problem generated using annual_attrition_rate (22%) as anchor

  ⚠️  Framework "Enterprise Risk Management" implies Risk Committee — none found
      Fix: Risk Committee generated with CRO + CFO + Independent Director

  ⚠️  Key term "EBITDA" in module but no ebitda metric in company data
      Fix: included in Financial metrics batch above

QUALITY ISSUES — will reduce simulation realism
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✏️  6 board members have default personality → role-specific personalities generated
  ✏️  4 problems are under 50 chars → expanded with metric quantification
  ✏️  initial_scenario mirrors company_overview → rewritten as boardroom briefing
  ✏️  Module topic "Financial Statement Analysis" has no key_principles → 3 generated
  ✏️  3 board members have tenure_years=0 → realistic values assigned

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[Apply All]   [Apply Blockers Only]   [Review Each Change]   [Show Diff]
```

**"Review Each Change"** expands a per-item panel showing the before state, the after state, and the module requirement that triggered it.

**"Show Diff"** shows a full JSON diff of every field proposed to change.

### Write-back behavior

All applied fixes write to `st.session_state.audit_data['company_data']` and `st.session_state.audit_data['module_data']`. The `audit_modified` flag is set to `True`. Existing Audit tab Save buttons handle the Firestore write — no new Firestore calls from the agent.

### LLM call summary

| Call | Purpose | Model | Temp | Max tokens |
|---|---|---|---|---|
| Call 1 — Generation | Generate all missing/thin content | `gemini-2.5-flash` | 0.55 | 6144 |

Phases 1 and 2 are fully deterministic — instant, no API call. The LLM call only runs when the admin clicks "Run Module Alignment Audit".

---

## Agent 3 — Simulation Planning Agent

### Core principle: design a story, not a schedule

The existing planning UI assigns `round_type`, `difficulty`, `time_pressure`, and `focus_area` per round. Agent 3 rethinks what those fields actually do.

The critical insight is in `llm.py:303`:
```python
f"- Focus Area: {round_config.get('focus_area') or 'General'}"
```

The `focus_area` string goes **directly into `get_scenario_generator_prompt()`** — every word in it shapes the scenario Gemini generates. A thin focus_area like `"Capital Allocation"` gives the scenario generator almost nothing to work with. A rich, narrative focus_area like `"[Act 2, Escalation] Following the Q1 budget freeze, the CFO now presents a covenant breach warning — board must choose between asset divestiture and equity raise, applying Capital Allocation frameworks"` produces a dramatically better, contextually grounded scenario.

Agent 3 treats the simulation as a **3-act story** and writes rich `focus_area` text for every round — that's its primary mechanism for making the simulation interesting.

---

### Where it lives

`pages/manage_simulations.py` — a collapsible **"AI Narrative Planner"** expander in **Tab 3: Simulation Planning**, visible when a session is loaded.

### Trigger

Admin loads a session and sets the number of rounds. Before configuring individual rounds, they click **"Design Simulation Narrative"**. The agent runs instant pre-analysis, then one LLM call generates the full plan. Admin previews and applies.

### What it receives

```python
session_data  = st.session_state.planning_session_data
config        = st.session_state.simulation_config

company_data  = session_data.get('company_data', {})
module_data   = session_data.get('module_data', {})
total_rounds  = config.get('total_rounds', 5)
initial_setup = config.get('initial_setup', {})
```

---

### Phase 1 — Learning Architecture Analysis (deterministic, instant)

Before any LLM call, the agent builds the structural foundation the narrative will be designed around.

#### 1a. Bloom's taxonomy sequencing of module topics

Topics are classified by cognitive level and sorted into a pedagogical sequence — foundational topics appear in early rounds, synthesis topics in final rounds:

| Bloom level | Keywords in topic name / description | Simulation position |
|---|---|---|
| 1 — Remember / Understand | introduction, overview, definition, basic, principles of, fundamentals | Act 1 — foundation rounds |
| 2 — Apply | application, analysis, using [framework], calculating, measuring, implementing | Act 2 — early complication |
| 3 — Analyze / Evaluate | evaluation, assessment, comparison, trade-offs, diagnosis, strategic | Act 2 — peak complication |
| 4 — Create / Synthesize | strategy, integration, synthesis, comprehensive, advanced, design | Act 3 — resolution rounds |

If a topic's level cannot be determined from keywords, it defaults to Level 2.

#### 1b. Board tension pair identification

The agent scans board_members and identifies natural opposition pairs — expertise conflicts that produce the APPROVE/OPPOSE dynamics that make deliberation feel real:

| Expertise pair | Typical conflict | When to activate |
|---|---|---|
| Finance ↔ HR | Cost-cutting vs. people investment | Rounds where restructuring or budget is the focus |
| Technology ↔ Finance | Innovation investment vs. capital constraint | Rounds where digital transformation is the focus |
| Risk ↔ Strategy (CEO) | Risk aversion vs. growth ambition | Rounds where expansion or bold decisions are required |
| Legal ↔ Operations | Compliance strictness vs. operational efficiency | Rounds where regulatory issues surface |
| Independent Director ↔ Executive | Governance scrutiny vs. management autonomy | Final rounds or governance-focused rounds |

Each tension pair is encoded into the `focus_area` text for the rounds where it should activate.

#### 1c. Learning objective × coverage requirement

For N rounds and M learning objectives, each objective must appear in at least 1 round. If `total_rounds < len(learning_objectives)`, the agent flags that some objectives will share rounds.

#### 1d. Assessment criteria → round type map

| Assessment criterion keyword | Best round type |
|---|---|
| Financial analysis / calculations | Finance-focused round, medium+ difficulty |
| Board consultation / stakeholder | Any round (tracked by scoring automatically) |
| Debate / persuasion / dissent | Hard difficulty round — OPPOSE responses likely |
| Strategic reasoning / synthesis | Final act round, hard difficulty |
| Risk assessment / governance | Risk-focused round, both type |

#### 1e. Pre-planning flags (shown to admin instantly, before LLM runs)

| Check | Flag |
|---|---|
| `total_rounds < len(learning_objectives)` | Some objectives will have to share a round |
| Any orphaned topic (no board expert) | That topic's round will produce hollow consultations |
| 0 board tension pairs identified | Simulation will feel consensus-heavy — consider adding opposing expertise |
| `starting_scenario == "crisis"` | Act 1 must start at medium difficulty minimum |
| `total_rounds < 4` | Insufficient rounds for 3-act structure — suggest minimum 5 |
| `total_rounds > len(problems) + len(topics)` | More rounds than unique content — late rounds will repeat themes |

---

### Phase 2 — Narrative Arc Design (LLM call)

The LLM's job is to design the simulation as a story. It receives the full pre-analysis from Phase 1 and outputs a complete plan with rich `focus_area` text for each round.

#### The 3-act structure

```
ACT 1 — ORIENTATION  (first 25–30% of rounds, minimum 1 round)
  Tone: Board is collegial. Situation is being understood. Stakes are emerging.
  Difficulty: Easy to medium. Time pressure: Relaxed to normal.
  Topics: Bloom Level 1–2 (foundational, application).
  Goal: Student gets grounded in the company context and applies basic module frameworks.
  focus_area style: "[Act 1] Opening boardroom situation — [specific problem surfaces for first time]
                    — board diagnoses, no major conflict yet. Apply: [foundational topic]."

ACT 2 — COMPLICATION  (middle 40–50% of rounds, minimum 2 rounds)
  Tone: Problems compound. Decisions from Act 1 have unintended consequences.
        Board tension pairs begin to activate. No easy answers.
  Difficulty: Medium to hard. Time pressure: Normal to urgent.
  Topics: Bloom Level 2–3 (application, analysis, evaluation).
  Goal: Student must apply module frameworks under pressure and navigate board dissent.
  focus_area style: "[Act 2, Escalation] Consequence of [Act 1 decision] — [new complication].
                    Tension: [Member A] vs [Member B] activated.
                    Apply: [framework/topic]. Board expected to split on this."

ACT 3 — RESOLUTION  (last 25–30% of rounds, minimum 1 round)
  Tone: Peak crisis. Board polarized. Defining strategic decision required.
        All module learnings must be synthesized.
  Difficulty: Hard. Time pressure: Urgent.
  Topics: Bloom Level 3–4 (evaluation, synthesis).
  Goal: Student demonstrates mastery by synthesizing all module topics into a coherent decision.
  focus_area style: "[Act 3, Climax] Full board crisis — [peak consequence of all previous decisions].
                    All tensions converge. Student must synthesize [list of module topics].
                    This round determines the simulation's outcome."
```

#### What the LLM writes for each round's `focus_area`

The `focus_area` field is not a topic label — it is a **narrative brief** for the scenario generator. It must include:

1. **Act and position tag** — `[Act 2, Round 4]` — tells the scenario generator where in the story this sits
2. **Dramatic situation** — specific, concrete situation with numbers where metrics are available
3. **Decision cascade link** — how this round connects to the previous round's outcome
4. **Named board characters** — the spotlight members and the tension being activated
5. **Module topic directive** — which topic/framework the student must apply, in explicit terms
6. **Learning objective** — which LO this round covers (so scenario generator can frame the question correctly)

Example — weak (old approach):
```
focus_area: "Capital Allocation"
```

Example — rich (Agent 3 approach):
```
focus_area: "[Act 2, Round 5] Following the austerity measures approved in Round 3, the CFO now
presents a covenant breach warning: debt-to-equity has reached 2.4x against a covenant ceiling
of 2.0x. Three options on the table — asset divestiture, rights issue, or debt renegotiation.
Spotlight: Sarah Kim (CFO) vs Marcus Webb (CRO) — financial pragmatism vs. risk exposure.
Apply: Capital Allocation Frameworks (module topic 6, Bloom Level 3).
Covers: LO3 — Evaluate capital structure decisions under financial distress."
```

This single field gives the scenario generator: act context, specific financials, named board characters, their conflict, the exact module topic to apply, and the learning objective being assessed.

#### Decision cascade design

The LLM designs a **cascade chain** across rounds — each round's focus_area references the consequence of the previous decision. This is what feeds the `previous_rounds` context in `get_scenario_generator_prompt()` (which the engine already passes). The cascade makes the simulation feel like a continuous story rather than disconnected episodes.

```
Round 1 decision:  "Approve emergency cost freeze across all divisions"
Round 2 cascade:   "Cost freeze has halted the customer success team's expansion — NPS dropped 8 pts"
Round 3 cascade:   "NPS decline triggered customer churn — Q2 revenue down 15%"
Round 4 cascade:   "Revenue decline breached debt covenant — lender has called a review"
Round 5 cascade:   "Board must now choose: restructure now or seek new capital (peak crisis)"
```

The cascade is written into each round's `focus_area` — not a separate field. The scenario generator automatically uses the `previous_rounds` chain to escalate.

#### Board member spotlight assignment per round

Each round is given a **spotlight member** — the board member whose expertise is most central to that round's scenario. The spotlight member is named in the `focus_area` text so the scenario generator naturally directs Options A–D toward them. This ensures every board member gets at least one round where they are the key voice the student must consult.

Spotlight assignment rule:
- Distribute spotlights evenly across board members with different expertise
- Ensure the member with the relevant expertise for the round's topic gets the spotlight
- Final round: "Full Board" — all tension pairs converge

#### LLM call specification

```
Model: gemini-2.5-flash
Temperature: 0.65  (needs narrative creativity, grounded in company/module data)
Max tokens: 8192   (large — generating rich focus_area text for all rounds)

Input:
  - company_name, industry, company_overview, initial_scenario
  - current_problems (the drama source — company's live challenges)
  - board_members with name, role, expertise, personality (the cast of characters)
  - committees (the governance structure)
  - module_name, subject_area, overview
  - learning_objectives (what must be demonstrated by end of simulation)
  - topics sorted by Bloom level (pedagogical sequence)
  - frameworks (what tools students must apply)
  - assessment_criteria (what students will be graded on)
  - total_rounds
  - act_structure: {act1: [1..], act2: [..], act3: [..N]}  (computed in Phase 1)
  - bloom_sequence: topics sorted Level 1 → Level 4
  - tension_pairs: [(member_a, member_b, conflict_type), ...]  (from Phase 1)
  - starting_scenario type (crisis/growth/stable/default/custom)
  - orphaned_topics: [topics with no board expert]

Output schema:
{
  "narrative_arc_title": "One sentence describing the simulation's story",
  "act_labels": {
    "act1": "Orientation subtitle",
    "act2": "Complication subtitle",
    "act3": "Resolution subtitle"
  },
  "rounds": [
    {
      "round_number": 1,
      "round_type": "business|module|both",
      "difficulty": "easy|medium|hard",
      "time_pressure": "relaxed|normal|urgent",
      "focus_area": "Rich narrative text as described above",
      "act": 1,
      "bloom_level": 1,
      "spotlight_member": "Name (Role)",
      "module_topic_applied": "Topic name",
      "learning_objective_covered": "LO text",
      "tension_activated": "Member A vs Member B — conflict type | null",
      "cascade_note": "How this round's decision seeds the next round"
    }
  ]
}
```

Only `round_type`, `difficulty`, `time_pressure`, and `focus_area` are written to Firestore (these are the standard round config fields). All other output fields (`act`, `bloom_level`, `spotlight_member`, `module_topic_applied`, `learning_objective_covered`, `tension_activated`, `cascade_note`) are **display only** — shown in the UI plan preview but not stored.

---

### Phase 3 — Coverage Verification (deterministic, instant)

After Phase 2 returns the plan, the agent verifies learning completeness before showing the admin:

**Learning objective coverage check:**
Every LO in `module_data.learning_objectives` must appear in at least one round's `learning_objective_covered`. Uncovered LOs are flagged — admin can add a round or override a focus area.

**Assessment criteria coverage check:**
Each assessment criterion is mapped to the round types/difficulties that exercise it. Criteria that no round covers are flagged.

**Board member spotlight balance:**
Every board member should have at least 1 spotlight round. Members with zero spotlight rounds are flagged — their expertise never gets directly exercised.

**Orphaned topic handling:**
If a module topic has no board expert (flagged in Phase 1 but not fixed by Agent 2), it is still placed into a round but marked with a warning in the plan.

---

### Output UI

```
NARRATIVE SIMULATION PLAN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Story Arc: "From Stability to Crisis — A Financial Restructuring at Meridian Bank"
8 rounds | 3 acts | 5/5 learning objectives covered | 4/4 assessment criteria covered

CONTENT FOUNDATION
  7 company problems · 12 module topics (sequenced Bloom L1→L4) · 6 board expertise areas
  Tension pairs: CFO ↔ CHRO, CRO ↔ CEO, CTO ↔ CFO
  Orphaned topics: none

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ACT 1: ORIENTATION — "The Cracks Appear" (Rounds 1–2)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Round 1 | Business | Easy | Relaxed | Spotlight: CEO (James Liu)
  Bloom: L1 — Financial Statement Analysis (foundational)
  Covers: LO1 — Analyze financial performance indicators

  "Opening board session: Q3 earnings reveal 12% revenue miss vs. forecast. CEO James Liu
   presents the situation — three contributing factors identified. Board must prioritize
   the diagnostic approach. No major conflict expected — board is gathering information."

  Round 2 | Module | Easy | Normal | Spotlight: CFO (Sarah Kim)
  Bloom: L2 — Cost Structure Analysis (application)
  Covers: LO1 extended — Apply cost analysis frameworks to diagnose margin pressure

  "CFO Sarah Kim presents the full cost breakdown using DuPont Analysis. Cost overruns
   in 3 divisions identified. Board must agree on remediation scope. First use of
   financial frameworks — student applies module week 2 tools in a low-stakes setting."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ACT 2: COMPLICATION — "Decisions Have Consequences" (Rounds 3–6)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Round 3 | Both | Medium | Normal | Spotlight: CHRO (Priya Nair)
  Bloom: L2 — Human Capital Risk (application)
  Covers: LO2 — Evaluate talent retention under restructuring pressure
  Tension: CFO ↔ CHRO activated

  "Cascade from Round 1: Cost freeze response triggered 18% attrition spike — CHRO Priya
   Nair warns of talent crisis. CFO pushes for deeper cuts; CHRO warns of irreversible
   skill loss. Board split. Student must navigate the CFO/CHRO tension using HR Risk
   frameworks (module week 4)."

  Round 4 | Both | Medium | Urgent | Spotlight: CRO (Marcus Webb)
  Bloom: L3 — Risk Governance Framework (analysis)
  Covers: LO3 — Apply enterprise risk framework to compliance exposure
  Tension: CRO ↔ CEO activated

  "Cascade from Round 3: Attrition in the compliance team triggered a regulatory audit.
   CRO Marcus Webb presents a critical risk exposure report. CEO pushes to downplay;
   CRO insists on full board disclosure. Student applies ERM framework to assess
   exposure and recommend disclosure strategy."

  Round 5 | Both | Hard | Urgent | Spotlight: CFO + CRO
  Bloom: L3 — Capital Allocation (analysis + evaluation)
  Covers: LO1 + LO3 synthesis — Evaluate capital structure under dual financial/risk pressure
  Tension: CFO ↔ CRO, CFO ↔ CEO

  "Cascade from Round 4: Regulatory fine risk + revenue decline have pushed debt-to-equity
   to 2.4x against a 2.0x covenant. CFO Sarah Kim presents three options: divestiture,
   rights issue, or debt renegotiation. CRO flags risk exposure for each option. Board
   deeply divided. Student must apply Capital Allocation frameworks under time pressure."

  Round 6 | Module | Hard | Urgent | Spotlight: Independent Director (Linda Tan)
  Bloom: L3 — Corporate Governance Standards (evaluation)
  Covers: LO5 — Assess board governance effectiveness under shareholder scrutiny
  Tension: Independent Director ↔ Executive Directors

  "Cascade from Round 5: Capital raise announcement triggered institutional shareholder
   scrutiny. Independent Director Linda Tan leads governance review. Executive directors
   resist oversight. Student applies Corporate Governance frameworks to recommend
   accountability measures — governance under crisis conditions."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ACT 3: RESOLUTION — "The Defining Decision" (Rounds 7–8)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Round 7 | Both | Hard | Urgent | Spotlight: CEO + CFO + CRO
  Bloom: L4 — Strategic Decision-Making (synthesis)
  Covers: LO4 — Develop and defend a comprehensive recovery strategy
  Tension: All pairs converge

  "Cascade from Round 6: Board must now vote on the 3-year recovery strategy — approve
   Meridian's restructuring plan or pursue a merger with a strategic acquirer. Full board
   polarized. Student synthesizes all previous module learnings into a single coherent
   strategic recommendation. This is the simulation's defining moment."

  Round 8 | Both | Hard | Urgent | Spotlight: Full Board
  Bloom: L4 — Performance Governance (synthesis)
  Covers: All LOs — Final accountability and KPI-setting

  "Resolution: Implement approved strategy. Board sets performance KPIs, accountability
   framework, and governance checkpoints. Student demonstrates mastery by designing
   a measurement framework using all module tools learned across the simulation."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LEARNING OBJECTIVE COVERAGE
  LO1: Analyze financial performance         → Rounds 1, 2, 5   ✓
  LO2: Evaluate talent retention             → Round 3           ✓
  LO3: Apply risk governance framework       → Rounds 4, 5       ✓
  LO4: Develop recovery strategy             → Round 7           ✓
  LO5: Assess board governance               → Round 6           ✓

ASSESSMENT CRITERIA COVERAGE
  AC1: Financial analysis depth              → Rounds 2, 5       ✓
  AC2: Board consultation quality            → All rounds        ✓
  AC3: Debate and persuasion effectiveness   → Rounds 3–7        ✓
  AC4: Strategic synthesis                   → Rounds 7–8        ✓

BOARD MEMBER SPOTLIGHT BALANCE
  James Liu (CEO)        → Rounds 1, 7   ✓
  Sarah Kim (CFO)        → Rounds 2, 5   ✓
  Priya Nair (CHRO)      → Round 3       ✓
  Marcus Webb (CRO)      → Rounds 4, 5   ✓
  Linda Tan (Ind. Dir.)  → Round 6       ✓
  David Osei (COO)       → ⚠️ No spotlight — consider adding to Round 2 or 8

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[Apply Full Plan]   [Apply Difficulty + Time Only]   [Apply Focus Areas Only]   [Discard]
```

### Write-back behavior

**Apply Full Plan** writes `round_type`, `difficulty`, `time_pressure`, and `focus_area` to `st.session_state.simulation_config['rounds']` for all rounds. Display fields (`act`, `bloom_level`, `spotlight_member`, etc.) are shown in the preview but not stored — they live only in the agent's output dict during the session.

The existing Save button in the planning tab persists to Firestore as normal. No new Firestore calls from the agent.

### LLM call summary

| Call | Purpose | Model | Temp | Max tokens |
|---|---|---|---|---|
| Call 1 — Narrative Design | Full 3-act plan with rich focus_area text | `gemini-2.5-flash` | 0.65 | 8192 |

Phase 1 (Bloom classification, tension pairs, coverage requirements, flags) is fully deterministic — instant, no API call. Phase 3 (coverage verification) is also deterministic — runs immediately after the LLM returns.

---

## Shared Design Principles

### No new API dependency
All three agents use the existing `GEMINI_API_KEY` from `st.secrets` with the same `genai.Client` pattern as `extractors/content_parser.py`.

### Agents never silently mutate state
Every fix is presented as a suggestion with an explicit apply button. No agent writes to session state without the admin clicking Apply.

### Source transparency
Every item in every report is labeled with its source — **Recovered from PDF**, **Enriched from context**, or **AI-Generated**. Admin always knows what came from the document vs what the AI invented.

### Agents are idempotent
Running the same agent twice on the same data produces the same suggestions. Re-running after applying fixes detects fewer issues.

### UI placement
Each agent lives inside `st.expander("AI Assistant", expanded=False)` — non-intrusive for admins who don't need it.

---

## Implementation Plan

### New file: `core/admin_agents.py`

```python
# Public API — one function per agent
run_create_review_agent(company_data, module_data, company_text, module_text) -> dict
run_audit_agent(company_data, module_data) -> dict
run_planning_agent(company_data, module_data, simulation_config) -> dict

# Agent 1 internals
_smart_truncate_text(raw_text, current_json, target_chars=80000) -> str
_build_recovery_prompt(company_text, company_data) -> str
_build_module_recovery_prompt(module_text, module_data) -> str
_build_enrichment_prompt(company_data, module_data, gaps) -> str

# Agent 2 internals
_build_module_requirement_map(module_data) -> dict
    # Returns: {
    #   "required_metric_categories": [...],
    #   "required_board_expertise": [(topic_name, expertise), ...],
    #   "required_problem_types": [(objective_text, problem_type), ...],
    #   "required_committees": [(framework_name, committee_type), ...],
    #   "metric_key_terms": [(term, metric_key_pattern), ...]
    # }
_run_cross_document_gap_analysis(company_data, module_data) -> list[dict]
    # Returns list of gap dicts: {type, severity, reason, module_trigger, fix_hint}
_run_structural_checks(company_data) -> list[dict]
_build_audit_generation_prompt(company_data, module_data, gaps) -> str
_compute_readiness_score(module_gaps, structural_gaps, completeness_gaps) -> dict
    # Returns: {module_score, structural_score, completeness_score, total}

# Agent 3 internals
_classify_topic_bloom_level(topic) -> int                   # 1-4 from keyword analysis
_identify_tension_pairs(board_members) -> list[dict]        # expertise conflict pairs
_compute_act_structure(total_rounds, starting_scenario) -> dict  # act1/act2/act3 round ranges
_check_coverage_requirements(module_data, total_rounds) -> dict  # LO + criteria mapping
_run_pre_planning_flags(company_data, module_data, config) -> list[dict]
_build_narrative_planning_prompt(company_data, module_data, config,
                                  bloom_sequence, tension_pairs,
                                  act_structure, coverage_reqs) -> str
_verify_coverage(plan, module_data, board_members) -> dict  # LO + criteria + spotlight check

# Shared
_call_admin_llm(prompt, temperature, max_tokens) -> str
_extract_json(text) -> dict
```

### Page modifications

| File | Change |
|---|---|
| [pages/create_simulation.py](../pages/create_simulation.py) | Add Agent 1 expander between Step 2 and Step 3 |
| [pages/manage_simulations.py](../pages/manage_simulations.py) | Add Agent 2 expander at top of `_render_company_audit()`; add Agent 3 expander at top of `_render_simulation_planning()` |

### No changes to
- `core/llm.py`
- `core/simulation_engine.py`
- `extractors/content_parser.py`
- Firestore schema

---

## Data Quality → Simulation Quality Chain

```
PDF Upload
  └─► PyPDF2 / Gemini extraction  →  raw text stored in dc_company_text / dc_module_text
        └─► parse_company_data()  →  structured JSON (first parse — lossy compression)

Agent 1 — Create Simulation Review  (raw text + structured JSON)
  Phase 1: PDF Recovery  (uses dc_company_text + dc_module_text)
    ├─ Recovers missed board members from appendix/bios  → More distinct voices
    ├─ Recovers metrics from financial tables            → Real numbers for scoring goals
    ├─ Recovers committee members from governance pages  → get_committee_prompt() works
    └─ Recovers tenure from appointment dates            → Board seniority context preserved

  Phase 2: Quality Enrichment  (uses post-Phase-1 JSON)
    ├─ Rewrites default personalities  → Each member debates with distinct voice
    ├─ Expands vague problems          → Scenarios have specific, quantified stakes
    └─ Rewrites initial_scenario       → Round 1 opens with a grounded briefing

  Phase 3: Gap Completion  (last resort, labeled AI-Generated)
    └─ Generates only what is absent from both PDF and JSON — admin reviews before saving

Firestore Save
  └─► Agent 2 — Module Alignment Audit  (company_data + module_data JSON only)

  Phase 1: Cross-Document Gap Analysis  (deterministic)
    ├─ module.subject_area → required metric categories → gaps flagged per CATEGORY_MAP
    ├─ module.topics → required board expertise → orphaned topics identified
    ├─ module.learning_objectives → required problem types → missing problems identified
    └─ module.frameworks → required committees → missing committee types identified

  Phase 2: Structural Integrity Checks  (deterministic)
    ├─ Committee chairperson/member name mismatches → engine prompt failures caught
    ├─ Invalid board roles → scenario generator option mapping issues caught
    └─ Zero-value metrics → scoring.py goal generation gaps caught

  Phase 3: Module-Guided Generation  (1 LLM call)
    ├─ Missing metrics generated with CATEGORY_MAP-compatible keys + calibrated values
    ├─ Missing board members generated with module-topic-matched expertise
    ├─ Missing committees generated with framework-derived purpose + correct members
    ├─ Missing problems generated phrased to be solvable via the triggering module topic
    └─ Every item carries generation_reason → admin knows why it was added

    Output: Readiness Score (Module Alignment / Structural / Completeness)
    Admin knows exact quality level and module coverage before configuring rounds

Simulation Planning
  └─► Agent 3 — Narrative Planner  (company_data + module_data + simulation_config)

  Phase 1: Learning Architecture Analysis  (deterministic)
    ├─ Bloom's taxonomy sequencing of topics  → Foundational → synthesis pedagogical order
    ├─ Board tension pair identification      → CFO↔CHRO, CRO↔CEO conflicts mapped to rounds
    ├─ LO × round coverage requirements      → Every learning objective must appear in ≥1 round
    └─ Assessment criteria → round type map  → Hard rounds exercise debate/synthesis criteria

  Phase 2: Narrative Arc Design  (1 LLM call — the story designer)
    ├─ 3-act structure designed              → Orientation → Complication → Resolution
    ├─ Rich focus_area written per round     → Narrative brief fed directly into scenario generator
    │    focus_area contains: act tag, specific dramatic situation, named board characters,
    │    tension activated, module topic directive, LO being covered, cascade from prev round
    ├─ Decision cascade planned              → Round N decision seeds Round N+1 scenario
    └─ Board member spotlights assigned      → Every member gets ≥1 prominent round

  Phase 3: Coverage Verification  (deterministic)
    ├─ LO coverage confirmed                → All learning objectives appear in at least 1 round
    ├─ Assessment criteria coverage checked → All criteria exercisable in the plan
    └─ Spotlight balance verified           → All board members have at least 1 spotlight round

Simulation Runtime
  └─► Scenario generator (gemini-2.5-flash) receives rich focus_area text per round
       → Produces specific, dramatically grounded scenarios with named characters and real stakes
       → Previous rounds escalate meaningfully via cascade chain
       → Students work through a coherent 3-act story, applying module topics in sequence
       → Every module learning objective is exercised and assessable
       → Board debates feel authentic — tension pairs activate at planned moments
```
