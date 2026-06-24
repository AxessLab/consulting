# Slack flow

This document describes how Slack assignment listings and thread-based fit
analysis and CV generation requests should work.

## Assignment list message

The assignment-listing automation posts compact Slack items. Each item should
include:

- assignment id in square brackets
- assignment title
- location and/or main role summary
- link to the full online ad
- suggested consultant names

Example:

```text
[12345] Senior Front-end Developer, Stockholm
<https://example.com/ad/12345|View ad>
Good matches: Joel, Lena
```

## Fit command

Users request detailed analysis by replying in the assignment thread:

```text
fit <assignment id> <name>
```

Examples:

```text
fit 12345 Joel
fit 12345 Joel Andersson
```

## Generate command

Users request an assignment-specific DOCX CV by replying in the assignment thread:

```text
generate <assignment id> <name> [language]
```

Examples:

```text
generate 12345 Joel
generate 12345 Joel Holmberg english
generate 12345 Joel Holmberg sv
```

The optional language token must be the final token. Supported values are
`english`, `swedish`, `en`, and `sv`.

## Fit automation flow

1. Read the Slack parent message and thread.
2. Parse the assignment id and consultant name from the `fit` command.
3. Find the matching assignment id in the parent message.
4. Read the full assignment ad link from that Slack item.
5. Fuzzy match the consultant name against `canonicalName` and `aliases` in
   `consultants.yaml`.
6. Ask for clarification if the name is ambiguous.
7. Fetch the consultant's Cinode profile using `cinodeCompanyUserId`.
8. Fetch the assignment ad page.
9. Score the consultant's active CV variants and select the best match for this
   assignment.
10. Load the selected variant's curated summary from `cv-summaries/`.
11. Reply in the thread with fit analysis and CV improvement suggestions,
    including which CV variant was used.

## CV variant selection

When a consultant has multiple active variants in `cvs`, both `fit` and
`generate` should:

- score each active variant against the assignment title, must-haves, role,
  seniority, domain, tech stack, and language requirements
- use the best-matching variant's `summaryFile` as the primary input
- state the chosen variant `label` in the Slack reply
- mention a close runner-up when two variants score similarly

Cinode profile data is shared across variants for a consultant.

## CV generation automation flow

1. Read the Slack parent message and thread.
2. Parse the assignment id, consultant name, and optional language from the
   `generate` command.
3. Find the matching assignment id in the parent message.
4. Read the full assignment ad link from that Slack item.
5. Fuzzy match the consultant name against `canonicalName` and `aliases` in
   `consultants.yaml`.
6. Ask for clarification if the name is ambiguous.
7. Score the consultant's active CV variants and select the best match for this
   assignment.
8. From the selected variant's `rawFiles`, prefer a DOCX source CV over PDF.
   Use the requested language when supplied.
9. Fetch the consultant's Cinode profile using `cinodeCompanyUserId`.
10. Load the selected variant's curated summary from `cv-summaries/`.
11. Fetch the assignment ad page.
12. Generate a new DOCX file under `generated-cvs/<assignment-id>/`.
13. Preserve the selected source DOCX layout when available. If the selected
    source CV is PDF, use `templates/axesslab-cv-template.docx`.
14. Commit the generated DOCX file to the repository.
15. Reply in the thread with a GitHub link to the generated DOCX file and a
    short review reminder.

## Ambiguity handling

If a provided name matches multiple active consultants, the automation should ask
the user to clarify instead of guessing.

Example:

```text
I found multiple active consultants matching "Joel". Which one should I analyze?
- Joel Andersson
- Joel Example
```

## Slack output privacy

Assignment list messages should not include sensitive consultant details,
internal CV weaknesses, private profile content, or unnecessary personal data.
Detailed fit replies should stay factual and relevant to the specific
assignment. Generated CV replies should link only to repository files intended
for reviewers with GitHub access, not to unauthenticated public file shares. Do
not paste full raw CV content into Slack.
