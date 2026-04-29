# Tech Debt

Running list of known inconsistencies and follow-up cleanups. Each entry
should be self-contained: what the debt is, why it exists, and what the
fix looks like. Add new items at the bottom; leave resolved items in
place with a `Resolved YYYY-MM-DD` line so the history stays readable.

---

## Application-dropdown source differs between Runs and Decisions

**Where:** [verity/src/verity/db/queries/runs.sql](../verity/src/verity/db/queries/runs.sql) (`list_runs_filter_applications`) vs [verity/src/verity/web/routes.py](../verity/src/verity/web/routes.py) `/admin/decisions` (uses `verity.list_applications()`).

**What:** The Application filter dropdown is sourced from two different
places on the two pages:

- **Runs** runs `SELECT DISTINCT application FROM execution_run_current`.
  Shows only apps that have at least one run. Costs grow with run history.
- **Decisions** reads the full `application` table. Shows every
  registered application, including ones with zero decisions. O(catalog),
  cheap, indexed.

**Why it's like this:** When the Decisions page got server-side filters
(2026-04-29), I sourced apps from the catalog table on purpose to avoid
adding another DISTINCT scan after pushback against that pattern. The
Runs query predates that conversation and was left untouched to avoid
silently changing the visible dropdown contents on a page the user wasn't
asking to modify.

**Fix options:**

1. **Switch Runs to the catalog source** — match Decisions, drop
   `list_runs_filter_applications`. Trade-off: dropdown now offers apps
   with zero runs (selecting one shows the empty state). Cheapest.
2. **Switch Decisions to a DISTINCT scan** — add a new
   `list_decisions_filter_applications` query mirroring the runs one.
   Same UX on both pages; same scaling concern on both pages.
3. **Add a small materialized view** keyed on `(application,
   has_runs, has_decisions)` so both pages can read it cheaply and
   filter to non-empty.

**Recommended:** option 1 unless there's a real product reason to hide
zero-activity apps from the Runs dropdown.

---
