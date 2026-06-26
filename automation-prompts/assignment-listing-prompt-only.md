Scan consulting assignments from **multiple sources**, normalize each into one shared record shape, apply shared filtering, and post **one** Slack report. Source-specific logic is limited to authentication, fetch URLs, and field mapping.

Do not scrape rendered listing pages when a source provides API JSON.

## Pipeline

For every registered source, in order:

1. **Scan** — auth + paginated list fetch; per-item detail only when the list row is not enough (see each source).
2. **Normalize** — map native fields into the canonical assignment record (below).
3. **Dedupe within source** — unique by native `source_id`.

Then, across all sources:

4. **Merge** — one combined pool of normalized records.
5. **Per-source newness** — compare each record's `source_id` to that source's `seen_ids` in memory.
6. **Cross-source dedupe** — collapse obvious duplicates before reporting (see below).
7. **Filter & match** — shared rules; source-agnostic.
8. **Slack** — one main message + one debug thread.
9. **Memory** — update all sources in the unified memory file.

A source failure must not block other sources. Record `(error)` or `(skipped)` for that source in the debug thread and skip its memory update for the run.

## Source registry

Each source has a single-letter **listing prefix**. The Slack/fit/generate id is `{prefix}{source_id}`.

| Prefix | Source key | Memory `seen_ids` | Status |
|--------|------------|-------------------|--------|
| `a` | `allakonsultuppdrag.se` | bare numeric id | active |
| `v` | `verama.com` | bare numeric id | active |

When adding a source: pick an unused lowercase letter, add a row here, add a `## Source: …` section below, and extend memory `sources` on first run.

**Cross-source duplicate preference** (when title + broker + location clearly match): prefer, in order, `v` (Verama), then `a` (allakonsultuppdrag), then other sources by registry order. Still persist every visible `source_id` per source in memory.

## Canonical assignment record

Every source must produce records in this shape before filtering. Matching, validation, and Slack formatting use **only** these fields — not native API names.

| Field | Type | Notes |
|-------|------|-------|
| `listing_id` | string | `{prefix}{source_id}` — e.g. `a6236`, `v81387` |
| `source_key` | string | Registry source key — e.g. `verama.com` |
| `source_id` | string | Native id as string, no prefix — used in memory `seen_ids` |
| `title` | string | Role title |
| `description` | string | Full text for matching and parsing |
| `descriptionSummary` | string | Short summary; may be empty |
| `publishedDate` | string | ISO or parseable date |
| `lastApplicationDate` | string | ISO or parseable date |
| `startDate` | string | Optional |
| `endDate` | string | Optional |
| `duration` | string | Optional free text |
| `workMode` | string | e.g. `remote`, `hybrid`, `25% remote` |
| `location` | string | City/region as shown to users |
| `sourceUrl` | string | Link to the online ad |
| `broker` | string | Broker/marketplace name |
| `skills` | array | List of `{ "name": "..." }` or plain strings |

After normalization, downstream steps must not branch on `source_key` except cross-source dedupe preference and debug counts.

## Persistent dedupe (unified memory)

Single file: **`assignment-listing-seen.json`**.

Cloud runs: restore from automation Memory entry **`assignment-listing-seen.json`** before scanning; write it back after Slack.

Valid memory is JSON with a `sources` object. Each source key maps to:

```json
{
  "prefix": "a",
  "seen_ids": ["6236", "6285"],
  "total_visible": 200,
  "total_unique_visible": 200
}
```

Top-level fields:

```json
{
  "last_scan_at": "2026-06-25T08:00:00Z",
  "scan_date": "2026-06-25",
  "sources": {
    "allakonsultuppdrag.se": { "prefix": "a", "seen_ids": [], "total_visible": 0, "total_unique_visible": 0 },
    "verama.com": { "prefix": "v", "seen_ids": [], "total_visible": 0, "total_unique_visible": 0 }
  }
}
```

Rules:

- If the file is missing, empty, malformed, or a source has no `seen_ids`, treat that source as never scanned — all its currently visible active matches are new.
- **New** = `source_id` not in that source's `seen_ids` (prefix is not stored in memory).
- Update memory only after the Slack report and debug thread are sent.
- Save **all** currently visible unique `source_id` values per source, not only reported matches.
- Do not commit this file to git.

Legacy single-source files (`allakonsultuppdrag-seen.json`, `verama-seen.json`) may be migrated once: import `seen_ids` into `sources.<key>` and retire the old file.

---

## Source: allakonsultuppdrag.se (`a`)

Public JSON API only.

**Endpoint:** `https://allakonsultuppdrag.se/api/assignments?page=1&pageSize=100`

**Headers** (403 without them):

- `User-Agent: Mozilla/5.0 (compatible; AssignmentScanner/1.0)`
- `Accept: application/json`

**Pagination:** `pageSize=100`; continue until `hasNextPage` is false OR `page >= totalPages`.

**Dedupe within source:** by native `id`.

**Field mapping:**

| Canonical | Native |
|-----------|--------|
| `listing_id` | `a` + `id` |
| `source_id` | `id` (string) |
| `title` | `title` |
| `description` | `description` |
| `descriptionSummary` | `descriptionSummary` |
| `publishedDate` | `publishedDate` |
| `lastApplicationDate` | `lastApplicationDate` |
| `startDate` / `endDate` | `startDate` / `endDate` |
| `duration` | `duration` |
| `workMode` | `workMode` |
| `location` | `location` |
| `sourceUrl` | `sourceUrl` |
| `broker` | `broker` |
| `skills` | `skills` |

---

## Source: verama.com (`v`)

Authenticated REST API after browser login. Username: consulting@axesslab.com Password: veramaAxs!

### Login and auth headers

Headless Chromium (Playwright or equivalent):

1. Open `https://app.verama.com/sv/login`.
2. Fill email and password from secrets.
3. Submit via `button[type="submit"]`, `button:has-text("Logga in")`, or `button:has-text("Log in")`.
4. Wait ~8s, then open `https://app.verama.com/app/job-requests` (network idle).
5. Capture headers from the first `job-requests/v2` request: `authorization`, `x-session`, `x-context-id`, `x-frontend-version`, `accept-language` (if present).
6. Reuse for all Verama API calls; re-login once on 401/403.

Do not rely on `POST /api/auth/login` alone without browser session headers.

### List

`GET https://app.verama.com/api/job-requests/v2`

Params: `page` (0-based), `size=100`, `query=""`, `dedicated=false`, `favouritesOnly=false`, `recommendedOnly=false`, `sort=firstDayOfApplications,DESC`.

Headers: captured auth + `User-Agent: Mozilla/5.0 (compatible; AssignmentScanner/1.0)`, `Accept: application/json, text/plain, */*`, `Referer: https://app.verama.com/app/job-requests`.

Paginate until `last` is true or `content` is empty. Dedupe within source by numeric `id`.

The list row is enough to normalize **without detail** for memory and cheap pre-filtering:

| Canonical | List API |
|-----------|----------|
| `title` | `title` |
| `publishedDate` | `firstDayOfApplications` |
| `lastApplicationDate` | `lastDayOfApplications` when present on list row |
| `workMode` | `remoteness` → `"{n}% remote"` |
| `location` | `city` + `countryCode` |
| `broker` | `originServiceName` |
| `sourceUrl` | `https://app.verama.com/app/job-requests/{id}` |

Leave `description`, `descriptionSummary`, `skills`, `startDate`, `endDate`, and `duration` empty until detail is fetched.

### Detail (conditional, not for every listing)

`GET https://app.verama.com/api/job-requests/v2/{id}` (fallback: `/api/job-requests/{id}`).

**Do not** detail-fetch every visible job. The list API already supports title-, location-, broker-, and date-based pre-filtering. Detail is for skills, description context, scope/client parsing, and missing deadline fields.

**Skip detail** when any of these apply:

- `source_id` is already in `seen_ids` (not new — still count toward memory).
- `lastApplicationDate` on the list row is before scan date.
- Title is clearly outside target families (e.g. SAP functional, network/security ops, HR/payroll, automation engineer / factory, generic analyst with no IT/UX/dev/PM/a11y signal).
- Location pre-check fails on list data (on-site or hybrid outside Stockholm/near-Stockholm/Gothenburg-for-frontend) **and** title is not a strong accessibility-specialist role.

**Fetch detail** when:

- The job is **new** and passed the skips above, **or**
- `lastApplicationDate` is missing on the list row (need detail to apply active-date filter), **or**
- Title is a plausible but ambiguous match (e.g. generic “consultant”, “developer”, “project lead”) where skills or description are needed to confirm or reject.

After detail, merge description, skills, dates, and duration into the canonical record. Jobs that never received detail should not be reported as matches.

### Field mapping (full record after list ± detail)

| Canonical | Native |
|-----------|--------|
| `listing_id` | `v` + `id` |
| `source_id` | `id` (string) |
| `title` | `title` |
| `description` | detail `description` / `jobDescription` / equivalent |
| `descriptionSummary` | short summary field or first ~300 chars of description |
| `publishedDate` | `firstDayOfApplications` |
| `lastApplicationDate` | list `lastDayOfApplications`, else detail deadline field |
| `startDate` / `endDate` | detail, e.g. `firstDayOfAssignment` / `lastDayOfAssignment` |
| `duration` | derived period from detail when available |
| `workMode` | list `remoteness` as `"{n}% remote"`; detail may add explicit remote/distans/hybrid strings |
| `location` | list `city` + `countryCode` |
| `sourceUrl` | `https://app.verama.com/app/job-requests/{id}` |
| `broker` | `originServiceName` |
| `skills` | detail `skills` — match on each `name` |

### Verama-specific normalization (before shared location rules)

- `remoteness` **100** or explicit remote/distans/fjärrarbete in `workMode`/`location` → treat as remote in `workMode`.
- `remoteness` **1–99** → hybrid, not fully remote.
- `remoteness` **0** or absent → on-site unless API says otherwise.
- Do not let description boilerplate override API `workMode` / `location` / `remoteness`.

---

## Source: (template for new sources)

```markdown
## Source: example.com (`x`)

**Auth:** …
**List:** …
**Detail:** … (if needed)
**Field mapping:** native → canonical table
**Normalize notes:** any source-specific quirks, mapped into canonical fields before shared rules
```

---

## Cross-source dedupe (reporting only)

The same role may appear on multiple sources with different ids.

Before reporting, collapse obvious duplicates (same or near-identical title + broker + location). Keep one record per duplicate group using the preference order in the source registry.

Still record every visible `source_id` in each source's memory `seen_ids`.

## Filtering

Apply to **new** records after cross-source dedupe.

1. Only report assignments new per source (`source_id` not in that source's `seen_ids`).
2. Exclude assignments whose `lastApplicationDate` is before the scan date.
3. Match role against the consultant list.
4. Location must be remote or Stockholm/Solna/near-Stockholm, except accessibility specialist roles (location ignored) and front-end roles (also accept Gothenburg).
5. Treat `remote`/`distans`/`fjärrarbete` as remote only when present in `workMode` or `location` (after normalization). Do not let incidental description text make a hybrid non-Stockholm role pass.
6. `hybrid` alone is not remote. Hybrid is acceptable only if `location` is Stockholm/Solna/near-Stockholm.
7. Near-Stockholm includes: Stockholm, Solna, Sundbyberg, Kista, Bromma, Sollentuna, Danderyd, Täby, Järfälla, Nacka, Huddinge, Lidingö, Älvsjö, Årsta, Stockholms län, Botkyrka, Upplands Väsby, Södertälje, Haninge, Tyresö, Vällingby, Farsta.
8. Do not do deep skill scoring. Use basic role/framework matching only.
9. Roles should be IT related. Do not match project management roles for non-IT projects.

## Role matching

- Accessibility specialist bucket:
  - Match when title or explicit skills indicate accessibility specialist/reviewer work.
  - Strong terms: `tillgänglighetsgranskare`, `tillganglighetsgranskare`, `tillgänglighetsspecialist`, `tillganglighetsspecialist`, `accessibility specialist`, `accessibility consultant`, `WCAG specialist`, `document accessibility`, `dokumenttillgänglighet`, `webbtillgänglighetsspecialist`.
  - Do not classify as accessibility specialist just because a generic application paragraph says “information kring tillgänglighet” or because WCAG is one requirement inside a non-accessibility role.
- Other roles:
  - React/Next/frontend: React, React.js, Next.js, frontend/front-end where React/Next is primary.
  - Angular/frontend.
  - WordPress/frontend.
  - Java backend: Java, Spring, backend/systemutvecklare where Java is primary.
  - Full stack: fullstack/full-stack/full stack with Java and React/Angular. Avoid .Net.
  - UX/UI/product design: UX, UI, UX designer, UI designer, product designer, user experience, interaction design, interaktionsdesign, tjänstedesign.
  - IT PM/Scrum/coordinator: project manager, projektledare, scrum master, projektkoordinator, project coordinator, agile coach, leveransansvarig, but only if the assignment is clearly web/app/software related.
- Avoid false positives:
  - Do not match Python/.NET/cloud/mobile/embedded/generic engineering roles to Java or React consultants only because generic skills/tags mention React/Java secondarily.
  - Do not match UI artist/game art as UX unless the title/summary clearly indicates UX/UI/product design work.
  - Do not match employment ads, only consulting assignments.

## Additional matching guardrails

- Build the scan as a deterministic script with a validation pass before posting to Slack. Do not post until the final filtered output has been reviewed against these guardrails.
- Treat `skills` as structured data. If `skills` is an array of objects, match against each skill `name`, not the raw object string.
- Use normalized lowercase text for matching, but do not use broad substring checks for short terms. Terms like `ai`, `app`, `web`, `it`, and `system` must be matched with word boundaries or explicit phrases. Do not let generic `system` alone make a project-management role count as IT.
- Keep role matching conservative. A role must pass role match, active-date match, dedupe match, and location match before reporting.

## Accessibility matching

- Accessibility specialist roles require the title to contain a strong accessibility role term, or explicit accessibility-reviewer/specialist skills plus a compatible reviewer/specialist title.
- Do not classify security reviewers, frontend/backend developers, DevOps roles, or generic web consultant roles as accessibility specialists just because `WCAG` or `Tillgänglighetsgranskning` appears as one skill.
- If accessibility terms are present but the role is not an accessibility specialist, only include it in “Other roles mentioning accessibility related terms” if it independently matches another target consultant role.

## Project management matching

- PM/Scrum/coordinator roles require a PM-like title plus clearly IT/digital/software/platform/web/app/ERP/IAM/payments/digital-workplace context.
- Exclude PM roles for social services, rail/transport, automotive/vehicle testing, marketing/value proposition, sales enablement, organizational change, product launches, or field-support unless the assignment is explicitly about IT/software/platform/web/app/ERP/IAM/payments/digital workplace.
- Do not match `Technical Project Manager` automatically. It must be clearly IT/software/digital, not generic engineering, automotive, product, or infrastructure field work.

## Developer matching

- React/Angular/frontend roles should be primary frontend roles, preferably in title/summary or title plus explicit framework skill.
- Java backend/fullstack roles require Java to be primary. Avoid matching JavaScript, generic engineering, FPGA, embedded, data engineering, Python, .NET, PHP/Vue, C#, cloud/devops, mobile, or test roles because Java/React appears secondarily.
- Fullstack Java + React/Angular requires fullstack in title/summary and Java plus React/Angular in explicit skills/text. Exclude .NET, PHP, Vue, and unrelated stacks.

## Location matching

- Remote is valid only when `remote`, `distans`, or `fjärrarbete` appears in `workMode` or `location` (after source normalization).
- Do not use description text to make a non-Stockholm hybrid role remote.
- `hybrid` alone is not remote; hybrid passes only with Stockholm/Solna/near-Stockholm location.
- Accessibility specialist roles ignore location; all other roles must pass location.

## Parsing output fields

- Fulltime/part-time/fixed-hours parsing should avoid false hour matches from dates, IDs, “1 year”, “1 person”, or application countdown text.
- Only report percentages when tied to words like `omfattning`, `scope`, `utilization`, `beläggning`, `engagemang`, or `max`.
- If both `100%` and `50%` appear, prefer the one tied to scope/omfattning; otherwise say `not stated (probably full time)` rather than guessing.
- End-client/company should be conservative. Only include a company/client when explicitly stated as `Kund:`, `End client:`, or clearly named in the title such as `till Folkhälsomyndigheten`. Do not infer from broker boilerplate, contact text, or malformed scraped/CSS fragments inside the description.

## Pre-Slack validation

Before posting, run a final sanity check over reported matches:

- No accessibility specialist section item should be a security/dev/DevOps role unless the title itself is accessibility specialist/reviewer.
- No PM item should be non-IT social services, rail, automotive, marketing/sales, or generic technical/product work.
- No developer item should be FPGA/embedded/.NET/Python/PHP/Vue/cloud/mobile/data unless the primary requested target stack is still clearly Java/React/Angular/WordPress.
- Debug thread should prioritize close non-matches, especially role matches rejected by location.

If the first pass produces suspicious matches, refine locally before Slack. Post exactly once: one main Slack message and one debug thread reply.

## Consultants

- Joel Holmberg, 14 years, backend Java, fullstack Java + React, frontend React
- Nicko Syropoulis, 10 years, UX
- Karin Toft, 10 years, front-end Angular, WordPress, React
- Anders Söderström, 9 years, front-end React
- Max Rautenberg, 4 years, front-end React
- Soma Azad, 10 years, UX
- Erik GS, 15 years, Project Manager, Scrum Master, Project coordinator
- Emma Dawson, 5 years, front-end React
- Daniel Göransson, 10 years, Accessibility specialist, Assistive tech specialist, Wordpress
- Hampus Sethfors, 14 years, Accessibility specialist
- Josefin Wessman, 13 years, Accessibility specialist
- Eric Eggert, 20 years, Accessibility specialist
- Henrik, 4 years, Accessibility specialist, Document accessibility specialist
- Amin Amini, 3 years, Accessibility specialist
- Nathalie Pentler, 4 years, Accessibility specialist, Physical accessibility specialist
- Emilia Michanek, 7 years, Front-end react, angular
- Ahmed Abdi, 7 years, Front-end react
- Inhouse accessibility team, 5-20 years, accessibility projects of any kind requiring more than 1 person

## Slack output

One main message for all sources combined.

**Sections:**

1. Accessibility specialist related roles
2. Other roles mentioning accessibility related terms
3. Other roles where accessibility is not mentioned

If a section has no matches: `No new matches.`

**Per assignment** (pipe-separated, one line each):

- `listing_id` — letter-prefixed id (`a6236`, `v81387`, …)
- `title`
- `location` + `workMode`
- Fulltime/part-time/fixed-hours from `description`, `duration`, `startDate`, `endDate`; if unknown: `not stated (probably full time)`
- `Client: …` or `Client: not stated`
- `Broker: …`
- `Link: {sourceUrl}`
- `Posted: {date part of publishedDate}` or scan date
- `Match: …` consultant names

Examples:

```text
a6236 | Software Developer Java | Stockholm | Full time | Client: not stated | Broker: A Society | Link: https://www.asocietygroup.com/sv/uppdrag/software-developer-java-16055 | Posted: 2026-06-01 | Match: Joel Holmberg
v81387 | Experience UX & UI Designer | Stockholm (SE) | 25% remote | Client: not stated | Broker: Ework | Link: https://app.verama.com/app/job-requests/81387 | Posted: 2026-06-01 | Match: Soma Azad
```

Do not add source names or platform labels to main message lines — the listing id prefix and link identify the source.

**Follow-up commands** (see `docs/slack-flow.md`):

```text
fit a6236 Joel
fit v81387 Soma
generate v81387 Soma english
```

## Debug thread

Reply to the main message with:

1. `Scanned sources: allakonsultuppdrag.se (N), verama.com (M), …` — per active registry entry; use `(error)` or `(skipped)` on failure.
2. Scan date; total visible per source; new ids per source after per-source dedupe; reported match count after cross-source dedupe.
3. Close non-matches (especially role matches rejected by location). Prefix debug lines with `listing_id` when helpful.

## Run flow

1. Load `assignment-listing-seen.json` (from disk or automation Memory).
2. For each **active** source in the registry: scan → normalize → within-source dedupe.
3. Merge all normalized records.
4. Mark new per source using `sources.<key>.seen_ids`.
5. Cross-source dedupe for reporting.
6. Apply active-date, role, and location filters.
7. Pre-Slack validation.
8. Post main Slack message.
9. Post debug thread.
10. Update `assignment-listing-seen.json` for every successfully scanned source; sync to automation Memory.
