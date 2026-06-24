# Slack flow

This document describes how Slack assignment listings and thread-based fit
analysis requests should work.

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

## CV generation command

Users request an assignment-specific DOCX CV by replying in the assignment
thread:

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
8. Load the consultant's curated CV summary from `cv-summaries/`.
9. Fetch the assignment ad page.
10. Reply in the thread with fit analysis and CV improvement suggestions.

## CV generation automation flow

1. Read the Slack parent message and thread.
2. Parse the assignment id, consultant name, and optional language from the
   `generate` command.
3. Find the matching assignment id in the parent message.
4. Read the full assignment ad link from that Slack item.
5. Fuzzy match the consultant name against `canonicalName` and `aliases` in
   `consultants.yaml`.
6. Ask for clarification if the name is ambiguous.
7. Select the best source CV from the consultant's `sourceCvFiles`, preferring
   DOCX files, requested language, assignment role fit, and then the default
   source CV.
8. Fetch the consultant's Cinode profile using `cinodeCompanyUserId`.
9. Load the consultant's curated CV summary from `cv-summaries/`.
10. Fetch the assignment ad page.
11. Generate a new DOCX file under `generated-cvs/<assignment-id>/`.
12. Preserve the selected source DOCX layout when available. If the selected
    source CV is PDF, use `templates/axesslab-cv-template.docx`.
13. Commit the generated DOCX file to the repository.
14. Reply in the thread with a GitHub link to the generated DOCX file and a
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
Detailed fit replies should stay factual and relevant to the specific assignment.
Generated CV replies should link only to repository files intended for reviewers
with GitHub access, not to unauthenticated public file shares.
