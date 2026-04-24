"""One-shot data migration scripts.

Each module in this package is a self-contained, idempotent data migration
that translates rows from a deprecated table shape into the current shape.
Migrations run AGAINST a populated DB (post-schema-apply, post-seed) and
are safe to re-run — they check for already-migrated rows and skip them.

Run a migration via: `python -m verity.db.migrations.<name>`.
"""
