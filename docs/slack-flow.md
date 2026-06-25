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
fit <assignment id> <name>   # from assignment list
fit <name>                     # from pasted ad text
```

Examples:

```text
fit 12345 Joel
fit 12345 Joel Andersson
fit v81387 Soma
fit Karin Toft
```

When the first token after `fit` is a listed assignment id (all digits, or `v`
followed by digits for Verama), the automation uses **listed assignment mode**
and reads the id and ad link from the parent message. When it is not a listed
id, the automation uses **pasted ad mode** and reads the assignment requirements
from the parent message text instead of fetching an online ad.

## Generate command

Users request an assignment-specific CV by replying in the assignment thread:

```text
generate <assignment id> <name> [language]   # from assignment list
generate <name> [language]                     # from pasted ad text
```

Examples:

```text
generate 12345 Joel
generate 12345 Joel Holmberg english
generate 12345 Joel Holmberg sv
generate v81387 Soma english
generate Karin Toft
generate Karin Toft english
generate Karin Toft sv
```

The optional language token must be the final token. Supported values are
`english`, `swedish`, `en`, and `sv`.

When the first token after `generate` is a listed assignment id (all digits, or
`v` followed by digits for Verama), the automation uses **listed assignment
mode** and reads the id and ad link from the parent message. When it is not a
listed id, the automation uses **pasted ad mode** and reads the assignment
requirements from the parent message text instead of fetching an online ad.

## Pasted ad flow

Sales can post assignment ad text directly in `#assignment-scanner` without
going through the assignment list:

1. Post the full assignment ad as a new channel message.
2. Reply in that thread with `fit <name>` or `generate <name>` (optionally plus
   language for `generate`).

The parent message is the assignment source. No assignment id or ad URL is
required.

## Fit automation flow

1. Read the Slack parent message and thread.
2. Parse the `fit` command and detect listed assignment mode vs pasted ad mode
   (listed assignment id vs consultant name).
3. **Listed assignment mode:** find the assignment id in the parent message,
   read the ad link, and fetch the online ad page.
4. **Pasted ad mode:** use the parent message text as the assignment ad.
5. Fuzzy match the consultant name against `canonicalName` and `aliases` in
   `consultants.yaml`.
6. Ask for clarification if the name is ambiguous.
7. Fetch the consultant's Cinode profile using `cinodeCompanyUserId`.
8. Score the consultant's active CV variants and select the best match for this
   assignment.
9. Load the selected variant's curated summary from `cv-summaries/`.
10. Reply in the thread with fit analysis and CV improvement suggestions,
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
2. Parse the `generate` command and detect listed assignment mode vs pasted ad
   mode (listed assignment id vs consultant name).
3. **Listed assignment mode:** find the assignment id in the parent message and
   read the ad link; fetch the online ad page.
4. **Pasted ad mode:** use the parent message text as the assignment ad; set
   `assignmentId` to `manual`.
5. Fuzzy match the consultant name against `canonicalName` and `aliases` in
   `consultants.yaml`.
6. Ask for clarification if the name is ambiguous.
7. Score the consultant's active CV variants and select the best match for this
   assignment.
8. From the selected variant's `rawFiles`, prefer a DOCX source CV over PDF.
   Use the requested language when supplied.
9. Fetch the consultant's Cinode profile using `cinodeCompanyUserId`.
10. Load the selected variant's curated summary from `cv-summaries/`.
11. Write assignment-specific CV content as JSON under
    `generated-cvs/<assignment-id> - <assignment title>/`.
12. Run `python scripts/render-cv.py` to produce HTML and PDF from
    `templates/cv.html.j2`.
13. Commit the generated JSON, HTML, and PDF files to the repository.
14. Reply in the thread with a GitHub link to the generated PDF and a short
    review reminder.

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
