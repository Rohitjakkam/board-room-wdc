"""
Firebase Client — Shared Firestore instance, initialized once.

Supports two credential sources (tried in order):
1. JSON key file at .streamlit/firebase_key.json
2. FIREBASE_SERVICE_ACCOUNT section in .streamlit/secrets.toml
"""

import json
import logging
import os
import streamlit as st
from google.cloud import firestore
from google.oauth2 import service_account

logger = logging.getLogger(__name__)

_KEY_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".streamlit", "firebase_key.json"
)


@st.cache_resource
def get_firestore_client() -> firestore.Client | None:
    """Return a cached Firestore client, or None if credentials are missing."""
    # Option 1: JSON key file (local dev — most reliable, no escaping issues)
    if os.path.exists(_KEY_FILE):
        try:
            with open(_KEY_FILE, "r", encoding="utf-8") as f:
                creds = json.load(f)
            client = firestore.Client.from_service_account_info(creds)
            logger.info("Firestore initialized from firebase_key.json")
            return client
        except Exception as e:
            logger.error(f"Failed to load firebase_key.json: {e}")

    # Option 2: secrets.toml [FIREBASE_SERVICE_ACCOUNT] section (Streamlit Cloud)
    try:
        raw = st.secrets.get("FIREBASE_SERVICE_ACCOUNT")
        if not raw:
            logger.warning("No Firebase credentials found (no key file or secrets entry)")
            return None

        # Build creds dict with explicit str() to strip any AttrDict wrappers
        creds = {str(k): str(v) for k, v in dict(raw).items()}

        # Fix private_key newlines: TOML may give literal "\n" or real newlines
        pk = creds.get("private_key", "")
        logger.info(f"PK length={len(pk)}, has_real_newlines={'\\n' in pk and len(pk.splitlines()) > 1}")

        if "\\n" in pk:
            # Literal backslash+n found — replace with real newlines
            creds["private_key"] = pk.replace("\\n", "\n")
            logger.info("Replaced literal \\n with real newlines in private_key")

        credentials = service_account.Credentials.from_service_account_info(creds)
        client = firestore.Client(credentials=credentials, project=creds.get("project_id"))
        logger.info("Firestore initialized from secrets.toml")
        return client
    except Exception as e:
        logger.error(f"Failed to initialize Firestore: {e}", exc_info=True)
        return None
