# Assignment listing automation prompt

Use this guidance when producing compact Slack assignment lists for consultant
matching.

## Goal

Post short Slack list items that help people quickly scan new IT assignments and
request a consultant fit analysis in a thread.

## Scan assignment sources

On each run, scan all configured platforms before posting:

1. Run `python scripts/scan-assignments.py --debug-summary` from the repo root.
2. Read the JSON from stdout. Use `assignments` as the candidate pool.
3. Configure Cursor Automation secrets `VERAMA_EMAIL` and `VERAMA_PASSWORD` for
   Verama login. See `docs/assignment-sources.md`.

Default platforms:

- `allakonsultuppdrag.se` — public aggregator API
- `verama.com` — authenticated Ework/Verama marketplace

Skip assignments that are clear duplicates across platforms (same title, buyer,
and location). Prefer the Verama listing when both point to the same role.

## Debug summary message

Before the assignment list items, post one short debug line to Slack summarizing
the scan. Use the `platforms` array from scanner JSON, or the stderr line from
`--debug-summary`.

Example:

```text
Scanned platforms: allakonsultuppdrag.se (511), verama.com (191)
```

If a platform failed, include that in the summary, e.g. `verama.com (error)`.

## Required Slack item content

Each assignment list item must include:

- `[assignment-id]`
- assignment title
- location and/or main role summary
- full online assignment ad link
- suggested consultant matches by first name or canonical name

Assignment id conventions:

- allakonsultuppdrag.se — numeric id, e.g. `[6236]`
- verama.com — `v` prefix + numeric id, e.g. `[v81392]`

Keep each item compact. Do not include sensitive consultant details, internal
notes, private profile content, availability constraints, or CV weaknesses in
the assignment list.

## Matching names

Use consultant names that can be resolved against `consultants.yaml`.

Prefer first names when they are unambiguous in the consultant data. Use the
canonical name when a first name could refer to more than one consultant.

## Example Slack output

```text
Scanned platforms: allakonsultuppdrag.se (511), verama.com (191)

[6236] Senior Front-end Developer, Stockholm
<https://example.com/ad/6236|View ad>
Good matches: Joel, Lena

[v81387] Experience UX & UI Designer, Stockholm (SE)
<https://app.verama.com/app/job-requests/81387|View ad>
Good matches: Soma, Nikolaos
```

## Follow-up commands

Slack users can request detailed analysis or tailored application guidance by
replying in the thread:

```text
fit 6236 Joel
fit v81387 Soma
generate v81387 Soma english
```

For assignments not in the listing, post the full ad text in the channel and
reply with `fit <name>` or `generate <name>` (no id).
