---
name: speckit-constitution
description: Use when creating or amending the project constitution - the binding engineering principles that every spec, plan and code change must satisfy. Run once at project start, then only to amend.
---

# speckit-constitution

The constitution is the one document that outranks every spec. It exists to stop
an agent rationalising its way into shortcuts under deadline pressure.

## Process

1. Read `.specify/memory/constitution.md` if it exists. Amending is the common case.
2. Derive principles from **this project's actual failure modes**, not a generic list.
   Ask: what will someone be tempted to do wrong here? Each principle should forbid
   something specific and plausible.
3. Each principle gets: a number, a short imperative name, and a rationale tying it
   to a real risk. A principle nobody could violate is decoration — cut it.
4. Cap at ~8. A constitution nobody can recite is not enforced.
5. Write to `.specify/memory/constitution.md`.

## Amending

Never silently rewrite. State which principle changed, why, and what it now permits
that it previously forbade. Append to the Amendment section.

## Red flags

| Thought | Reality |
|---------|---------|
| "Adopt all nine spec-kit articles" | They target multi-library products. Adapt deliberately, and say you adapted. |
| "This principle is obviously good" | If it forbids nothing concrete, it earns nothing. |
| "The spec needs this exception" | Then amend the constitution explicitly, or comply. Never quietly. |
