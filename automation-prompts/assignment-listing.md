# Assignment listing automation prompt

Use this guidance when producing Slack assignment lists for consultant matching.

## Goal

Post new IT consulting assignments from **all configured sources** in three
sections, with a debug thread reply.

**Python handles the deterministic pipeline** (source fetch, normalization,
per-source memory, cross-source reporting dedupe, filtering, matching, Slack
line formatting). Review the output for the guardrails below before posting.

## Run flow

### 0. Restore dedupe memory (cloud runs — required)

Cloud agent checkouts **do not** keep `assignment-listing-seen.json` between runs
(the file is gitignored). Without restoring memory, every run treats all visible
assignments as new.

1. Ensure **Memories** is enabled for this automation.
2. Read the automation Memory entry named **`assignment-listing-seen.json`**.
3. If it contains JSON, seed the local file before fetch:

```bash
python3 scripts/listing-memory-bridge.py seed <<'EOF'
<paste the full JSON from the memory entry>
EOF
```

If the memory entry does not exist yet, skip — the first run starts with an
empty dedupe set.

Local-only runs can skip this step when `assignment-listing-seen.json` already
exists on disk from a previous `--commit-memory`.

### 1. Run deterministic listing

```bash
python3 scripts/list-assignments.py -o listing-output.json
```

This scans every active source in `scripts/assignment_platforms.py`, normalizes
each source into the canonical record shape, applies per-source newness and
cross-source reporting dedupe, then writes:

- `slack_main` — the one channel message
- `slack_debug` — the one threaded debug reply
- `matches` — reported records for validation
- `memory_update` — draft memory (do not commit until after Slack post)
- `source_results` / `stats.new_ids_by_source` — debug counts

Set `VERAMA_EMAIL` and `VERAMA_PASSWORD` in automation secrets for Verama.

### 2. Validate output before Slack

Read `listing-output.json`. Review `slack_main`, `slack_debug`, and `matches`
against the guardrails below. If the deterministic output is suspicious, fix the
shared code locally and re-run the deterministic listing before posting.

### 3. Post Slack

- Post `slack_main` as the channel message.
- Reply in that thread with `slack_debug`.
- Do not add CV weaknesses, availability, or internal notes.

### 4. Persist dedupe memory (after Slack)

The local file alone is **not** enough for the next cloud run. After posting:

```bash
python3 scripts/finalize-listing.py --commit-memory listing-output.json --print-memory > memory-export.json
```

Then **overwrite** the automation Memory entry **`assignment-listing-seen.json`**
with the contents of `memory-export.json`. Do not commit that file or
`assignment-listing-seen.json`.

Verify the next run will restore correctly: `stats.previously_seen` in
`listing-candidates.json` should be greater than zero after the first successful
persist (except on the very first run ever).

Persistent dedupe shape: a top-level `sources` object. Each source stores its
listing prefix, bare native `seen_ids`, and visible counts.

## Filtering rules

Apply to **new** assignments only.

1. Exclude assignments whose `lastApplicationDate` is before the scan date
   (already handled by the deterministic listing).
2. Match role against consultants in `consultants.yaml` (`mainRoles`, active
   `cvs[].roles`, `locations`). Use `consultants` in the fetch output as a
   shortcut.
3. Location must be remote or Stockholm/Solna/near-Stockholm, except
   accessibility specialist roles (location ignored) and front-end roles (also
   accept Gothenburg).
4. Treat `remote` / `distans` / `fjärrarbete` as remote only when present in
   API `workMode` or `location`. Do not let incidental description text make a
   hybrid non-Stockholm role pass.
5. `hybrid` alone is not remote. Hybrid is acceptable only if `location` is
   Stockholm/Solna/near-Stockholm.
6. Near-Stockholm includes: Stockholm, Solna, Sundbyberg, Kista, Bromma,
   Sollentuna, Danderyd, Täby, Järfälla, Nacka, Huddinge, Lidingö, Älvsjö,
   Årsta, Stockholms län, Botkyrka, Upplands Väsby, Södertälje, Haninge,
   Tyresö, Vällingby, Farsta.
7. Do not do deep skill scoring. Use basic role/framework matching only.
8. Roles should be IT related. Do not match project management roles for
   non-IT projects.

## Role matching

### Accessibility specialist (section 1)

- Match when title or explicit skills indicate accessibility specialist/reviewer
  work.
- Strong terms: `tillgänglighetsgranskare`, `tillgänglighetsspecialist`,
  `accessibility specialist`, `accessibility consultant`, `WCAG specialist`,
  `document accessibility`, `dokumenttillgänglighet`,
  `webbtillgänglighetsspecialist`.
- Do **not** classify as accessibility specialist just because a generic
  application paragraph says “information kring tillgänglighet” or because WCAG
  is one requirement inside a non-accessibility role.
- Do not classify security reviewers, frontend/backend developers, DevOps, or
  generic web consultant roles as accessibility specialists just because WCAG
  appears as one skill.
- Team/multi-person a11y ads: add **Inhouse accessibility team** when the ad
  clearly needs more than one accessibility person.

### Other roles (sections 2 and 3)

- **React/Next/frontend** — React, Next.js, frontend where React/Next is primary.
- **Angular / WordPress** — primary framework roles.
- **Java backend** — Java, Spring, backend/systemutvecklare where Java is primary.
- **Full stack** — fullstack with Java and React/Angular. Avoid .NET.
- **UX/UI/product design** — UX, UI, product designer, user experience,
  interaction design, interaktionsdesign, tjänstedesign.
- **IT PM/Scrum/coordinator** — project manager, projektledare, scrum master,
  projektkoordinator, agile coach, leveransansvarig — only when clearly
  IT/digital/software/system/web/app/platform related.

### False positives to avoid

- Do not match Python/.NET/cloud/mobile/embedded/generic engineering to Java or
  React consultants because React/Java appear secondarily.
- Do not match UI artist/game art as UX unless title/summary clearly indicates
  UX/UI/product design.
- Do not match employment ads — consulting assignments only.
- Do not match scrum-master consultants to generic PM/architect roles unless the
  title explicitly asks for scrum master.
- Remote anywhere does **not** override role mismatch (e.g. Barcelona data
  architect is not a match for Stockholm PM consultants).

### Section 2 vs 3

- Section 2: independently matches a target consultant role **and** mentions
  accessibility terms in title/description/skills.
- Section 3: matches a target role with no accessibility mention.

## Project management guardrails

- PM/Scrum roles need a PM-like title plus IT/digital/software/platform/web/app
  context.
- Exclude PM for social services, rail/transport, automotive, marketing/sales,
  organizational change, field support unless explicitly IT/software/digital.
- Do not match “Technical Project Manager” unless clearly IT/software/digital.

## Pre-Slack validation

Before finalize/post:

- No section-1 item is security/dev/DevOps unless the title is accessibility
  specialist/reviewer.
- No PM item is non-IT social services, rail, automotive, marketing, or generic
  technical/product work.
- No developer item is FPGA/embedded/.NET/Python/PHP/Vue/cloud/mobile/data unless
  the primary stack is still clearly Java/React/Angular/WordPress.
- Debug thread should prioritize close non-matches, especially role matches
  rejected by location.

If the first pass looks suspicious, refine `curated-listing.json` and re-finalize.
Post exactly once: one main message and one debug reply.

## Main message format

Three sections (built by `finalize-listing.py`). Section titles are **bold** in Slack (`*1. …*`). Assignment lines are separated by a blank line.

1. Accessibility specialist related roles
2. Other roles mentioning accessibility related terms
3. Other roles where accessibility is not mentioned

Pipe-separated lines. Verama ids use `v` prefix. Platform is implied by the
assignment link. Title is a Slack link (`<url|title>`). Omit client and hours/scope when unknown.

```text
*1. Accessibility specialist related roles*
No new matches.

*3. Other roles where accessibility is not mentioned*
a6236 | 2026-06-01 | <https://...|Software Developer Java> | Stockholm | A Society | Match: Joel Holmberg

v81387 | 2026-06-01 | <https://...|Experience UX & UI Designer> | Stockholm (SE) | 50% | Client: Acme | Ework | Match: Soma Azad
```

If a section has no matches, it shows `No new matches.`

## Follow-up commands

```text
fit a6236 Joel
fit v81387 Soma
generate v81387 Soma english
```

## Source of truth

| Concern | Location |
|---------|----------|
| Source scanners | `scripts/assignment_platforms.py` |
| Deterministic listing | `scripts/list-assignments.py` |
| Fetch + candidate debugging | `scripts/fetch-assignments.py` |
| Memory bridge (cloud) | `scripts/listing-memory-bridge.py` |
| Heuristic hints (not final) | `scripts/assignment_matching.py` |
| Slack formatting + memory | `scripts/finalize-listing.py` |
| Consultant names, roles, locations | `consultants.yaml` |

When adding a new source, register a scanner and prefix in `assignment_platforms.py`.

## Debug / candidate mode

```bash
python3 scripts/fetch-assignments.py -o listing-candidates.json
```

Candidate JSON is useful for tuning `assignment_matching.py`; production Slack
posting uses `scripts/list-assignments.py`.

`scripts/scan-assignments.py` — raw unfiltered fetch for ingestion debugging.
