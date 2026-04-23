"""
Diff audit for Agent 1 and Agent 2 — same methodology as Agent 3:
list every key the agent writes to its patch vs every key the apply
function reads back into session state.

Known suspect: `assessment_criteria_add` is in the Phase 1 LLM schema
but may not be wired into _apply_module_recovery_delta.
"""
import sys, os, types, logging, time, importlib.util, copy, json

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

from core.admin_agents import run_create_review_agent, run_audit_agent
from core.data_manager import list_saved_sessions, load_extracted_data

spec_cs = importlib.util.spec_from_file_location(
    "create_sim", os.path.join(ROOT, "pages", "create_simulation.py"))
create_sim = importlib.util.module_from_spec(spec_cs)
spec_cs.loader.exec_module(create_sim)

spec_ms = importlib.util.spec_from_file_location(
    "manage_sim", os.path.join(ROOT, "pages", "manage_simulations.py"))
manage_sim = importlib.util.module_from_spec(spec_ms)
spec_ms.loader.exec_module(manage_sim)

PASS, FAIL, WARN = "[PASS]", "[FAIL]", "[WARN]"
def sep(t): print(f"\n{'='*72}\n  {t}\n{'='*72}")
def check(label, cond, val=None):
    icon = PASS if cond else FAIL
    detail = f" -> {val}" if val is not None else ""
    print(f"  {icon} {label}{detail}")
    return cond

# ============================================================
# Canonical catalogs (authoritative lists from the agent code)
# ============================================================
AGENT1_COMPANY_PATCH_KEYS = {
    # Phase 1 (PDF recovery)
    "board_members_add",
    "board_members_update",
    "metrics_add",
    "metrics_update",
    "committees_add",
    "committees_member_corrections",
    "problems_add",
    "initial_scenario",
    "company_overview_append",
    # Phase 2/3 (enrichment + generation)
    "board_members_personality",
    "board_members_expertise",
    "board_members_tenure",
    "problems_expanded",
    "problems_generated",
    "committee_purposes",
    "committee_members_assigned",
    "committees_generated",
    "board_members_generated",
    "metric_descriptions",
    "metric_units",
}

AGENT1_MODULE_PATCH_KEYS = {
    # Phase 1 (PDF recovery)
    "topics_add",
    "key_terms_add",
    "frameworks_add",
    "learning_objectives_add",
    "assessment_criteria_add",
    "topics_formula_update",
    # Phase 2/3 (enrichment)
    "topic_principles",
    "topic_examples",
    "framework_components",
    "learning_objectives",
    "assessment_criteria",
    "module_overview",
}

AGENT2_COMPANY_PATCH_KEYS = {
    "metrics_generated",
    "metrics_fixed_values",
    "board_members_generated",
    "committees_generated",
    "problems_generated",
}

# ============================================================
# STEP A: Extract keys that _apply_agent1_patch actually reads from the patch
# ============================================================
sep("AGENT 1 -- which patch keys does _apply_agent1_patch read?")

import re

def _extract_function_body(src: str, fname: str) -> str:
    """Extract everything between `def fname(` and the NEXT top-level `def ` line."""
    # Find 'def fname(' at column 0
    start_match = re.search(rf"^def {fname}\(", src, re.MULTILINE)
    if not start_match:
        return ""
    start = start_match.end()
    # Find the next top-level def after this one
    rest = src[start:]
    end_match = re.search(r"\n(?=def |\Z)", rest)
    if end_match:
        return rest[:end_match.start()]
    return rest

apply_src = open(os.path.join(ROOT, "pages", "create_simulation.py"), encoding="utf-8").read()
apply_body = _extract_function_body(apply_src, "_apply_agent1_patch")

# Heuristic: "cp.get(\"KEY\"" and "mp.get(\"KEY\"" patterns, plus cp[\"KEY\"]
cp_keys = set(re.findall(r'cp\.get\("([^"]+)"', apply_body) +
              re.findall(r'cp\["([^"]+)"\]', apply_body) +
              re.findall(r'cp\.get\(\'([^\']+)\'', apply_body))
mp_keys = set(re.findall(r'mp\.get\("([^"]+)"', apply_body) +
              re.findall(r'mp\["([^"]+)"\]', apply_body) +
              re.findall(r'mp\.get\(\'([^\']+)\'', apply_body))

print(f"  _apply_agent1_patch reads {len(cp_keys)} company keys, {len(mp_keys)} module keys\n")

print("  Company keys in apply vs patch catalog:")
for k in sorted(AGENT1_COMPANY_PATCH_KEYS | cp_keys):
    in_patch = k in AGENT1_COMPANY_PATCH_KEYS
    in_apply = k in cp_keys
    if in_patch and in_apply:
        icon = "[KEPT]   "
    elif in_patch and not in_apply:
        icon = "[DROPPED]"
    else:
        icon = "[EXTRA]  "
    print(f"    {icon} {k}")

print("\n  Module keys in apply vs patch catalog:")
for k in sorted(AGENT1_MODULE_PATCH_KEYS | mp_keys):
    in_patch = k in AGENT1_MODULE_PATCH_KEYS
    in_apply = k in mp_keys
    if in_patch and in_apply:
        icon = "[KEPT]   "
    elif in_patch and not in_apply:
        icon = "[DROPPED]"
    else:
        icon = "[EXTRA]  "
    print(f"    {icon} {k}")

dropped_c = AGENT1_COMPANY_PATCH_KEYS - cp_keys
dropped_m = AGENT1_MODULE_PATCH_KEYS - mp_keys
print(f"\n  Summary: {len(dropped_c)} company keys dropped, {len(dropped_m)} module keys dropped")

# ============================================================
# STEP B: Check if LLM schema asks for any keys that are NEVER
#         added to the patch by the admin_agents code
# ============================================================
sep("AGENT 1 -- keys in LLM schema but NEVER written to patch")

agents_src = open(os.path.join(ROOT, "core", "admin_agents.py"), encoding="utf-8").read()

# Find JSON schema keys mentioned inside _build_*_prompt functions
# Scan for lines like: "KEY_NAME": [ or "KEY_NAME": {
schema_keys_with_context = re.findall(
    r'"([a-z_]+)":\s*(?:\[|\{|")',
    agents_src,
)
# Filter to keys that look like patch keys (have _add, _update, _generated, etc.)
suspect_schema_keys = set(k for k in schema_keys_with_context
                          if any(suffix in k for suffix in
                                  ("_add", "_update", "_generated", "_expanded",
                                   "_descriptions", "_units", "_components",
                                   "_principles", "_examples", "_personality",
                                   "_expertise", "_tenure", "_purposes", "_members",
                                   "_corrections", "_candidate", "_supplement",
                                   "_append", "_formula_update")))

# Find keys that are consumed in _apply_*_delta (so written to patch)
written_to_patch = set(re.findall(
    r'patch\[\"(?:company|module)\"\](?:\.setdefault\(\"|\[\")([a-z_]+)\"',
    agents_src,
))

print(f"  LLM schema suspect keys: {len(suspect_schema_keys)}")
print(f"  Keys actually written to patch: {len(written_to_patch)}")

orphan_schema_keys = suspect_schema_keys - written_to_patch
# Some of these will be keys that are READ from delta, translated, and stored under a
# different patch key — e.g. initial_scenario_candidate -> initial_scenario
# So we also check if they appear in `delta.get("KEY"` form
delta_get_keys = set(re.findall(r'delta\.get\("([a-z_]+)"', agents_src))

print("\n  Keys in LLM schema but NOT directly written to patch:")
for k in sorted(orphan_schema_keys):
    in_delta_get = k in delta_get_keys
    # translate_candidates: _candidate/_supplement get translated
    is_translated = any(k.endswith(suffix) for suffix in ("_candidate", "_supplement"))
    if is_translated:
        print(f"    [TRANSLATED] {k}  (mapped to another patch key)")
    elif in_delta_get:
        print(f"    [READ-ONLY]  {k}  (consumed from delta but NOT put in patch)")
    else:
        print(f"    [ORPHAN]     {k}  (NEVER consumed anywhere)")

# ============================================================
# STEP C: Agent 2 — patch keys vs apply handler
# ============================================================
sep("AGENT 2 -- which patch keys does _apply_agent2_patch read?")

apply2_src = open(os.path.join(ROOT, "pages", "manage_simulations.py"), encoding="utf-8").read()
apply2_body = _extract_function_body(apply2_src, "_apply_agent2_patch")
cp2_keys = set(re.findall(r'company_patch\.get\("([^"]+)"', apply2_body))
mp2_keys = set(re.findall(r'module_patch\.get\("([^"]+)"',  apply2_body))

print(f"  _apply_agent2_patch reads {len(cp2_keys)} company keys, {len(mp2_keys)} module keys\n")

print("  Company keys in apply vs patch catalog:")
for k in sorted(AGENT2_COMPANY_PATCH_KEYS | cp2_keys):
    in_patch = k in AGENT2_COMPANY_PATCH_KEYS
    in_apply = k in cp2_keys
    if in_patch and in_apply:
        icon = "[KEPT]   "
    elif in_patch and not in_apply:
        icon = "[DROPPED]"
    else:
        icon = "[EXTRA]  "
    print(f"    {icon} {k}")

dropped2 = AGENT2_COMPANY_PATCH_KEYS - cp2_keys
print(f"\n  Summary: {len(dropped2)} Agent 2 company keys dropped")

# ============================================================
# STEP D: Live Agent 2 run — are top-level result keys (readiness/gaps/flags/summary) persisted?
# ============================================================
sep("AGENT 2 -- are top-level result keys (readiness/gaps/flags) persisted anywhere?")

# readiness_score is rendered in UI; gaps/flags/summary too. But is any of it
# saved to session state or Firestore after apply?
# Search audit_data-related writes
audit_writes = set(re.findall(
    r'st\.session_state\.audit_data(?:\.setdefault\(|\[")([a-zA-Z_]+)"?\]?',
    apply2_src,
))
agent2_top_level = {"readiness_score", "gaps", "flags", "summary", "items"}
print(f"  audit_data keys written anywhere: {audit_writes}")
print(f"  Agent 2 result top-level keys: {sorted(agent2_top_level)}")

persisted = agent2_top_level & audit_writes
not_persisted = agent2_top_level - audit_writes
print(f"\n  Top-level keys that ARE persisted in audit_data: {persisted}")
print(f"  Top-level keys NOT persisted (re-run to see): {not_persisted}")
# NOTE: Agent 2 is a point-in-time audit — readiness becomes stale as data changes,
# so not persisting is BY DESIGN. No action needed unless UI really needs them.

# ============================================================
# STEP E: Live Agent 1 run — prove _apply_agent1_patch preserves all keys on a real patch
# ============================================================
sep("AGENT 1 -- live run to prove end-to-end preservation")

sessions = list_saved_sessions()
target = sessions[0]
session_data = load_extracted_data(target["doc_id"])
company_data = copy.deepcopy(session_data["company_data"])
module_data  = copy.deepcopy(session_data["module_data"])

# Force some gaps so Agent 1 has work to do
# Blank a few board member personalities to trigger enrichment
for i, m in enumerate(company_data.get("board_members", [])[:3]):
    m["personality"] = "Professional and analytical"  # default, triggers enrichment
# Blank an initial_scenario
company_data["initial_scenario"] = ""
# Blank one topic's principles
if module_data.get("topics"):
    module_data["topics"][0]["key_principles"] = []
    module_data["topics"][0]["examples"] = []

print(f"  Running Agent 1 (this takes ~60-90s)...")
t0 = time.time()
result = run_create_review_agent(company_data, module_data, company_text="", module_text="")
print(f"  Completed in {time.time()-t0:.1f}s")

patch = result.get("patch", {})
cp = patch.get("company", {})
mp = patch.get("module", {})

print(f"\n  Agent 1 populated {len(cp)} company patch keys, {len(mp)} module patch keys")
print(f"  Company keys produced: {sorted(cp.keys())}")
print(f"  Module keys produced:  {sorted(mp.keys())}")

# Snapshot before apply
st.session_state["dc_company_data"] = copy.deepcopy(company_data)
st.session_state["dc_module_data"]  = copy.deepcopy(module_data)
before_c = copy.deepcopy(st.session_state["dc_company_data"])
before_m = copy.deepcopy(st.session_state["dc_module_data"])

# Apply
create_sim._apply_agent1_patch(patch, apply_generated=True)
after_c = st.session_state["dc_company_data"]
after_m = st.session_state["dc_module_data"]

# For each key the patch has, verify its effect is visible in after_c/after_m
print("\n  Verifying each populated patch key had an observable effect:")
for key in sorted(cp.keys()):
    val = cp[key]
    if key == "board_members_add":
        new_names = {m["name"] for m in val}
        before_names = {m.get("name") for m in before_c.get("board_members", [])}
        after_names = {m.get("name") for m in after_c.get("board_members", [])}
        diff = after_names - before_names
        check(f"company.{key}: +{len(new_names)} names added",
              new_names.issubset(diff) if new_names else True,
              f"added={diff & new_names}")
    elif key == "board_members_personality":
        all_applied = True
        for name, expected in val.items():
            for m in after_c.get("board_members", []):
                if m.get("name") == name:
                    if m.get("personality") != expected:
                        all_applied = False
                    break
        check(f"company.{key}: all {len(val)} applied", all_applied)
    elif key == "metrics_add":
        added = set(val.keys()) - set(before_c.get("metrics", {}).keys())
        check(f"company.{key}: {len(added)} new metrics",
              len(added) == len(val))
    elif key == "metric_descriptions":
        ok = all(
            after_c.get("metrics", {}).get(k, {}).get("description") == v
            for k, v in val.items() if k in after_c.get("metrics", {})
        )
        check(f"company.{key}: {len(val)} descriptions applied", ok)
    elif key == "problems_generated":
        check(f"company.{key}: {len(val)} problems appended",
              all(p in after_c.get("current_problems", []) for p in val))
    elif key == "problems_expanded":
        any_changed = any(v in after_c.get("current_problems", []) for v in val.values())
        check(f"company.{key}: at least 1 expansion visible", any_changed or not val)
    elif key == "initial_scenario":
        check(f"company.{key}: scenario updated",
              after_c.get("initial_scenario") == val)
    elif key == "committee_purposes":
        ok = all(
            any(c.get("name") == name and c.get("purpose") == purpose
                for c in after_c.get("committees", []))
            for name, purpose in val.items()
        )
        check(f"company.{key}: {len(val)} purposes applied", ok)
    elif key == "committees_generated":
        added_names = {c.get("name") for c in val}
        after_names = {c.get("name") for c in after_c.get("committees", [])}
        check(f"company.{key}: {len(added_names)} committees added",
              added_names.issubset(after_names))
    elif key == "board_members_generated":
        added_names = {m.get("name") for m in val}
        after_names = {m.get("name") for m in after_c.get("board_members", [])}
        check(f"company.{key}: {len(added_names)} members added",
              added_names.issubset(after_names))
    else:
        print(f"    [INFO]   company.{key}: present in patch (effect not spot-checked)")

for key in sorted(mp.keys()):
    val = mp[key]
    if key == "topic_principles":
        ok = True
        for topic_name, principles in val.items():
            for t in after_m.get("topics", []):
                if t.get("name") == topic_name:
                    if t.get("key_principles") != principles:
                        ok = False
                    break
        check(f"module.{key}: {len(val)} topics updated", ok)
    elif key == "topic_examples":
        ok = True
        for topic_name, examples in val.items():
            for t in after_m.get("topics", []):
                if t.get("name") == topic_name:
                    if t.get("examples") != examples:
                        ok = False
                    break
        check(f"module.{key}: {len(val)} topics updated", ok)
    elif key == "topics_add":
        added_names = {t.get("name") for t in val}
        after_names = {t.get("name") for t in after_m.get("topics", [])}
        check(f"module.{key}: {len(added_names)} added",
              added_names.issubset(after_names))
    elif key == "learning_objectives_add":
        check(f"module.{key}: {len(val)} appended",
              all(lo in after_m.get("learning_objectives", []) for lo in val))
    elif key == "module_overview":
        check(f"module.{key}: overview updated",
              after_m.get("overview") == val)
    else:
        print(f"    [INFO]   module.{key}: present in patch (effect not spot-checked)")

# ============================================================
# STEP F: Agent 2 — verify audit snapshot persists through save + load
# ============================================================
sep("AGENT 2 -- live run: audit snapshot (readiness/gaps/flags/summary) persists")

from core.data_manager import save_extracted_data
from core.data_manager import update_simulation

# Run Agent 2
print(f"  Running Agent 2...")
t0 = time.time()
agent2_result = run_audit_agent(after_c, after_m)
print(f"  Completed in {time.time()-t0:.1f}s")

# Set up audit_data and apply with context
st.session_state.audit_data = {"company_data": copy.deepcopy(after_c), "module_data": copy.deepcopy(after_m)}
ok = manage_sim._apply_agent2_patch(agent2_result["patch"], audit_context=agent2_result)
check("Agent 2 apply returned True", ok)
check("audit_data._audit_snapshot present after apply",
      "_audit_snapshot" in st.session_state.audit_data)

snap = st.session_state.audit_data.get("_audit_snapshot", {})
check("snapshot has readiness_score", isinstance(snap.get("readiness_score"), dict))
check("snapshot has gaps",            isinstance(snap.get("gaps"), dict))
check("snapshot has flags",           isinstance(snap.get("flags"), list))
check("snapshot has summary",         isinstance(snap.get("summary"), dict))
check("snapshot has timestamp",       bool(snap.get("timestamp")))
check("snapshot has items_applied count", "items_applied" in snap)

from datetime import datetime
from core.firebase_client import get_firestore_client

sname = f"A1_A2_DIFF_{int(time.time())}"

doc_id = save_extracted_data(
    company_data=st.session_state.audit_data["company_data"],
    module_data=st.session_state.audit_data["module_data"],
    session_name=sname,
    simulation_config={"total_rounds": 1, "rounds": [{"round_number": 1, "round_type": "both", "difficulty": "easy", "focus_area": "test", "time_pressure": "normal"}]},
)
check("Saved to Firestore", bool(doc_id), doc_id)

# Now merge in the audit_snapshot via Firestore direct (simulates what the full data_manager path should do)
if doc_id:
    db = get_firestore_client()
    ref = db.collection("simulations").document(doc_id)
    existing = ref.get().to_dict()
    existing["_audit_snapshot"] = st.session_state.audit_data["_audit_snapshot"]
    ref.set(existing)

    # Load back and verify
    from core.data_manager import load_extracted_data
    reloaded = load_extracted_data(doc_id)
    check("Reloaded: _audit_snapshot present",
          "_audit_snapshot" in reloaded)
    rs_snap = reloaded.get("_audit_snapshot", {})
    check("Reloaded: readiness_score.overall preserved",
          isinstance(rs_snap.get("readiness_score", {}).get("overall"), int),
          rs_snap.get("readiness_score", {}).get("overall"))
    check("Reloaded: flags count preserved",
          len(rs_snap.get("flags", [])) == len(agent2_result["flags"]),
          f"{len(rs_snap.get('flags', []))} flags")

print("\nDone.")
