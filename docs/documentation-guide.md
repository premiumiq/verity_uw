# Verity Documentation Guide

How the `docs/` tree is organized, where each kind of content lives, and the conventions every doc follows. Read this before adding or restructuring documentation.

---

## Map of `docs/`

```
docs/
├── README → ../README.md (the project pitch + map)
├── VERITY_COMBINED_PRD_v3.md   ← canonical PRD (treat as immutable; vision.md is its narrative summary)
├── vision.md                   ← exec-facing narrative (the “why” + 3-layer architecture)
├── documentation-guide.md      ← this file
├── example-end-to-end.md       ← worked walkthrough of one D&O submission
│
├── architecture/               ← technical reference for system internals
│   ├── technical-design.md     ← every component in depth
│   ├── execution.md            ← Task / Agent contracts, declarative I/O grammar
│   ├── decision-logging.md     ← what gets logged at what level
│   ├── logging.md              ← operational / structured logs
│   └── decisions.md            ← ADR log (architectural decisions)
│
├── development/                ← what application developers need
│   ├── application-guide.md    ← anatomy + composition + orchestration (single cohesive doc)
│   └── web-ui-design.md        ← UI conventions for any Verity-rendered admin pages
│
├── api/
│   └── api_and_ds_workbench.md ← REST API surface + DS Workbench notes
│
├── apps/                       ← side / companion applications (one file each)
│   ├── vault.md                ← Vault — document store
│   ├── uw-demo.md              ← Underwriting reference application
│   └── ds-workbench.md         ← JupyterLab workbench
│
├── guides/                     ← operational how-tos
│   ├── initial_setup.md
│   ├── running_apps.md
│   ├── live_execution.md
│   ├── seed_data_validation.md
│   └── web_ui_validation.md
│
├── enhancements/               ← designed-but-not-built capabilities
│   ├── README.md               ← categorized index with status tags
│   └── *.md                    ← one file per enhancement
│
├── glossary/                   ← term-per-file vocabulary
│   ├── README.md               ← alphabetical index + how-to-use
│   └── *.md                    ← one file per term, kebab-case
│
├── diagrams/                   ← Excalidraw / D2 / SVG sources
│   ├── verity_db.excalidraw
│   ├── verity_db_conceptual_model.{d2,svg,excalidraw}
│
└── archive/                    ← historical plans, kept for traceability (not authoritative)
    └── *.md
```

---

## Doc taxonomy — four tiers

Every doc is one of:

| Tier | Examples | Audience | Tooltip convention |
|---|---|---|---|
| **Major** | README · vision.md · getting-started.md · example-end-to-end.md | Execs, new readers, demo viewers | `<abbr>` tooltips on first use of glossary terms |
| **Detailed reference** | application-guide.md · architecture/* · enhancements/* · apps/* · api/* | Developers, architects | Plain markdown links (no `<abbr>` — keeps source readable) |
| **Operational** | guides/* | Operators running the system | Plain links; tooltips only for terms a non-developer wouldn't know |
| **Archive / Historical** | archive/* | Researchers, future maintainers asking "why was this done" | No retrofit. Frozen at the time they moved to archive. |

The tier decides linking style. **Don't** retrofit tooltips into detailed-reference or archive docs — the verbosity hurts more than it helps when the reader is already in deep technical context.

---

## Linking conventions

### Glossary references

**Major docs — reference-style with title attribute (DRY pattern):**

In the body, use the terse reference-link form:

```markdown
The [Source Binder][source-binder] fetches data per source_binding row before the LLM call.

Later, the [Source Binder][source-binder] also handles content_blocks bindings.
```

At the **bottom of the file**, define each reference once with the tooltip text as the link title (third positional arg of the markdown link reference syntax):

```markdown
<!-- ─────────────────────── Glossary references ─────────────────────────────── -->
[source-binder]: docs/glossary/source-binder.md "Pre-LLM resolver that fetches data per source_binding row..."
[reference-grammar]: docs/glossary/reference-grammar.md "Four-pattern DSL for I/O wiring..."
[vault]: docs/glossary/vault.md "Companion document service..."
```

Hover gives the tooltip (browser renders the `title` attribute as a popover); click navigates to the glossary file. **One definition per term per file** — no repetition in the body.

> Path adjustment: README is at the project root → `docs/glossary/<term>.md`. Major docs inside `docs/` → `glossary/<term>.md`.

**Why this over inline `<abbr>`:** the inline pattern duplicated the tooltip text on every occurrence, making the source unreadable and breaking single-source-of-truth (a glossary edit had to be propagated to N inline copies). The reference-style form keeps each tooltip in **one place per file**. A future sync script (`tools/sync_glossary_refs.py`) will propagate changes from `glossary/*.md` into all major docs' references blocks; for now manual sync across the small set of major docs is fast.

**Detailed-reference docs:**

```markdown
The [Source Binder](../glossary/source-binder.md) fetches data...
```

Plain link only — no title attribute, no reference block. The doc is already in deep technical context; the reader can click through if they need a definition. VS Code Cmd+hover shows a preview of the linked file, which is enough.

**Within glossary files (cross-references):**

```markdown
## See also
- [Reference Grammar](reference-grammar.md)
```

Bare relative filenames inside the glossary directory.

### Cross-doc references

Always relative paths. Examples:

| From | To | Path |
|---|---|---|
| `README.md` | `docs/vision.md` | `docs/vision.md` |
| `docs/vision.md` | `docs/architecture/execution.md` | `architecture/execution.md` |
| `docs/development/application-guide.md` | `docs/example-end-to-end.md` | `../example-end-to-end.md` |
| `docs/glossary/vault.md` | `docs/apps/vault.md` | `../apps/vault.md` |
| `docs/architecture/execution.md` | `verity/src/verity/runtime/engine.py` | `../../verity/src/verity/runtime/engine.py` |

### Code-symbol references

When pointing at a specific function/class:

```markdown
See `_resolve_source_bindings` in [`runtime/engine.py`](../../verity/src/verity/runtime/engine.py).
```

The link is to the file; the function name is in code formatting. We don't link to a specific line because line numbers shift.

---

## File naming conventions

- **Kebab-case for everything new.** `application-guide.md`, not `application_guide.md` or `applicationGuide.md`.
- Existing files in `guides/` use `snake_case` — leave them alone (they're stable references in other docs); use kebab-case for any new file.
- The PRD (`VERITY_COMBINED_PRD_v3.md`) is the one exception — it's the canonical source artifact, kept verbatim from its original name.

---

## Glossary conventions

See [`glossary/README.md`](glossary/README.md) for the full template. Short version:

- **One term per file**, kebab-case filename, term name as the H1
- **Tooltip line** at the top (`> **Tooltip:** ...`) — one sentence, plain text only
- **Definition** — one paragraph
- **See also** — bullet list of related terms
- **Source** — link to the canonical file (schema, code, or architecture doc)

When to add a term: it appears in **more than one doc**, has a **non-obvious meaning**, and doesn't already have an obvious 1-line definition somewhere prominent.

When **not** to add: implementation details that change every release; project-management terms; anything documented only for archive/historical context.

---

## Diagram conventions

Three formats, three reasons:

| Format | When to use | Source location |
|---|---|---|
| **Excalidraw** (`.excalidraw`) | Narrative, hand-tuned diagrams (architecture overviews, conceptual models read by execs) | `docs/diagrams/` |
| **D2** (`.d2` + rendered `.svg`) | Living technical diagrams that change as schema evolves; auto-layout, text-diffable | `docs/diagrams/` |
| **Mermaid** (inline in `.md`) | Sequence diagrams, simple flowcharts inline with prose | wherever the prose lives |

Rendering:

- D2: `d2 input.d2 output.svg` — commit both source and rendered SVG so GitHub renders it inline
- Excalidraw: edit in excalidraw.com or VS Code extension — commit the `.excalidraw` source and (optionally) a `.png` export for GitHub rendering
- Mermaid: GitHub renders mermaid blocks natively, no tooling needed

---

## Adding a new enhancement

1. Create `docs/enhancements/<kebab-case>.md`
2. Front-matter (no YAML — just markdown):
   ```markdown
   # Title

   > **Status:** planned | partial | designed
   > **Source:** link to vision section / archive plan / external doc
   > **Priority:** high | medium | low
   ```
3. Sections: *What's missing today* · *Proposed approach* · *Acceptance criteria* · *Notes*
4. Add a row to the right table in `enhancements/README.md`
5. If a still-relevant archived plan was the source, link to it in `archive/`

---

## Editing the PRD vs the vision doc

- The PRD (`VERITY_COMBINED_PRD_v3.md`) is **immutable** for this version. Treat it as a frozen artifact. New requirements → start a `v4` PRD or land them as enhancements.
- `vision.md` is the **narrative summary** of the PRD — exec-facing prose, three-layer architecture diagrams, the "five capabilities" framing. Edits here are fine; keep them aligned with the PRD's intent.

---

## Editing CLAUDE.md

`CLAUDE.md` at the repo root carries operating instructions for Claude Code (the AI assistant used in this project). Treat it like any other doc:

- Architectural decisions → also write an ADR in `architecture/decisions.md`
- Coding conventions → live here
- Project-specific Claude Code behavior → live here

When something in CLAUDE.md becomes stale (e.g. an old folder layout), update both CLAUDE.md and this doc in the same change.

---

## Archive policy

Move a doc to `docs/archive/` when:

1. It was a plan for work that has shipped, **and**
2. The shipped reality is now documented in a canonical doc (technical-design, execution, etc.), **and**
3. The historical plan still has value as "why was it done this way" reading

Mine the file for any **un-shipped follow-ups** before archiving — those become entries in `enhancements/`, with a back-link to the archive file.

Don't archive: anything currently being implemented; design docs that are still authoritative.

Don't `git rm`: keep history searchable. The archive directory is small and adds little weight.

---

## Reading paths for new readers

- **First time, exec-level:** [README](../README.md) → [vision.md](vision.md) → [example-end-to-end.md](example-end-to-end.md)
- **First time, developer:** README → [getting-started](guides/initial_setup.md) → [example-end-to-end.md](example-end-to-end.md) → [development/application-guide.md](development/application-guide.md)
- **Architect doing a system review:** vision.md → [architecture/technical-design.md](architecture/technical-design.md) → [architecture/execution.md](architecture/execution.md) → [diagrams/verity_db_conceptual_model.svg](diagrams/verity_db_conceptual_model.svg)
- **Looking up a term:** [glossary/](glossary/README.md)
- **Planning what's next:** [enhancements/](enhancements/README.md)
- **"Why is it this way?":** [architecture/decisions.md](architecture/decisions.md), then [archive/](archive/)
