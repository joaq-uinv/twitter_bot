# Tasks: [NAME]

**Plan:** `./plan.md`

`[P]` = parallelisable (no shared files, no ordering dependency).
Each task states its verification. Per §2, test tasks precede implementation tasks.

## Phase N: [name]

- [ ] **T001** [P] Description
  - **Files:** `path`
  - **Verify:** exact command + expected result
  - **Covers:** FR-1, AC-1.1

## Traceability

Every FR and AC in `spec.md` maps to at least one task.

| Requirement | Tasks |
|-------------|-------|
