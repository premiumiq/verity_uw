# Champion Resolution

> **Tooltip:** How Verity picks which version to run: default current champion, date-pinned (SCD-2 temporal), or version-pinned by ID.

## Definition

The lookup mechanism by which Verity selects which entity version to run. Default: returns the current champion (the version with `lifecycle_state='champion'` and `valid_to IS NULL`). Date-pinned: returns the champion as of a specific date (SCD Type 2 temporal). Version-pinned: returns a specific version by ID (used for replay and audit).

## See also

- [Lifecycle State](lifecycle-state.md)
- [Asset Registry](asset-registry.md)

## Source

[`verity/src/verity/governance/registry.py`](../../verity/src/verity/governance/registry.py)
