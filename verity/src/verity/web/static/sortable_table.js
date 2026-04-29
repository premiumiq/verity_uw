/* ════════════════════════════════════════════════════════════
   sortable_table.js — client-side sort + search for tables

   Two features only:
     1. Click-to-sort column headers (asc / desc cycle).
     2. A page-scoped search input that hides rows whose joined
        text doesn't contain the substring.

   No column filters. Per-column filtering happens server-side
   on Runs / Decisions, so a second client-side filter layer
   would be confusing duplication.

   USAGE (markup contract)
   ───────────────────────
   <input type="text"
          id="myTableSearch"
          class="table-search"
          placeholder="Search items..."
          onkeyup="filterTable('myTableSearch','myTable')">

   <table class="verity-table sortable-table" id="myTable">
     <thead>
       <tr>
         <th class="sortable" onclick="sortTable('myTable',0)">Name</th>
         <!-- list-valued column: a single cell holds N values rendered
              with a delimiter (default ", "). Sorted lexicographically
              on the canonicalized list. -->
         <th class="sortable" data-column-type="list"
             onclick="sortTable('myTable',1)">Tools</th>
         <th>Configuration JSON</th>   <!-- non-sortable -->
       </tr>
     </thead>
     <tbody>...</tbody>
   </table>
   ════════════════════════════════════════════════════════════ */

(function () {
  "use strict";

  // Per-table sort state, keyed by table id so multiple tables on
  // the same page (e.g. tabs) sort independently.
  const sortState = {};   // { tableId: { col: number, dir: 'asc'|'desc' } }

  // Default delimiter for list-valued cells. Override per-column
  // via <th data-list-delimiter="; ">.
  const DEFAULT_LIST_DELIM = ", ";

  // Date-shape detector — generous enough to catch the
  // "MM-DD HH:MM" style this app already renders. If both sides
  // look date-y AND parse, we sort chronologically.
  const DATE_HINT_RE = /^\d{2,4}[-\/]\d{1,2}([-\/]\d{1,4})?(\s+\d{1,2}:\d{2}(:\d{2})?)?$/;

  // ── DOM helpers ───────────────────────────────────────────

  function getTable(tableId) {
    return document.getElementById(tableId);
  }

  function getRows(tableId) {
    const t = getTable(tableId);
    if (!t || !t.tBodies[0]) return [];
    return Array.from(t.tBodies[0].rows);
  }

  function getHeaders(tableId) {
    const t = getTable(tableId);
    if (!t || !t.tHead || !t.tHead.rows[0]) return [];
    return Array.from(t.tHead.rows[0].cells);
  }

  function isListColumn(th) {
    return !!(th && th.dataset && th.dataset.columnType === "list");
  }

  function listDelim(th) {
    return (th && th.dataset && th.dataset.listDelimiter) || DEFAULT_LIST_DELIM;
  }

  // Split a list-valued cell into its items.
  function parseList(cellText, delim) {
    if (!cellText) return [];
    return cellText
      .split(delim)
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
  }

  // ── Sort ──────────────────────────────────────────────────

  // Compare two scalar strings. Numeric comparison if both parse
  // as numbers; chronological if both look like dates and parse;
  // case-insensitive alphabetical otherwise.
  function scalarCompare(a, b) {
    const aTrim = a.trim();
    const bTrim = b.trim();

    const na = parseFloat(a);
    const nb = parseFloat(b);
    const aIsNum = !isNaN(na) && aTrim !== "" && /^-?\d/.test(aTrim);
    const bIsNum = !isNaN(nb) && bTrim !== "" && /^-?\d/.test(bTrim);
    if (aIsNum && bIsNum) return na - nb;

    if (DATE_HINT_RE.test(aTrim) && DATE_HINT_RE.test(bTrim)) {
      const da = Date.parse(a);
      const db = Date.parse(b);
      if (!isNaN(da) && !isNaN(db)) return da - db;
    }

    return a.toLowerCase().localeCompare(b.toLowerCase());
  }

  // Lex compare on canonicalized lists (each input is already
  // alphabetized internally by the caller). Empty lists sort to
  // the bottom regardless of asc/desc — the caller flips the
  // result for desc, but empties stay last in either direction.
  function listCompare(a, b) {
    if (a.length === 0 && b.length === 0) return 0;
    if (a.length === 0) return 1;
    if (b.length === 0) return -1;
    const n = Math.min(a.length, b.length);
    for (let i = 0; i < n; i++) {
      const c = a[i].toLowerCase().localeCompare(b[i].toLowerCase());
      if (c !== 0) return c;
    }
    return a.length - b.length;
  }

  function sortTable(tableId, colIdx) {
    const headers = getHeaders(tableId);
    const th = headers[colIdx];
    if (!th) return;

    // Cycle asc → desc → asc.
    const cur = sortState[tableId];
    let dir = "asc";
    if (cur && cur.col === colIdx && cur.dir === "asc") dir = "desc";
    sortState[tableId] = { col: colIdx, dir };

    headers.forEach((h) => h.classList.remove("sort-asc", "sort-desc"));
    th.classList.add(dir === "asc" ? "sort-asc" : "sort-desc");

    const tbody = getTable(tableId).tBodies[0];
    const rows = Array.from(tbody.rows);
    const isList = isListColumn(th);
    const delim = listDelim(th);

    // Pre-extract sort keys + original index for stable sort
    // (older v8 / Safari engines aren't guaranteed stable).
    const tagged = rows.map((row, i) => {
      const cell = row.cells[colIdx];
      const text = cell ? (cell.textContent || "").trim() : "";
      const key = isList
        ? parseList(text, delim).slice().sort((a, b) =>
            a.toLowerCase().localeCompare(b.toLowerCase())
          )
        : text;
      return { row, key, i };
    });

    tagged.sort((x, y) => {
      const cmp = isList
        ? listCompare(x.key, y.key)
        : scalarCompare(x.key, y.key);
      if (cmp !== 0) return dir === "asc" ? cmp : -cmp;
      return x.i - y.i;
    });

    const frag = document.createDocumentFragment();
    tagged.forEach((t) => frag.appendChild(t.row));
    tbody.appendChild(frag);
  }

  // ── Search ────────────────────────────────────────────────

  // Hide rows whose joined visible-cell text doesn't contain the
  // search term. Live on every keystroke; case-insensitive.
  function filterTable(searchInputId, tableId) {
    const input = document.getElementById(searchInputId);
    const q = ((input && input.value) || "").toLowerCase().trim();
    const rows = getRows(tableId);

    if (!q) {
      rows.forEach((r) => (r.style.display = ""));
      return;
    }

    rows.forEach((row) => {
      let combined = "";
      for (let i = 0; i < row.cells.length; i++) {
        combined += " " + (row.cells[i].textContent || "").toLowerCase();
      }
      row.style.display = combined.indexOf(q) === -1 ? "none" : "";
    });
  }

  // Inline onclick / onkeyup handlers in the markup expect these
  // on window — this file is intentionally not a module.
  window.sortTable = sortTable;
  window.filterTable = filterTable;
})();
