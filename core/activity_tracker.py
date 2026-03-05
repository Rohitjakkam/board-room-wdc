"""
Activity Tracker — Persists student simulation activity to Firebase Firestore.

Each simulation attempt is stored as an independent Firestore document.
No shared files, no corruption risk, fully concurrent-safe.
"""

import logging
import uuid
from datetime import datetime, timezone

from google.cloud.firestore_v1 import ArrayUnion, Increment
from google.cloud.firestore_v1.base_query import FieldFilter
from google.cloud import firestore

from core.firebase_client import get_firestore_client

logger = logging.getLogger(__name__)

_COLLECTION = "activity_sessions"


def _get_collection():
    """Return Firestore collection reference, or None if unavailable."""
    db = get_firestore_client()
    if db is None:
        return None
    return db.collection(_COLLECTION)


# ── Public API ──────────────────────────────────────────────────


def start_session(
    student_name: str,
    student_id: str,
    simulation_name: str,
    module_name: str,
    player_role: str,
    total_rounds: int,
) -> str:
    """Create a new activity session. Returns session_id."""
    session_id = str(uuid.uuid4())[:12]

    # Count prior attempts for this student + simulation
    attempt_number = 1
    try:
        col = _get_collection()
        if col:
            prior = (
                col.where(filter=FieldFilter("student_name", "==", student_name))
                   .where(filter=FieldFilter("student_id", "==", student_id))
                   .where(filter=FieldFilter("simulation_name", "==", simulation_name))
            )
            attempt_number = sum(1 for _ in prior.stream()) + 1
    except Exception:
        logger.warning("Failed to count prior attempts, defaulting to 1")

    record = {
        "session_id": session_id,
        "student_name": student_name,
        "student_id": student_id,
        "simulation_name": simulation_name,
        "module_name": module_name,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "status": "in_progress",
        "player_role": player_role,
        "total_rounds": total_rounds,
        "attempt_number": attempt_number,
        "rounds_completed": 0,
        "rounds": [],
        "final_score": None,
        "grade": None,
        "grade_description": None,
        "metrics_improved": None,
        "metrics_declined": None,
    }

    try:
        col = _get_collection()
        if col is None:
            logger.warning("Firestore unavailable — session not tracked")
            return session_id
        col.document(session_id).set(record)
    except Exception as e:
        logger.error(f"Failed to start activity session: {e}")

    return session_id


def log_round(
    session_id: str,
    round_number: int,
    decision: str,
    score: float,
    board_consultations: int = 0,
    committee_consultations: int = 0,
    force_submitted: bool = False,
    time_taken_seconds: int | None = None,
    strengths: list[str] | None = None,
    improvements: list[str] | None = None,
):
    """Append a completed round to the session document."""
    round_data = {
        "round_number": round_number,
        "decision": (decision or "")[:500],
        "score": score,
        "board_consultations": board_consultations,
        "committee_consultations": committee_consultations,
        "force_submitted": force_submitted,
        "time_taken_seconds": time_taken_seconds,
        "strengths": (strengths or [])[:3],
        "improvements": (improvements or [])[:3],
    }

    try:
        col = _get_collection()
        if col is None:
            return
        doc_ref = col.document(session_id)

        # Remove any existing entry for this round, then append new one
        doc = doc_ref.get()
        if not doc.exists:
            logger.warning(f"Session {session_id} not found in Firestore")
            return

        existing_rounds = doc.to_dict().get("rounds", [])
        updated_rounds = [r for r in existing_rounds if r.get("round_number") != round_number]
        updated_rounds.append(round_data)
        updated_rounds.sort(key=lambda r: r["round_number"])

        doc_ref.update({
            "rounds": updated_rounds,
            "rounds_completed": len(updated_rounds),
        })
    except Exception as e:
        logger.error(f"Failed to log round {round_number}: {e}")


def complete_session(
    session_id: str,
    final_score: float,
    grade: str,
    grade_description: str = "",
    metrics_improved: int = 0,
    metrics_declined: int = 0,
):
    """Mark a session as completed with final results."""
    try:
        col = _get_collection()
        if col is None:
            return
        col.document(session_id).update({
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "status": "completed",
            "final_score": final_score,
            "grade": grade,
            "grade_description": grade_description,
            "metrics_improved": metrics_improved,
            "metrics_declined": metrics_declined,
        })
    except Exception as e:
        logger.error(f"Failed to complete session: {e}")


def get_all_records() -> list[dict]:
    """Return all activity records (for admin dashboard)."""
    try:
        col = _get_collection()
        if col is None:
            return []
        return [doc.to_dict() for doc in col.stream()]
    except Exception as e:
        logger.error(f"Failed to read activity records: {e}")
        return []


def get_records_by_simulation(simulation_name: str) -> list[dict]:
    """Filter records for a specific simulation (server-side query)."""
    try:
        col = _get_collection()
        if col is None:
            return []
        query = col.where(filter=FieldFilter("simulation_name", "==", simulation_name))
        return [doc.to_dict() for doc in query.stream()]
    except Exception as e:
        logger.error(f"Failed to query by simulation: {e}")
        return []


def get_records_by_student(student_id: str) -> list[dict]:
    """Filter records for a specific student (server-side query)."""
    try:
        col = _get_collection()
        if col is None:
            return []
        query = col.where(filter=FieldFilter("student_id", "==", student_id))
        return [doc.to_dict() for doc in query.stream()]
    except Exception as e:
        logger.error(f"Failed to query by student: {e}")
        return []


def save_progress(session_id: str, progress: dict) -> bool:
    """Save simulation progress checkpoint to Firestore for crash recovery."""
    try:
        col = _get_collection()
        if col is None:
            return False
        col.document(session_id).update({"progress": progress})
        return True
    except Exception as e:
        logger.error(f"Failed to save progress for {session_id}: {e}")
        return False


def find_resumable_session(student_name: str, student_id: str, simulation_name: str) -> dict | None:
    """Find an in-progress session with saved progress for this student + simulation.

    Returns the session dict (including 'session_id' and 'progress') or None.
    """
    try:
        col = _get_collection()
        if col is None:
            return None
        query = (
            col.where(filter=FieldFilter("student_name", "==", student_name))
               .where(filter=FieldFilter("student_id", "==", student_id))
               .where(filter=FieldFilter("simulation_name", "==", simulation_name))
               .where(filter=FieldFilter("status", "==", "in_progress"))
        )
        best = None
        for doc in query.stream():
            data = doc.to_dict()
            if data.get("progress"):
                if best is None or data.get("started_at", "") > best.get("started_at", ""):
                    best = data
        return best
    except Exception as e:
        logger.error(f"Failed to find resumable session: {e}")
        return None


def clear_progress(session_id: str) -> bool:
    """Clear saved progress from a session document."""
    try:
        col = _get_collection()
        if col is None:
            return False
        col.document(session_id).update({"progress": firestore.DELETE_FIELD})
        return True
    except Exception as e:
        logger.error(f"Failed to clear progress for {session_id}: {e}")
        return False


def delete_all_records():
    """Clear all activity logs (batch delete)."""
    try:
        col = _get_collection()
        if col is None:
            return
        batch = get_firestore_client().batch()
        count = 0
        for doc in col.stream():
            batch.delete(doc.reference)
            count += 1
            if count % 400 == 0:  # Firestore batch limit is 500
                batch.commit()
                batch = get_firestore_client().batch()
        if count % 400 != 0:
            batch.commit()
    except Exception as e:
        logger.error(f"Failed to delete activity records: {e}")
