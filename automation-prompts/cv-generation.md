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
- HTML template at `templates/cv.html.j2`.
- Portrait images under `photos/` (see `photos/README.md`).
- Shared logo at `templates/assets/axesslab-logo.png`.
- CV content schema at `schemas/cv-content.schema.json`.

## Environment setup

Before rendering CVs, install Python dependencies once in the automation runtime:

```bash
pip install -r requirements.txt
```

PDF rendering requires a Chromium-based browser (`msedge`, `chrome`, or `chromium`) available on `PATH` or in a standard install location. See `scripts/README.md`.

## Required flow

1. Parse the command as `generate <assignment id> <name> [language]`.
2. Treat the optional final token as a requested language only when it is one of
   `en`, `english`, `sv`, or `swedish`. If omitted, infer language based on the title of the assignment.
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
11. From the selected variant's `rawFiles`, prefer a DOCX source CV over PDF as
    the factual content source. Use the requested language when supplied. If no
    raw CV is available, explain that the variant needs a source CV before a CV
    can be generated and stop.
12. Use the consultant's `cinodeCompanyUserId` and company id to fetch the Cinode
    CompanyUserProfile:
    `GET https://api.cinode.com/v0.1/companies/{companyId}/users/{companyUserId}/profile`
13. Load the selected variant's curated CV summary from this repo.
14. Fetch the assignment ad page.
15. Build assignment-specific CV content as JSON that validates against
    `schemas/cv-content.schema.json`. Do not write HTML, PDF, or DOCX directly.
16. Save the JSON under:
    `generated-cvs/<assignment-id> - <assignment title>/<consultant-slug>-<language>.json`
    Build the folder name as `{assignmentId} - {assignmentTitle}`. Replace characters
    that are invalid in file paths (`:`, `/`, `\`, `|`, `?`, `*`, `<`, `>`) before
    writing. A colon in the title becomes ` - ` (for example
    `4 - Team Webbkonsulter - Roll 2 - Frontend Developer, Level 3 (Vinnova)`).
17. Run the render script:
    `python scripts/render-cv.py "generated-cvs/<assignment-folder>/<consultant-slug>-<language>.json" --skip-json`
    This produces matching `.html` and `.pdf` files in the same directory.
18. Commit the generated JSON, HTML, and PDF to the repository's main branch
    according to the automation runtime's GitHub permissions.
19. Reply in the Slack thread with the GitHub link to the **PDF** and a short
    summary of the selected CV variant, source CV, language, and assignment
    positioning.

## Content rules

- Keep facts grounded in the source CV, Cinode profile, curated CV summary, and
  assignment ad.
- Do not invent clients, dates, titles, certifications, outcomes, language
  ability, availability, or security clearance.
- Tailor emphasis, ordering, summary text, project selection, and skills
  presentation to the assignment requirements.
- Preserve consultant identity and contact details only when they already appear
  in the selected source CV and are appropriate for generated CV storage.
- Use `assignmentTitle` in the Slack reply only. Do **not** include assignment
  names, tailoring notes, or internal sales guidance in rendered CV content.
- Write client-ready profile and project text. Avoid phrases such as "for this
  assignment", "tailored for", or "most relevant for the role".
- Use `consultantSlug` matching the filename convention (`karin-toft`, not
  `karin-toft-frontend-engineer`).
- Keep internal notes, uncertainty, and prompt reasoning out of the JSON and
  rendered files.

## Swedish–English translation

When `language` is `english`, follow `automation-prompts/translation-sv-en.md`.

In short: translate **tillgänglighet** / **tillgänglig** as **accessibility** /
**accessible** in roles, skills, projects, and certifications. Use
**availability** / **available** only for start date, schedule, or assignment
capacity — not for accessibility work.

Before committing English JSON, check that skill chips, role titles, and project
text do not contain “availability” where the Swedish source means digital
accessibility.

## JSON content shape

Required top-level fields are defined in `schemas/cv-content.schema.json`. In
summary:

- `contact`: Axesslab contact person from the source CV header.
- `consultantName` and `roleTitle`: consultant identity from the source CV.
- `profileParagraphs`: 1–3 client-ready summary paragraphs (emphasis may reflect
  the assignment, but wording must not reference the assignment or sales process).
- `selectedEvidence`: 2–4 short highlight blocks; use the most relevant projects
  for the assignment.
- `competenceChips`: scannable skill tags for the assignment.
- `projects`: fuller project history, ordered with the most relevant first.
- `skillLevels`: grouped skills (`Expert`, `Advanced`, etc.).
- `languages`: language and proficiency pairs.

Use Swedish section labels via the optional `labels` object when
`language` is `swedish`. When omitted, the render script applies defaults.

See `examples/karin-toft-english.json` for a complete example.

## Source CV usage

- DOCX and PDF source CVs are **content sources only**. Do not edit or regenerate
  DOCX files.
- PDF source CVs are acceptable when no DOCX exists for the selected variant.
- Portrait images are resolved from `photos/<consultant-slug>.png`. Run
  `python scripts/extract-photos.py` if a portrait is missing.

## Slack reply format

Reply in the Slack thread with:

- `Generated CV`: GitHub link to the **PDF** file.
- `Preview`: GitHub link to the HTML file (optional but helpful).
- `Assignment`: `assignmentTitle` from the JSON (internal context for sales).
- `CV variant`: selected variant `label` and `id`.
- `Language`: generated CV language.
- `Source CV`: source CV path or filename used.
- `Template`: `templates/cv.html.j2`.
- `Positioning`: one compact sentence about how the CV was tailored.
- `Review note`: remind the requester to review the generated CV before sending
  it to a client.

## Failure handling

- If the requested language is unsupported, explain the supported values:
  `english`, `swedish`, `en`, `sv`.
- If there are multiple equally good CV variants, ask which variant to use
  instead of guessing.
- If JSON validation or `render-cv.py` fails, reply with a short error summary
  and do not commit broken output files.
- If GitHub write-back fails, reply that generation succeeded locally but the
  file could not be stored, without exposing tokens, stack traces, or secrets.

If environment variables are not found use these values:

CINODE_API_KEY=e<API_KEY_HERE>
CINODE_COMPANY_ID=<CINODE_COMPANY_ID_HERE>
