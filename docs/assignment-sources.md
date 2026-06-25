# Assignment sources

## Listing (Slack)

```bash
python scripts/list-assignments.py -o listing-output.json
# post slack_main + slack_debug
python scripts/list-assignments.py --commit-memory listing-output.json
```

Scans all registered platforms, applies three-tier filtering/matching, and
outputs Slack-ready text. Dedupe memory: `assignment-listing-seen.json`.

## Registered platforms

Defined in `scripts/assignment_platforms.py` → `PLATFORM_SCANNERS`:

| Platform | Auth | Notes |
|----------|------|-------|
| `allakonsultuppdrag.se` | None | JSON API only |
| `verama.com` | `VERAMA_EMAIL`, `VERAMA_PASSWORD` | Playwright login + REST API |

Add new platforms by implementing `scan_<name>() -> (list[AssignmentRecord], PlatformScanResult)`
and registering it in `PLATFORM_SCANNERS`.

## Matching

`scripts/assignment_matching.py` loads active consultants from `consultants.yaml`
(`mainRoles`, `locations`, active `cvs[].roles`) and applies role/location rules.

## Raw fetch (debug)

```bash
python scripts/scan-assignments.py --debug-summary
```

Unfiltered fetch only — not for Slack posting.

## Secrets

Store `VERAMA_EMAIL` and `VERAMA_PASSWORD` in Cursor Automation secrets or a
local `.env` from `.env.example`. Do not commit credentials.
