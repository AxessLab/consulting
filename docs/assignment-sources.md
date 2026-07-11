# Assignment sources

## Listing (Slack) — deterministic workflow

```bash
python scripts/list-assignments.py -o listing-output.json
# post slack_main + slack_debug
python scripts/finalize-listing.py --commit-memory listing-output.json
```

Python fetches, normalizes, dedupes, filters, matches, and formats Slack output.
Dedupe memory: `assignment-listing-seen.json` locally, synced via automation
Memory entry **`assignment-listing-seen.json`** on cloud runs (see
`automation-prompts/assignment-listing.md` steps 0 and 4).

## Registered sources

Defined in `scripts/assignment_platforms.py` → `SOURCE_REGISTRY` and
`PLATFORM_SCANNERS`:

| Source | Prefix | Auth | Notes |
|--------|--------|------|-------|
| `allakonsultuppdrag.se` | `a` | None | JSON API only |
| `verama.com` | `v` | `VERAMA_EMAIL`, `VERAMA_PASSWORD` | Playwright login + REST API |

Add new sources by choosing an unused lowercase prefix, implementing
`scan_<name>()`, and registering it in `SOURCE_REGISTRY` and
`PLATFORM_SCANNERS`.

## Matching

`consultants.yaml` is the consultant source of truth. `assignment_matching.py`
implements the shared deterministic filtering and matching rules.

## Raw / debug

```bash
python scripts/scan-assignments.py --debug-summary
python scripts/fetch-assignments.py -o listing-candidates.json
```

## Secrets

Store `VERAMA_EMAIL` and `VERAMA_PASSWORD` in Cursor Automation secrets or a
local `.env` from `.env.example`. Do not commit credentials.
