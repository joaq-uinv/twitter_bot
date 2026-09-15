---
name: speckit-clarify
description: Use after speckit-specify when a spec contains NEEDS CLARIFICATION markers - resolves ambiguity by asking the user, before planning begins.
---

# speckit-clarify

Drives every `[NEEDS CLARIFICATION]` in a spec to a decision.

## Process

1. Read the spec; collect all markers.
2. Rank by blast radius — a question that changes the architecture outranks a
   question about message wording.
3. Ask with `AskUserQuestion`. Offer concrete options with real trade-offs, and say
   which you recommend and why. Batch related questions; never exceed 4 at a time.
4. Replace each marker **in place** with the decision. Add a `## Decisions` entry
   recording what was chosen and the reasoning, so it survives context loss.
5. Re-read the spec for contradictions the new answers introduced.
6. Stop when zero markers remain. Implementation is blocked until then.

## Ask about

Scope boundaries, behaviour under failure, volume and rate limits, what to do on
first run, retention, who is notified and when, and any place two readings of the
spec would produce materially different software.

## Do not ask about

Anything answerable from the repo, the constitution, or an obvious convention.
Burning a question on something you could look up costs the user's attention.
