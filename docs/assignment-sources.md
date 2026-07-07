# Assignment sources

## Listing (Slack) — hybrid workflow

```bash
python scripts/fetch-assignments.py -o listing-candidates.json
# agent curates → curated-listing.json
python scripts/finalize-listing.py listing-candidates.json curated-listing.json -o listing-output.json
# post slack_main + slack_debug
python scripts/finalize-listing.py --commit-memory listing-output.json
```

Python fetches, normalizes, and dedupes; the automation agent applies filtering rules and
writes `curated-listing.json`. Dedupe memory: `assignment-listing-seen.json`
locally, synced via automation Memory entry **`assignment-listing-seen.json`**
on cloud runs (see `automation-prompts/assignment-listing.md` step 0 and 5).
The memory shape is a unified `sources` object with one entry per source and
bare native `seen_ids` (listing prefixes are not stored in memory).

## Registered sources

Defined in `scripts/assignment_platforms.py` → `SOURCE_REGISTRY` and
`PLATFORM_SCANNERS`:

| Prefix | Source | Auth | Notes |
|--------|--------|------|-------|
| `a` | `allakonsultuppdrag.se` | None | JSON API only |
| `v` | `verama.com` | `VERAMA_EMAIL`, `VERAMA_PASSWORD` | Playwright login + REST API; list rows plus conditional detail fetch |

Add new sources by choosing an unused lowercase prefix, implementing
`scan_<name>()`, and registering it in `SOURCE_REGISTRY` and
`PLATFORM_SCANNERS`.

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
