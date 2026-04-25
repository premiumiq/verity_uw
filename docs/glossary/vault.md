# Vault

> **Tooltip:** Companion document service (collections, lineage, tags, text extraction). Independent DB. Verity reaches it via the canonical data_connector.

## Definition

An independent companion service for document storage, text extraction, lineage tracking, and tag governance. Owns its database (`vault_db`) and APIs. Verity governs the use of Vault (declared via the canonical `data_connector` named `vault`) but never connects to it directly. Renamed from EDMS in the docs; the rename to code/env vars is tracked in [`enhancements/production-readiness-k8s.md`](../enhancements/production-readiness-k8s.md).

## See also

- [Data Connector](data-connector.md)
- [Verity Planes](verity-planes.md)

## Source

[`docs/apps/vault.md`](../../docs/apps/vault.md)
