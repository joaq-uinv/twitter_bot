# Quickstart: verify mirror health end to end

Run from the repo root. Each step names the requirement it proves.

## 1. One-time setup (operator)

```bash
# Enable GitHub Pages with "GitHub Actions" as the source (research R-4: currently off).
gh api -X POST repos/joaq-uinv/twitter_bot/pages -f build_type=workflow

# Second Healthchecks check, "tweet-relay mirrors": Period 6 hours, Grace 18 hours
# (24 h total = D-1). Then store its ping URL:
gh secret set HEALTHCHECKS_MIRRORS_PING_URL
```

## 2. Local, no network (§5)

```bash
docker compose run --rm --entrypoint python relay -m pytest            # all green
docker compose run --rm --entrypoint python relay -m pytest tests/adversarial -v
```

## 3. Local probe against real mirrors (sends nothing, FR-2)

```bash
mkdir -p /tmp/mh-data /tmp/mh-site
docker compose run --rm -v /tmp/mh-data:/mh-data -v /tmp/mh-site:/mh-site relay \
  probe-mirrors --data /mh-data --site-out /mh-site; echo "exit=$?"
```

Expect:
- An exit code of `0`, or `3` if at risk.
- `/mh-data/history.jsonl` with one line per mirror.
- `/mh-site/status.json`.
- A **reason label for every unhealthy mirror** (compare with research R-2).

Then run:

```bash
grep -c . /tmp/mh-data/history.jsonl
python3 -I -m json.tool /tmp/mh-site/status.json | head -40
```

Check that **no response text appears anywhere** (FR-16): only hosts, labels,
times and numbers.

## 4. The page (US-3, FR-17)

Serve `site/` with the generated `status.json` and open it on a desktop **and** a
phone-width window. Check:
- The banner verdict matches the exit code.
- Every in-use mirror shows its status, reason, response time and newest-post age.
- Candidates are ranked healthy first.
- Edit `generated_at` in `status.json` to 13 hours ago and reload: **the stale
  warning appears** (AC-3.3).

## 5. Alerts (US-1, US-2; D-3 revised)

| Scenario | How to produce it | Expected |
|---|---|---|
| At risk | Run with `NITTER_INSTANCES` set to one working mirror and one dead one | Exit `3`. The run fails and the summary says **at risk**. Healthchecks goes DOWN once; a second at-risk run sends **no** new Healthchecks email, but GitHub emails again |
| All clear | Restore the config and run again | Exit `0`. Healthchecks goes UP: one all-clear |
| Check broken | Run with `--data` pointing at an unwritable path | Exit `1`. The summary says **check broken**. No Healthchecks ping |
| Soft warning | Feed the tracker two unhealthy rounds 24 h apart (unit test) or wait | One issue `Mirror unhealthy for 24h: <host>`; closed on recovery |

## 6. Live (after merge)

The `publish` job uses the `github-pages` environment. Its default protection only
allows the default branch, so run the workflow from `main`.

```bash
gh workflow run mirrors.yml && gh run watch
```

Then open `https://joaq-uinv.github.io/twitter_bot/` and confirm it matches step 3.
Check that the `mirror-status` branch has exactly one commit:

```bash
git fetch origin mirror-status && git log --oneline origin/mirror-status | wc -l   # 1
```
