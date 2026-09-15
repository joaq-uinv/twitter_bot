# Tasks: Tweet → WhatsApp Relay

**Plan:** `./plan.md` | `[P]` = parallelisable (no shared files, no ordering dependency)

Per §2, each test task precedes its implementation task. Tick a box only after the
stated verification command actually passed.

All commands run in the container: `docker compose run --rm relay <cmd>`

---

## P1 — Foundations

- [ ] **T001** Package skeleton + `pyproject.toml` (deps: httpx, defusedxml,
      pydantic-settings, pytest, hypothesis, respx) + `Dockerfile` + `docker-compose.yml`
  - **Files:** `pyproject.toml`, `Dockerfile`, `docker-compose.yml`, `src/tweet_relay/__init__.py`
  - **Verify:** `docker compose build` succeeds; `pytest --version` runs in the image
- [ ] **T002** [P] `models.py` — `Tweet`, `TweetKind`, `SourceUnavailable`, `DeliveryFailed`
  - **Verify:** `pytest tests/unit/test_models.py` — **Covers:** data-model
- [ ] **T003** Tests for handle extraction + config validation, incl. rejection of
      `https://evil.com/x`, `https://x.com/../../admin`, 16-char and empty handles
  - **Verify:** fails before T004 — **Covers:** AC-5.2, E-20
- [ ] **T004** `config.py` implementing T003
  - **Verify:** `pytest tests/unit/test_config.py` — **Covers:** FR-1, AC-5.2, E-20

## P2 — Source

- [ ] **T005** Parser tests over `tests/fixtures/santtiagom_.xml`: 19 items parsed,
      kinds classified, out-of-order input, `guid`→id, `#m` stripped, host rewritten
  - **Verify:** fails before T006 — **Covers:** FR-3, FR-4, E-1
- [ ] **T006** `sources/nitter_rss.py` parsing + classification + URL normalisation
  - **Verify:** `pytest tests/unit/test_nitter_parse.py` — **Covers:** FR-3/4/7, DD-3/4/5
- [ ] **T007** Failover tests (respx): 1st mirror 500 → 2nd used; all fail →
      `SourceUnavailable`; wrong-account channel title → `SourceUnavailable`
  - **Verify:** fails before T008 — **Covers:** FR-9, E-7
- [ ] **T008** Failover, byte cap, timeout, no-cross-host-redirect in `nitter_rss.py`
  - **Verify:** `pytest tests/unit/test_nitter_fetch.py` — **Covers:** FR-8/9, E-9, E-18
- [ ] **T009** **GATE (DD-9):** probe the syndication endpoint from inside the container.
      Returns data → implement `sources/syndication.py` + tests. Still 429/blocked →
      **delete the adapter** and record resolution in `plan.md`
  - **Verify:** either its tests pass, or no `syndication.py` exists and DD-9 is updated

## P3 — State

- [ ] **T010** State tests: round-trip; membership not high-water (insert an **old** ID,
      assert still undelivered); 300-cap eviction; handle-change resets; corrupt/truncated
      /wrong-schema recovery; atomic write leaves no partial file; concurrent lock
  - **Verify:** fails before T011 — **Covers:** FR-2/5/6, E-6, E-16, E-17, DD-1, DD-2
- [ ] **T011** `state.py` implementing T010
  - **Verify:** `pytest tests/unit/test_state.py`

## P4 — Sink and formatting

- [ ] **T012** [P] Formatter tests: RT/quote markers, 900-char truncation with link
      surviving, control/bidi stripping, emoji intact
  - **Verify:** fails before T013 — **Covers:** E-13, data-model rendering
- [ ] **T013** [P] `formatter.py`
  - **Verify:** `pytest tests/unit/test_formatter.py`
- [ ] **T014** Sink tests (respx): params encoded not interpolated; 200-with-error-body
      → `DeliveryFailed`; 5xx retried then raises; apikey absent from logs and repr
  - **Verify:** fails before T015 — **Covers:** FR-12, FR-13, E-19
- [ ] **T015** `sinks/callmebot.py` + `sinks/console.py`
  - **Verify:** `pytest tests/unit/test_callmebot.py`

## P5 — Pipeline

- [ ] **T016** Pipeline tests: filtering by kind; chronological delivery; cap withholds
      (not drops) and drains next check; bootstrap sends exactly one liveness message;
      no liveness on restart; partial-send failure keeps 1-2 seen and retries 3-5;
      outage notified once and re-armed on recovery
  - **Verify:** fails before T017
  - **Covers:** AC-1.1/1.2/1.3, AC-2.1/2.3/2.4, AC-3.1/3.2/3.3, AC-4.1/4.2/4.3,
    FR-2/3/4/10/11/12, E-5, E-14, D-2, D-3, DD-6, DD-7
- [ ] **T017** `pipeline.py` implementing T016
  - **Verify:** `pytest tests/unit/test_pipeline.py`
- [ ] **T018** [P] `cli.py` — `run [--once] [--dry-run]`, `check-source`, `test-whatsapp`
  - **Verify:** `check-source` prints mirror + parsed items

## P6 — Adversarial (`tests/adversarial/`)

- [ ] **T019** Hostile XML: XXE (assert entity unresolved), billion-laughs (bounded
      time), decompression bomb, 50MB body, truncated XML, valid-XML-not-RSS, items
      missing guid/link/pubDate — **Covers:** FR-8, E-8, E-9, E-10
- [ ] **T020** [P] Malicious content: wrong-account channel title; link to
      `evil.com/status/1`; guid non-numeric/negative/10³⁰; duplicate guids; pubDate
      future/unparseable/1970; text with script tags, U+202E, zero-width, NUL, 10k
      chars, 4-byte emoji — **Covers:** FR-7, E-3, E-7, E-10, E-12
- [ ] **T021** [P] Sink injection: text containing `&text=`, `&apikey=`, `#`, newlines;
      assert outgoing query parses back to exactly one `text` param; suite-wide log
      capture asserts the apikey never appears — **Covers:** FR-13, E-11
- [ ] **T022** [P] SSRF/config: `NITTER_INSTANCES` with `http://169.254.169.254/`,
      `file:///etc/passwd`, `http://localhost:22`, `http://10.0.0.1` all rejected;
      https-only enforced — **Covers:** E-20
- [ ] **T023** [P] Network: all mirrors 429/500/timeout → one notification, state
      untouched; hanging mirror hits timeout; 200 empty body; cross-host redirect not
      followed — **Covers:** FR-9, FR-10, E-18
- [ ] **T024** [P] Property-based (hypothesis): for any feed permutation the delivered
      **set** is identical and ordering is chronological; N runs over one feed deliver
      each post exactly once — **Covers:** FR-2, FR-3, FR-5, E-1, E-2

## P7 — Runtime

- [ ] **T025** `scheduler.py` — interval + jitter, SIGTERM-aware
  - **Verify:** `pytest tests/unit/test_scheduler.py`; `docker compose up` logs 2 cycles
- [ ] **T026** Compose healthcheck on `last_success` age + log rotation; `.env.example`
  - **Verify:** `docker compose ps` reports healthy
- [ ] **T027** Live integration (marked, excluded by default): real mirror fetch + real
      WhatsApp send — **Verify:** `pytest -m live`; message arrives on the phone
- [ ] **T028** Full `quickstart.md` walkthrough on a clean checkout
  - **Verify:** every step executes as written

---

## Traceability

| Requirement | Tasks |
|-------------|-------|
| FR-1 | T004, T025 |
| FR-2 | T010, T011, T016, T024 |
| FR-3 | T005, T006, T016, T024 |
| FR-4 | T005, T006, T016 |
| FR-5 | T010, T011, T024 |
| FR-6 | T010, T011 |
| FR-7 | T007, T008, T020 |
| FR-8 | T008, T019, T020 |
| FR-9 | T007, T008, T023 |
| FR-10 | T016, T023 |
| FR-11 | T016, T017 |
| FR-12 | T014, T015, T016 |
| FR-13 | T014, T021 |
| FR-14 | T009 (no paid source), research R-1 |
| AC-1.1/1.2/1.3 | T016 |
| AC-2.1/2.2/2.3/2.4 | T005, T016, T024 |
| AC-3.1/3.2/3.3 | T016 |
| AC-4.1/4.2/4.3 | T016, T023 |
| AC-5.1 | T010, T016 |
| AC-5.2 | T003, T004 |
| E-1..E-3 | T005, T020, T024 |
| E-5, E-6 | T010, T016 |
| E-7..E-11 | T019, T020, T021 |
| E-12..E-14 | T012, T016, T020 |
| E-16..E-20 | T010, T022, T023 |
