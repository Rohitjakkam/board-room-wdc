# Timer Issues

Audit of the countdown timer in `pages/simulation.py` (lines 133-253).

---

## How the Timer Currently Works

```
1. Round starts → datetime.now() stored in session_state (line 136)
2. On each Streamlit rerun → remaining_seconds calculated server-side (line 170)
3. JS countdown renders in browser → ticks every 1s, purely visual (lines 194-236)
4. JS reaches 00:00 → shows "Time's Up!", clears interval, stops (lines 213-218)
5. Next user interaction → Streamlit reruns → Python detects remaining <= 0 → sets timer_expired (line 174)
6. force_submitted flag set → warning shown (lines 251-253)
```

---

## Issue #1: No Auto-Rerun When Timer Expires

**Severity:** High
**File:** `pages/simulation.py:213-218`

### Problem

When the JS countdown reaches `00:00`, it only updates the DOM:

```javascript
if (remainingSeconds <= 0) {
    displayEl.innerHTML = "⏱️ 00:00";
    labelEl.innerHTML = "⚠️ Time's Up!";
    container.className = "timer-container timer-expired";
    clearInterval(window['timerInterval_' + timerId]);
    return;  // ← stops here, no Streamlit rerun triggered
}
```

The Python side (`timer_expired_key` at line 174) only executes on a Streamlit rerun — which only happens when the user **clicks something**. Until then:
- `timer_expired` stays `False` in session state
- `force_submitted` is never set
- The student sees "Time's Up!" visually but the app doesn't know

### Impact

A student can let the timer expire, then take unlimited extra time to craft their answer. When they eventually submit, the `force_submitted` check runs for the first time and flags it — but the actual "extra time" is invisible. The timer is decorative, not enforced.

### Suggested Fix

Trigger a Streamlit rerun from JS when the timer hits zero:

```javascript
if (remainingSeconds <= 0) {
    displayEl.innerHTML = "⏱️ 00:00";
    labelEl.innerHTML = "⚠️ Time's Up!";
    container.className = "timer-container timer-expired";
    clearInterval(window['timerInterval_' + timerId]);
    // Trigger Streamlit rerun so Python side detects expiry
    window.parent.postMessage({type: 'streamlit:setComponentValue', value: true}, '*');
    return;
}
```

Or use `st_autorefresh` (from `streamlit-autorefresh` package) to poll every 30s, though that adds a dependency.

A simpler native approach: use `st.empty()` with a placeholder that triggers `st.rerun()` via a hidden button or `st.fragment` with `run_every`.

---

## Issue #2: Student Can Take Unlimited Time After Expiry

**Severity:** High
**File:** `pages/simulation.py:248-253`

### Problem

When the timer is detected as expired (on next rerun), the code only shows a warning:

```python
if timer_expired and not decision_submitted:
    st.session_state[f"force_submitted_{state.current_round}"] = True
    st.warning("⚠️ **Time has expired!** You can still submit your decision,
                but this will be recorded as a late submission and may affect your score.")
```

The submit button (line 531) remains fully functional. The student can:
1. See the warning
2. Continue consulting board members and committees
3. Take as long as they want
4. Submit whenever ready

The only penalty is the `force_submitted` flag, which reduces positive metric impacts by 15% and amplifies negative ones by 15% — but there's **no escalating penalty** for how late the submission is.

### Impact

A student who takes 5 extra seconds gets the same penalty as one who takes 30 extra minutes. There's no incentive to submit quickly after expiry.

### Suggested Fix

Option A — **Lock consultations** after expiry: disable board/committee consultation buttons when `timer_expired` is `True`. The student can still submit but can't gather more information.

Option B — **Escalating penalty**: scale the `force_submitted` penalty by how much overtime was taken:

```python
if force_submitted:
    overtime_seconds = elapsed.total_seconds() - total_seconds
    penalty_factor = min(0.5, 0.15 + (overtime_seconds / 600) * 0.35)  # 15% → 50% over 10min
    impact_values = {
        k: v * (1 - penalty_factor) if v > 0 else v * (1 + penalty_factor) if v < 0 else 0
        for k, v in impact_values.items()
    }
```

Option C — **Auto-submit**: when the timer expires, automatically submit whatever is in the text area (even if empty). This is the strictest enforcement.

---

## Issue #3: Timer Continues Running During Deliberation Phase

**Severity:** Medium
**File:** `pages/simulation.py:133-136, 447-466`

### Problem

The round timer starts at line 136 and runs continuously:

```python
timer_key = f"round_start_time_{state.current_round}"
if timer_key not in st.session_state:
    st.session_state[timer_key] = datetime.now()
```

After the student submits a decision, the deliberation phase begins (line 461). During deliberation, the student debates with board members — this can take significant time. But the timer was already started before the student even saw the scenario.

The timer display switches to "Submitted" after evaluation (line 238-244), but the `time_taken_seconds` logged at line 653 includes **all time**: reading the scenario + consulting + typing the decision + waiting for LLM responses + entire deliberation + evaluation processing.

### Impact

- `time_taken_seconds` in analytics is inflated by LLM response times and deliberation duration, neither of which reflect student decision-making speed
- Comparing students by "time taken" is misleading

### Suggested Fix

Record `decision_submit_time` separately when the submit button is clicked:

```python
if st.button("Submit Decision", ...):
    st.session_state[f"decision_submit_time_{state.current_round}"] = datetime.now()
```

Then compute `time_taken` as `decision_submit_time - round_start_time` (excludes deliberation and evaluation).

---

## Issue #4: `time_taken_seconds` Includes LLM Processing Time

**Severity:** Low
**File:** `pages/simulation.py:649-653`

### Problem

```python
_round_start = st.session_state.get(f"round_start_time_{state.current_round}")
_time_taken = int((datetime.now() - _round_start).total_seconds()) if _round_start else None
```

`datetime.now()` is captured **after** evaluation completes (line 649 is inside the evaluation results block). The evaluation involves:
- `evaluate_decision()` — 1 LLM call (3-10 seconds)
- `calculate_metric_impacts()` — 1 LLM call (3-10 seconds)
- `display_deliberation_phase()` — multiple LLM calls for stances + debate

Total LLM time can be 20-60 seconds, all added to the student's "time taken."

### Impact

Analytics show students taking longer than they actually did. A student who decided in 2 minutes might show 3+ minutes due to LLM latency.

### Suggested Fix

Same as Issue #3 — use `decision_submit_time` instead of `datetime.now()` post-evaluation.

---

## Issue #5: Stale Timer CSS Class Until JS Takes Over

**Severity:** Low
**File:** `pages/simulation.py:180-187`

### Problem

The initial timer CSS class is set server-side based on `remaining_seconds` from the last rerun:

```python
if remaining_seconds <= 0:
    timer_class = "timer-expired"
elif time_pressure == "urgent":
    timer_class = "timer-urgent"
elif time_pressure == "normal":
    timer_class = "timer-normal"
else:
    timer_class = "timer-relaxed"
```

If a student hasn't interacted for a while (no rerun), `remaining_seconds` is stale. The HTML renders with the old class, then the JS `updateTimer()` corrects it on the first tick (within 1 second).

### Impact

Minor visual flicker — for ~1 second, the timer may show the wrong color (e.g., green when it should be red). Negligible UX issue.

### Suggested Fix

No fix needed — JS corrects within 1 second. Alternatively, always start with a neutral class and let JS set the correct one immediately.

---

## Summary Table

| # | Issue | Severity | Core Problem |
|---|-------|----------|-------------|
| 1 | No auto-rerun on expiry | High | JS timer is purely visual; Python doesn't know time expired until next click |
| 2 | Unlimited time after expiry | High | Student can still consult and take as long as they want; flat penalty |
| 3 | Timer includes deliberation | Medium | `time_taken` inflated by post-submission deliberation phase |
| 4 | Timer includes LLM latency | Low | LLM processing time (20-60s) added to student's recorded time |
| 5 | Stale CSS class on rerun | Low | 1-second visual flicker; JS corrects immediately |
