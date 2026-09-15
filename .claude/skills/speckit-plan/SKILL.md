---
name: speckit-plan
description: Use after a spec is clarified to design the technical solution - produces plan.md, research.md, data-model.md and contracts/. This is where technology choices belong.
---

# speckit-plan

Turns an approved spec into a technical design. **This is the only place technology
gets chosen.**

## Process

1. Read `.specify/memory/constitution.md` and `spec.md`. **Refuse to proceed while
   any `[NEEDS CLARIFICATION]` remains** — run `/speckit-clarify` instead.
2. **Fill the Constitution Gate table first.** Any "no" blocks the plan. Redesign,
   or amend the constitution deliberately. Never proceed with a failing gate.
3. **Research before deciding, and verify claims against reality.** Documentation
   and blog posts go stale; services die. Where a decision rests on an external
   service behaving a certain way, probe it and record the observed result with a
   date in `research.md`. An unverified assumption at the centre of a design is the
   most expensive kind of mistake.
4. Write `plan.md` from the template: technical context, architecture, decision
   table with rejected alternatives, risks.
5. Write `data-model.md` — entities, fields, types, invariants, validation rules.
6. Write `contracts/` — one file per adapter interface (§3), with the failure modes
   each implementation must handle.
7. Write `quickstart.md` — how a human verifies the feature end to end.

## Design decisions must record rejected alternatives

A decision table with no rejected alternatives is a preference, not a decision. For
each: what was chosen, what was rejected, and the property that decided it.

## Red flags

| Thought | Reality |
|---------|---------|
| "The docs say the API works this way" | Docs lie and services die. Probe it; record the date. |
| "I'll pick the obvious library" | Record what you rejected and why, or the next reader re-opens the question. |
| "The gate table is boilerplate" | It is the only automatic check that the constitution is real. |
