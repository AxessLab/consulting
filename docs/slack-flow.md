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
