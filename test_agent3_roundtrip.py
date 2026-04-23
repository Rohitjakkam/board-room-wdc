"""
Final Agent 3 round-trip validation:
Agent 3 output -> apply -> Firestore save -> Firestore load -> confirm
every field survives, including topics_covered and scenario-prompt piping.
"""
import sys, os, types, logging, time, importlib.util, json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
logging.basicConfig(level=logging.WARNING)

class _S(dict):
    def get(self, k, d=None): return self[k] if k in self else d
class _Ctx:
    def __enter__(self): return self
    def __exit__(self, *a): pass
class _SS(dict):
    def __getattr__(self, n):
        try: return self[n]
        except KeyError: raise AttributeError(n)
    def __setattr__(self, n, v): self[n] = v
    def __delattr__(self, n): del self[n]
def _cache(f=None, **kw):
    def w(g):
        g.clear = lambda: None
        return g
    return w(f) if f is not None else w

st = types.ModuleType("streamlit")
def _load_api_key():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".streamlit", "secrets.toml")
    if os.path.exists(path):
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib
        with open(path, "rb") as f:
            return tomllib.load(f).get("GEMINI_API_KEY", "")
    return os.environ.get("GEMINI_API_KEY", "")

st.secrets        = _S({"GEMINI_API_KEY": _load_api_key()})
st.error = st.warning = st.info = st.success = lambda *a, **kw: None
st.write = lambda *a, **kw: None
st.spinner = lambda m="": _Ctx()
st.expander = lambda *a, **kw: _Ctx()
st.session_state  = _SS()
st.cache_data     = _cache
st.cache_resource = _cache
st.rerun          = lambda: None
sys.modules["streamlit"] = st

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from core.admin_agents  import run_planning_agent
from core.data_manager  import (
    get_default_simulation_config, save_extracted_data, load_extracted_data,
    list_saved_sessions,
)
from core.llm           import get_scenario_generator_prompt

spec = importlib.util.spec_from_file_location(
    "manage_sim", os.path.join(ROOT, "pages", "manage_simulations.py"))
manage_sim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manage_sim)

PASS, FAIL = "[PASS]", "[FAIL]"
def check(label, cond, val=None):
    icon = PASS if cond else FAIL
    detail = f" -> {val}" if val is not None else ""
    print(f"  {icon} {label}{detail}")
    return cond

# ===== Load real data =====
sessions = list_saved_sessions()
target = sessions[0]
session_data = load_extracted_data(target["doc_id"])
company_data = session_data["company_data"]
module_data  = session_data["module_data"]

# ===== Run Agent 3 =====
print(f"Running Agent 3 on {target['session_name']}…")
t0 = time.time()
result = run_planning_agent(company_data, module_data, get_default_simulation_config())
print(f"Done in {time.time()-t0:.1f}s")

# ===== Apply =====
st.session_state.simulation_config = get_default_simulation_config()
manage_sim._apply_agent3_plan(result)
cfg = st.session_state.simulation_config

# ===== Save to Firestore =====
session_name = f"A3_ROUNDTRIP_{int(time.time())}"
doc_id = save_extracted_data(
    company_data=company_data, module_data=module_data,
    session_name=session_name, simulation_config=cfg,
)
print(f"\nSaved: {doc_id}\n")

# ===== Reload from Firestore =====
reloaded = load_extracted_data(doc_id)
rcfg = reloaded["simulation_config"]

print("="*70)
print("  TOP-LEVEL — all 6 narrative keys survive Firestore round-trip")
print("="*70)
check("_narrative_arc_title", bool(rcfg.get("_narrative_arc_title")), rcfg.get("_narrative_arc_title", "")[:50])
check("_act_labels (3 acts)", len(rcfg.get("_act_labels", {})) == 3)
check("_coverage present",    isinstance(rcfg.get("_coverage"), dict) and "covered" in rcfg["_coverage"])
check("_tension_pairs list",  isinstance(rcfg.get("_tension_pairs"), list))
check("_planning_flags list", isinstance(rcfg.get("_planning_flags"), list))
check("_planning_summary dict", isinstance(rcfg.get("_planning_summary"), dict))

print("\n"+"="*70)
print("  PER-ROUND — all 11 fields survive")
print("="*70)
required = ["round_number", "round_type", "difficulty", "focus_area", "time_pressure",
            "_title", "_tension_pair", "_cascade_seed",
            "_act", "_act_label", "_topics_covered"]
for i, r in enumerate(rcfg["rounds"], 1):
    missing = [f for f in required if f not in r]
    check(f"Round {i} has all 11 fields", not missing, "OK" if not missing else f"missing: {missing}")

# Sample values from round 1 for visual check
r1 = rcfg["rounds"][0]
print(f"\n  Round 1 sample:")
print(f"    _act: {r1['_act']} | _act_label: {r1['_act_label']}")
print(f"    _title: {r1['_title'][:60]}")
print(f"    _topics_covered ({len(r1['_topics_covered'])}): {r1['_topics_covered'][:3]}")

print("\n"+"="*70)
print("  SCENARIO PROMPT — new fields piped through")
print("="*70)
# Find a round with ALL fields populated
sample = None
for r in rcfg["rounds"]:
    if r.get("_act_label") and r.get("_topics_covered") and r.get("_title"):
        sample = r
        break
sample = sample or rcfg["rounds"][0]

prompt = get_scenario_generator_prompt(
    company_data=company_data, module_data=module_data,
    round_config=sample,
    player_role={"name": "Test", "role": "CEO", "expertise": "Strategy"},
)
check("Prompt includes act_label ('Narrative act:')",
      sample.get("_act_label") and sample["_act_label"] in prompt and "Narrative act:" in prompt)
check("Prompt includes _title",
      sample["_title"] in prompt)
check("Prompt includes topics_covered list ('Module topics this round must exercise:')",
      "Module topics this round must exercise:" in prompt)
if sample["_topics_covered"]:
    first_topic = sample["_topics_covered"][0]
    check(f"Prompt cites first topic: {first_topic[:40]}",
          first_topic in prompt)

# Count planning metadata that the scenario prompt uses
narrative_section_start = prompt.find("NARRATIVE DESIGN")
narrative_section_end   = prompt.find("\n\n", narrative_section_start) if narrative_section_start > 0 else -1
if narrative_section_start > 0:
    nd_block = prompt[narrative_section_start:narrative_section_end] if narrative_section_end > 0 else prompt[narrative_section_start:]
    print(f"\n  NARRATIVE DESIGN block in prompt ({len(nd_block)} chars):")
    print("  " + nd_block.replace("\n", "\n  ")[:600])

print(f"\nDone — Firestore doc: {doc_id}")
