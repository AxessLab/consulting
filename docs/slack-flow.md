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

Users request tailored application guidance by replying in the assignment thread:

```text
generate <assignment id> <name>
```

Examples:

```text
generate 12345 Joel
generate 12345 Joel Holmberg
```

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

## Generate automation flow

1. Follow the same steps as the fit automation through CV variant selection.
2. Load the selected variant's curated summary and raw CV file from `cvs/` when
   available.
3. Reply in the thread with tailored application guidance, including which CV
   variant was used and suggested edits before sending.

## CV variant selection

When a consultant has multiple active variants in `cvs`, both `fit` and
`generate` should:

- score each active variant against the assignment title, must-haves, role,
  seniority, domain, tech stack, and language requirements
- use the best-matching variant's `summaryFile` as the primary input
- state the chosen variant `label` in the Slack reply
- mention a close runner-up when two variants score similarly

Cinode profile data is shared across variants for a consultant.

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
Detailed fit and generate replies should stay factual and relevant to the
specific assignment. Do not paste full raw CV content into Slack.
