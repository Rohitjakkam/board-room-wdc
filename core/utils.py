"""
Utility functions for safe data conversion and validation.
"""

import re
import hashlib
from typing import Dict, List, Optional


def safe_index(options: List[str], value: str, default: int = 0) -> int:
    """Safely get index of value in options list, returning default if not found."""
    try:
        return options.index(value)
    except (ValueError, TypeError):
        return default


def safe_key(prefix: str, value: str) -> str:
    """Generate a safe Streamlit widget key from potentially problematic strings."""
    safe_value = hashlib.md5(str(value).encode()).hexdigest()[:8]
    return f"{prefix}_{safe_value}"


def ensure_dict(data: Optional[Dict], default_keys: List[str] = None) -> Dict:
    """Ensure data is a dict with required keys initialized."""
    if data is None:
        data = {}
    if default_keys:
        for key in default_keys:
            if key not in data:
                data[key] = {} if key.endswith('_data') or key == 'metrics' or key == 'key_terms' else []
    return data


def ensure_list(data) -> List:
    """Ensure data is a list."""
    if data is None:
        return []
    if isinstance(data, list):
        return data
    return []


def safe_float(value, default: float = 0.0) -> float:
    """Safely convert a value to float, returning default if conversion fails.

    Handles cases where data may contain non-numeric strings like '12-18', 'N/A', etc.
    """
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return default
        try:
            return float(value)
        except ValueError:
            match = re.search(r'-?\d+\.?\d*', value)
            if match:
                try:
                    return float(match.group())
                except ValueError:
                    pass
            return default
    return default


def safe_int(value, default: int = 0) -> int:
    """Safely convert a value to int, returning default if conversion fails.

    Handles cases where data may contain non-numeric strings like '12-18', 'N/A', etc.
    """
    if value is None:
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return default
        try:
            return int(float(value))
        except ValueError:
            match = re.search(r'-?\d+', value)
            if match:
                try:
                    return int(match.group())
                except ValueError:
                    pass
            return default
    return default


def safe_str(value, default: str = '') -> str:
    """Safely convert a value to string, returning default if value is None or empty."""
    if value is None:
        return default
    result = str(value).strip()
    return result if result else default
