# Verity Studio — UI-Driven Authoring & Management

> **Status:** designed in detail 2026-04-30. See [docs/plans/studio-build-plan.md](../plans/studio-build-plan.md) for the comprehensive vision, architecture, development guidelines, testing strategy, and phased work plan.
>
> **Source:** introduced as a sketch 2026-04-25; promoted to a full build plan 2026-04-30.
> **Priority:** medium-high — the bottleneck on engineering for any composition work; productivity unlock for non-developer users.

## What this is

Verity Studio is the authoring frontend for Verity assets (agents, tasks, prompts, tools, configs, connectors). It turns Verity from a developer-only governance backend into a platform that the people accountable for AI behavior — underwriters, governance officers, compliance officers, SMEs — can use directly.

## Where to read more

The full design lives in [docs/plans/studio-build-plan.md](../plans/studio-build-plan.md), which covers:

1. **Vision** — beachhead, success criteria, anti-goals.
2. **Architecture** — four-mode IA (Compose / Validate / Deploy / Govern), composition model, embed-vs-share for prompts, reference-grammar UI, YAML round-trip, ephemeral LLM overrides, AI-assisted authoring, schema additions, new endpoints, frontend stack.
3. **Development guidelines** — naming, routing, templates, HTMX/Alpine usage, error handling, accessibility.
4. **Testing strategy** — pyramid, YAML round-trip property tests, champion-safety negative tests, browser golden paths.
5. **Work plan** — six phases (S0 foundations → S5 govern), with exit criteria and parallelization notes.
6. **Open questions** — items requiring resolution before S0 starts.

## Why this stub still exists

This file is kept as a redirect so anyone landing here from search or older links is pointed at the live plan. Do not edit design content here — edit the plan doc.
