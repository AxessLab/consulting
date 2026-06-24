# CV generation automation prompt

Use this guidance for the Slack thread automation triggered by:

```text
generate <assignment id> <name> [language]
```

Examples:

```text
generate 12345 Joel
generate 12345 Joel Holmberg english
generate 12345 Joel Holmberg sv
```

## Inputs

- Slack parent message and thread.
- User's thread reply containing the `generate` command.
- `consultants.yaml`.
- Source CV files listed in the consultant's `sourceCvFiles`.
- Curated CV summary referenced by `cvSummaryFile`.
- Cinode CompanyUserProfile response.
- Full online assignment ad page.

## Required flow

1. Parse the command as `generate <assignment id> <name> [language]`.
2. Treat the optional final token as a requested language only when it is one of
   `en`, `english`, `sv`, or `swedish`.
3. Normalize `en` and `english` to `english`; normalize `sv` and `swedish` to
   `swedish`.
4. Read the Slack parent message/thread.
5. Find the requested assignment id in the Slack message.
6. Resolve the assignment ad URL from the Slack message.
7. Fuzzy match the provided name against consultant `canonicalName` and
   `aliases` in `consultants.yaml`.
8. If the name is ambiguous, ask for clarification in the Slack thread and stop.
9. If no active consultant matches, explain that no matching active consultant
   was found and stop.
10. Select the best source CV from `sourceCvFiles`:
    - Prefer the requested language when supplied.
    - Prefer a source CV whose `role` best matches the assignment.
    - Use the consultant's `default: true` CV when no role-specific match is
      clear.
    - If no source CV is available, explain that the consultant needs source CV
      metadata before a DOCX can be generated and stop.
11. Use the consultant's `cinodeCompanyUserId` and company id to fetch the Cinode
    CompanyUserProfile:
    `GET https://api.cinode.com/v0.1/companies/{companyId}/users/{companyUserId}/profile`
12. Load the consultant's curated CV summary from this repo.
13. Fetch the assignment ad page.
14. Generate a new assignment-specific DOCX CV. Do not overwrite the source CV.
15. Save the generated file under:
    `generated-cvs/<assignment-id>/<consultant-slug>-<language>.docx`
16. Commit the generated DOCX directly to the repository's main branch according
    to the automation runtime's GitHub permissions.
17. Reply in the Slack thread with the GitHub file link and a short summary of
    the selected source CV, language, and assignment positioning.

## Generated CV rules

- Generate DOCX output only.
- Keep facts grounded in the source CV, Cinode profile, curated CV summary, and
  assignment ad.
- Do not invent clients, dates, titles, certifications, outcomes, language
  ability, availability, or security clearance.
- Tailor emphasis, ordering, summary text, and skills presentation to the
  assignment requirements.
- Translate to the requested language when needed. If no language is requested,
  use the selected source CV's language.
- Preserve consultant identity and contact details only when they already appear
  in the selected source CV and are appropriate for generated CV storage.
- Keep internal notes, uncertainty, and prompt reasoning out of the generated
  DOCX.

## Slack reply format

Reply in the Slack thread with:

- `Generated CV`: GitHub link to the DOCX file.
- `Language`: generated CV language.
- `Source CV`: source CV path or filename used.
- `Positioning`: one compact sentence about how the CV was tailored.
- `Review note`: remind the requester to review the generated CV before sending
  it to a client.

## Failure handling

- If the requested language is unsupported, explain the supported values:
  `english`, `swedish`, `en`, `sv`.
- If there are multiple equally good source CVs, ask which role/language variant
  to use instead of guessing.
- If GitHub write-back fails, reply that generation succeeded locally but the
  file could not be stored, without exposing tokens, stack traces, or secrets.
