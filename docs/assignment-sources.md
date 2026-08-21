# Assignment sources

## Listing (Slack) — hybrid workflow

```bash
python scripts/fetch-assignments.py -o listing-candidates.json
# agent curates → curated-listing.json
python scripts/finalize-listing.py listing-candidates.json curated-listing.json -o listing-output.json
# post slack_main + slack_debug
python scripts/finalize-listing.py --commit-memory listing-output.json
```

Python fetches and dedupes; the automation agent applies filtering rules and
writes `curated-listing.json`. Dedupe memory: `assignment-listing-seen.json`
locally, synced via automation Memory entry **`assignment-listing-seen.json`**
on cloud runs (see `automation-prompts/assignment-listing.md` step 0 and 5).

## Active sources

Defined by `ACTIVE_SOURCE_ORDER` in `scripts/assignment_platforms.py`:

| Source | Prefix | Auth | Notes |
|--------|--------|------|-------|
| `verama.com` | `v` | `VERAMA_EMAIL`, `VERAMA_PASSWORD` | Playwright login + REST API |
| `chaspartnernetwork.se` | `c` | None | WP REST index + admin-ajax Konsult filter + detail HTML scrape |
| `allakonsultuppdrag.se` | `a` | None | JSON API only |

Add new sources by implementing `scan_<name>()`, assigning an unused prefix, and
adding the source to `ACTIVE_SOURCE_ORDER`.

## Matching

`consultants.yaml` is the consultant source of truth. `assignment_matching.py`
provides heuristic suggestions only; the automation prompt defines final
filtering and matching rules.

## Raw / debug

```bash
python scripts/scan-assignments.py --debug-summary
python scripts/list-assignments.py --deterministic -o listing-output.json
```

## Secrets

Store `VERAMA_EMAIL` and `VERAMA_PASSWORD` in Cursor Automation secrets or a
local `.env` from `.env.example`. Do not commit credentials.
