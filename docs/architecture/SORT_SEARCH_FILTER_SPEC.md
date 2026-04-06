# Sort, Search & Filter Specification

## 1. Overview

### Purpose

This specification defines the behavior for client-side sort, search, and filter capabilities on tabular data views. It is intended to serve as a reusable pattern for any application that displays data in HTML tables and needs interactive data exploration without server round-trips.

### Reference Implementation

The patterns described here are derived from the IRP Dashboard's batch detail page ([batch_detail.html](app/templates/batch_detail.html), [scripts.js](app/static/js/scripts.js)), extended with support for **list-valued columns** — columns where a single cell contains multiple categorical values.

### Scope

- Client-side only — all data is rendered server-side into the DOM; sort/search/filter operate on the already-loaded rows.
- Each table instance maintains independent state (sort, filters, search).
- The three features compose together using AND logic: a row must satisfy all active constraints to remain visible.

---

## 2. Architecture

### Approach

All operations happen in the browser via DOM manipulation. No server requests are made when the user sorts, searches, or filters. This keeps interactions instant and avoids backend complexity.

### State Management

Each table tracks three independent pieces of state:

| State | Structure | Purpose |
|-------|-----------|---------|
| **Sort state** | `{ column: number, direction: 'asc' \| 'desc' }` | Which column is sorted and in which direction |
| **Filter state** | `{ columnIndex: selectedValues[] }` | Per-column filter selections |
| **Search state** | `string` | Current search box text |

State is keyed by table ID, so multiple tables on the same page (e.g., in different tabs) operate independently.

### Composition Rule

When evaluating whether a row is visible:

```
visible = matchesSearch(row) AND matchesAllColumnFilters(row)
```

All active constraints must pass. Search and column filters are AND'd together. Multiple column filters are AND'd across columns. Within a single column filter, selected values are OR'd (the row must match at least one selected value).

---

## 3. Search

### Behavior

A single text input provides global free-text search across all visible columns of a table.

| Property | Detail |
|----------|--------|
| **Trigger** | On every keystroke (`keyup` event) |
| **Match logic** | Case-insensitive substring match |
| **Scope** | All visible columns in the row, including text content of list-valued columns |
| **Structured data** | For cells with embedded structured data (e.g., JSON stored in `data-` attributes), search should also match against the raw data string |
| **Empty search** | Shows all rows (subject to active column filters) |

### Search and List Columns

For list-valued columns, the search term is matched against the **joined text representation** of the list. For example, if a cell displays `Tag A, Tag B, Tag C`, searching for `"tag b"` matches that cell.

### UI

- One search input per table, placed above the table.
- Placeholder text: `"Search {entity}..."` (e.g., "Search jobs...").
- No submit button — filtering is live on keyup.

---

## 4. Sort

### Behavior

Clicking a sortable column header sorts the entire table by that column.

| Property | Detail |
|----------|--------|
| **Trigger** | Click on column header |
| **Cycle** | First click → ascending. Second click → descending. Third click does not reset; it toggles back to ascending. |
| **Scope** | Single-column sort only. Clicking a new column replaces the previous sort. |
| **Stability** | Original row order is preserved for equal values (stable sort). |

### Type Detection

The sort function auto-detects the comparison strategy per column:

| Column type | Detection | Comparison |
|-------------|-----------|------------|
| **Numeric** | Both compared values parse as numbers | Numeric comparison |
| **Text** | Default fallback | Case-insensitive alphabetical |
| **Date/Timestamp** | Values match a date pattern or are in a known date column | Chronological |
| **List** | Cell is identified as a list-valued column | Lexicographic (see below) |

### Sorting List-Valued Columns

List-valued columns are sorted using **lexicographic ordering on the sorted list elements**:

1. Sort each cell's list alphabetically (internal sort), producing a canonical form.
2. Compare two cells element by element:
   - Compare the first elements alphabetically.
   - If equal, compare the second elements.
   - Continue until a difference is found or one list is exhausted.
3. A shorter list that is a prefix of a longer list sorts first (e.g., `["A", "B"]` < `["A", "B", "C"]`).
4. **Empty lists sort to the bottom**, regardless of ascending/descending direction.

**Example sort (ascending):**

| Original cell value | Canonical form | Sort position |
|---------------------|---------------|---------------|
| `Cat A, Cat C` | `[Cat A, Cat C]` | 1 |
| `Cat A, Cat D` | `[Cat A, Cat D]` | 2 |
| `Cat B` | `[Cat B]` | 3 |
| `Cat B, Cat A` | `[Cat A, Cat B]` | 4 |
| _(empty)_ | `[]` | 5 (bottom) |

### Visual Indicators

| State | Indicator | CSS class |
|-------|-----------|-----------|
| Unsorted | `⇅` (dimmed) | `sortable` |
| Ascending | `▲` | `sort-asc` |
| Descending | `▼` | `sort-desc` |

Indicators are rendered via CSS `::after` pseudo-elements on `<th>` elements.

### Non-Sortable Columns

Columns that should not be sortable (e.g., JSON blobs, action buttons) omit the `sortable` class and have no click handler.

---

## 5. Column Filters

### Behavior

Each filterable column can have an inline filter control in a dedicated filter row below the header row. The filter row is hidden by default and toggled via a button.

### Adaptive Control Type

The filter control type is determined automatically based on the **cardinality** of unique values in the column:

| Unique values | Control | Behavior |
|---------------|---------|----------|
| **<= 15** | Multi-select dropdown (`<select multiple>`) | User picks from a list of all distinct values |
| **> 15** | Text input | Case-insensitive substring match |

### Non-Filterable Columns

Columns containing unstructured or complex data (e.g., JSON blobs) are skipped during filter generation. Detection is based on:
- Column header containing "JSON" or "Configuration"
- Or an explicit `data-no-filter` attribute on the `<th>` element

### Filter Logic for Scalar Columns

Standard single-valued columns use exact match against selected filter values:

```
columnPasses = selectedValues.includes(cellText)
```

If no filter is active on a column (no values selected / empty text input), the column is ignored in evaluation.

### Filter Logic for List-Valued Columns

List-valued columns use **ANY/OR match** semantics:

```
columnPasses = cellList.some(item => selectedValues.includes(item))
```

A row passes the column filter if **at least one** of its list items matches **at least one** of the user's selected filter values.

**Example:**

| Cell value | Selected filters | Match? | Reason |
|------------|-----------------|--------|--------|
| `Cat A, Cat B, Cat C` | `Cat B` | Yes | Cat B is in the cell list |
| `Cat A, Cat B, Cat C` | `Cat B, Cat D` | Yes | Cat B is in the cell list |
| `Cat A, Cat B` | `Cat D, Cat E` | No | No overlap |
| _(empty)_ | `Cat A` | No | Empty list has no matches |

### Dropdown Population for List-Valued Columns

The multi-select dropdown shows the **deduplicated union of all individual values** across all rows, not the distinct list combinations.

**Example:** Given three rows with values `[Cat A, Cat B]`, `[Cat B, Cat C]`, `[Cat A, Cat C]`, the dropdown shows:
- Cat A
- Cat B
- Cat C

Values are sorted alphabetically in the dropdown.

### Identifying List-Valued Columns

List columns are identified by a `data-column-type="list"` attribute on the `<th>` element. The list delimiter in the rendered cell text defaults to `", "` (comma-space) and can be overridden via a `data-list-delimiter` attribute.

```html
<th class="sortable" data-column-type="list" onclick="sortTable('myTable', 3)">
    Categories
</th>
```

### Cross-Column Composition

When multiple column filters are active, they are combined with AND logic:

```
rowVisible = column1Passes AND column2Passes AND ... AND columnNPasses AND matchesSearch
```

---

## 6. UI/UX Patterns

### Layout

```
┌──────────────────────────────────────────────────┐
│  [Search box: "Search items..."]                 │
├──────────────────────────────────────────────────┤
│  [Show Filters]  [Clear Filters (n active)]      │
├──────────────────────────────────────────────────┤
│  Column A ⇅  │ Column B ▲  │ Column C ⇅  │ ... │  ← Header row
├──────────────┼─────────────┼─────────────┼──────┤
│  [dropdown]  │ [text input]│ [dropdown]  │ ...  │  ← Filter row (hidden by default)
├──────────────┼─────────────┼─────────────┼──────┤
│  data        │ data        │ data        │ ...  │  ← Data rows
│  ...         │ ...         │ ...         │ ...  │
└──────────────────────────────────────────────────┘
```

### Filter Controls

| Element | Behavior |
|---------|----------|
| **Show/Hide Filters** button | Toggles visibility of the filter row. Label changes to "Hide Filters" when visible. |
| **Clear Filters** button | Resets all column filters and search box. Clears filter count badge. |
| **Filter count badge** | Shows number of active column filters, e.g., `"Clear Filters (3 active)"`. Hidden when count is zero. |

### Tab-Scoped Independence

When the page has multiple tabs, each tab's table maintains fully independent state. Switching tabs does not affect the other tab's sort, filter, or search state.

### Auto-Refresh Considerations

If the page auto-refreshes to pick up new data:
- Filter/search/sort state is **lost** on refresh in the base implementation.
- Optional enhancement: persist state to `sessionStorage` keyed by table ID and restore on page load.

---

## 7. Implementation Notes

### Required DOM Structure

```html
<!-- Search box linked to table by ID -->
<input type="text" id="{tableId}Search"
       onkeyup="filterTable('{tableId}Search', '{tableId}')">

<!-- Filter controls -->
<button onclick="toggleFilterRow('{tableId}')">Show Filters</button>
<button onclick="clearFilters('{tableId}')">Clear Filters</button>

<!-- Table with consistent ID -->
<table class="data-table" id="{tableId}">
    <thead>
        <tr>
            <!-- Sortable scalar column -->
            <th class="sortable" onclick="sortTable('{tableId}', 0)">Name</th>

            <!-- Sortable list column -->
            <th class="sortable" data-column-type="list"
                onclick="sortTable('{tableId}', 1)">Categories</th>

            <!-- Non-sortable, non-filterable column -->
            <th data-no-filter>JSON Data</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td>Row value</td>
            <td>Cat A, Cat B</td>  <!-- List rendered with delimiter -->
            <td>...</td>
        </tr>
    </tbody>
</table>
```

### Key Functions

| Function | Responsibility |
|----------|---------------|
| `sortTable(tableId, columnIndex)` | Sort rows by column. Detect column type (scalar vs. list). Toggle direction. Update header indicators. |
| `initializeFilters(tableId)` | Scan column data, determine control type (select vs. text), handle list columns by exploding values, build filter row. |
| `applyAllFilters(tableId)` | Evaluate every row against all active filters + search. Use ANY-match for list columns, exact match for scalar columns. Set row visibility. Update filter count. |
| `filterTable(searchId, tableId)` | Read search input, store in search state, call `applyAllFilters()`. |
| `toggleFilterRow(tableId)` | Show/hide filter row. Lazy-initialize filters on first show. |
| `clearFilters(tableId)` | Reset all filter controls, clear search input, show all rows. |

### CSS Classes

| Class | Applied to | Purpose |
|-------|-----------|---------|
| `sortable` | `<th>` | Marks column as sortable, adds pointer cursor and sort indicator |
| `sort-asc` | `<th>` | Shows ascending indicator |
| `sort-desc` | `<th>` | Shows descending indicator |
| `filter-row` | `<tr>` | Styles the filter input row |
| `filter-input` | `<input>` | Styles text filter inputs |
| `filter-select` | `<select>` | Styles multi-select dropdowns |
| `filter-active` | `.filter-toggle-btn` | Indicates filters are visible |

### Data Attributes

| Attribute | Element | Purpose |
|-----------|---------|---------|
| `data-column-type="list"` | `<th>` | Identifies list-valued columns for filter/sort logic |
| `data-list-delimiter` | `<th>` | Override default `", "` delimiter for list parsing |
| `data-no-filter` | `<th>` | Exclude column from filter generation |
| `data-json` | `<td>` child | Stores raw JSON for search matching and modal display |

### Performance Considerations

- **Row count < 500**: No concerns. DOM manipulation is fast.
- **Row count 500-2000**: Filter/search should debounce keyup events (150-200ms delay) to avoid per-keystroke reflow.
- **Row count > 2000**: Consider virtual scrolling or server-side pagination. Client-side filtering alone will degrade.
- **List column explosion**: When building filter dropdowns for list columns with high total cardinality, cap the dropdown at the same 15-unique-value threshold (applied to the deduplicated union, not to the raw cell count).
