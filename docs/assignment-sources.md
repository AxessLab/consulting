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

## Registered sources

Defined in `scripts/assignment_platforms.py` → `SOURCE_REGISTRY` and
`PLATFORM_SCANNERS`:

| Source | Prefix | Auth | Notes |
|--------|--------|------|-------|
| `allakonsultuppdrag.se` | `a` | None | JSON API only |
| `verama.com` | `v` | `VERAMA_EMAIL`, `VERAMA_PASSWORD` | Playwright login + REST API |

Add new sources by selecting an unused prefix, implementing `scan_<name>()`, and
registering it in both `SOURCE_REGISTRY` and `PLATFORM_SCANNERS`.

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
