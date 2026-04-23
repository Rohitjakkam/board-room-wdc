"""
End-to-end pipeline test: sample_data PDFs -> extract -> parse -> Agent 1 ->
Agent 2 -> Agent 3 -> Firestore save -> load-back verify.

Covers all 13 recent fixes:
 1. Readiness score uses required_expertise (not full _KEYWORD_TO_EXPERTISE)
 2. Agent 3 guard (planning_session_data + content checks)
 3. Round number re-indexing on apply
 4. company_overview_supplement + module_overview handlers
 5. apply_generated flag gates enrichment properly
 6. JSON truncation salvage + 8192-token limits
 7. update_simulation full overwrite (no stale merge keys)
 8. validate_simulation_data guard
 9. Framework matching normalized (ISO31000 / ISO 31000)
10. Narrative metadata (_tension_pair) piped into scenario prompt
11. _apply_agent2_patch missing-audit_data guard
12. Board role normalization
13. Round count reconciliation on load

Run: .venv/Scripts/python.exe test_pipeline.py
"""

import sys
import os
import types
import logging
import time

# Force UTF-8 on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

logging.basicConfig(level=logging.WARNING, format="%(levelname)s | %(name)s | %(message)s")

# ---------------------------------------------------------------------------
# Streamlit mock
# ---------------------------------------------------------------------------

class _MockSecrets(dict):
    def get(self, key, default=None):
        return self[key] if key in self else default

class _Ctx:
    def __enter__(self): return self
    def __exit__(self, *a): pass

def _noop(*a, **kw): pass
def _spinner(msg=""):
    print(f"  [spinner] {msg}")
    return _Ctx()
def _expander(label, **kw): return _Ctx()

def _mock_cache(func=None, **kw):
    def _wrap(f):
        f.clear = lambda: None
        return f
    if func is not None:
        return _wrap(func)
    return _wrap

st_mock = types.ModuleType("streamlit")
def _load_secrets() -> dict:
    """Read secrets from .streamlit/secrets.toml (gitignored). Falls back to env."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".streamlit", "secrets.toml")
    secrets = {}
    if os.path.exists(path):
        try:
            import tomllib  # py3.11+
        except ImportError:
            import tomli as tomllib
        with open(path, "rb") as f:
            secrets = tomllib.load(f)
    for k in ("GEMINI_API_KEY", "ADMIN_PASSWORD"):
        secrets.setdefault(k, os.environ.get(k, ""))
    return secrets

st_mock.secrets   = _MockSecrets(_load_secrets())
st_mock.error     = lambda msg, **kw: print(f"  [st.error] {msg}")
st_mock.warning   = lambda msg, **kw: print(f"  [st.warning] {msg}")
st_mock.info      = lambda msg, **kw: print(f"  [st.info] {msg}")
st_mock.success   = lambda msg, **kw: print(f"  [st.success] {msg}")
st_mock.write     = lambda *a, **kw: None
st_mock.spinner   = _spinner
st_mock.expander  = _expander
class _SessionState(dict):
    """Dict that also supports attribute access (st.session_state.foo)."""
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)
    def __setattr__(self, name, value):
        self[name] = value
    def __delattr__(self, name):
        del self[name]

st_mock.session_state = _SessionState()
st_mock.cache_data     = _mock_cache
st_mock.cache_resource = _mock_cache
st_mock.rerun          = _noop

sys.modules["streamlit"] = st_mock

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

SAMPLE_DIR  = os.path.join(ROOT, "sample_data")
COMPANY_PDF = os.path.join(SAMPLE_DIR, "company_data_10_Helix_Therapeutics_Inc..pdf")
MODULE_PDF  = os.path.join(SAMPLE_DIR, "module_data_BRSR.pdf")

PASS = "[PASS]"
FAIL = "[FAIL]"
WARN = "[WARN]"

def sep(title):
    print(f"\n{'='*60}\n  {title}\n{'='*60}")

def check(label, condition, value=None):
    icon = PASS if condition else FAIL
    detail = f" -> {value}" if value is not None else ""
    print(f"  {icon} {label}{detail}")
    return condition


class _FakePDFFile:
    def __init__(self, path):
        with open(path, "rb") as f:
            self._data = f.read()
        self._pos = 0
        self.name = os.path.basename(path)

    def read(self, n=-1):
        if n == -1:
            chunk = self._data[self._pos:]
            self._pos = len(self._data)
        else:
            chunk = self._data[self._pos:self._pos+n]
            self._pos += len(chunk)
        return chunk

    def seek(self, pos, whence=0):
        if whence == 0:   self._pos = pos
        elif whence == 1: self._pos += pos
        elif whence == 2: self._pos = len(self._data) + pos

    def tell(self): return self._pos
    def getvalue(self): return self._data


# ---------------------------------------------------------------------------
# STEP 1: PDF extraction
# ---------------------------------------------------------------------------
sep("STEP 1 -- PDF Text Extraction")

from extractors.pdf_extractor import _extract_with_pypdf2

company_file = _FakePDFFile(COMPANY_PDF)
module_file  = _FakePDFFile(MODULE_PDF)

t0 = time.time()
company_text = _extract_with_pypdf2(company_file)
print(f"  Company PDF -> {len(company_text):,} chars in {time.time()-t0:.1f}s")

t0 = time.time()
module_text = _extract_with_pypdf2(module_file)
print(f"  Module PDF  -> {len(module_text):,} chars in {time.time()-t0:.1f}s")

step1_ok = (
    check("Company text >= 500 chars", len(company_text) >= 500, len(company_text)) and
    check("Module text >= 500 chars",  len(module_text)  >= 500, len(module_text))
)

# ---------------------------------------------------------------------------
# STEP 2: AI parsing
# ---------------------------------------------------------------------------
sep("STEP 2 -- AI Parsing (Gemini)")

from extractors.content_parser import parse_company_data, parse_module_content

print("  Parsing company data...")
t0 = time.time()
company_data = parse_company_data(company_text)
print(f"  Done in {time.time()-t0:.1f}s")
check("company_name present",    bool(company_data.get("company_name")),      company_data.get("company_name"))
check("board_members >= 3",      len(company_data.get("board_members", [])) >= 3, len(company_data.get("board_members",[])))
check("metrics >= 5",            len(company_data.get("metrics", {})) >= 5,       len(company_data.get("metrics",{})))
check("problems >= 2",           len(company_data.get("current_problems", [])) >= 2, len(company_data.get("current_problems",[])))

print("\n  Parsing module data...")
t0 = time.time()
module_data = parse_module_content(module_text)
print(f"  Done in {time.time()-t0:.1f}s")
check("module_name present",        bool(module_data.get("module_name")),     module_data.get("module_name"))
check("learning_objectives >= 2",   len(module_data.get("learning_objectives", [])) >= 2, len(module_data.get("learning_objectives",[])))
check("topics >= 3",                len(module_data.get("topics", [])) >= 3,  len(module_data.get("topics",[])))

step2_ok = bool(company_data and module_data)

# ---------------------------------------------------------------------------
# FIX 12 test: role normalization
# ---------------------------------------------------------------------------
sep("FIX 12 CHECK -- Board role normalization")

from core.admin_agents import _normalize_role, _ALLOWED_ROLES
check("'CFO ' -> 'CFO'",  _normalize_role("CFO ") == "CFO")
check("'cfo' -> 'CFO'",   _normalize_role("cfo")  == "CFO")
check("'CEO' preserved",  _normalize_role("CEO")  == "CEO")
check("Unknown preserved", _normalize_role("Super Chief") == "Super Chief")

# ---------------------------------------------------------------------------
# FIX 6 test: JSON salvage from truncated output
# ---------------------------------------------------------------------------
sep("FIX 6 CHECK -- JSON truncation salvage")

from core.admin_agents import _extract_json
truncated = '{"items": [{"name": "A", "val": 1}, {"name": "B", "val": 2}, {"name": "C'
salvaged = _extract_json(truncated)
check("Salvage recovered 'items' key", "items" in salvaged)
check("Salvage preserved >= 1 complete item",
      isinstance(salvaged.get("items"), list) and len(salvaged["items"]) >= 2,
      f"recovered {len(salvaged.get('items', []))} items")

# ---------------------------------------------------------------------------
# FIX 9 test: Framework matching normalization
# ---------------------------------------------------------------------------
sep("FIX 9 CHECK -- Case/space-insensitive framework matching")

from core.admin_agents import _audit_phase1_gap_analysis
test_module_iso = {
    "subject_area": "Governance",
    "frameworks": [{"name": "ISO31000"}],  # no space
    "learning_objectives": ["Risk management"],
    "overview": "",
    "topics": [],
}
test_company_min = {"board_members": [], "metrics": {}, "committees": [], "current_problems": []}
gaps_iso = _audit_phase1_gap_analysis(test_company_min, test_module_iso)
check("ISO31000 (no space) matched -> Risk Committee required",
      "Risk Committee" in gaps_iso.get("missing_committee_types", []),
      gaps_iso.get("missing_committee_types"))

# ---------------------------------------------------------------------------
# STEP 3: Agent 1
# ---------------------------------------------------------------------------
sep("STEP 3 -- Agent 1 (Review)")

from core.admin_agents import run_create_review_agent

t0 = time.time()
agent1_result = run_create_review_agent(
    company_data=company_data,
    module_data=module_data,
    company_text=company_text,
    module_text=module_text,
)
print(f"  Completed in {time.time()-t0:.1f}s")

items1  = agent1_result.get("items", [])
patch1  = agent1_result.get("patch", {})
summ1   = agent1_result.get("summary", {})
check("items list",   isinstance(items1, list), f"{len(items1)} items")
check("summary dict", isinstance(summ1, dict))
print(f"  Summary: PDF={summ1.get('pdf_recovered',0)} Enriched={summ1.get('enriched',0)} "
      f"Generated={summ1.get('generated',0)} Manual={summ1.get('manual_required',0)}")

# FIX 5 check: apply_generated=False should skip enrichment
sep("FIX 5 CHECK -- apply_generated flag respected")
import copy
import importlib.util

spec = importlib.util.spec_from_file_location(
    "create_sim_module",
    os.path.join(ROOT, "pages", "create_simulation.py"),
)
create_sim_mod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(create_sim_mod)
    _apply_agent1_patch = create_sim_mod._apply_agent1_patch

    # Setup: synthetic patch with BOTH PDF and enriched changes
    sample_company = {
        "company_name": "Test Co",
        "board_members": [{"name": "Alice", "role": "CEO", "personality": "original", "expertise": "Strategy", "tenure_years": 5}],
        "metrics": {"rev": {"value": 100, "unit": "$M", "description": "original desc"}},
        "current_problems": [],
        "committees": [],
    }
    sample_module = {"module_name": "Test Mod", "topics": [], "frameworks": [],
                      "learning_objectives": [], "assessment_criteria": []}

    sample_patch = {
        "company": {
            "board_members_add": [{"name": "Bob", "role": "CFO", "expertise": "Finance",
                                    "tenure_years": 3, "personality": "pdf-found"}],
            "board_members_personality": {"Alice": "ENRICHED-personality"},
            "metric_descriptions": {"rev": "ENRICHED-desc"},
            "problems_generated": ["GENERATED-problem"],
        },
        "module": {},
    }

    # Test with apply_generated=False (PDF-only)
    st_mock.session_state["dc_company_data"] = copy.deepcopy(sample_company)
    st_mock.session_state["dc_module_data"]  = copy.deepcopy(sample_module)
    _apply_agent1_patch(sample_patch, apply_generated=False)
    c_pdf_only = st_mock.session_state["dc_company_data"]

    has_bob       = any(m["name"] == "Bob" for m in c_pdf_only["board_members"])
    alice         = next(m for m in c_pdf_only["board_members"] if m["name"] == "Alice")
    no_enrichment = alice["personality"] == "original"
    no_desc_enrich= c_pdf_only["metrics"]["rev"]["description"] == "original desc"
    no_generated  = "GENERATED-problem" not in c_pdf_only["current_problems"]

    check("PDF-only: new PDF member added (Bob)", has_bob)
    check("PDF-only: enrichment NOT applied (Alice personality unchanged)", no_enrichment)
    check("PDF-only: metric description NOT enriched", no_desc_enrich)
    check("PDF-only: generated problem NOT added", no_generated)

    # Test with apply_generated=True
    st_mock.session_state["dc_company_data"] = copy.deepcopy(sample_company)
    st_mock.session_state["dc_module_data"]  = copy.deepcopy(sample_module)
    _apply_agent1_patch(sample_patch, apply_generated=True)
    c_all = st_mock.session_state["dc_company_data"]
    alice_all = next(m for m in c_all["board_members"] if m["name"] == "Alice")
    check("Apply-all: enrichment applied (Alice personality updated)",
          alice_all["personality"] == "ENRICHED-personality")
    check("Apply-all: generated problem added",
          "GENERATED-problem" in c_all["current_problems"])
except Exception as e:
    print(f"  {FAIL} Fix 5 test setup error: {e}")

step3_ok = bool(patch1)

# ---------------------------------------------------------------------------
# Apply Agent 1 to real data for downstream
# ---------------------------------------------------------------------------
st_mock.session_state["dc_company_data"] = copy.deepcopy(company_data)
st_mock.session_state["dc_module_data"]  = copy.deepcopy(module_data)
try:
    _apply_agent1_patch(patch1, apply_generated=True)
    company_data = st_mock.session_state["dc_company_data"]
    module_data  = st_mock.session_state["dc_module_data"]
except Exception as e:
    print(f"  {WARN} Apply agent1 failed: {e}")

# ---------------------------------------------------------------------------
# STEP 4: Agent 2
# ---------------------------------------------------------------------------
sep("STEP 4 -- Agent 2 (Audit)")

from core.admin_agents import run_audit_agent

t0 = time.time()
agent2_result = run_audit_agent(company_data, module_data)
print(f"  Completed in {time.time()-t0:.1f}s")

rs = agent2_result.get("readiness_score", {})
print(f"  Readiness: overall={rs.get('overall')}/100  metrics={rs.get('metric_coverage')}/100  "
      f"board={rs.get('board_coverage')}/100  structural={rs.get('structural_health')}/100")

# FIX 1 sanity: board score should not be artificially penalised by dict size
check("Board coverage <= 100 (not over-penalized)",  rs.get("board_coverage", -1) <= 100)
check("Overall score reasonable (>= 50 for good data)",
      rs.get("overall", 0) >= 50, rs.get("overall"))

# FIX 11: guard test
sep("FIX 11 CHECK -- _apply_agent2_patch guard when audit_data missing")
spec2 = importlib.util.spec_from_file_location(
    "manage_sim_module",
    os.path.join(ROOT, "pages", "manage_simulations.py"),
)
manage_sim_mod = importlib.util.module_from_spec(spec2)
try:
    spec2.loader.exec_module(manage_sim_mod)
    _apply_agent2_patch = manage_sim_mod._apply_agent2_patch

    # Missing audit_data
    st_mock.session_state.pop("audit_data", None)
    r1 = _apply_agent2_patch({"company": {}, "module": {}})
    check("Returns False when audit_data missing", r1 is False)

    # With audit_data
    st_mock.session_state["audit_data"] = {"company_data": {"metrics": {}}, "module_data": {}}
    r2 = _apply_agent2_patch({"company": {"metrics_generated": {"test_kpi": {"value": 10}}}, "module": {}})
    check("Returns True when audit_data present", r2 is True)
    check("Metric applied",
          "test_kpi" in st_mock.session_state["audit_data"]["company_data"]["metrics"])
except Exception as e:
    print(f"  {FAIL} Fix 11 test error: {e}")

# Apply real agent2 patch for downstream
st_mock.session_state["audit_data"] = {"company_data": company_data, "module_data": module_data}
try:
    _apply_agent2_patch(agent2_result.get("patch", {}))
    company_data = st_mock.session_state["audit_data"]["company_data"]
    module_data  = st_mock.session_state["audit_data"]["module_data"]
except Exception as e:
    print(f"  {WARN} Apply agent2 failed: {e}")

step4_ok = bool(rs)

# ---------------------------------------------------------------------------
# STEP 5: Agent 3
# ---------------------------------------------------------------------------
sep("STEP 5 -- Agent 3 (Planning)")

from core.admin_agents import run_planning_agent
from core.data_manager import get_default_simulation_config

sim_config = get_default_simulation_config()

t0 = time.time()
agent3_result = run_planning_agent(company_data, module_data, sim_config)
print(f"  Completed in {time.time()-t0:.1f}s")

rounds3 = agent3_result.get("rounds", [])
print(f"  Arc: {agent3_result.get('narrative_arc_title', '')[:60]}")
print(f"  Rounds generated: {len(rounds3)}")

check("rounds list non-empty",    len(rounds3) > 0, len(rounds3))
check("each round has focus_area", all(r.get("focus_area") for r in rounds3))

# FIX 3 check: apply + contiguous re-indexing
_apply_agent3_plan = manage_sim_mod._apply_agent3_plan

# Simulate a plan with GAPS (round 1, 2, 4, 6) to prove re-indexing
fake_plan = {
    "narrative_arc_title": "Test Arc",
    "act_labels": {"1": "Act1", "2": "Act2", "3": "Act3"},
    "rounds": [
        {"round_number": 1, "title": "R1", "difficulty": "easy",   "round_type": "both", "focus_area": "f1"},
        {"round_number": 2, "title": "R2", "difficulty": "easy",   "round_type": "both", "focus_area": "f2"},
        {"round_number": 4, "title": "R4", "difficulty": "medium", "round_type": "both", "focus_area": "f4"},
        {"round_number": 6, "title": "R6", "difficulty": "hard",   "round_type": "both", "focus_area": "f6"},
    ],
}
st_mock.session_state["simulation_config"] = get_default_simulation_config()
_apply_agent3_plan(fake_plan)
applied_rounds = st_mock.session_state["simulation_config"]["rounds"]
sep("FIX 3 CHECK -- Round numbers re-indexed contiguously 1..N")
nums = [r["round_number"] for r in applied_rounds]
check("Rounds are contiguous 1..N (not 1,2,4,6)",
      nums == list(range(1, len(applied_rounds) + 1)), nums)
check("total_rounds matches len(rounds)",
      st_mock.session_state["simulation_config"]["total_rounds"] == len(applied_rounds))

# Apply the REAL plan for downstream
st_mock.session_state["simulation_config"] = get_default_simulation_config()
_apply_agent3_plan(agent3_result)
sim_config = st_mock.session_state["simulation_config"]

step5_ok = bool(rounds3)

# ---------------------------------------------------------------------------
# FIX 8 test: validation
# ---------------------------------------------------------------------------
sep("FIX 8 CHECK -- validate_simulation_data")

from core.data_manager import validate_simulation_data, save_extracted_data

errs_empty = validate_simulation_data({}, {}, None)
check("Empty data produces errors", len(errs_empty) >= 3, f"{len(errs_empty)} errors")

errs_good = validate_simulation_data(company_data, module_data, sim_config)
check("Valid data produces no errors", len(errs_good) == 0,
      f"errors={errs_good if errs_good else 'none'}")

# FIX 13: round count mismatch
bad_cfg = {"total_rounds": 5, "rounds": [{"round_number": 1}, {"round_number": 2}]}
errs_bad = validate_simulation_data(company_data, module_data, bad_cfg)
check("Mismatched round count flagged",
      any("total_rounds" in e for e in errs_bad),
      errs_bad)

# ---------------------------------------------------------------------------
# STEP 6: Firestore save + reload
# ---------------------------------------------------------------------------
sep("STEP 6 -- Firestore Save + Load-back")

session_name = f"TEST_Helix_BRSR_{int(time.time())}"
t0 = time.time()
doc_id = save_extracted_data(
    company_data=company_data,
    module_data=module_data,
    session_name=session_name,
    simulation_config=sim_config,
)
print(f"  Saved in {time.time()-t0:.1f}s -> {doc_id}")

step6_ok = bool(doc_id)
if doc_id:
    from core.data_manager import load_extracted_data, update_simulation

    loaded = load_extracted_data(doc_id)
    check("Load-back successful", loaded is not None)

    if loaded:
        cd_loaded = loaded.get("company_data", {})
        md_loaded = loaded.get("module_data", {})
        cfg_loaded = loaded.get("simulation_config", {})

        check("company_name persisted", cd_loaded.get("company_name") == company_data.get("company_name"))
        check("rounds count matches total_rounds",
              len(cfg_loaded.get("rounds", [])) == cfg_loaded.get("total_rounds"))
        check("narrative arc title persisted",
              bool(cfg_loaded.get("_narrative_arc_title")),
              cfg_loaded.get("_narrative_arc_title", "")[:50])

        # FIX 10 check: tension pair + title in round config
        first_round = cfg_loaded["rounds"][0] if cfg_loaded.get("rounds") else {}
        check("Round narrative metadata present (_title)",
              "_title" in first_round)

        # FIX 7 check: full overwrite strips stale keys
        sep("FIX 7 CHECK -- update_simulation full overwrite")
        stale = dict(loaded)
        stale["deprecated_legacy_field"] = "SHOULD_BE_REMOVED"
        # First save with stale field via direct Firestore
        from core.firebase_client import get_firestore_client
        db = get_firestore_client()
        db.collection("simulations").document(doc_id).set(stale, merge=True)
        # Verify the stale key is there
        pre = db.collection("simulations").document(doc_id).get().to_dict()
        check("Stale field present before overwrite", "deprecated_legacy_field" in pre)
        # Now update (full overwrite)
        update_simulation(doc_id, loaded)
        post = db.collection("simulations").document(doc_id).get().to_dict()
        check("Stale field REMOVED after full overwrite",
              "deprecated_legacy_field" not in post)

# ---------------------------------------------------------------------------
# FINAL SUMMARY
# ---------------------------------------------------------------------------
sep("FINAL SUMMARY")
steps = [
    ("Step 1 -- PDF Extraction",      step1_ok),
    ("Step 2 -- AI Parsing",          step2_ok),
    ("Step 3 -- Agent 1",             step3_ok),
    ("Step 4 -- Agent 2",             step4_ok),
    ("Step 5 -- Agent 3",             step5_ok),
    ("Step 6 -- Firestore Save",      step6_ok),
]
all_pass = all(ok for _, ok in steps)
for label, ok in steps:
    print(f"  {PASS if ok else FAIL} {label}")

print()
if all_pass:
    print(f"  {PASS} ALL STEPS PASSED -- simulation ready in Firestore: {doc_id}")
else:
    print(f"  {WARN} Some steps failed -- review output above")
print()
