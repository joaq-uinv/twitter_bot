---
name: speckit-specify
description: Use when turning a feature idea into a formal specification - the WHAT and WHY, never the HOW. Creates specs/NNN-slug/spec.md. Run before any planning or implementation.
---

# speckit-specify

Produces `specs/NNN-slug/spec.md` from a feature description.

## Process

1. Read `.specify/memory/constitution.md`.
2. Scan `specs/` for the highest `NNN`; the new feature is `NNN+1`, zero-padded to 3.
   Slug is 2-4 kebab words from the description.
3. Create `specs/NNN-slug/` and apply `.specify/templates/spec-template.md`.
4. Write user scenarios with **testable** acceptance criteria in Given/When/Then form.
   "The system should be reliable" is not testable. "Given all sources fail, when a
   poll runs, then the operator receives exactly one notification" is.
5. **Enumerate edge cases aggressively.** This is where a spec earns its cost. For
   each external input ask: what if it is missing, malformed, duplicated, enormous,
   out of order, hostile, or from the wrong party?
6. Mark every unknown `[NEEDS CLARIFICATION: specific question]`. Do not guess and do
   not paper over a gap with a plausible default.
7. Report the clarification count to the user.

## The hard rule (constitution §1)

**A spec may not name a language, library, protocol, vendor or data format.**

- ✅ "The system retrieves posts published by the monitored account."
- ❌ "The system fetches the Nitter RSS feed and parses it with defusedxml."

If a constraint genuinely is a requirement rather than a choice — "must cost nothing
to run" — state it as a constraint on outcomes, not as a technology.

## Red flags

| Thought | Reality |
|---------|---------|
| "Obviously we'll use X, I'll just write it down" | That is `plan.md`. Specs that name tech cannot be re-planned. |
| "I'll assume a sensible default" | Mark `[NEEDS CLARIFICATION]`. Assumptions hide decisions the user wanted. |
| "Edge cases can wait for implementation" | Edge cases found at implementation time get fixed by whoever is least equipped to decide. |
