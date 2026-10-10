# Research: Mirror Health & Status Page

**Date of probing:** 2026-10-10, 18:14–18:16 UTC. Everything below was **observed by
making real requests** from the operator's machine, one request per host. Re-verify
before trusting any of it after about 2026-12: mirrors change weekly.

## R-1: Which community list to discover from

| Candidate | Probed result | Verdict |
|---|---|---|
| `https://status.d420.de/api/v1/instances` | HTTP 200, `application/json`, 10.5 kB, 1.7 s. `last_update` was **7 seconds** before the probe | **Selected** |
| `https://raw.githubusercontent.com/wiki/zedeus/nitter/Instances.md` | HTTP 200, markdown, 5.4 kB | Rejected: **stale**. It still lists `xcancel.com` and `nitter.poast.org` as ✅ working, and both were dead on 2026-09-15 (001 research R-1) |
| `https://github.com/zedeus/nitter/wiki/Instances` | HTTP 200, 224 kB of HTML | Rejected: the same stale content, wrapped in HTML that would need scraping |
| Farside (`farside.link`) | Not probed | Rejected by design: it redirects to one instance and is not a list |

**Observed `status.d420.de` format** (top level `{"hosts": [...], "last_update": ..., "latest_commit": ...}`):

| Field | Example | Used? |
|---|---|---|
| `url` | `"https://nitter.pp.ua"` | **Yes.** It is the only field we take, and it must pass FR-11 validation |
| `domain` | `"nitter.pp.ua"` | As a consistency check only: it must equal `url`'s host, or the entry is dropped |
| `rss`, `healthy`, `points`, `country`, `version`, … | — | **No.** They are third-party claims about third-party hosts. We measure health ourselves, and nothing from the list is published (FR-16) |

There were 9 hosts on 2026-10-10, well under the cap of 25. All 4 in-use mirrors
appear in the list. They are excluded from candidates (FR-13, E-12), which leaves 5
candidates.

## R-2: The state of the in-use mirrors today

The feature turns out to be needed already. One `GET /santtiagom_/rss` per host,
with the relay's User-Agent:

| Host | Role | Result | Spec 002 label |
|---|---|---|---|
| `nitter.kareem.one` | in use | 200, valid feed, 17 items, 1.3 s | usable, fresh |
| `nitter.meowing.monster` | in use | 200, valid feed, 18 items, **12.0 s** | usable, fresh (the relay timeout is 15 s) |
| `nitter.netbub.com` | in use | **307** to `?__goaway_challenge=cookie…` | `sent elsewhere` |
| `nitter.jaydenha.uk` | in use | **200 with an HTML "Nitter Access Queue" page** | `malformed content` |
| `shitter.thepixora.com` | listed | 200, valid feed, 18 items, 2.5 s | usable, fresh |
| `nitter.pp.ua` | listed | 200, valid feed, 18 items, 1.5 s | usable, fresh |
| `nitter.tiekoetter.com` | listed | 403, HTML | `refused answer` |

The newest post was the same on all four working feeds (2026-10-10T15:48:23Z), so
all four are fresh.

**Consequences:**
- The relay is at the urgent threshold right now: **exactly 2 healthy in-use
  mirrors**. Under FR-7 one more death means "at risk".
- E-6 is real, not hypothetical: a mirror can answer 200 with a non-feed page. The
  relay's existing parser already rejects it; the probe must label it.
- The 12 s answer shows that response time is worth publishing (AC-3.2). A mirror
  near the timeout is about to become "timed out".
- `status.d420.de` said `netbub` had `rss: false`, and our probe agrees. The list's
  claims are sometimes right, but we still do not use them (see R-1).

## R-3: Gaps in the existing address validation

`config._validate_instance` (001 E-20) is the obvious thing to reuse for FR-11.
Reading it against FR-11 shows three gaps:

1. **It uses `ip.is_private`.** In Python 3.12, `ipaddress.ip_address("100.64.0.1").is_private`
   is `False`: carrier-grade NAT space is neither private nor global. The correct
   test is `not ip.is_global`, which also covers documentation ranges and similar.
2. **It accepts ports, paths, queries and credentials.** `https://u:p@host:8443/x?y`
   passes. FR-11 requires a bare host.
3. **The DNS check runs at config time.** FR-11 asks for it at probe time, because a
   list entry can resolve differently later.

Plan: one strict validator, `validate_mirror_url()`, used for discovered entries.
The relay's config keeps calling it too, so 001 E-20 also gains gaps 1 and 2. That
is a tightening of an existing guarantee, recorded as a decision in `plan.md`.

## R-4: Deployment prerequisites (checked with `gh api`)

| Item | Observed | Needed |
|---|---|---|
| GitHub Pages | `GET /repos/joaq-uinv/twitter_bot/pages` returned **404, not enabled** | One-time setup: enable Pages with source "GitHub Actions" (quickstart step 1) |
| Issues | `has_issues: true` | Nothing |
| Repository visibility | public | Free Actions minutes and free Pages |
| Healthchecks.io | One check in use (the relay, A-9). The free plan allows 20 | A second check for the probe |

## R-5: Things deliberately not probed

- **Whether GitHub disables schedules on quiet public repos.** GitHub documents
  that scheduled workflows are disabled after 60 days without repository activity.
  The relay's state commits probably count as activity, but this was not verified.
  It does not matter for correctness: the Healthchecks dead man's switch (FR-9)
  catches a disabled schedule whatever the cause.
- **DNS rebinding.** A host can resolve publicly when checked and privately when
  connected to. This was not tested, and is accepted as a risk in `plan.md`.
