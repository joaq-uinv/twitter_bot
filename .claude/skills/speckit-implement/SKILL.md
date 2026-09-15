---
name: speckit-implement
description: Use to execute tasks.md - drives the TDD implementation loop against an approved plan, one task at a time.
---

# speckit-implement

Executes `tasks.md` in order.

## Process

1. Read the constitution, `spec.md`, `plan.md`, `tasks.md`.
2. Invoke `superpowers:test-driven-development` and follow it. Do not reimplement
   the TDD loop here.
3. For each task in order:
   - Write the failing test. **Run it. Watch it fail for the expected reason** — a
     test that passes before the code exists is testing nothing.
   - Implement the minimum that passes.
   - Run the verification command from the task.
   - Tick the box in `tasks.md` only after the command actually passed.
4. When a bug appears, invoke `superpowers:systematic-debugging` before proposing a
   fix. Do not pattern-match a guess onto a symptom.
5. Before claiming completion, invoke `superpowers:verification-before-completion`.

## When the plan is wrong

Implementation reveals what planning missed. When a task cannot be done as written:

**Stop. Say so. Fix the plan, then continue.** Do not silently implement something
different from the approved design — the spec is the source of truth, and a
divergence nobody recorded is how the two drift apart permanently.

## Red flags

| Thought | Reality |
|---------|---------|
| "I'll write the test after, it's faster" | §2 violation. The test that follows the code is shaped by the code's bugs. |
| "Close enough, tick the box" | Tick only after the verification command passed. |
| "I'll deviate slightly from the plan" | Record it and amend, or comply. Silent drift kills SDD. |
