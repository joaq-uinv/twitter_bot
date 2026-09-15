# Constitution — tweet-relay

Ratified 2026-09-15. These principles bind every spec, plan, task and line of code.
A change that violates one is rejected in review regardless of whether it works.

Spec-Kit ships nine articles written for multi-library products. Adopting all nine
here would be cargo-culting, so this is a deliberate adaptation: eight principles
that actually constrain a single-package relay with an untrusted upstream.

---

## §1 — Spec before code

No implementation begins without an approved `spec.md`. A spec describes
**observable behaviour and acceptance criteria**. It may not name a language,
library, protocol or vendor — those are `plan.md` decisions. If a spec mentions
"RSS" or "Docker", it has leaked implementation and must be rewritten.

## §2 — Test-first

Red → green → refactor. A failing test precedes every behaviour. "I'll add tests
after" is a §2 violation, not a scheduling preference.

## §3 — Adapters at the edges

Every external system — tweet source, message sink, state store, clock — sits
behind an interface defined in `contracts/`. Non-negotiable: our upstream is a
rotating cast of volunteer-run mirrors that die without notice. Swapping one must
be a single new adapter, never a change to pipeline logic.

## §4 — All input is hostile

Feed bytes come from an untrusted third party and end up interpolated into an
outbound URL carrying a secret. Therefore:

- XML is parsed with a hardened parser. Never stdlib `ElementTree`.
- Response bodies are size-capped before parsing.
- Every field is validated for shape before use: IDs are integers, links match an
  expected path form, the channel must identify the account we asked for.
- Outbound URLs are built by the HTTP client's encoder. Never string interpolation.
- A malformed item is dropped and logged. It never crashes the run and never
  corrupts state.

## §5 — No network in unit tests

Unit and adversarial tests make zero network calls; they run against fixtures
captured from real responses. Tests that touch the network live in
`tests/integration/`, are marked, and are excluded from the default run.

## §6 — Secrets via environment only

Secrets arrive as environment variables. Never committed, never logged, never
included in an exception message or traceback. This is asserted by a test that
scans captured log output for the key.

## §7 — Fail loud

A relay that silently stops relaying is indistinguishable from a quiet account, and
that is the worst failure mode this system has. Total source failure notifies the
operator. Degraded states are logged at WARNING with the reason. Silence means
healthy — never means broken.

## §8 — Simplicity

One package, one entrypoint. No abstraction without a second caller. No
configuration option without a use case. Delete before you add.

---

## Amendment

Amending this document requires stating which principle changed, why, and what it
now permits that it previously forbade. Record amendments below.

*(none yet)*
