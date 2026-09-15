# tweet-relay

Relays new posts from a configurable X profile to a single WhatsApp number.
Built **Spec-Driven** (SDD) as a learning exercise — the process is as much the
deliverable as the code.

## Non-negotiables

Read `.specify/memory/constitution.md` before writing any code. Its eight
principles bind every change. The two that get violated most often:

- **§1 Spec before code.** No implementation without an approved `spec.md`.
- **§4 All input is hostile.** We parse XML from volunteer-run mirrors and put the
  result into an outbound URL that carries a secret. Validate every byte.

## The SDD loop

Artifacts live in `specs/NNN-slug/`. Produce them by invoking the project skills
in order — do not hand-write them, that defeats the exercise:

| Step | Skill | Output |
|------|-------|--------|
| 1 | `/speckit-constitution` | `.specify/memory/constitution.md` (one-time) |
| 2 | `/speckit-specify` | `spec.md` — user stories + acceptance criteria, **no tech** |
| 3 | `/speckit-clarify` | resolves `[NEEDS CLARIFICATION]` markers in `spec.md` |
| 4 | `/speckit-plan` | `plan.md`, `research.md`, `data-model.md`, `contracts/` |
| 5 | `/speckit-tasks` | `tasks.md` — ordered, `[P]`-marked for parallel |
| 6 | `/speckit-implement` | code, TDD, per `tasks.md` |

The separation that makes SDD work: **`spec.md` describes behaviour and may not
name a library, protocol, or language.** Tech decisions belong in `plan.md`. If
you catch yourself writing "RSS" or "Docker" in a spec, stop.

## Process skills (already installed — do not reimplement)

The `superpowers` plugin owns the process layer:

- `superpowers:brainstorming` — before any creative/design work
- `superpowers:test-driven-development` — the red/green/refactor loop
- `superpowers:systematic-debugging` — before proposing any bug fix
- `superpowers:verification-before-completion` — before claiming anything works
- `superpowers:requesting-code-review` — before merging

## Commands

Everything runs in Docker; there is no host Python environment.

```bash
docker compose build
docker compose run --rm relay pytest            # full suite
docker compose run --rm relay pytest tests/adversarial -v
docker compose run --rm relay check-source      # which mirror answered, what parsed
docker compose run --rm relay run --once --dry-run
docker compose run --rm relay test-whatsapp     # sends one real message
docker compose up -d                            # the actual relay
docker compose logs -f relay
```

## Project facts that are easy to get wrong

These were established by probing live services on 2026-09-15. Full evidence in
`specs/001-tweet-to-whatsapp/research.md`.

1. **`<guid>` in the feed is the bare tweet ID** (snowflake integer).
2. **The feed is not date-ordered.** Always sort by `published_at` yourself.
3. **Retweets carry the *original* tweet's ID**, which can be years old. Therefore
   **dedup is a bounded set of seen IDs, never a `since_id` high-water mark.** A
   high-water mark silently swallows retweets. This is the #1 correctness trap.
4. **The X API is not an option** — no free tier since 2026-02-06, and this project
   is free-services-only.
5. **Mirrors die.** `xcancel.com`, `nitter.net` and `nitter.poast.org` all died in
   2026. Four working mirrors are pinned in `.env.example`; expect churn.

## Secrets

`.env` is gitignored and holds `CALLMEBOT_APIKEY`. Never log it, never put it in an
exception message, never commit it. `tests/adversarial/` asserts this.
