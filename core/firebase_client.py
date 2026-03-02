"""
Firebase Client — Shared Firestore instance, initialized once.

Supports three credential sources (tried in order):
1. JSON key file at .streamlit/firebase_key.json  (local dev)
2. FIREBASE_JSON string in secrets.toml            (Streamlit Cloud — recommended)
3. [FIREBASE_SERVICE_ACCOUNT] section in secrets    (Streamlit Cloud — fallback)
"""

import json
import logging
import os
import tempfile
import streamlit as st
from google.cloud import firestore

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

    # Option 2: FIREBASE_JSON — raw JSON string (bypasses TOML section issues)
    try:
        raw_json = st.secrets.get("FIREBASE_JSON")
        if raw_json:
            creds = json.loads(raw_json)
            pk = creds.get("private_key", "")
            logger.info(
                f"FIREBASE_JSON: pk_len={len(pk)}, "
                f"lines={len(pk.splitlines())}, "
                f"starts={repr(pk[:40])}, "
                f"ends={repr(pk[-30:])}"
            )
            # Write to temp file — avoids any in-memory string encoding issues
            tmp = tempfile.NamedTemporaryFile(
                mode='w', suffix='.json', delete=False, encoding='utf-8'
            )
            json.dump(creds, tmp)
            tmp.close()
            client = firestore.Client.from_service_account_json(tmp.name)
            os.unlink(tmp.name)
            logger.info("Firestore initialized from FIREBASE_JSON secret")
            return client
    except Exception as e:
        logger.error(f"Failed to load FIREBASE_JSON: {e}", exc_info=True)

    # Option 3: [FIREBASE_SERVICE_ACCOUNT] TOML section — write to temp file
    try:
        raw = st.secrets.get("FIREBASE_SERVICE_ACCOUNT")
        if not raw:
            logger.warning("No Firebase credentials found")
            return None

        creds = {str(k): str(v) for k, v in dict(raw).items()}
        # Write to temp JSON file to let google-cloud handle parsing
        tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8'
        )
        json.dump(creds, tmp)
        tmp.close()
        client = firestore.Client.from_service_account_json(tmp.name)
        os.unlink(tmp.name)
        logger.info("Firestore initialized from secrets.toml section (via temp file)")
        return client
    except Exception as e:
        logger.error(f"Failed to initialize Firestore: {e}", exc_info=True)
        return None
