# Assignment listing automation prompt

Use this guidance when producing Slack assignment lists for consultant matching.

## Goal

Post new IT consulting assignments from **all configured platforms** in three
sections, with a debug thread reply. Filtering and matching are deterministic —
do not re-implement them in the automation.

## Run the listing script

1. From the repo root, run:

```bash
python scripts/list-assignments.py -o listing-output.json
```

By default this scans every platform registered in
`scripts/assignment_platforms.py` (currently `allakonsultuppdrag.se` and
`verama.com`). Override with `--platform` if needed.

2. Read `listing-output.json`. It contains:
   - `slack_main` — post as the channel message
   - `slack_debug` — post as a thread reply on that message (includes scanned
     platforms summary)
   - `memory_update` — do not edit manually

3. After both Slack messages are sent, persist dedupe memory:

```bash
python scripts/list-assignments.py --commit-memory listing-output.json
```

4. Persistent dedupe state lives in `assignment-listing-seen.json` (per-platform
   `seen_ids` plus unified `seen_keys`). Do not commit this file.

Set `VERAMA_EMAIL` and `VERAMA_PASSWORD` in automation secrets for Verama. See
`docs/assignment-sources.md`.

## Slack posting rules

- Post **exactly once** per run: one main message, then one debug thread reply.
- Use `slack_main` and `slack_debug` verbatim unless a field is clearly broken.
- Do not add consultant CV weaknesses, availability, or internal notes.

## Main message format

Three sections (already formatted in `slack_main`):

1. Accessibility specialist related roles
2. Other roles mentioning accessibility related terms
3. Other roles where accessibility is not mentioned

Each assignment line is pipe-separated. Non-allakonsult assignments use a
`v`-prefixed id for Verama and may include `[platform]` after the id.

```text
6236 | Software Developer Java | Stockholm | not stated (probably full time) | Client: not stated | Broker: A Society | Link: https://... | Posted: 2026-06-01 | Match: Joel Holmberg
v81387 [verama.com] | Experience UX & UI Designer | Stockholm (SE) | ... | Match: Soma Azad
```

If a section has no matches, the script outputs `No new matches.`

## Follow-up commands

```text
fit 6236 Joel
fit v81387 Soma
generate v81387 Soma english
```

Listed ids are all digits (allakonsultuppdrag) or `v` + digits (Verama). See
`docs/slack-flow.md`.

## Source of truth

| Concern | Location |
|---------|----------|
| Platform scanners | `scripts/assignment_platforms.py` |
| Role/location filters + matching | `scripts/assignment_matching.py` |
| Consultant names, roles, locations | `consultants.yaml` |
| Listing orchestration | `scripts/list-assignments.py` |

When adding a new platform, register a scanner in `assignment_platforms.py`.
Matching rules apply automatically once assignments use the normalized
`AssignmentRecord` shape.

## Raw fetch only

`scripts/scan-assignments.py` fetches unfiltered assignments from configured
platforms. Use it for debugging ingestion, not for Slack posting.
