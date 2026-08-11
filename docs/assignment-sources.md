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

## Active source registry

Defined in `scripts/assignment_platforms.py` → `SOURCE_REGISTRY`:

| Prefix | Source | Auth | Notes |
|--------|--------|------|-------|
| `v` | `verama.com` | `VERAMA_EMAIL`, `VERAMA_PASSWORD` | Playwright login + REST API; conditional detail fetch for plausible new rows |
| `c` | `chaspartnernetwork.se` | None | WP REST index + admin-ajax Konsult filter + detail HTML scrape |
| `a` | `allakonsultuppdrag.se` | None | JSON API only |

Add new active sources by implementing `scan_<name>()`, registering it in
`PLATFORM_SCANNERS`, and adding a prefix row to `SOURCE_REGISTRY`. Inactive
ad-hoc scanners may exist in code but are not part of the default Slack listing.

## Matching

`consultants.yaml` is the consultant source of truth. `assignment_matching.py`
provides heuristic suggestions only; the automation prompt defines final
filtering and matching rules.

## Memory shape

`assignment-listing-seen.json` stores a top-level `sources` object. Each source
entry stores its prefix, bare native `seen_ids`, and visible/unique-visible
counts. Cloud runs sync the same file through automation Memory.

## Raw / debug

```bash
python scripts/scan-assignments.py --debug-summary
python scripts/list-assignments.py --deterministic -o listing-output.json
```

## Secrets

Store `VERAMA_EMAIL` and `VERAMA_PASSWORD` in Cursor Automation secrets or a
local `.env` from `.env.example`. Do not commit credentials.
