"""
Diff audit: what Agent 3 GENERATES vs what ends up in simulation_config.
Lists every field that is silently dropped during apply.
"""
import sys, os, types, logging, time, copy, json, importlib.util

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

from core.admin_agents import run_planning_agent
from core.data_manager import get_default_simulation_config, list_saved_sessions, load_extracted_data

spec = importlib.util.spec_from_file_location(
    "manage_sim", os.path.join(ROOT, "pages", "manage_simulations.py"))
manage_sim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manage_sim)


def dump_keys(label, obj, indent=0):
    pad = "  " * indent
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)) and v:
                print(f"{pad}{k}: {type(v).__name__}({len(v)})")
            else:
                val = str(v)[:55] + ("..." if len(str(v)) > 55 else "")
                print(f"{pad}{k}: {val!r}")


# Load a real session
sessions = list_saved_sessions()
target = sessions[0]
session_data = load_extracted_data(target["doc_id"])
company_data = session_data["company_data"]
module_data  = session_data["module_data"]
print(f"Loaded: {target['session_name']}\n")

# Run Agent 3
sim_config = get_default_simulation_config()
print("Running Agent 3 (this takes ~40s)…")
t0 = time.time()
result = run_planning_agent(company_data, module_data, sim_config)
print(f"Done in {time.time()-t0:.1f}s\n")

# =======================================================================
print("="*72)
print("  WHAT AGENT 3 PRODUCED — top-level keys + a sample round")
print("="*72)
print("\nTop-level keys in Agent 3 result:")
for k, v in result.items():
    if isinstance(v, (dict, list)) and v:
        print(f"  - {k}: {type(v).__name__}({len(v)})")
    else:
        print(f"  - {k}: {type(v).__name__} = {str(v)[:50]}")

print("\nSample round[0] fields:")
sample = result["rounds"][0]
for k, v in sample.items():
    val = str(v)[:60] + ("…" if len(str(v)) > 60 else "")
    print(f"  - {k}: {val}")

# =======================================================================
print("\n" + "="*72)
print("  NOW APPLY AND SEE WHAT SURVIVES")
print("="*72)
st.session_state.simulation_config = get_default_simulation_config()
manage_sim._apply_agent3_plan(result)
cfg_after = st.session_state.simulation_config

print("\nTop-level cfg keys after apply:")
for k, v in cfg_after.items():
    if isinstance(v, (dict, list)) and v:
        print(f"  - {k}: {type(v).__name__}({len(v)})")
    else:
        val = str(v)[:50]
        print(f"  - {k}: {val}")

print("\nSample cfg.rounds[0] fields after apply:")
for k, v in cfg_after["rounds"][0].items():
    val = str(v)[:60] + ("…" if len(str(v)) > 60 else "")
    print(f"  - {k}: {val}")

# =======================================================================
print("\n" + "="*72)
print("  GAP ANALYSIS — fields Agent 3 returns that are DROPPED")
print("="*72)

# Top-level
agent3_top = set(result.keys())
cfg_top    = set(cfg_after.keys())
missing_top = agent3_top - cfg_top - {"rounds"}  # rounds merged separately
top_alias = {
    "narrative_arc_title": "_narrative_arc_title",
    "act_labels":          "_act_labels",
    "coverage":            "_coverage",
    "tension_pairs":       "_tension_pairs",
    "flags":               "_planning_flags",
    "summary":             "_planning_summary",
}
print("\nTop-level keys in Agent 3 result (mapped to underscore aliases where applicable):")
for k in sorted(agent3_top):
    eq = top_alias.get(k, k)
    if eq in cfg_top or k == "rounds":
        print(f"  [KEPT]    {k:25s} (stored as {eq})")
    else:
        print(f"  [DROPPED] {k:25s}  <-- LOST")

# Per-round
agent3_round = set(result["rounds"][0].keys())
cfg_round    = set(cfg_after["rounds"][0].keys())
round_alias = {
    "title":          "_title",
    "tension_pair":   "_tension_pair",
    "cascade_seed":   "_cascade_seed",
    "act":            "_act",
    "act_label":      "_act_label",
    "topics_covered": "_topics_covered",
}
print("\nPer-round fields (mapped to underscore aliases where applicable):")
for k in sorted(agent3_round):
    eq = round_alias.get(k, k)
    if eq in cfg_round:
        print(f"  [KEPT]    {k:20s} (stored as {eq})")
    else:
        print(f"  [DROPPED] {k:20s}  <-- LOST")

print()
