"""
Comparison module for visa bulletin data.

Compares two parsed bulletin dicts and produces a structured diff that highlights
which visa categories changed, were added, or were removed between two scraper runs.
Intended to be used alongside store.py for historical comparison.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# Fields that identify a category row rather than representing date values
_IDENTITY_KEYS = frozenset(
    {
        "visa_category",
        "preference_level",
        "family_preference",
        "employment_preference",
        "category",
        # Actual parser output keys
        "family-sponsored",
        "employment-based",
        "region",
    }
)

# Maps employment-based ordinals to subscription codes
_EB_ORDINAL_TO_CODE = {
    "1st": "EB-1",
    "2nd": "EB-2",
    "3rd": "EB-3",
    "4th": "EB-4",
    "5th": "EB-5",
}

# String values that mean "immediately available / no backlog"
_CURRENT_VALUES = frozenset({"c", "current"})

# Date formats used in visa bulletins (e.g. "01 JAN 26" or "01JAN26")
_DATE_FORMATS = ("%d %b %y", "%d%b%y", "%d %b %Y", "%d%b%Y")


def _derive_category_key(category: Dict[str, Any]) -> str:
    """Return the stable identity key for a category row."""
    # Family-sponsored: value IS the subscription code (F1, F2A, F2B, F3, F4)
    fs = category.get("family-sponsored")
    if fs:
        return str(fs).strip()

    # Employment-based: map ordinal to EB code
    eb = category.get("employment-based")
    if eb:
        eb_clean = str(eb).strip()
        code = _EB_ORDINAL_TO_CODE.get(eb_clean)
        if code:
            return code
        # Try prefix match for entries like "1st Preference"
        for ordinal, mapped_code in _EB_ORDINAL_TO_CODE.items():
            if eb_clean.lower().startswith(ordinal):
                return mapped_code
        return eb_clean  # e.g. "Other Workers"

    # Diversity Visa: key per region
    region = category.get("region")
    if region:
        return f"DV-{str(region).strip()}"

    # Legacy / alternate formats
    for key in (
        "visa_category",
        "preference_level",
        "family_preference",
        "employment_preference",
        "category",
    ):
        value = category.get(key)
        if value:
            return str(value).strip()

    # Fallback: deterministic string from sorted items
    return str(sorted(category.items()))


def _build_category_index(
    categories: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Index categories by their canonical identity key for O(1) lookup."""
    index: Dict[str, Dict[str, Any]] = {}
    for cat in categories:
        key = _derive_category_key(cat)
        index[key] = cat  # last write wins on duplicate keys
    return index


def _parse_date(value: str) -> Optional[datetime]:
    """Attempt to parse a visa bulletin date string. Returns None if unparseable."""
    value = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return None


def _is_current(value: str) -> bool:
    """Return True if the value represents 'immediately available' (e.g. 'C' or 'Current')."""
    return value.strip().lower() in _CURRENT_VALUES


def _diff_date_field(
    field: str,
    current_val: str,
    previous_val: str,
) -> Optional[Dict[str, Any]]:
    """
    Compare two date values for a single field.

    Returns None if equal; otherwise a change record with a direction:
        advanced       - cutoff date moved forward (good news)
        retrogressed   - cutoff date moved back (bad news)
        became_current - changed to "Current" / "C"
        lost_current   - was "Current", now a specific date
        changed        - value changed but dates could not be parsed
    """
    c_norm = current_val.strip()
    p_norm = previous_val.strip()

    if c_norm == p_norm:
        return None
    # Both are semantically "Current" even if spelled differently
    if _is_current(c_norm) and _is_current(p_norm):
        return None

    change: Dict[str, Any] = {"field": field, "previous": p_norm, "current": c_norm}

    if _is_current(c_norm):
        change["direction"] = "became_current"
    elif _is_current(p_norm):
        change["direction"] = "lost_current"
    else:
        c_date = _parse_date(c_norm)
        p_date = _parse_date(p_norm)
        if c_date is not None and p_date is not None:
            change["direction"] = "advanced" if c_date > p_date else "retrogressed"
        else:
            change["direction"] = "changed"

    return change


def _diff_category(
    key: str,
    current_cat: Dict[str, Any],
    previous_cat: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Produce a field-level diff for a single category.
    Returns None if identical; otherwise a dict with 'category_key' and 'field_changes'.
    """
    all_fields = set(current_cat) | set(previous_cat)
    field_changes: List[Dict[str, Any]] = []

    for field in sorted(all_fields):
        if field in _IDENTITY_KEYS:
            continue

        c_val = current_cat.get(field)
        p_val = previous_cat.get(field)

        if c_val is None and p_val is None:
            continue

        if p_val is None:
            field_changes.append(
                {"field": field, "previous": None, "current": str(c_val), "direction": "added"}
            )
            continue

        if c_val is None:
            field_changes.append(
                {"field": field, "previous": str(p_val), "current": None, "direction": "removed"}
            )
            continue

        change = _diff_date_field(field, str(c_val), str(p_val))
        if change is not None:
            field_changes.append(change)

    if not field_changes:
        return None

    return {"category_key": key, "field_changes": field_changes}


def compare_bulletins(
    current: Dict[str, Any],
    previous: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Compare two parsed bulletin dicts and return a structured diff.

    Args:
        current:  Parser output from the current run.
        previous: Parser output from the previous successful run of the same type.

    Returns:
        Structured comparison dict. Never raises; errors are captured in the 'error' field.
    """
    compared_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    try:
        current_cats = current.get("categories", [])
        previous_cats = previous.get("categories", [])

        current_index = _build_category_index(current_cats)
        previous_index = _build_category_index(previous_cats)

        added_keys = current_index.keys() - previous_index.keys()
        removed_keys = previous_index.keys() - current_index.keys()
        common_keys = current_index.keys() & previous_index.keys()

        categories_added = [current_index[k] for k in sorted(added_keys)]
        categories_removed = [previous_index[k] for k in sorted(removed_keys)]

        categories_changed: List[Dict[str, Any]] = []
        total_field_changes = 0
        for key in sorted(common_keys):
            diff = _diff_category(key, current_index[key], previous_index[key])
            if diff is not None:
                categories_changed.append(diff)
                total_field_changes += len(diff["field_changes"])

        has_changes = bool(categories_added or categories_removed or categories_changed)

        return {
            "compared_at": compared_at,
            "current_run_bulletin_date": current.get("bulletin_date"),
            "previous_run_bulletin_date": previous.get("bulletin_date"),
            "has_changes": has_changes,
            "summary": {
                "categories_added": len(categories_added),
                "categories_removed": len(categories_removed),
                "categories_changed": len(categories_changed),
                "total_field_changes": total_field_changes,
            },
            "categories_added": categories_added,
            "categories_removed": categories_removed,
            "categories_changed": categories_changed,
            "error": None,
        }

    except Exception as e:
        return {
            "compared_at": compared_at,
            "current_run_bulletin_date": (
                current.get("bulletin_date") if isinstance(current, dict) else None
            ),
            "previous_run_bulletin_date": (
                previous.get("bulletin_date") if isinstance(previous, dict) else None
            ),
            "has_changes": False,
            "summary": {
                "categories_added": 0,
                "categories_removed": 0,
                "categories_changed": 0,
                "total_field_changes": 0,
            },
            "categories_added": [],
            "categories_removed": [],
            "categories_changed": [],
            "error": str(e),
        }


def format_comparison_for_display(diff: Dict[str, Any]) -> str:
    """
    Render a comparison result as a human-readable string for terminal output.

    Args:
        diff: Structured diff dict from compare_bulletins()

    Returns:
        Multi-line string suitable for printing to stdout
    """
    lines = []
    lines.append("=" * 60)
    lines.append("BULLETIN COMPARISON")
    lines.append("=" * 60)

    error = diff.get("error")
    if error:
        lines.append(f"[ERROR] Comparison failed: {error}")
        return "\n".join(lines)

    lines.append(f"Previous: {diff.get('previous_run_bulletin_date', 'Unknown')}")
    lines.append(f"Current:  {diff.get('current_run_bulletin_date', 'Unknown')}")
    lines.append(f"Compared: {diff.get('compared_at', 'Unknown')}")
    lines.append("")

    summary = diff.get("summary", {})
    has_changes = diff.get("has_changes", False)

    if not has_changes:
        lines.append("No changes detected between the two bulletins.")
        lines.append("=" * 60)
        return "\n".join(lines)

    lines.append("Changes detected:")
    lines.append(f"  Categories added:    {summary.get('categories_added', 0)}")
    lines.append(f"  Categories removed:  {summary.get('categories_removed', 0)}")
    lines.append(f"  Categories changed:  {summary.get('categories_changed', 0)}")
    lines.append(f"  Total field changes: {summary.get('total_field_changes', 0)}")

    for cat in diff.get("categories_added", []):
        key = _derive_category_key(cat)
        lines.append(f"\n  [ADDED]   {key}")

    for cat in diff.get("categories_removed", []):
        key = _derive_category_key(cat)
        lines.append(f"\n  [REMOVED] {key}")

    for cat_diff in diff.get("categories_changed", []):
        key = cat_diff.get("category_key", "?")
        lines.append(f"\n  {key}:")
        for fc in cat_diff.get("field_changes", []):
            field = fc.get("field", "?")
            prev = fc.get("previous") or "(none)"
            curr = fc.get("current") or "(none)"
            direction = fc.get("direction", "")
            direction_tag = f"  [{direction.upper()}]" if direction else ""
            lines.append(f"    {field}: {prev} → {curr}{direction_tag}")

    lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)
