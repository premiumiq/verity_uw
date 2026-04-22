"""Verity Metrics Engine — compute classification and extraction metrics.

Pure computation module. No database access, no I/O. All functions take
lists/dicts and return metric dicts. Implements from scratch for
regulatory auditability — no sklearn dependency.

Used by:
- Validation runner: compute aggregate metrics after running entity against ground truth
- Test runner: compare test case outputs to expected outputs
- Reporting: model inventory metric summaries

Metrics implemented:
- Classification: precision, recall, F1 (macro-averaged), Cohen's kappa, confusion matrix
- Field extraction: per-field accuracy with tolerance support, overall extraction rate
- Exact match: simple equality check with difference reporting
- Schema validation: JSON schema compliance check
"""

from collections import Counter
from typing import Any, Optional


# ══════════════════════════════════════════════════════════════
# CLASSIFICATION METRICS
# ══════════════════════════════════════════════════════════════

def classification_metrics(
    actual: list[str],
    expected: list[str],
) -> dict[str, Any]:
    """Compute classification metrics from predicted vs expected labels.

    Args:
        actual: List of predicted labels (from the entity's output).
        expected: List of ground truth labels (from authoritative annotations).
        Both lists must be the same length.

    Returns:
        Dict with: precision, recall, f1 (macro-averaged), cohens_kappa,
        confusion_matrix (canonical format), per_class breakdown, total_samples.
    """
    if len(actual) != len(expected):
        raise ValueError(f"Length mismatch: actual={len(actual)}, expected={len(expected)}")

    if not actual:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0, "cohens_kappa": 0.0,
                "confusion_matrix": {}, "per_class": {}, "total_samples": 0}

    # Collect all unique labels (union of actual and expected)
    labels = sorted(set(actual) | set(expected))

    # Build confusion matrix
    # matrix[i][j] = count of samples where expected=labels[i] and actual=labels[j]
    label_to_idx = {label: i for i, label in enumerate(labels)}
    n = len(labels)
    matrix = [[0] * n for _ in range(n)]

    for a, e in zip(actual, expected):
        matrix[label_to_idx[e]][label_to_idx[a]] += 1

    # Per-class metrics
    per_class = {}
    precisions = []
    recalls = []
    f1s = []

    for i, label in enumerate(labels):
        tp = matrix[i][i]
        fp = sum(matrix[j][i] for j in range(n)) - tp  # column sum minus diagonal
        fn = sum(matrix[i][j] for j in range(n)) - tp  # row sum minus diagonal

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

        per_class[label] = {
            "tp": tp, "fp": fp, "fn": fn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        }
        precisions.append(precision)
        recalls.append(recall)
        f1s.append(f1)

    # Macro-averaged metrics (unweighted mean across classes)
    macro_precision = sum(precisions) / len(precisions) if precisions else 0.0
    macro_recall = sum(recalls) / len(recalls) if recalls else 0.0
    macro_f1 = sum(f1s) / len(f1s) if f1s else 0.0

    # Cohen's kappa
    kappa = _cohens_kappa(actual, expected, labels)

    return {
        "precision": round(macro_precision, 4),
        "recall": round(macro_recall, 4),
        "f1": round(macro_f1, 4),
        "cohens_kappa": round(kappa, 4),
        "confusion_matrix": {
            "labels": labels,
            "matrix": matrix,
            "per_class": per_class,
        },
        "per_class": per_class,
        "total_samples": len(actual),
    }


def _cohens_kappa(actual: list[str], expected: list[str], labels: list[str]) -> float:
    """Compute Cohen's kappa coefficient.

    Measures agreement between two raters (predicted vs expected) while
    accounting for agreement that would occur by chance.

    kappa = (p_o - p_e) / (1 - p_e)
    where p_o = observed agreement, p_e = expected agreement by chance.
    """
    n = len(actual)
    if n == 0:
        return 0.0

    # Observed agreement: proportion of matching labels
    p_o = sum(1 for a, e in zip(actual, expected) if a == e) / n

    # Expected agreement by chance
    actual_counts = Counter(actual)
    expected_counts = Counter(expected)
    p_e = sum(
        (actual_counts.get(label, 0) / n) * (expected_counts.get(label, 0) / n)
        for label in labels
    )

    if p_e == 1.0:
        return 1.0  # perfect agreement by chance — kappa undefined, treat as perfect

    return (p_o - p_e) / (1 - p_e)


# ══════════════════════════════════════════════════════════════
# FIELD EXTRACTION METRICS
# ══════════════════════════════════════════════════════════════

def field_accuracy(
    actual_fields: dict[str, Any],
    expected_fields: dict[str, Any],
    field_configs: Optional[list[dict]] = None,
) -> dict[str, Any]:
    """Compute per-field accuracy for extraction tasks.

    Args:
        actual_fields: Dict of {field_name: extracted_value} from entity output.
            Value can be a dict with "value" key (e.g., {"value": "Acme", "confidence": 0.95})
            or a plain value.
        expected_fields: Dict of {field_name: expected_value} from ground truth.
            Same format flexibility as actual_fields.
        field_configs: Optional list of field config dicts with keys:
            field_name, field_type, match_type, tolerance_value, tolerance_unit, is_required

    Returns:
        Dict with: per_field results, overall_accuracy, fields_evaluated,
        records_evaluated (always 1 for single-record), missing_fields, extra_fields.
    """
    configs = {}
    if field_configs:
        configs = {c["field_name"]: c for c in field_configs}

    # Normalize: extract "value" from dicts if needed
    actual_norm = _normalize_fields(actual_fields)
    expected_norm = _normalize_fields(expected_fields)

    all_fields = sorted(set(actual_norm.keys()) | set(expected_norm.keys()))
    per_field = {}
    correct_count = 0
    total_count = 0

    for field_name in all_fields:
        actual_val = actual_norm.get(field_name)
        expected_val = expected_norm.get(field_name)

        if expected_val is None:
            # Extra field in actual (not in ground truth) — skip
            continue

        total_count += 1
        config = configs.get(field_name, {})
        match_type = config.get("match_type", "exact")
        tolerance = config.get("tolerance_value")
        tolerance_unit = config.get("tolerance_unit", "percent")

        matched, match_score, error_detail = _compare_field(
            actual_val, expected_val, match_type, tolerance, tolerance_unit
        )

        if matched:
            correct_count += 1

        per_field[field_name] = {
            "actual": actual_val,
            "expected": expected_val,
            "correct": matched,
            "match_score": round(match_score, 4) if match_score is not None else None,
            "match_type": match_type,
        }
        if error_detail:
            per_field[field_name]["error"] = error_detail

    # Missing and extra fields
    missing = [f for f in expected_norm if f not in actual_norm]
    extra = [f for f in actual_norm if f not in expected_norm]

    overall = correct_count / total_count if total_count > 0 else 0.0

    return {
        "per_field": per_field,
        "overall_accuracy": round(overall, 4),
        "fields_evaluated": total_count,
        "fields_correct": correct_count,
        "missing_fields": missing,
        "extra_fields": extra,
    }


def _normalize_fields(fields: dict) -> dict:
    """Extract plain values from field dicts that may have {value, confidence, note} structure."""
    result = {}
    for k, v in fields.items():
        if isinstance(v, dict) and "value" in v:
            result[k] = v["value"]
        else:
            result[k] = v
    return result


def _compare_field(
    actual, expected, match_type: str,
    tolerance: Optional[float] = None,
    tolerance_unit: str = "percent",
) -> tuple[bool, Optional[float], Optional[str]]:
    """Compare a single field value against expected.

    Returns: (matched: bool, match_score: float or None, error_detail: str or None)
    """
    if actual is None and expected is None:
        return True, 1.0, None

    if actual is None:
        return False, 0.0, "missing"

    if expected is None:
        return True, 1.0, None  # extra field, not an error

    if match_type == "exact":
        matched = actual == expected
        return matched, 1.0 if matched else 0.0, None if matched else f"expected={expected}, got={actual}"

    if match_type == "case_insensitive":
        matched = str(actual).lower().strip() == str(expected).lower().strip()
        return matched, 1.0 if matched else 0.0, None if matched else f"case mismatch"

    if match_type == "contains":
        matched = str(expected).lower() in str(actual).lower()
        return matched, 1.0 if matched else 0.0, None if matched else f"not found in output"

    if match_type == "numeric_tolerance":
        try:
            actual_num = float(actual)
            expected_num = float(expected)
        except (TypeError, ValueError):
            return False, 0.0, f"cannot compare as numeric: actual={actual}, expected={expected}"

        if expected_num == 0:
            matched = actual_num == 0
            return matched, 1.0 if matched else 0.0, None

        if tolerance_unit == "percent":
            tol = tolerance or 0.05  # default 5%
            error_pct = abs(actual_num - expected_num) / abs(expected_num)
            matched = error_pct <= tol
            return matched, round(1.0 - error_pct, 4), f"error={error_pct:.2%}" if not matched else None
        else:
            # Absolute tolerance
            tol = tolerance or 0
            diff = abs(actual_num - expected_num)
            matched = diff <= tol
            return matched, round(1.0 - (diff / max(abs(expected_num), 1)), 4), f"diff={diff}" if not matched else None

    # Unknown match type — fall back to exact
    matched = actual == expected
    return matched, 1.0 if matched else 0.0, f"unknown match_type={match_type}"


# ══════════════════════════════════════════════════════════════
# EXACT MATCH
# ══════════════════════════════════════════════════════════════

def exact_match(actual: Any, expected: Any) -> dict[str, Any]:
    """Simple equality check with difference reporting.

    Args:
        actual: Entity output.
        expected: Ground truth expected output.

    Returns:
        Dict with: matched (bool), differences (list of strings).
    """
    if actual == expected:
        return {"matched": True, "differences": []}

    differences = []
    if isinstance(actual, dict) and isinstance(expected, dict):
        all_keys = set(actual.keys()) | set(expected.keys())
        for key in sorted(all_keys):
            a = actual.get(key)
            e = expected.get(key)
            if a != e:
                differences.append(f"{key}: expected={e}, got={a}")
    else:
        differences.append(f"expected={expected}, got={actual}")

    return {"matched": False, "differences": differences}


# ══════════════════════════════════════════════════════════════
# SCHEMA VALIDATION
# ══════════════════════════════════════════════════════════════

def schema_valid(output: dict, schema: dict) -> dict[str, Any]:
    """Check if output matches expected schema structure.

    Simple structural check — verifies required keys are present and
    value types match. Not a full JSON Schema validator.

    Args:
        output: Entity output dict.
        schema: Dict of {field_name: expected_type_string} e.g., {"risk_score": "string"}.

    Returns:
        Dict with: valid (bool), errors (list of strings).
    """
    if not isinstance(output, dict):
        return {"valid": False, "errors": [f"Expected dict, got {type(output).__name__}"]}

    errors = []
    type_map = {
        "string": str, "number": (int, float), "integer": int, "float": float,
        "boolean": bool, "array": list, "object": dict,
    }

    for field_name, expected_type_str in schema.items():
        if field_name not in output:
            errors.append(f"Missing required field: {field_name}")
            continue

        value = output[field_name]
        if value is None:
            continue  # null is acceptable for any type

        expected_types = type_map.get(expected_type_str)
        if expected_types and not isinstance(value, expected_types):
            errors.append(
                f"Field '{field_name}': expected {expected_type_str}, "
                f"got {type(value).__name__}"
            )

    return {"valid": len(errors) == 0, "errors": errors}


# ══════════════════════════════════════════════════════════════
# THRESHOLD CHECKING
# ══════════════════════════════════════════════════════════════

def check_thresholds(
    metrics: dict[str, Any],
    thresholds: list[dict],
) -> dict[str, Any]:
    """Check computed metrics against threshold requirements.

    Args:
        metrics: Computed metrics dict (from classification_metrics or field_accuracy).
        thresholds: List of threshold dicts with keys:
            metric_name, field_name (nullable), minimum_acceptable, target_champion.

    Returns:
        Dict with: all_passed (bool), details (list of per-threshold results).
    """
    details = []

    for t in thresholds:
        metric_name = t["metric_name"]
        field_name = t.get("field_name")
        minimum = float(t["minimum_acceptable"])
        target = float(t["target_champion"])

        # Look up the achieved value
        if field_name:
            # Per-field threshold — look in per_field dict
            per_field = metrics.get("per_field", {})
            field_data = per_field.get(field_name, {})
            if isinstance(field_data, dict):
                achieved = field_data.get("accuracy", field_data.get(metric_name, 0.0))
            else:
                achieved = 0.0
        else:
            # Aggregate threshold
            achieved = metrics.get(metric_name, 0.0)

        achieved = float(achieved) if achieved is not None else 0.0
        passed = achieved >= minimum
        met_target = achieved >= target

        details.append({
            "metric_name": metric_name,
            "field_name": field_name,
            "minimum_acceptable": minimum,
            "target_champion": target,
            "achieved": round(achieved, 4),
            "passed": passed,
            "met_target": met_target,
        })

    all_passed = all(d["passed"] for d in details)

    return {
        "all_passed": all_passed,
        "thresholds_checked": len(details),
        "thresholds_passed": sum(1 for d in details if d["passed"]),
        "details": details,
    }
