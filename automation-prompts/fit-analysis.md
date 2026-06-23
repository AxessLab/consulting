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
- Curated CV summary referenced by `cvSummaryFile`.
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
9. Load the consultant's curated CV summary from this repo.
10. Fetch the assignment ad page.
11. Compare the assignment with the consultant data and curated summary.

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

Do not invent facts. Clearly separate evidence from assumptions. Use curated CV
summary content for application advice and Cinode data for profile evidence.

## Slack reply format

Reply in the Slack thread with:

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
