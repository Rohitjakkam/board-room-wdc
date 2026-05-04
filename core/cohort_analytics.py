"""
Cohort Analytics — Closed-feedback-loop analytics for Agent 3 (X.1).

Aggregates completed simulation runs from the activity_sessions Firestore
collection into per-round and per-simulation insights, then derives
calibration recommendations Agent 3 can apply to its next narrative plan.

Design principles:
- Deterministic: pure stats, no LLM. Recommendations are rule-based.
- Future-proof: insight schema is stable; new dimensions added as new keys,
  not by changing existing keys. Recommendations are emitted as typed dicts.
- Cold-start safe: returns None when N < MIN_SESSIONS so first-time admins
  see no spurious recommendations.
- Privacy-preserving: aggregates only; no per-student fields exposed.
"""

from __future__ import annotations

import logging
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from core.activity_tracker import get_records_by_simulation

logger = logging.getLogger(__name__)


# Minimum completed sessions before we trust the aggregate.
# Below this, recommendations would be noise.
MIN_SESSIONS_FOR_INSIGHTS = 5

# Cap how far back we look — old data goes stale (curriculum, players, prompts evolve).
DEFAULT_MAX_AGE_DAYS = 90
DEFAULT_MAX_SESSIONS = 30

# Calibration thresholds — all derived from the feedback PDF's observed patterns.
# Tweak these to make recommendations more/less aggressive.
_THRESHOLDS = {
    # Round avg score >= this AND std dev tight → too easy
    "too_easy_avg_score": 90.0,
    "too_easy_std_dev_max": 8.0,
    # Round avg score <= this → too hard
    "too_hard_avg_score": 55.0,
    # Force-submit rate above this → time pressure too tight
    "high_force_submit_rate": 0.30,
    # If avg time taken < this, players are rushing → scenario probably too thin
    "rushing_avg_seconds": 90,
    # Plateau detection: 3+ consecutive rounds within this score band → ceiling
    "plateau_band_pts": 4.0,
    "plateau_min_rounds": 3,
    # Vocabulary score below this → players aren't catching the M6 terms
    "low_vocab_score": 50,
    # Dissenter never persuaded across N rounds → adjust prompt/role
    "stuck_dissenter_min_appearances": 3,
}


def aggregate_cohort_insights(
    simulation_name: str,
    max_sessions: int = DEFAULT_MAX_SESSIONS,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
) -> Optional[Dict[str, Any]]:
    """Pull recent completed sessions for this simulation and compute insights.

    Returns None if there are fewer than MIN_SESSIONS_FOR_INSIGHTS completed
    sessions in the lookback window — prevents cold-start noise.
    """
    if not simulation_name:
        return None
    try:
        records = get_records_by_simulation(simulation_name)
    except Exception:
        logger.exception("Failed to fetch records for %s", simulation_name)
        return None
    if not records:
        return None

    # Filter to completed sessions within the lookback window
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    completed: List[Dict] = []
    for r in records:
        if r.get("status") != "completed":
            continue
        completed_at = _parse_iso(r.get("completed_at"))
        if completed_at and completed_at < cutoff:
            continue
        completed.append(r)

    if len(completed) < MIN_SESSIONS_FOR_INSIGHTS:
        return None

    # Sort newest-first, cap to max_sessions
    completed.sort(key=lambda r: r.get("completed_at") or "", reverse=True)
    cohort = completed[:max_sessions]

    # ── Per-round aggregation ─────────────────────────────────────────
    rounds_by_num: Dict[int, List[Dict]] = {}
    for sess in cohort:
        for rd in sess.get("rounds", []) or []:
            rnum = rd.get("round_number")
            if rnum is None:
                continue
            rounds_by_num.setdefault(int(rnum), []).append(rd)

    per_round: Dict[int, Dict[str, Any]] = {}
    for rnum, rounds in rounds_by_num.items():
        scores = [_safe_num(r.get("score")) for r in rounds]
        scores = [s for s in scores if s is not None]
        times = [_safe_num(r.get("time_taken_seconds")) for r in rounds]
        times = [t for t in times if t is not None and t > 0]
        force_submits = [bool(r.get("force_submitted")) for r in rounds]
        vocab_scores = [_safe_num(r.get("vocabulary_score")) for r in rounds]
        vocab_scores = [v for v in vocab_scores if v is not None]

        # Aggregate the most-frequently-missed vocabulary terms across the cohort
        missed_counter: Dict[str, int] = {}
        for r in rounds:
            for term in (r.get("vocabulary_missed") or []):
                if isinstance(term, str) and term.strip():
                    missed_counter[term.strip()] = missed_counter.get(term.strip(), 0) + 1
        # Top 5 missed terms
        top_missed = sorted(missed_counter.items(), key=lambda kv: -kv[1])[:5]

        # Track stuck dissenters: those who appear in unpersuaded list often
        unpersuaded_counter: Dict[str, int] = {}
        persuaded_counter: Dict[str, int] = {}
        for r in rounds:
            for n in (r.get("dissenters_unpersuaded") or []):
                if isinstance(n, str) and n.strip():
                    unpersuaded_counter[n.strip()] = unpersuaded_counter.get(n.strip(), 0) + 1
            for n in (r.get("dissenters_persuaded") or []):
                if isinstance(n, str) and n.strip():
                    persuaded_counter[n.strip()] = persuaded_counter.get(n.strip(), 0) + 1

        per_round[rnum] = {
            "n_attempts":         len(rounds),
            "avg_score":          round(statistics.fmean(scores), 1) if scores else None,
            "std_dev_score":      round(statistics.stdev(scores), 1) if len(scores) > 1 else 0.0,
            "min_score":          min(scores) if scores else None,
            "max_score":          max(scores) if scores else None,
            "avg_time_seconds":   round(statistics.fmean(times), 1) if times else None,
            "force_submit_rate":  round(sum(force_submits) / len(force_submits), 2) if force_submits else 0.0,
            "avg_vocab_score":    round(statistics.fmean(vocab_scores), 1) if vocab_scores else None,
            "top_missed_vocab":   top_missed,
            "unpersuaded_dissenters": unpersuaded_counter,
            "persuaded_dissenters":   persuaded_counter,
        }

    # ── Simulation-level aggregation ──────────────────────────────────
    finals = [_safe_num(s.get("final_score")) for s in cohort]
    finals = [f for f in finals if f is not None]
    abandoned_in_window = sum(1 for r in records if r.get("status") == "abandoned")
    completion_rate = (
        len(cohort) / (len(cohort) + abandoned_in_window) if (len(cohort) + abandoned_in_window) else 1.0
    )

    insights = {
        "simulation_name":       simulation_name,
        "n_sessions":            len(cohort),
        "as_of":                 datetime.now(timezone.utc).isoformat(),
        "lookback_days":         max_age_days,
        "completion_rate":       round(completion_rate, 2),
        "avg_final_score":       round(statistics.fmean(finals), 1) if finals else None,
        "median_final_score":    round(statistics.median(finals), 1) if finals else None,
        "score_std_dev":         round(statistics.stdev(finals), 1) if len(finals) > 1 else 0.0,
        "per_round":             per_round,
    }
    return insights


def derive_calibration_recommendations(insights: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Convert raw insights into typed recommendations Agent 3 can act on.

    Each recommendation is shape: {
        "type": "<recommendation type>",   # machine-readable
        "round": <int> or None,             # which round this applies to
        "severity": "high" | "medium" | "low",
        "message": "<human-readable explanation>",
        "directive": "<short imperative for the LLM prompt>",
    }
    """
    recs: List[Dict[str, Any]] = []
    if not insights or not insights.get("per_round"):
        return recs
    per_round = insights["per_round"]

    # ── Per-round signals ────────────────────────────────────────────
    for rnum, stats in sorted(per_round.items()):
        avg = stats.get("avg_score")
        std = stats.get("std_dev_score") or 0.0

        # Too easy: high avg, low variance
        if (avg is not None and avg >= _THRESHOLDS["too_easy_avg_score"]
                and std <= _THRESHOLDS["too_easy_std_dev_max"]):
            recs.append({
                "type": "too_easy",
                "round": rnum,
                "severity": "high",
                "message": (
                    f"Round {rnum}: cohort avg score {avg}/100 "
                    f"(std dev {std}) — players are not being challenged."
                ),
                "directive": (
                    f"INCREASE difficulty for Round {rnum}: add a competing constraint, "
                    f"a hidden risk, or a stakeholder objection that complicates the obvious answer."
                ),
            })

        # Too hard: low avg
        if avg is not None and avg <= _THRESHOLDS["too_hard_avg_score"]:
            recs.append({
                "type": "too_hard",
                "round": rnum,
                "severity": "high",
                "message": (
                    f"Round {rnum}: cohort avg score {avg}/100 — most players are failing."
                ),
                "directive": (
                    f"DECREASE difficulty for Round {rnum}: simplify the framing, "
                    f"give one extra piece of context up front, or relax the time pressure one notch."
                ),
            })

        # Time pressure too tight: high force-submit rate
        fsr = stats.get("force_submit_rate") or 0.0
        if fsr >= _THRESHOLDS["high_force_submit_rate"]:
            recs.append({
                "type": "time_pressure_tight",
                "round": rnum,
                "severity": "medium",
                "message": (
                    f"Round {rnum}: {int(fsr*100)}% of players time out (force_submit_rate). "
                    f"Time pressure is too tight."
                ),
                "directive": (
                    f"RELAX time_pressure for Round {rnum} (urgent → normal, normal → relaxed)."
                ),
            })

        # Players rushing through (low avg time on a non-trivial round)
        avg_time = stats.get("avg_time_seconds") or 0
        if (avg_time and avg_time < _THRESHOLDS["rushing_avg_seconds"]
                and rnum > 1):  # Round 1 may be tutorial-fast
            recs.append({
                "type": "rushing",
                "round": rnum,
                "severity": "low",
                "message": (
                    f"Round {rnum}: avg time {int(avg_time)}s — players rushing through; "
                    f"scenario may be too thin or option set too obvious."
                ),
                "directive": (
                    f"Make Round {rnum}'s focus_area more specific and consequential — "
                    f"add at least one stakeholder consideration that needs to be weighed."
                ),
            })

        # Vocabulary engagement low
        avg_vocab = stats.get("avg_vocab_score")
        if avg_vocab is not None and avg_vocab < _THRESHOLDS["low_vocab_score"]:
            top_missed = stats.get("top_missed_vocab") or []
            missed_str = ", ".join(t for t, _ in top_missed[:3]) or "(unknown)"
            recs.append({
                "type": "low_vocabulary_engagement",
                "round": rnum,
                "severity": "medium",
                "message": (
                    f"Round {rnum}: avg vocabulary score {avg_vocab}/100. "
                    f"Most-missed terms: {missed_str}."
                ),
                "directive": (
                    f"Embed terms [{missed_str}] EXPLICITLY in Round {rnum}'s focus_area "
                    f"so the scenario surfaces them and the player is prompted to engage."
                ),
            })

        # Stuck dissenters: appear in unpersuaded but rarely in persuaded
        unpers = stats.get("unpersuaded_dissenters") or {}
        pers = stats.get("persuaded_dissenters") or {}
        for name, unp_count in unpers.items():
            if unp_count < _THRESHOLDS["stuck_dissenter_min_appearances"]:
                continue
            p_count = pers.get(name, 0)
            if p_count >= unp_count:  # roughly balanced — skip
                continue
            recs.append({
                "type": "stuck_dissenter",
                "round": rnum,
                "severity": "low",
                "message": (
                    f"Round {rnum}: '{name}' opposed in {unp_count} runs but persuaded in only "
                    f"{p_count}. May be too rigid OR too central to the scenario."
                ),
                "directive": (
                    f"In Round {rnum}, give the player an explicit angle to address {name}'s "
                    f"specific expertise concern — make their objection addressable, not blanket."
                ),
            })

    # ── Cross-round signal: plateau (feedback PDF B14/B15) ───────────
    plateau = _detect_plateau(per_round)
    if plateau:
        rounds_str = ", ".join(str(r) for r in plateau["rounds"])
        recs.append({
            "type": "score_plateau",
            "round": None,
            "severity": "medium",
            "message": (
                f"Score plateau detected at ~{plateau['band']} across rounds {rounds_str}. "
                f"Rubric ceiling — players can't break through without specific structural elements."
            ),
            "directive": (
                f"For rounds {rounds_str}, embed in focus_area: 'High-scoring responses include "
                f"(a) forward-looking risk mitigation, (b) broader stakeholder/legal/regulatory context, "
                f"(c) multi-tier communication strategy.' This is the documented ceiling-breaker pattern."
            ),
        })

    return recs


def _detect_plateau(per_round: Dict[int, Dict]) -> Optional[Dict[str, Any]]:
    """Find 3+ consecutive rounds whose avg_score sits in a narrow band."""
    rounds_sorted = sorted((rn, st.get("avg_score")) for rn, st in per_round.items() if st.get("avg_score") is not None)
    if len(rounds_sorted) < _THRESHOLDS["plateau_min_rounds"]:
        return None
    band = _THRESHOLDS["plateau_band_pts"]
    for i in range(len(rounds_sorted) - _THRESHOLDS["plateau_min_rounds"] + 1):
        window = rounds_sorted[i:i + _THRESHOLDS["plateau_min_rounds"]]
        scores = [s for _, s in window]
        if max(scores) - min(scores) <= band:
            return {
                "rounds": [r for r, _ in window],
                "band":   round(statistics.fmean(scores), 1),
            }
    return None


def format_insights_for_prompt(
    insights: Dict[str, Any],
    recommendations: List[Dict[str, Any]],
    max_chars: int = 2000,
) -> str:
    """Render insights + recommendations as a compact text block for the LLM prompt."""
    if not insights:
        return ""
    lines: List[str] = []
    lines.append(
        f"OBSERVED COHORT PERFORMANCE (last {insights['n_sessions']} completed sessions, "
        f"≤{insights['lookback_days']} days):"
    )
    lines.append(
        f"  Avg final score: {insights.get('avg_final_score')}/100 "
        f"(median {insights.get('median_final_score')}, std {insights.get('score_std_dev')})  "
        f"Completion: {int((insights.get('completion_rate') or 0)*100)}%"
    )
    lines.append("")
    lines.append("Per-round cohort stats:")
    for rnum, s in sorted(insights.get("per_round", {}).items()):
        lines.append(
            f"  Round {rnum}: avg {s.get('avg_score')}/100  "
            f"force_submit {int((s.get('force_submit_rate') or 0)*100)}%  "
            f"avg_time {s.get('avg_time_seconds')}s  "
            f"vocab {s.get('avg_vocab_score')}/100"
        )
    if recommendations:
        lines.append("")
        lines.append("CALIBRATION DIRECTIVES (apply these to your generated plan):")
        for r in recommendations[:12]:
            lines.append(f"  - [{r['severity']}] {r['directive']}")
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars - 80] + "\n  ... (truncated; see analytics dashboard for full data)"
    return text


# ── helpers ──────────────────────────────────────────────────────────


def _safe_num(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_iso(s: Any) -> Optional[datetime]:
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
