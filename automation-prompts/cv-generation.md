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
- Curated CV summaries and raw files for the consultant's active `cvs` variants.
- Cinode CompanyUserProfile response.
- Full online assignment ad page.
- Fallback DOCX template at `templates/axesslab-cv-template.docx`.

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
10. Score the consultant's active CV variants and select the best match for this
    assignment using the same rules as the `fit` automation (see
    `automation-prompts/fit-analysis.md`, section "CV variant selection").
11. From the selected variant's `rawFiles`, prefer a DOCX source CV over PDF.
    Use the requested language when supplied. If no raw CV is available, explain
    that the variant needs a source CV before a DOCX can be generated and stop.
12. Use the consultant's `cinodeCompanyUserId` and company id to fetch the Cinode
    CompanyUserProfile:
    `GET https://api.cinode.com/v0.1/companies/{companyId}/users/{companyUserId}/profile`
13. Load the selected variant's curated CV summary from this repo.
14. Fetch the assignment ad page.
15. Generate a new assignment-specific DOCX CV. Do not overwrite the source CV.
16. Save the generated file under:
    `generated-cvs/<assignment-id>/<consultant-slug>-<language>.docx`
17. Commit the generated DOCX directly to the repository's main branch according
    to the automation runtime's GitHub permissions.
18. Reply in the Slack thread with the GitHub file link and a short summary of
    the selected CV variant, source CV, template source, language, and assignment
    positioning.

## Layout and template rules

- When the selected source CV is DOCX, use that DOCX as the base document and
  preserve its layout, styles, headers, footers, tables, spacing, section order,
  and branding as far as the editing tool supports.
- Rewrite or replace only the content needed to tailor the CV to the assignment.
- When the selected source CV is PDF, use it only as a content source. Generate
  the DOCX from `templates/axesslab-cv-template.docx` and include a Slack review
  note that the original PDF layout was not preserved.
- If no source CV matches the requested language, translate the generated content
  into the requested language while preserving the selected DOCX layout or the
  fallback template layout.
- If no language is requested, use the selected source CV's language.

## Generated CV rules

- Generate DOCX output only.
- Keep facts grounded in the source CV, Cinode profile, curated CV summary, and
  assignment ad.
- Do not invent clients, dates, titles, certifications, outcomes, language
  ability, availability, or security clearance.
- Tailor emphasis, ordering, summary text, and skills presentation to the
  assignment requirements.
- Preserve consultant identity and contact details only when they already appear
  in the selected source CV and are appropriate for generated CV storage.
- Keep internal notes, uncertainty, and prompt reasoning out of the generated
  DOCX.

## Slack reply format

Reply in the Slack thread with:

- `Generated CV`: GitHub link to the DOCX file.
- `CV variant`: selected variant `label` and `id`.
- `Language`: generated CV language.
- `Source CV`: source CV path or filename used.
- `Template`: source DOCX layout used, or
  `templates/axesslab-cv-template.docx` when the source CV was PDF.
- `Positioning`: one compact sentence about how the CV was tailored.
- `Review note`: remind the requester to review the generated CV before sending
  it to a client.

## Failure handling

- If the requested language is unsupported, explain the supported values:
  `english`, `swedish`, `en`, `sv`.
- If there are multiple equally good CV variants, ask which variant to use
  instead of guessing.
- If GitHub write-back fails, reply that generation succeeded locally but the
  file could not be stored, without exposing tokens, stack traces, or secrets.
