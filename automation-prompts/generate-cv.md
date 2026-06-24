# Generate CV automation prompt

Use this guidance for the Slack thread automation triggered by:

```text
generate <assignment id> <name>
```

Examples:

```text
generate 12345 Joel
generate 12345 Joel Holmberg
```

## Inputs

- Slack parent message and thread.
- User's thread reply containing the `generate` command.
- `consultants.yaml`.
- Curated CV summaries for the consultant's active `cvs` variants.
- Raw CV files referenced by the selected variant's `rawFiles`, when available.
- Cinode CompanyUserProfile response.
- Full online assignment ad page.

## Required flow

1. Parse the command as `generate <assignment id> <name>`.
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
10. Select the best-matching active CV variant for this assignment using the same
    rules as the `fit` automation (see `automation-prompts/fit-analysis.md`,
    section "CV variant selection").
11. Load the selected variant's curated CV summary from this repo.
12. Load the selected variant's raw CV file from `rawFiles` when present. Prefer
    editable source formats (for example `.docx`) over `.pdf` when both exist for
    the same variant.
13. Produce a tailored application package for the assignment.

## CV variant selection

Use the same variant-selection rules as `fit`:

- Score each active variant in `cvs` against the assignment.
- Pick the variant with the strongest match for the assignment's core role and
  must-haves.
- State the chosen variant `label` and `id` in the Slack reply.
- Mention a close runner-up variant when relevant.

## Generation output

Reply in the Slack thread with:

- `CV used`: the selected variant `label`, `id`, and brief reason it was chosen.
- `Tailored summary`: short positioning paragraph for this assignment.
- `Key highlights to lead with`: bullets mapped to assignment must-haves.
- `Suggested CV edits`: concrete changes to make in the selected raw CV before
  sending, based on assignment gaps and the curated summary's improvement notes.
- `Cover letter angle`: short guidance or draft opening paragraph, if useful.
- `Confidence`: High, Medium, or Low, with a brief reason.

Do not paste the full raw CV into Slack. Keep output actionable and compact.

## Data use rules

- Use the selected variant's curated summary as the primary source for what to
  emphasize and what to adjust.
- Use Cinode profile data to fill gaps or verify facts, not to replace the
  variant's positioning.
- Use the raw CV file to understand current structure and wording, not as the
  only source of truth.
- Do not invent experience, skills, certifications, or outcomes.
- Clearly separate verified evidence from suggested edits that need human review.

## Clarification example

If `generate 12345 Joel` matches more than one active consultant, reply:

```text
I found multiple active consultants matching "Joel". Which CV should I generate for?
- Joel Andersson
- Joel Example
```
