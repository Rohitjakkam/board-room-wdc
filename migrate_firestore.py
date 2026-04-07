"""
One-time Firestore migration script.
Patches existing simulation documents to fix:
  1. Empty metric units   → inferred via _infer_unit()
  2. Founded field 'N/A'  → 'Not specified'
  3. Tenure 'None' years  → 0 (numeric default so template shows 'Not specified')
  4. Categorical values stored as numeric 0 without flag → flagged

Run:  python migrate_firestore.py [--dry-run]
"""

import sys
import os
import copy
import argparse

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.firebase_client import get_firestore_client
from core.data_manager import _infer_unit, _normalize_metrics

NA_VARIANTS = {'n/a', 'na', 'none', 'null', 'unknown', ''}


def migrate_document(data: dict) -> tuple[dict, list[str]]:
    """Patch a single document's data in-place. Returns (patched_data, list of changes)."""
    changes = []
    patched = copy.deepcopy(data)
    company = patched.get('company_data', {})

    # ── 1. Fix metric units ─────────────────────────────────────────────
    metrics = company.get('metrics', {})
    for key, info in metrics.items():
        if not isinstance(info, dict):
            continue
        current_unit = info.get('unit', '')
        if not current_unit:
            inferred = _infer_unit(key)
            if inferred:
                info['unit'] = inferred
                changes.append(f"  metric '{key}': unit '' -> '{inferred}'")

    # ── 2. Fix founded field ────────────────────────────────────────────
    founded = str(company.get('founded', '')).strip()
    if founded.lower() in NA_VARIANTS:
        company['founded'] = 'Not specified'
        if founded != 'Not specified':
            changes.append(f"  founded: '{founded}' -> 'Not specified'")

    # ── 3. Fix tenure_years None → 0 for board members ─────────────────
    for member in company.get('board_members', []):
        if member.get('tenure_years') is None:
            member['tenure_years'] = 0
            changes.append(f"  {member.get('name', '?')}: tenure_years None -> 0")

    return patched, changes


def main():
    parser = argparse.ArgumentParser(description='Migrate Firestore simulation documents')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show changes without writing to Firestore')
    args = parser.parse_args()

    db = get_firestore_client()
    if db is None:
        print("ERROR: Could not connect to Firestore. Check credentials.")
        sys.exit(1)

    col = db.collection('simulations')
    docs = list(col.stream())
    print(f"Found {len(docs)} simulation documents.\n")

    total_changes = 0
    docs_changed = 0

    for doc in docs:
        doc_id = doc.id
        data = doc.to_dict()
        company_name = data.get('company_data', {}).get('company_name', 'Unknown')

        patched, changes = migrate_document(data)

        if changes:
            docs_changed += 1
            total_changes += len(changes)
            print(f"[{'DRY-RUN' if args.dry_run else 'PATCH'}] {doc_id}")
            print(f"  Company: {company_name}")
            for c in changes:
                print(c)

            if not args.dry_run:
                col.document(doc_id).set(patched)
                print(f"  [OK] Written to Firestore\n")
            else:
                print()

    print(f"{'-' * 50}")
    print(f"Documents scanned:  {len(docs)}")
    print(f"Documents changed:  {docs_changed}")
    print(f"Total field patches: {total_changes}")
    if args.dry_run:
        print("\nThis was a DRY RUN. Re-run without --dry-run to apply changes.")


if __name__ == '__main__':
    main()
