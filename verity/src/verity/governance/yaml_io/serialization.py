"""Bundle ↔ YAML text serialization.

Two requirements:

1. **Deterministic output.** Re-exporting the same Bundle must produce
   byte-identical YAML so git diffs are meaningful and the round-trip
   property test (slice 4B) can compare exports directly.

2. **Readable output.** Multi-line strings (prompt content, descriptions)
   must use the ``|`` literal block scalar — not escaped one-liners — so
   prompts read as prose in code review.

We use PyYAML with three configuration choices:

- ``sort_keys=False`` — keep the field declaration order from the
  Pydantic models (the human-readable order: ``kind`` first, then
  ``name``, etc.) instead of alphabetising.
- Custom string representer: ``|`` block style for any string with
  newlines.
- Custom datetime representer: ISO 8601 (``2026-05-01T02:19:21+00:00``)
  instead of PyYAML's space-separated default.

PyYAML preserves dict insertion order on dump, and Pydantic's
``.model_dump()`` returns keys in declaration order, so the chain
preserves the order we want without extra work.

Empty-list fields (e.g., a version with no delegations) are stripped
from the output before dumping, so a fully-wired version doesn't show
``sources: []`` / ``targets: []`` / ``delegations: []`` clutter.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import yaml

from verity.governance.yaml_io.models import Bundle


# ── Custom representer for multi-line strings ───────────────────────────────


def _str_representer(dumper: yaml.Dumper, data: str) -> yaml.ScalarNode:
    """Use ``|`` block style for strings containing newlines.

    PyYAML's default representer will sometimes use double-quoted
    style for multi-line strings (especially short ones), which
    produces ``"line1\nline2"`` in the output. That's correct YAML
    but unreadable for prompts. This representer forces the literal
    block style for any string with a newline.
    """
    if "\n" in data:
        # ``|`` literal block scalar — preserves newlines, no escaping.
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


def _datetime_representer(dumper: yaml.Dumper, data: datetime) -> yaml.ScalarNode:
    """Emit datetimes in ISO 8601 form.

    PyYAML's default uses ``2026-05-01 02:19:21+00:00`` (space between
    date and time). Most config tooling — and most humans — prefer
    ``2026-05-01T02:19:21+00:00``. We coerce to a string so YAML
    consumers always get a quote-safe scalar and don't need to know
    YAML's native ``timestamp`` type.
    """
    return dumper.represent_scalar("tag:yaml.org,2002:str", data.isoformat())


class _VerityDumper(yaml.SafeDumper):
    """SafeDumper subclass with custom representers.

    Subclassing instead of mutating yaml.Dumper directly so the rest
    of the application's PyYAML usage is unaffected.
    """


_VerityDumper.add_representer(str, _str_representer)
_VerityDumper.add_representer(datetime, _datetime_representer)


def _strip_empty_lists(data: Any) -> Any:
    """Recursively remove keys whose value is an empty list.

    A version with no source bindings shouldn't render ``sources: []``
    in the YAML; the absence of the key is enough — the importer
    treats missing keys as empty. Applied to dicts only; list elements
    pass through (we want ``[]`` to be removable as a *value*, not as
    a list element).

    Empty *dicts* (e.g. an unset ``scope: {}`` on a delegation) are
    kept because a flow-style empty dict reads cleanly and authors
    sometimes write ``{}`` to communicate "explicitly empty". An
    empty list reads as noise either way.
    """
    if isinstance(data, dict):
        return {
            key: _strip_empty_lists(value)
            for key, value in data.items()
            if not (isinstance(value, list) and len(value) == 0)
        }
    if isinstance(data, list):
        return [_strip_empty_lists(item) for item in data]
    return data


# ── Public API ──────────────────────────────────────────────────────────────


def dumps_bundle(bundle: Bundle) -> str:
    """Serialize a Bundle to YAML text.

    The output is:
      - Block style (no flow style anywhere)
      - Field-order preserving (kind first, then name, etc.)
      - 2-space indent
      - Multi-line strings as ``|`` literal blocks
      - UTF-8, no leading directive
    """
    # exclude_none=True keeps unset optional fields out of the YAML
    # so the output is sparse and stable: a row with no
    # ``mock_responses`` produces no ``mock_responses:`` key. We then
    # strip empty-list fields too — a version with no delegations
    # should not render ``delegations: []`` clutter.
    data = bundle.model_dump(exclude_none=True, mode="python")
    data = _strip_empty_lists(data)

    return yaml.dump(
        data,
        Dumper=_VerityDumper,
        sort_keys=False,
        default_flow_style=False,
        indent=2,
        allow_unicode=True,
    )


def loads_bundle(yaml_text: str) -> Bundle:
    """Parse a YAML text into a validated Bundle.

    Validation errors raise ``pydantic.ValidationError`` with the
    full path to the offending field — sufficient for the slice-4B
    importer to produce a precise error report.
    """
    raw: Any = yaml.safe_load(yaml_text)
    if raw is None:
        raise ValueError("Bundle YAML is empty.")
    if not isinstance(raw, dict):
        raise ValueError(
            f"Bundle YAML must be a mapping at the top level; got {type(raw).__name__}."
        )
    return Bundle.model_validate(raw)
