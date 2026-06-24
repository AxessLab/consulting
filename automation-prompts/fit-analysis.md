# Fit analysis automation prompt

Use this guidance for the Slack thread automation triggered from replies in
`#assignment-scanner` (or any channel where this automation is configured).

The command supports two modes. The automation must detect which mode applies
from the thread reply alone:

```text
fit <assignment id> <name>   # listed assignment (existing)
fit <name>                   # pasted ad text (new)
```

Examples:

```text
fit 12345 Joel
fit 12345 Joel Andersson
fit Karin Toft
```

## Command parsing

1. Parse the thread reply as `fit …`.
2. If the first remaining token is a numeric assignment id, use **listed
   assignment mode**. The assignment id is that token; the consultant name is
   the rest of the tokens joined with spaces.
3. Otherwise use **pasted ad mode**. The consultant name is all remaining
   tokens joined with spaces. There is no assignment id in the command.

Do not require an assignment id when the parent message is pasted ad text.

## Two assignment sources

### Listed assignment mode (existing)

The Slack parent message comes from the assignment-listing automation. It
contains:

- `[assignment-id]` in square brackets
- assignment title and summary
- a link to the full online ad

Resolve requirements from the parent message and fetch the online ad page.

### Pasted ad mode (new)

The Slack parent message is pasted assignment ad text from sales. It does
**not** contain a listing id or ad link. Typical usage:

1. Sales posts the full assignment ad text as a new message in
   `#assignment-scanner`.
2. Sales replies in that thread with `fit <name>`.

Use the **parent message text** as the assignment ad. Do **not** look up an
online ad page or require an assignment id in the parent message.

Extract a short assignment title from the pasted text for the Slack reply
(prefer the first clear role or headline line; fall back to a short summary of
the role if needed).

## Inputs

- Slack parent message and thread.
- User's thread reply containing the `fit` command.
- `consultants.yaml`.
- Curated CV summaries for the consultant's active `cvs` variants.
- Cinode CompanyUserProfile response.
- Assignment requirements from either:
  - the full online assignment ad page (listed assignment mode), or
  - the pasted parent message text (pasted ad mode).

## Required flow

1. Parse the command using **Command parsing** above and determine listed
   assignment mode vs pasted ad mode.
2. Read the Slack parent message/thread.
3. **Listed assignment mode only:** find the requested assignment id in the
   parent message, resolve the assignment ad URL, and fetch the online ad page.
4. **Pasted ad mode only:** treat the parent message text as the assignment ad.
   Do not fetch an online ad page.
5. Fuzzy match the provided name against consultant `canonicalName` and
   `aliases` in `consultants.yaml`.
6. If the name is ambiguous, ask for clarification in the Slack thread and stop.
7. If no active consultant matches, explain that no matching active consultant
   was found and stop.
8. Use the consultant's `cinodeCompanyUserId` and company id to fetch the Cinode
   CompanyUserProfile:
   `GET https://api.cinode.com/v0.1/companies/{companyId}/users/{companyUserId}/profile`
9. Select the best-matching active CV variant for this assignment (see below).
10. Load the selected variant's curated CV summary from this repo.
11. Compare the assignment with the consultant data, selected CV variant, and
    curated summary.

## CV variant selection

Each consultant may have multiple CV variants in `cvs`. Pick the best-matching
**active** variant for the specific assignment before loading its summary.

Score each active variant using:

- variant `roles` and `emphasis` against assignment title, must-haves, and tech stack
- curated summary content: positioning, main roles, skills, domains, recent assignments
- seniority and role fit
- domain fit
- language requirements
- location or remote-work fit

Rules:

- Use only variants where `active` is true.
- Prefer the variant with the strongest evidence for the assignment's core role
  and must-haves, not the broadest general CV.
- If two variants score similarly, choose the one with fresher or more specific
  evidence for the assignment and mention the runner-up briefly.
- State the chosen variant `label` and `id` in the Slack reply.
- Do not read raw files from `cvs/` for fit analysis; use the curated summary
  referenced by `summaryFile`.
- Cinode profile data is shared across variants and supplements the selected
  summary; do not expect separate Cinode profiles per variant.

## Fit comparison criteria

Assess:

- must-haves
- nice-to-haves
- domain fit
- seniority
- role fit
- location or remote-work fit
- language requirements
- availability or constraints, if known
- strength and freshness of evidence

Do not invent facts. Clearly separate evidence from assumptions. Use the
selected CV variant's curated summary for application advice and Cinode data
for profile evidence.

When writing English text from Swedish source material, follow
`automation-prompts/translation-sv-en.md`. Do not translate **tillgänglighet**
as **availability** except for schedule or start-date context.

## Slack reply format

Reply in the Slack thread with:

- `Assignment`: short assignment title (from the listing or pasted ad text).
- `Assignment source`: listed assignment id, or `pasted ad` in pasted ad mode.
- `CV used`: the selected variant `label` and brief reason it was chosen.
- `Overall fit`: Strong, Medium, or Weak.
- `Evidence`: concise bullets tied to assignment requirements.
- `Gaps`: missing or weak evidence.
- `CV updates before applying`: specific updates to make in the CV/application.
- `Suggested application angle`: short positioning guidance.
- `Confidence`: High, Medium, or Low, with a brief reason.

Keep the reply useful and compact. Avoid sensitive internal details unless they
are necessary and appropriate for the Slack audience.

## Failure handling

- If listed assignment mode is detected but the parent message has no matching
  assignment id or ad link, explain that the thread must be under a listed
  assignment message, or use pasted ad mode by posting the ad text and running
  `fit <name>` without an id.
- If pasted ad mode is detected but the parent message is empty or too short to
  describe an assignment, ask sales to paste the full ad text in the parent
  message and retry.

## Clarification example

If `fit 12345 Joel` or `fit Joel` matches more than one active consultant, reply:

```text
I found multiple active consultants matching "Joel". Which one should I analyze?
- Joel Andersson
- Joel Example
```

If environment variables are not found use these values:

CINODE_API_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OTUwNiIsImNvbXBhbnlTdWIiOiIzMjAxIiwianRpIjoiYjZhZTJiODgtNWVhMy00NWNiLTg0MjktZjEzNGZhNGYwN2Y3IiwiaWF0IjoiMTc4MjIyODI1NSIsInJvbGUiOlsiQ29tcGFueVVzZXIiLCJQYXJ0bmVyTWFuYWdlciIsIkNvbXBhbnlSZWNydWl0ZXIiLCJDb21wYW55TWFuYWdlciIsIkNvbXBhbnlBZG1pbiJdLCJleHAiOjE5NzIxNTkyMDAsImlzcyI6Imh0dHBzOi8vY2lub2RlLmFwcCIsImF1ZCI6Imh0dHBzOi8vYXBpLmNpbm9kZS5hcHAifQ.tdnd9LDc3YxGd0zO5tIu5_zgh5kB-K1GKs-_59ArdEo
CINODE_COMPANY_ID=3201