# Fit analysis automation prompt

Use this guidance for the Slack thread automation triggered by:

```text
fit <assignment id> <name>
```

Examples:

```text
fit 12345 Joel
fit 12345 Joel Andersson
```

## Inputs

- Slack parent message and thread.
- User's thread reply containing the `fit` command.
- `consultants.yaml`.
- Curated CV summaries for the consultant's active `cvs` variants.
- Cinode CompanyUserProfile response.
- Full online assignment ad page.

## Required flow

1. Parse the command as `fit <assignment id> <name>`.
2. Read the Slack parent message/thread.
3. Find the requested assignment id in the Slack message.
4. Resolve the assignment ad URL from the Slack message.
5. Fuzzy match the provided name against consultant `canonicalName` and
   `aliases` in `consultants.yaml`.
6. If the name is ambiguous, ask for clarification in the Slack thread and stop.
7. If no active consultant matches, explain that no matching active consultant
   was found and stop.
8. Use the consultant's `cinodeCompanyUserId` and company id to fetch the Cinode
   CompanyUserProfile:
   `GET https://api.cinode.com/v0.1/companies/{companyId}/users/{companyUserId}/profile`
9. Fetch the assignment ad page.
10. Select the best-matching active CV variant for this assignment (see below).
11. Load the selected variant's curated CV summary from this repo.
12. Compare the assignment with the consultant data, selected CV variant, and
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

## Slack reply format

Reply in the Slack thread with:

- `CV used`: the selected variant `label` and brief reason it was chosen.
- `Overall fit`: Strong, Medium, or Weak.
- `Evidence`: concise bullets tied to assignment requirements.
- `Gaps`: missing or weak evidence.
- `CV updates before applying`: specific updates to make in the CV/application.
- `Suggested application angle`: short positioning guidance.
- `Confidence`: High, Medium, or Low, with a brief reason.

Keep the reply useful and compact. Avoid sensitive internal details unless they
are necessary and appropriate for the Slack audience.

## Clarification example

If `fit 12345 Joel` matches more than one active consultant, reply:

```text
I found multiple active consultants matching "Joel". Which one should I analyze?
- Joel Andersson
- Joel Example
```
