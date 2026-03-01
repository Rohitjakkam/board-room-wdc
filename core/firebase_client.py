"""
Firebase Client — Shared Firestore instance, initialized once from secrets.
"""

import json
import logging
import streamlit as st
from google.cloud import firestore

logger = logging.getLogger(__name__)


@st.cache_resource
def get_firestore_client() -> firestore.Client | None:
    """Return a cached Firestore client, or None if credentials are missing."""
    try:
        raw = st.secrets.get("FIREBASE_SERVICE_ACCOUNT", "")
        if not raw:
            logger.warning("FIREBASE_SERVICE_ACCOUNT not set in secrets.toml")
            return None

        creds = json.loads(raw) if isinstance(raw, str) else dict(raw)
        return firestore.Client.from_service_account_info(creds)
    except Exception as e:
        logger.error(f"Failed to initialize Firestore: {e}")
        return None
