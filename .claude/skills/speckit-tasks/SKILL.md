---
name: speckit-tasks
description: Use after speckit-plan to decompose a design into an ordered, verifiable task list. Produces tasks.md, ready for implementation.
---

# speckit-tasks

Turns `plan.md` and its companions into `tasks.md`.

## Process

1. Read `spec.md`, `plan.md`, `data-model.md`, `contracts/`.
2. Decompose into tasks that are each **independently verifiable** — a task whose
   completion cannot be checked is not a task.
3. Order by dependency. Per §2, **the test task precedes the implementation task**
   for every behaviour.
4. Mark `[P]` only where tasks share no files and have no ordering dependency.
5. Every task states: files touched, exact verification command with expected
   result, and which FR/AC it covers.
6. Build the traceability table. **Every FR and AC maps to at least one task.** An
   unmapped requirement means the plan is incomplete — go back.

## Sizing

One behaviour per task. If a task's verification needs the word "and", split it.
If a task cannot be verified without three other tasks, the ordering is wrong.

## Red flags

| Thought | Reality |
|---------|---------|
| "Mark everything [P] to go faster" | Parallel tasks touching one file corrupt each other. `[P]` needs proof of independence. |
| "'Implement the parser' is a task" | Not verifiable. Split until each has a concrete pass/fail. |
| "Traceability is bookkeeping" | It is how you discover the plan silently dropped a requirement. |
