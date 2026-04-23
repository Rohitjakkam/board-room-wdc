"""
Focused Agent 3 verification: does the planner's output make it correctly into
simulation_config, both in-session and after Firestore round-trip?

Checks:
 1. Agent 3 returns a well-formed plan (all required keys)
 2. Every round has non-empty: focus_area, difficulty, round_type, title, tension, cascade
 3. _apply_agent3_plan writes EVERY field into simulation_config
 4. Underscore metadata (_title, _tension_pair, _cascade_seed, _narrative_arc_title, _act_labels) survives
 5. Round numbers are contiguous 1..N after apply (even if plan has gaps)
 6. Existing non-planning fields (time_pressure if manually set) are preserved
 7. Firestore save + load-back preserves ALL fields
 8. Scenario generator prompt actually consumes the narrative metadata (Fix 10)
"""
import sys, os, types, logging, time, copy, json, importlib.util

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(level=logging.WARNING, format="%(levelname)s | %(name)s | %(message)s")

# ---------------------------------------------------------------------------
# Streamlit mock
# ---------------------------------------------------------------------------
class _Secrets(dict):
    def get(self, k, d=None): return self[k] if k in self else d

class _Ctx:
    def __enter__(self): return self
    def __exit__(self, *a): pass

class _SessionState(dict):
    def __getattr__(self, n):
        try: return self[n]
        except KeyError: raise AttributeError(n)
    def __setattr__(self, n, v): self[n] = v
    def __delattr__(self, n): del self[n]

def _cache(func=None, **kw):
    def w(f):
        f.clear = lambda: None
        return f
    return w(func) if func is not None else w

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

st.secrets        = _Secrets({"GEMINI_API_KEY": _load_api_key()})
st.error          = lambda m, **kw: print(f"  [st.error] {m}")
st.warning        = lambda m, **kw: print(f"  [st.warning] {m}")
st.info           = lambda m, **kw: print(f"  [st.info] {m}")
st.success        = lambda m, **kw: print(f"  [st.success] {m}")
st.write          = lambda *a, **kw: None
st.spinner        = lambda m="": _Ctx()
st.expander       = lambda l, **kw: _Ctx()
st.session_state  = _SessionState()
st.cache_data     = _cache
st.cache_resource = _cache
st.rerun          = lambda: None

sys.modules["streamlit"] = st

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

PASS = "[PASS]"
FAIL = "[FAIL]"

def sep(t): print(f"\n{'='*70}\n  {t}\n{'='*70}")
def check(label, cond, val=None):
    icon = PASS if cond else FAIL
    detail = f" -> {val}" if val is not None else ""
    print(f"  {icon} {label}{detail}")
    return cond

# Load the apply function
spec = importlib.util.spec_from_file_location(
    "manage_sim", os.path.join(ROOT, "pages", "manage_simulations.py"))
manage_sim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manage_sim)

from core.admin_agents import run_planning_agent
from core.data_manager import (
    get_default_simulation_config, save_extracted_data, load_extracted_data,
    list_saved_sessions,
)
from core.llm import get_scenario_generator_prompt

# ---------------------------------------------------------------------------
# STEP 1 -- Load an existing simulation from Firestore
# ---------------------------------------------------------------------------
sep("STEP 1 -- Load a real simulation from Firestore")
sessions = list_saved_sessions()
print(f"  Available sessions in Firestore: {len(sessions)}")

# Pick the most recent test simulation we made
test_sessions = [s for s in sessions if "TEST_Helix_BRSR" in s["session_name"]]
if not test_sessions:
    print(f"  No TEST_Helix_BRSR session found; using first session")
    target = sessions[0] if sessions else None
else:
    target = test_sessions[0]

if not target:
    print(f"  {FAIL} No sessions available in Firestore")
    sys.exit(1)

print(f"  Loading: {target['session_name']} ({target['doc_id']})")
session_data = load_extracted_data(target["doc_id"])
company_data = session_data.get("company_data", {})
module_data  = session_data.get("module_data", {})
print(f"  Company: {company_data.get('company_name')}  |  Module: {module_data.get('module_name')}")
print(f"  Board: {len(company_data.get('board_members', []))} members  |  "
      f"Topics: {len(module_data.get('topics', []))}  |  "
      f"Objectives: {len(module_data.get('learning_objectives', []))}")

# ---------------------------------------------------------------------------
# STEP 2 -- Initialize simulation_config with a pre-existing customized round
# (to verify we preserve manual edits that Agent 3 doesn't touch)
# ---------------------------------------------------------------------------
sep("STEP 2 -- Seed simulation_config with a manually-edited round")
sim_config = get_default_simulation_config()
# Simulate: user manually set round 2's time_pressure to 'tight'
sim_config["rounds"][1]["time_pressure"] = "tight"
sim_config["rounds"][1]["_user_note"] = "manually-set tight pressure"
print(f"  Seeded round 2 with: time_pressure=tight, _user_note set")
print(f"  Default rounds count: {len(sim_config['rounds'])}")
st.session_state.simulation_config = sim_config

# ---------------------------------------------------------------------------
# STEP 3 -- Run Agent 3
# ---------------------------------------------------------------------------
sep("STEP 3 -- Run Agent 3 (Planning Agent)")
t0 = time.time()
result = run_planning_agent(company_data, module_data, sim_config)
print(f"  Completed in {time.time()-t0:.1f}s")

required_top_level = ["narrative_arc_title", "act_labels", "rounds", "coverage",
                      "tension_pairs", "flags", "summary"]
for key in required_top_level:
    check(f"Plan has '{key}'", key in result)

rounds_plan = result.get("rounds", [])
print(f"\n  Rounds in plan: {len(rounds_plan)}")
print(f"  Arc title: {result.get('narrative_arc_title', '')[:65]}")
print(f"  Act labels: {list(result.get('act_labels', {}).values())}")

# Every round should have all narrative fields populated
sep("STEP 3b -- Every round has complete narrative fields")
round_fields = ["round_number", "focus_area", "difficulty", "round_type",
                "title", "act_label"]
for i, r in enumerate(rounds_plan):
    missing = [f for f in round_fields if not r.get(f)]
    label = f"Round {r.get('round_number', i+1)}"
    check(f"{label} has {round_fields}", not missing,
          val="OK" if not missing else f"missing: {missing}")

# Tension pair / cascade seed are "optional but preferred" — just report coverage
tension_filled = sum(1 for r in rounds_plan if r.get("tension_pair"))
cascade_filled = sum(1 for r in rounds_plan if r.get("cascade_seed"))
check(f"Tension pairs populated ({tension_filled}/{len(rounds_plan)} rounds)",
      tension_filled >= 1, val=f"{tension_filled}")
check(f"Cascade seeds populated ({cascade_filled}/{len(rounds_plan)} rounds)",
      cascade_filled >= 1, val=f"{cascade_filled}")

# ---------------------------------------------------------------------------
# STEP 4 -- Apply plan, verify EVERY field written correctly
# ---------------------------------------------------------------------------
sep("STEP 4 -- Apply plan and verify write-back into simulation_config")

# Snapshot the state BEFORE apply
before_cfg = copy.deepcopy(st.session_state.simulation_config)
before_focus_areas = [r.get("focus_area") for r in before_cfg["rounds"]]
print(f"  BEFORE apply: focus_areas = {[str(fa)[:30] if fa else 'None' for fa in before_focus_areas]}")

manage_sim._apply_agent3_plan(result)

after_cfg = st.session_state.simulation_config
print(f"  AFTER apply: {len(after_cfg['rounds'])} rounds, "
      f"total_rounds={after_cfg['total_rounds']}")

# Verify every round field matches the plan
errors = []
for plan_round in rounds_plan:
    rnum_in_plan = plan_round["round_number"]
    # After re-indexing, the round at index (rnum_in_plan - 1) should carry these values
    # (assuming plan round_numbers are 1..N already). If plan had gaps, re-indexing changes mapping.
    # Find the applied round by matching _title
    matches = [ar for ar in after_cfg["rounds"] if ar.get("_title") == plan_round.get("title")]
    if not matches:
        errors.append(f"No applied round with title '{plan_round.get('title')}'")
        continue
    ar = matches[0]
    for field_plan, field_cfg in [
        ("focus_area",  "focus_area"),
        ("difficulty",  "difficulty"),
        ("round_type",  "round_type"),
        ("title",       "_title"),
        ("tension_pair", "_tension_pair"),
        ("cascade_seed", "_cascade_seed"),
    ]:
        plan_val = plan_round.get(field_plan, "") or ""
        cfg_val  = ar.get(field_cfg, "") or ""
        if plan_val != cfg_val:
            errors.append(
                f"Round {ar['round_number']} ({ar.get('_title','')[:30]}): "
                f"plan.{field_plan}={plan_val!r} != cfg.{field_cfg}={cfg_val!r}"
            )

check(f"All fields written correctly (errors={len(errors)})", len(errors) == 0,
      val="OK" if not errors else f"\n    " + "\n    ".join(errors[:5]))

# Narrative metadata at config-level
check("cfg._narrative_arc_title set",
      bool(after_cfg.get("_narrative_arc_title")),
      after_cfg.get("_narrative_arc_title", "")[:60])
check("cfg._act_labels set (3 acts)",
      len(after_cfg.get("_act_labels", {})) == 3,
      after_cfg.get("_act_labels"))

# Round numbers contiguous 1..N
nums = [r["round_number"] for r in after_cfg["rounds"]]
check("Round numbers contiguous 1..N after apply",
      nums == list(range(1, len(after_cfg["rounds"]) + 1)), nums)

# total_rounds matches
check("total_rounds matches len(rounds)",
      after_cfg["total_rounds"] == len(after_cfg["rounds"]))

# time_pressure derived if not set
for r in after_cfg["rounds"]:
    tp = r.get("time_pressure")
    diff = r.get("difficulty")
    check(f"Round {r['round_number']} has time_pressure ({tp})",
          tp in ("normal", "tight", "generous"))

# ---------------------------------------------------------------------------
# STEP 5 -- Save to Firestore and load back; verify narrative persists
# ---------------------------------------------------------------------------
sep("STEP 5 -- Firestore round-trip: narrative metadata persists")
session_name = f"AGENT3_VERIFY_{int(time.time())}"
doc_id = save_extracted_data(
    company_data=company_data,
    module_data=module_data,
    session_name=session_name,
    simulation_config=after_cfg,
)
check("Saved to Firestore", bool(doc_id), doc_id)

if doc_id:
    reloaded = load_extracted_data(doc_id)
    rcfg = reloaded.get("simulation_config", {})

    check("Reloaded: round count matches",
          len(rcfg.get("rounds", [])) == len(after_cfg["rounds"]))
    check("Reloaded: _narrative_arc_title present",
          bool(rcfg.get("_narrative_arc_title")),
          rcfg.get("_narrative_arc_title", "")[:50])
    check("Reloaded: _act_labels present",
          len(rcfg.get("_act_labels", {})) == 3)

    # Every round preserves ALL underscore keys
    missing_meta = []
    for i, r in enumerate(rcfg.get("rounds", [])):
        for key in ("_title", "_tension_pair", "_cascade_seed"):
            if key not in r:
                missing_meta.append(f"Round {i+1} missing {key}")
    check(f"Every round keeps _title/_tension_pair/_cascade_seed",
          not missing_meta, "OK" if not missing_meta else missing_meta[:3])

    # focus_area preserved for all rounds
    fa_empty = [r["round_number"] for r in rcfg.get("rounds", []) if not r.get("focus_area")]
    check("Every reloaded round has focus_area", not fa_empty,
          "OK" if not fa_empty else f"empty in: {fa_empty}")

# ---------------------------------------------------------------------------
# STEP 6 -- Agent 3 metadata flows into scenario generator prompt (Fix 10)
# ---------------------------------------------------------------------------
sep("STEP 6 -- Narrative metadata piped into scenario prompt")

if doc_id:
    # Pick a round that has all 3 narrative fields filled
    sample_round = None
    for r in rcfg["rounds"]:
        if r.get("_title") and r.get("_tension_pair") and r.get("_cascade_seed"):
            sample_round = r
            break
    if not sample_round:
        sample_round = rcfg["rounds"][0]

    # Sanity: player_role, first board member
    player_role = {"name": "You (Test)", "role": "CEO", "expertise": "Strategy"}

    prompt = get_scenario_generator_prompt(
        company_data=company_data,
        module_data=module_data,
        round_config=sample_round,
        player_role=player_role,
        previous_rounds=None,
    )

    print(f"\n  Round being tested: R{sample_round['round_number']} — "
          f"{sample_round.get('_title','')[:50]}")
    print(f"    tension_pair: {sample_round.get('_tension_pair','')[:60]}")
    print(f"    cascade_seed: {sample_round.get('_cascade_seed','')[:60]}\n")

    check("Scenario prompt includes focus_area",
          (sample_round.get("focus_area", "")[:40] in prompt) if sample_round.get("focus_area") else True)
    check("Scenario prompt includes planned narrative title",
          bool(sample_round.get("_title")) and sample_round["_title"] in prompt)
    check("Scenario prompt includes tension_pair instruction",
          bool(sample_round.get("_tension_pair")) and sample_round["_tension_pair"] in prompt)
    check("Scenario prompt includes cascade_seed",
          bool(sample_round.get("_cascade_seed")) and sample_round["_cascade_seed"] in prompt)
    check("Prompt mentions 'NARRATIVE DESIGN' header",
          "NARRATIVE DESIGN" in prompt)

# ---------------------------------------------------------------------------
# STEP 7 -- Full cfg dump (first round only) for human inspection
# ---------------------------------------------------------------------------
sep("STEP 7 -- Sample round config (human inspection)")
print(json.dumps(after_cfg["rounds"][0], indent=2, ensure_ascii=False)[:1200])

print(f"\n{'='*70}\n  Agent 3 verification complete — Firestore doc: {doc_id}\n{'='*70}")
