"""Enrichment MCP server — simulated third-party data providers for UW triage.

Exposes four tools, one per simulated data provider, over MCP stdio:
  - lexisnexis_lookup(company_name)   litigation + regulatory + sanctions
  - dnb_lookup(company_name)          financial stress + paydex + firmographics
  - pitchbook_lookup(company_name)    funding rounds + valuation + investors
  - factset_lookup(company_name)      financial fundamentals + credit rating

Data source: a curated JSON file at data/profiles.json keyed by company
name, with a deterministic synthetic fallback (seeded by the company name)
for unknown names. Same company name always produces the same output —
good for demos and audit reruns.

Launch standalone:
    python -m mcp_servers.enrichment.server

Uses stdlib only — no additional Python deps beyond mcp (already in
Verity's runtime optional-dependencies).
"""
