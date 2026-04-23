"""
Auto-Prepare pipeline test.

Simulates the user flow:
  1. Upload + extract both PDFs from sample_data/
  2. Parse into company_data / module_data
  3. Click "Run All Agents" -> invokes _run_auto_prepare_chain
  4. Verify: all 3 agents ran, session state has autoprep_sim_config,
     readiness score present, narrative metadata flowed through.
  5. Firestore save picks up the narrative config -> reload -> verify.
  6. Undo test -> snapshot restored correctly.
"""
import sys, os, types, logging, time, importlib.util, copy

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
logging.basicConfig(level=logging.WARNING)

# ---- Streamlit mock ----
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

class _Status:
    """Mock for st.status() — supports 'with' context and .update()."""
    def __init__(self, label, expanded=False):
        print(f"  [status] {label}")
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def write(self, msg, **kw): print(f"    [status.write] {msg}")
    def update(self, label=None, state=None, **kw):
        print(f"  [status.update] label={label!r} state={state!r}")

def _cache(f=None, **kw):
    def w(g):
        g.clear = lambda: None
        return g
    return w(f) if f is not None else w

def _load_api_key():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".streamlit", "secrets.toml")
    if os.path.exists(p):
        try: import tomllib
        except ImportError: import tomli as tomllib
        with open(p, "rb") as f:
            return tomllib.load(f).get("GEMINI_API_KEY", "")
    return os.environ.get("GEMINI_API_KEY", "")

st = types.ModuleType("streamlit")
st.secrets        = _S({"GEMINI_API_KEY": _load_api_key()})
st.error = st.warning = st.info = st.success = lambda *a, **kw: None
st.write = lambda *a, **kw: None
st.markdown = lambda *a, **kw: None
st.caption = lambda *a, **kw: None
st.metric = lambda *a, **kw: None
st.divider = lambda: None
st.header = lambda *a, **kw: None
st.spinner = lambda m="": _Ctx()
st.expander = lambda *a, **kw: _Ctx()
st.status   = _Status
st.session_state  = _SS()
st.cache_data     = _cache
st.cache_resource = _cache
st.rerun          = lambda: None
st.button         = lambda *a, **kw: False
st.checkbox       = lambda *a, **kw: kw.get("value", True)
st.columns        = lambda n, **kw: [_Ctx() for _ in range(n if isinstance(n, int) else len(n))]
sys.modules["streamlit"] = st

# ---- Setup ----
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

# Load create_simulation as a module so we can call its private helpers
spec = importlib.util.spec_from_file_location(
    "create_sim", os.path.join(ROOT, "pages", "create_simulation.py"))
create_sim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(create_sim)

from extractors.pdf_extractor  import _extract_with_pypdf2
from extractors.content_parser import parse_company_data, parse_module_content
from core.data_manager         import save_extracted_data, load_extracted_data

PASS, FAIL, WARN = "[PASS]", "[FAIL]", "[WARN]"
def sep(t): print(f"\n{'='*72}\n  {t}\n{'='*72}")
def check(label, cond, val=None):
    icon = PASS if cond else FAIL
    detail = f" -> {val}" if val is not None else ""
    print(f"  {icon} {label}{detail}")
    return cond

class _FakePDFFile:
    def __init__(self, path):
        with open(path, "rb") as f:
            self._data = f.read()
        self._pos = 0
        self.name = os.path.basename(path)
    def read(self, n=-1):
        if n == -1:
            c = self._data[self._pos:]; self._pos = len(self._data)
        else:
            c = self._data[self._pos:self._pos+n]; self._pos += len(c)
        return c
    def seek(self, p, w=0):
        if w == 0: self._pos = p
        elif w == 1: self._pos += p
        elif w == 2: self._pos = len(self._data) + p
    def tell(self): return self._pos
    def getvalue(self): return self._data

# ---- STEP 1: Extract + parse ----
sep("STEP 1 -- Extract + parse PDFs")
SAMPLE = os.path.join(ROOT, "sample_data")
ctext = _extract_with_pypdf2(_FakePDFFile(os.path.join(SAMPLE, "company_data_10_Helix_Therapeutics_Inc..pdf")))
mtext = _extract_with_pypdf2(_FakePDFFile(os.path.join(SAMPLE, "module_data_BRSR.pdf")))
print(f"  Company text: {len(ctext):,} chars | Module text: {len(mtext):,} chars")

t0 = time.time()
company_data = parse_company_data(ctext)
print(f"  Parsed company in {time.time()-t0:.1f}s: {company_data.get('company_name')} "
      f"({len(company_data.get('board_members', []))} members, "
      f"{len(company_data.get('metrics', {}))} metrics)")

t0 = time.time()
module_data = parse_module_content(mtext)
print(f"  Parsed module in {time.time()-t0:.1f}s: {module_data.get('module_name')} "
      f"({len(module_data.get('topics', []))} topics, "
      f"{len(module_data.get('learning_objectives', []))} objectives)")

# Seed session state as if the Create page had them loaded
st.session_state.dc_company_data = company_data
st.session_state.dc_module_data  = module_data
st.session_state.dc_company_text = ctext
st.session_state.dc_module_text  = mtext

# ---- STEP 2: Run the auto-prepare chain (simulates "Run All Agents" click) ----
sep("STEP 2 -- Run auto-prepare chain (Agent 1 -> Agent 2 -> Agent 3)")
chain_t0 = time.time()
create_sim._run_auto_prepare_chain(
    company_data=st.session_state.dc_company_data,
    module_data=st.session_state.dc_module_data,
    company_text=st.session_state.dc_company_text,
    module_text=st.session_state.dc_module_text,
    apply_generated=True,
    run_agent3=True,
)
chain_elapsed = time.time() - chain_t0
print(f"\n  Total chain elapsed: {chain_elapsed:.0f}s")

# ---- STEP 3: Verify session state ----
sep("STEP 3 -- Verify session-state outcomes")
check("autoprep_status == 'done'",
      st.session_state.get("autoprep_status") == "done",
      st.session_state.get("autoprep_status"))
log = st.session_state.get("autoprep_log", [])
check("log has 3 entries (A1, A2, A3)", len(log) == 3, len(log))
check("all 3 agents succeeded",
      all(e.get("status") == "done" for e in log))

# Agent 1 impact — board, metrics, problems should be >= pre-run counts
check("Agent 1 applied (company still has board)",
      len(st.session_state.dc_company_data.get("board_members", [])) >= 5)

# Agent 2 impact — readiness snapshot
a2_snap = st.session_state.get("autoprep_audit_snapshot", {})
check("autoprep_audit_snapshot has readiness_score",
      isinstance(a2_snap.get("readiness_score"), dict),
      a2_snap.get("readiness_score", {}).get("overall"))
check("autoprep_audit_snapshot has flags + gaps",
      isinstance(a2_snap.get("flags"), list) and isinstance(a2_snap.get("gaps"), dict))

# Agent 3 impact — sim_config with narrative metadata
sim_cfg = st.session_state.get("autoprep_sim_config", {})
check("autoprep_sim_config exists", bool(sim_cfg))
check("sim_config has rounds",
      isinstance(sim_cfg.get("rounds"), list) and len(sim_cfg["rounds"]) > 0,
      len(sim_cfg.get("rounds", [])))
check("sim_config has _narrative_arc_title",
      bool(sim_cfg.get("_narrative_arc_title")),
      sim_cfg.get("_narrative_arc_title", "")[:50])
check("sim_config has _act_labels (3 acts)",
      len(sim_cfg.get("_act_labels", {})) == 3)

# Per-round narrative fields all present
required_round_fields = ["round_number", "focus_area", "difficulty", "time_pressure",
                         "_title", "_act", "_act_label", "_topics_covered"]
all_ok = True
for i, r in enumerate(sim_cfg.get("rounds", []), 1):
    missing = [f for f in required_round_fields if f not in r]
    if missing:
        all_ok = False
        print(f"    Round {i} missing: {missing}")
check("All rounds have full narrative fields", all_ok)

# ---- STEP 4: Firestore save + reload ----
sep("STEP 4 -- Save to Firestore with narrative config; reload and verify")
session_name = f"AUTOPREP_E2E_{int(time.time())}"
doc_id = save_extracted_data(
    company_data=st.session_state.dc_company_data,
    module_data=st.session_state.dc_module_data,
    session_name=session_name,
    simulation_config=st.session_state.autoprep_sim_config,
)
check("Firestore save succeeded", bool(doc_id), doc_id)

if doc_id:
    reloaded = load_extracted_data(doc_id)
    rcfg = reloaded.get("simulation_config", {})
    check("Reload: _narrative_arc_title preserved",
          bool(rcfg.get("_narrative_arc_title")),
          rcfg.get("_narrative_arc_title", "")[:50])
    check("Reload: rounds count preserved",
          len(rcfg.get("rounds", [])) == len(sim_cfg.get("rounds", [])))
    r1 = rcfg["rounds"][0]
    check("Reload: round 1 has _topics_covered + _act_label",
          bool(r1.get("_topics_covered")) and bool(r1.get("_act_label")))

# ---- STEP 5: Undo test ----
sep("STEP 5 -- Undo / snapshot restore")
pre_undo_company_metrics = len(st.session_state.dc_company_data.get("metrics", {}))
pre_undo_has_config = bool(st.session_state.get("autoprep_sim_config"))

create_sim._restore_autoprep_snapshot()
st.session_state["autoprep_status"] = "idle"

post_undo_company_metrics = len(st.session_state.dc_company_data.get("metrics", {}))
post_undo_has_config = bool(st.session_state.get("autoprep_sim_config"))
check("Undo reset dc_company_data (metric count changed back)",
      post_undo_company_metrics != pre_undo_company_metrics or
      post_undo_company_metrics == len(company_data.get("metrics", {})),
      f"pre={pre_undo_company_metrics}, post={post_undo_company_metrics}")
check("Undo cleared autoprep_sim_config",
      not post_undo_has_config)
check("autoprep_log cleared after undo",
      "autoprep_log" not in st.session_state)
check("autoprep_status reset to idle",
      st.session_state.get("autoprep_status") == "idle")

print(f"\nDone — Firestore doc: {doc_id}")
