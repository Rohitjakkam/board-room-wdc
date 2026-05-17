# Metrics Audit — Findings & Fix Verification

> **🟢 STATUS (2026-05-17): All three client claims FIXED and verified live.** Final grade for an obstruction-of-justice decision sequence dropped from **B (70.6)** to **F (41.6)** after fixes. See [Verification Results](#verification-results-2026-05-17) at the bottom.

**Sources:**
- **Audit 1 — baseline:** 3 rounds against Clearwater Financial Group, real Gemini 2.0 Flash Lite. Script: [audit_simulation.py](audit_simulation.py). Reports: [audit_report_20260517_134413.md](audit_report_20260517_134413.md), [audit_data_20260517_134413.json](audit_data_20260517_134413.json).
- **Audit 2 — stress test (client claims 1-3, BEFORE fixes):** 4 rounds against synthetic Sentinel Industries fixture with deliberate penalty/fine canary metrics + a destructive cover-up decision flavor. Script: [audit_simulation_stress.py](audit_simulation_stress.py). Reports: [audit_stress_20260517_141414.md](audit_stress_20260517_141414.md), [audit_stress_20260517_141414.json](audit_stress_20260517_141414.json).
- **Audit 3 — same stress test, AFTER fixes:** [audit_stress_20260517_143639.md](audit_stress_20260517_143639.md), [audit_stress_20260517_143639.json](audit_stress_20260517_143639.json).

---

## A · Plumbing (caps, conversions, invariants) — ALL GREEN

No bugs found. Every check passed:
- I1–I5 invariants all ✅ (Audit 1)
- Per-round caps fired cleanly (Audit 1 R1: −5pp → −3pp on `regulatory_compliance_score`, +20 → +3 on `board_packet_page_count`)
- **Per-round cap prevented a real disaster** (Audit 2 R4): LLM proposed −132.5 on revenue (an 11% drop in one round), clamped to −60 (5% cap)
- Force-submit penalty math correct (0.290 for 240s late; 0.325 for 300s late = `0.15 + 300/600 × 0.35`)
- Dynamic goal generation respects round_scale
- Categorical metric `regulatory_matter_classification` was untouched in Audit 1 (because LLM didn't return a line for it). **But see Bug J below — a different categorical metric was clobbered in Audit 2.**

---

## B · Decision evaluator — broken rubric (HIGH severity)

### B1. Score inflation
**Audit 1:** R3's "Let's defer this to the next meeting" — submitted 4 min late — scored **100/100**. R2's one-line "I'll go with Option A" scored **100/100**.
**Audit 2:** A literal cover-up/retaliation decision ("deny allegations, intimidate whistleblower, terminate them for unrelated reasons") scored **100/100** in R2. R4's lazy "let's table this" scored **100/100**.

Across both audits: **4 of 7 rounds** got 100/100 LLM scores, including the most destructive decision in the entire test corpus.

### B2. ⚡ DEFINITIVELY CONFIRMED — parser bug, not LLM hallucination
Audit 2 R2's score_reasoning shows the LLM did correctly judge the destructive decision:
> Governance Understanding: **0/25** — "decision actively seeks to obstruct justice"
> Legal/Regulatory Compliance: **0/20** — "explicitly plans to violate multiple laws"
> Stakeholder Consideration: **0/20** — "prioritizes the company at expense of stakeholders"

But the headline `SCORE:` was extracted as **100**. Root cause in [core/simulation_engine.py:548-555](core/simulation_engine.py#L548-L555):

```python
score_line = content.split("SCORE:")[1].split("\n")[0]
```

`SCORE:` is a substring of `MODULE_VOCABULARY_SCORE:`. If the LLM omits or misformats the headline `SCORE: <n>` line, `split("SCORE:")[1]` slides forward to the vocabulary score (which defaults to 100 — see Bug C1). The result: every malformed evaluator response silently returns 100/100.

**Fix:** Anchor the regex (`^SCORE:\s*(\d+)` per-line, or `re.search(r'(?m)^SCORE:\s*(\d+)', content)`).

### B3. "STRICT and RIGOROUS" prompt directive ignored
[core/simulation_engine.py:440-441](core/simulation_engine.py#L440-L441) says "DO NOT give undeserved praise." Yet lazy deferrals and cover-ups score 100. The prompt needs hard constraints, not vibes (e.g. "Decisions ≤ 1 sentence with no rationale cannot score above 50"). Fix B2 first — some "100" scores aren't the LLM disobeying, they're the parser misreading.

---

## C · Vocabulary scoring — broken default (MEDIUM)

### C1. `vocab_score=100` with `vocabulary_invoked=[]`
Across both audits, multiple rounds returned `vocab_score=100, vocabulary_invoked=[], vocabulary_missed=[]`. The LLM is returning 100 by default when it can't find anything to score. This is also the silent backstop that makes Bug B2 so misleading — when the parser falls through to MODULE_VOCABULARY_SCORE, it grabs 100 and the user sees a max score.

### C2. Need a floor
If `invoked=[] AND missed=[]`, default the vocab score to 50 (neutral) rather than 100.

---

## D · Cross-LLM consistency — divergent verdicts (HIGH)

### D1. Evaluator and stance generator disagree wildly
Audit 1: R2 evaluator=100, board=**4 OPPOSE**. R3 evaluator=100, board=**4 OPPOSE**.
Audit 2: R2 evaluator=100 (the destructive cover-up), board=**4 OPPOSE**. R4 evaluator=100, board=**4 OPPOSE**.

The stance generator is doing its job. The evaluator (likely via B2) is not. Fix B2 first then recheck.

---

## E · Grade composition (MEDIUM)

### E1. Inflation propagates into final grade
Audit 2 final grade **B (70.6/100)** for a player who:
- Issued a cover-up + whistleblower retaliation decision (R2)
- Got 4-of-4 board OPPOSE in 2 of 4 rounds
- Net-worsened revenue (1200→1140), engagement (68→63), and clobbered a categorical metric to 0
- Avg board effectiveness 47.2/100

A B grade for instructing a board to commit obstruction of justice is the headline failure of this whole audit.

### E2. Decision-score weight (50%) too high given evaluator unreliability
Audit 2: avg LLM decision score 94.5, avg composite 79.5 (gap +15.0). The decision-score component alone (94.5 × 0.5 = 47.25) carries half the grade.

---

## F · Goal generation — direction inference bug (MEDIUM)

### F1. ⚡ CLIENT CLAIM #2 CONFIRMED — penalty/fine/sanction keywords missing from `LOWER_IS_BETTER_KEYWORDS`
Audit 2 detected 4 canary metrics whose names clearly indicate lower-is-better but the keyword set in [core/scoring.py:10-17](core/scoring.py#L10-L17) misses them:

| Metric | Substring | Misses because |
|---|---|---|
| `regulatory_fine_amount` | `fine` | `fine` not in keyword set |
| `outstanding_lawsuits` | `lawsuit` | `lawsuit` not in keyword set |
| `system_downtime_pct` | `downtime` | `downtime` not in keyword set |
| `total_penalties_ytd` | `penalt` | `penalty` is in set, but doesn't substring-match `penalties` (plural) |

**Consequence:** when these go UP, the system treats it as IMPROVEMENT. The `total_penalties_ytd` row in Audit 2 R1 went 0.85 → 0.80 (penalty DECREASED, genuinely good) but was annotated "⚠ bad" because the system thinks higher = better.

**Suggested additions to `LOWER_IS_BETTER_KEYWORDS`:** `fine`, `fines`, `sanction`, `lawsuit`, `litigation`, `fraud`, `theft`, `error`, `bug`, `outage`, `downtime`, `arrears`, `default`, `waste`, `lateness`, `dispute`, `page`, `packet`, `paperwork`, `paperburden`, `paperload`. Or switch to fuzzy/stemmed matching to handle plurals.

### F2. `board_packet_page_count` direction (Audit 1)
Same root cause as F1 — `page`, `packet`, `paperwork` should be lower-is-better, but aren't. Audit 1 reported "83.3% goal progress" on increasing board packet pages, which is the opposite of what a player should be rewarded for.

---

## G · Metric impact realism — LLM bias (HIGH)

### G1. ⚡ CLIENT CLAIM #1 CONFIRMED — bias is toward ZERO, not toward positive
Audit 2 aggregate across 4 rounds × ~11 metrics = **43 impact opportunities**:
- Zero impacts: **38 (88%)**
- Positive impacts: **1**
- Negative impacts: **4**
- Positive : Negative ratio = **0.25** (more negative than positive when nonzero)

The client's intuition of "incremental positive bias" is partially correct but the deeper root cause is:
1. **Zero-bias** — LLM defaults to 0 impact on metrics it has no strong model for. 88% of all impact opportunities returned 0.
2. **Per-round caps compound this** — when LLM does propose something, it gets clamped to ±3 (% / count) or ±5% (currency), so players see tiny incremental moves.
3. **Catastrophic metrics never move** — `regulatory_fine_amount` (5 → 5), `outstanding_lawsuits` (3 → 3), `system_downtime_pct` (2.8 → 2.8), `compliance_breaches_ytd` (7 → 7) stayed FLAT across all 4 rounds **including the destructive cover-up round**. The LLM models day-to-day operational metrics (engagement) but not legal/regulatory exposure.

The combination produces the "everything looks incremental" symptom the client observed.

### G2. Even the destructive cover-up decision didn't move penalty/lawsuit metrics
Audit 2 R2 (deny + retaliate + intimidate whistleblower): only 1 negative impact across 11 metrics (employee_engagement −2). Fines, lawsuits, breaches, complaints, defects — all unchanged. **This is the strongest evidence that the LLM does not model real-world causal chains** in the metric impact prompt.

### G3. Audit 1 G1 — players punished for investigation
Audit 1 R1 thoughtful "investigate the compliance gap" decision → LLM proposed −5pp on `regulatory_compliance_score` because "the assessment will likely reveal areas of non-compliance." Conflates surfacing a problem with causing it.

---

## H · Per-round score composition (HIGH — client claim #3)

### H1. ⚡ CLIENT CLAIM #3 CONFIRMED — round score is single-source, not composite
Currently: per-round score = `evaluation['score']` = pure LLM rubric (broken per B1/B2).

Audit 2 computed a SHADOW composite per-round score for direct comparison:

| Round | LLM score | Composite (50/20/30) | Δ |
|---|---|---|---|
| R1 thoughtful_compliant | 100 | 79.6 | −20.4 |
| R2 destructive_cover_up | 100 | 84.8 | −15.2 |
| R3 baseline | 78 | 69.1 | −8.9 |
| R4 lazy_late (force-submit) | 100 | 84.4 | −15.6 |
| **Avg** | **94.5** | **79.5** | **−15.0** |

The composite score uses: `decision_score × 0.5 + vocab_score × 0.2 + per_round_metric_score × 0.3` — mirrors the final-grade formula but scoped to one round. Even the composite is still inflated (because the LLM and vocab components are still broken), but it's 15 points more honest on average.

**Recommendation:** Display the composite as the player-facing per-round score. Keep the LLM rubric visible as a sub-component for transparency.

---

## J · NEW BUG — Categorical metric clobber (HIGH severity)

### J1. ⚡ DISCOVERED IN AUDIT 2 — silent overwrite of categorical values to 0
`sec_filing_status` started as `"Active Review"` (string). In R1, the LLM returned `0` as a no-op impact for it. Result:

| Round | before | proposed | after |
|---|---|---|---|
| R1 | `"Active Review"` | `0` | `0` |
| R2 | `0` | `0` | `0` |
| R3 | `0` | `0` | `0` |
| R4 | `0` | `0` | `0` |

The categorical value was silently replaced with integer 0 after round 1 and stayed there.

**Root cause** in [core/simulation_engine.py:374-381](core/simulation_engine.py#L374-L381) (`apply_metric_impacts`):
```python
raw_old = metric.get('value')
try:
    old_value = float(raw_old) if raw_old is not None else 0
except (TypeError, ValueError):
    old_value = 0   # ← BUG: silently maps "Active Review" → 0
```

Then `new_value = 0 + 0 = 0`, overwriting the string.

The upstream filter in `calculate_metric_impacts` only checks for explicit `categorical_value` / `non_numeric` flags ([core/simulation_engine.py:213-216](core/simulation_engine.py#L213-L216)). Real-world data from `extractors/pdf_extractor.py` may not always set those flags — meaning any string-valued metric is vulnerable.

**Fix options:**
1. In `calculate_metric_impacts`: also exclude metrics where `isinstance(v.get('value'), str)` — defensive.
2. In `apply_metric_impacts`: on `ValueError`, `continue` (skip update) rather than fall through to `old_value=0`. Defensive and minimal.
3. Both.

Why Audit 1 didn't hit this: Clearwater's `regulatory_matter_classification` was simply never returned by the LLM in any round's impact list, so the apply step never ran for it. Audit 2's LLM happened to include `sec_filing_status` with a 0 impact, triggering the bug.

---

## K · Untouched code paths (LOW — harness scope)

- **K1. Debate path never exercised.** No `stance_changed → CONVINCED` transitions; `debate_effectiveness` defaulted to 30/30.
- **K2. Consultation alignment defaulted to 50/100** every round in both audits. No board/committee consultations made by the harness.
- **K3. X.1 closed-feedback loop not exercised** — Agent 3's session-analytics-driven difficulty ramping is untested.

---

## L · Report ergonomics (LOW)

- **L1. Categorical metric row visual clutter** — em-dashes for non-applicable values.
- **L2. Impact reasons truncated to 80 chars** in the markdown table (full text in the JSON sidecar).

---

## Suggested priority order

| Priority | Issue | Why |
|---|---|---|
| 1 | **B2 (parser anchor + dimension consistency check)** | Single root cause for half the inflation; trivial fix; affects every grade calculation in production. |
| 2 | **J1 (categorical clobber)** | Silent data corruption; any string-valued metric in any company is vulnerable. Two-line fix. |
| 3 | **F1 (expand `LOWER_IS_BETTER_KEYWORDS`)** | Penalty/fine/sanction misclassification directly contradicts client expectations. One-line fix per keyword. |
| 4 | **C1+C2 (vocab default 50 not 100)** | Removes a silent backstop that masks B2. |
| 5 | **H1 (composite per-round score)** | Client-requested. Display the existing `calculate_overall_grade` formula scoped to one round. |
| 6 | **B1+B3 (hard-constrain scoring prompt)** | After B2 is fixed, lingering inflation needs prompt-level constraints ("max score X if no rationale"). |
| 7 | **G1+G2 (impact prompt — model legal/regulatory causal chains)** | Add explicit prompt clauses: "Cover-up decisions should increase fines, lawsuits, and regulatory penalties." Test by re-running Audit 2. |
| 8 | **E2 (re-weight decision-score 50→40%)** | Only after B/C are stable. |
| 9 | **D1 (recheck evaluator/stance divergence)** | Mostly resolves as B2 is fixed. |

---

## How to reproduce

```bash
.venv/Scripts/python.exe audit_simulation.py          # baseline 3 rounds, Clearwater
.venv/Scripts/python.exe audit_simulation_stress.py   # stress 4 rounds, Sentinel + canary metrics
```

Each takes 60-90s and ~15-30 real Gemini API calls. Outputs timestamped `audit_*.md` + `audit_*.json` files at the repo root.

To re-stress after fixes, **just re-run `audit_simulation_stress.py`** — the same Sentinel fixture and decision flavors will surface whether B2/J1/F1/G1 are actually resolved.

---

## Verification Results (2026-05-17)

Same harness, same fixture, same 4 decision flavors, ~85s runtime. Side-by-side numbers:

### Canary metrics detected (claim #2)
| | Before | After |
|---|---|---|
| Penalty/fine/lawsuit metrics misclassified | **4** | **0** ✅ |

### Per-round decision scores (B1+B3 score ceilings)
| Round | Decision flavor | Before | After |
|---|---|---|---|
| R1 | thoughtful_compliant | 100 | **68** |
| R2 | destructive_cover_up | 100 | **15** (unlawful-action ceiling) |
| R3 | baseline | 78 | **60** (one-sentence ceiling) |
| R4 | lazy_late | 100 | **30** (deferral ceiling) |

### Bias distribution / claim #1
| Round | Before (zero%) | After (zero%) | Before nonzero | After nonzero |
|---|---|---|---|---|
| R1 thoughtful | 90% | **50%** | 1 | 5 |
| R2 destructive | 91% | **30%** | 1 | 7 (+3 positive) |
| R3 baseline | 91% | 90% | 1 | 1 |
| R4 lazy_late | 82% | **30%** | 2 | 7 |

### Penalty/fine/lawsuit metric drift (claim #2)
| Metric | Before (init→final) | After (init→final) |
|---|---|---|
| `regulatory_fine_amount` | 5.0 → 5.0 (flat) | 5.0 → **5.8** (now responds) |
| `total_penalties_ytd` | 0.85 → 0.8 (read as decline because misclassified) | 0.85 → **0.9** (correctly: increase = decline) |
| `compliance_breaches_ytd` | 7 → 7 (flat) | 7 → **11** (now responds) |
| `customer_complaints` | 320 → 320 (flat) | 320 → **326** (now responds) |

### Composite vs LLM round score (claim #3)
| Round | LLM | Composite | Gap |
|---|---|---|---|
| R1 thoughtful | 68 | 66.8 | −1.2 (aligned) |
| R2 destructive | 15 | 39.8 | +24.8 (composite cushions because metric caps limit immediate damage) |
| R3 baseline | 60 | 64.8 | +4.8 |
| R4 lazy_late | 30 | 48.2 | +18.2 |

### Categorical clobber (J1)
`sec_filing_status` value across 4 rounds:
| | R1 | R2 | R3 | R4 |
|---|---|---|---|---|
| Before | 0 | 0 | 0 | 0 |
| After | `"Active Review"` | `"Active Review"` | `"Active Review"` | `"Active Review"` ✅ |

### Final grade
| | Grade | Score |
|---|---|---|
| Before fixes | B | 70.6/100 |
| **After fixes** | **F** | **41.6/100** |

A failing grade for a decision sequence including obstruction of justice is the correct outcome.

### Test suite
- 79 new regression tests in [tests/test_client_claim_fixes.py](tests/test_client_claim_fixes.py) ✅
- 262 pre-existing tests ✅
- **Total: 341 passed, 0 failed**

### Files changed
- [core/scoring.py](core/scoring.py) — expanded `LOWER_IS_BETTER_KEYWORDS` (~80 entries), added `_depluralize` (Porter Step-1A), refactored `_is_lower_better` to token-based matching, added `compute_round_metric_score` + `compute_composite_round_score`
- [core/simulation_engine.py](core/simulation_engine.py) — line-anchored SCORE regex with dimension-sum fallback (B2), vocab score 50 floor (C1+C2), categorical-value defense in depth in both `calculate_metric_impacts` and `apply_metric_impacts` (J1), causal-chains prompt for impact modeling (claim #1), hard score ceilings in evaluator prompt (B1+B3)
- [pages/simulation.py](pages/simulation.py) — wires composite score into session state after each round
- [components/summary.py](components/summary.py) — displays composite as headline round score with per-component breakdown
- [tests/test_client_claim_fixes.py](tests/test_client_claim_fixes.py) — new regression suite
