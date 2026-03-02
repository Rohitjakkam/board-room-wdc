# Metrics & Goals Logic Issues

Audit of the metrics pipeline: how decisions affect company metrics, how goals are generated/tracked, and how the final grade is calculated.

---

## Pipeline Overview

```
evaluate_decision()          →  score (0-100)
    ↓
calculate_metric_impacts()   →  LLM generates per-metric changes (hardcoded 12 keys)
    ↓
force_submitted penalty      →  positive impacts * 0.85
    ↓
apply_metric_impacts()       →  current_metrics updated
    ↓
generate_game_goals()        →  7 hardcoded metric keys → fixed delta targets
    ↓
calculate_goal_progress()    →  progress % toward targets
    ↓
calculate_overall_grade()    →  Decision Quality (50%) + Business Impact (30%) + Board Effectiveness (20%)
```

---

## Issue #1: Metric Impacts Hardcoded to 12 Keys — Ignores Actual Company Metrics

**Severity:** High
**File:** `core/simulation_engine.py:197-211`

### Problem

The LLM prompt in `calculate_metric_impacts()` always requests impacts for **12 hardcoded metric keys**, regardless of what metrics the company actually has:

```python
METRIC_IMPACTS:
- total_revenue_annual: [change] | [reason]
- ebitda: [change] | [reason]
- net_profit_margin: [change] | [reason]
- platform_uptime: [change] | [reason]
- net_promoter_score: [change] | [reason]
- customer_churn_rate_annual: [change] | [reason]
- employee_engagement_score: [change] | [reason]
- annual_attrition_rate: [change] | [reason]
- regulatory_compliance_score: [change] | [reason]
- open_high_severity_risks: [change] | [reason]
- deployment_frequency: [change] | [reason]
- revenue_growth_yoy: [change] | [reason]
```

Meanwhile, the prompt **does** pass the actual company metrics as context (`metrics_context` at line 171-174), but the response format ignores them.

### Impact

- If a company has metrics with different keys (e.g., `market_share`, `debt_to_equity`, `r_and_d_spending`), the LLM generates impacts for keys that don't exist in the company data.
- `apply_metric_impacts()` only applies changes where `key in impacts` — so impacts for non-existent keys are silently dropped, and actual company metrics are never updated.
- A company with entirely non-standard metric keys would see **zero metric movement** across all rounds.

### Suggested Fix

Build the metric key list dynamically from `company_data['metrics'].keys()` instead of hardcoding.

---

## Issue #2: Goals Only Generated from 7 Hardcoded Metrics

**Severity:** High
**File:** `core/scoring.py:69-138`

### Problem

`generate_game_goals()` checks for exactly 7 metric keys:

| Key | Goal |
|-----|------|
| `revenue_growth_yoy` | +5% |
| `net_profit_margin` | +3% (cap 25) |
| `net_promoter_score` | +10 (cap 80) |
| `customer_churn_rate_annual` | -2% (floor 3) |
| `platform_uptime` | +0.5% (cap 99.99) |
| `open_high_severity_risks` | -2 (floor 0) |
| `employee_engagement_score` | +5% (cap 95) |

If the company's extracted metrics use different keys, **zero goals are generated**. The student sees an empty goals panel, and goal progress is always 0%.

### Relationship to Issue #1

Even if Issue #1 is fixed (metric impacts use actual keys), the goals would still reference the hardcoded 7 keys. A company with `market_share` but not `net_promoter_score` would have metric movements but no goals tracking them.

### Suggested Fix

Generate goals dynamically from whatever metrics the company has, using the metric's `unit` and `priority` to determine direction and target delta.

---

## Issue #3: `force_submitted` Penalty is Asymmetric

**Severity:** Medium
**File:** `pages/simulation.py:507-508`

### Problem

When a student's timer expires and the decision is force-submitted, positive impacts are reduced by 15%:

```python
if force_submitted:
    impact_values = {k: v * 0.85 if v > 0 else v for k, v in impact_values.items()}
```

This means:
- A **good decision** submitted late: positive impacts reduced (revenue +10 → +8.5), but negative impacts unchanged
- A **bad decision** submitted late: only the negatives remain, which are **untouched** — no additional penalty

### Impact

Late submission of bad decisions has **no consequence**, while late submission of good decisions is disproportionately punished. A student who makes a terrible decision late gets the same metric damage as one who submits on time.

### Suggested Fix

Apply a symmetric penalty: amplify negative impacts by the same factor (e.g., `v * 1.15 if v < 0`), or apply a flat reduction across all impacts.

---

## Issue #4: Decision Score Drives Metric Impact Direction — Circular Logic

**Severity:** High
**File:** `core/simulation_engine.py:189, 215-216`

### Problem

The LLM prompt passes the decision quality score **into** the metric impact calculation:

```
DECISION QUALITY SCORE: {score}/100
...
Good decisions (score > 70) should generally have positive impacts.
Poor decisions (score < 50) should have negative impacts.
```

This creates a circular dependency:

```
Decision → Score (LLM #1) → Score passed to Metric Impact (LLM #2) → Impacts mirror score
```

The metric impacts become a **derivative of the score** rather than an independent analysis of the decision's real-world consequences. A decision scored 80 will almost always get positive impacts, and a decision scored 30 will almost always get negative impacts, regardless of nuance.

### Impact

- A poorly-scored decision that accidentally benefits one specific metric (e.g., cost-cutting that hurts morale but improves profit) won't show the profit improvement because the LLM is told "poor decisions should have negative impacts."
- Metric movements become predictable from the score alone, adding no new information.
- The "Business Impact" component of the final grade (30%) becomes redundant with the "Decision Quality" component (50%).

### Suggested Fix

Remove the score from the metric impact prompt. Let the LLM evaluate business impact independently based on the decision content alone.

---

## Issue #5: Goal Targets Are Fixed Deltas Regardless of Round Count

**Severity:** Medium
**File:** `core/scoring.py:69-138`

### Problem

Goal targets use hardcoded deltas (e.g., `+5%` for revenue growth, `+3%` for profit margin) regardless of the `total_rounds` parameter passed to the function:

```python
def generate_game_goals(metrics: Dict, total_rounds: int) -> List[Dict]:
    # total_rounds is accepted but NEVER USED
    if 'revenue_growth_yoy' in metrics:
        target = current + 5  # Always +5, whether 3 rounds or 10 rounds
```

### Impact

- In a **3-round** simulation: +5% revenue growth is very ambitious (needs ~1.7% per round)
- In a **10-round** simulation: +5% revenue growth is trivially easy (only ~0.5% per round)
- Students in short simulations are unfairly penalized, while students in long simulations easily achieve all goals

### Suggested Fix

Scale targets by round count: `target = current + (base_delta * total_rounds / 5)` where 5 is the reference round count.

---

## Issue #6: No Clamping for Unrealistic Single-Round Metric Swings

**Severity:** Medium
**File:** `core/simulation_engine.py:262-285`

### Problem

`apply_metric_impacts()` applies whatever change the LLM returns with only basic bounds:

```python
if unit == '%':
    new_value = max(0, min(100, new_value))
elif unit in ('count', 'employees'):
    new_value = max(0, int(new_value))
elif isinstance(new_value, float):
    new_value = max(0, round(new_value, 1))
```

There is **no maximum change per round**. The LLM could return `+50` for net_profit_margin, and it would be applied directly (clamped at 100, but a jump from 12% to 62% is absurd).

### Impact

- LLM hallucinations can cause wildly unrealistic metric swings in a single round
- A single outlier round can dominate the entire simulation's final grade
- No guardrail prevents metrics from oscillating wildly between rounds

### Suggested Fix

Add per-round change caps based on metric type:
- Percentage metrics: max |change| of 3-5% per round
- Revenue/EBITDA: max |change| of 5-10% of current value per round
- Count metrics (risks, employees): max |change| of 2-3 per round

---

## Summary Table

| # | Issue | Severity | File | Core Problem |
|---|-------|----------|------|-------------|
| 1 | Hardcoded 12 metric keys | High | `simulation_engine.py:197-211` | Ignores actual company metrics |
| 2 | Hardcoded 7 goal metrics | High | `scoring.py:69-138` | No goals if company has different keys |
| 3 | Asymmetric force penalty | Medium | `simulation.py:507-508` | Late bad decisions have no extra penalty |
| 4 | Score drives impacts | High | `simulation_engine.py:189,215-216` | Circular logic, impacts redundant with score |
| 5 | Fixed goal deltas | Medium | `scoring.py:69-138` | `total_rounds` param is ignored |
| 6 | No per-round change cap | Medium | `simulation_engine.py:262-285` | LLM can produce unrealistic swings |
