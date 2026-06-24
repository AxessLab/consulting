# Consulting automation data

This private repository is the source of truth for consultant metadata, source
CV files, generated CV drafts, and manually curated CV/application summaries
used by Cursor Automations that analyze consultant fit for IT assignments posted
in Slack.

The repository is intentionally simple and human-editable. It contains
consultant metadata, Markdown guidance, source CV files, and generated DOCX
drafts, with no application code, build step, runtime services, or stored
secrets.

## Consultant metadata

Consultant lookup data is stored in `consultants.yaml`.

Each consultant entry includes:

- `canonicalName`: the preferred display name.
- `aliases`: names the Slack automation may fuzzy match against.
- `cinodeCompanyUserId`: the consultant's Cinode company user id.
- `mainRoles`: short role tags used for assignment matching.
- `locations`: location tags used for assignment matching.
- `cvSummaryFile`: path to the curated Markdown summary in this repo.
- `sourceCvFiles`: source PDF/DOCX CV variants available for generated CVs.
- `active`: whether the consultant should be considered for new matches.

The YAML structure is documented in `schemas/consultants.schema.json`.

## Source CVs and CV summaries

Source CV files live under `cvs/`.

Each consultant's `sourceCvFiles` metadata lists the source CV variants available
for assignment-specific DOCX generation. Use the source filename to infer the
role and language. Ignore client names in filenames when choosing the `role`
value.

Generated assignment-specific DOCX files should be stored under:

`generated-cvs/<assignment-id>/<consultant-slug>-<language>.docx`

The generation automation may commit generated DOCX files directly to the main
branch when configured with appropriate GitHub permissions. The Slack reply
should link to the generated file in GitHub.

Curated CV/application summaries live under `cv-summaries/`.

Each file should follow the structure in `cv-summaries/_template.md` and should
contain factual, reviewed, non-sensitive information that helps the automation
compare an assignment ad with the consultant's relevant experience.

## Slack assignment list flow

The existing assignment-listing automation should keep Slack assignment list
items compact while including:

- assignment id
- title
- location or main role summary
- link to the full online ad
- suggested consultant names

Example:

`[12345] Senior Front-end Developer, Stockholm`
`<https://example.com/ad/12345|View ad>`
`Good matches: Joel, Lena`

Prompt guidance for this automation is in
`automation-prompts/assignment-listing.md`.

## Slack fit command

A second automation is triggered from Slack thread replies using:

`fit <assignment id> <name>`

Examples:

- `fit 12345 Joel`
- `fit 12345 Joel Andersson`

The automation should read the Slack parent message/thread, find the assignment
id, resolve the assignment ad link from the parent message, fuzzy match the
provided name against `consultants.yaml`, fetch the consultant profile from
Cinode using the consultant's `cinodeCompanyUserId`, load the curated CV summary
from this repo, fetch the assignment ad page, and post a Slack thread reply with
fit analysis and CV improvement suggestions.

Prompt guidance for this automation is in `automation-prompts/fit-analysis.md`.

## Slack CV generation command

A separate automation is triggered from Slack thread replies using:

`generate <assignment id> <name> [language]`

Examples:

- `generate 12345 Joel`
- `generate 12345 Joel Holmberg english`
- `generate 12345 Joel Holmberg sv`

The optional language token must be the final token. Supported language values
are `english`, `swedish`, `en`, and `sv`.

The automation should read the Slack parent message/thread, find the assignment
id, resolve the assignment ad link from the parent message, fuzzy match the
provided name against `consultants.yaml`, select the best source CV from the
consultant's `sourceCvFiles`, fetch the consultant profile from Cinode using the
consultant's `cinodeCompanyUserId`, load the curated CV summary from this repo,
fetch the assignment ad page, generate an assignment-specific DOCX CV, store it
under `generated-cvs/`, commit it to the repository, and post a Slack thread
reply with a GitHub link to the generated file.

Prompt guidance for this automation is in
`automation-prompts/cv-generation.md`.

## Cinode IDs

`companyId` identifies the Cinode company. Each consultant's
`cinodeCompanyUserId` identifies the user within that company.

The fit automation uses these values to fetch:

`GET https://api.cinode.com/v0.1/companies/{companyId}/users/{companyUserId}/profile`

Cinode setup notes are in `docs/cinode.md`.

## Secrets and configuration

Do not store API tokens, Slack credentials, private keys, or other secrets in
this repository.

Configure secrets and environment variables in Cursor Automation secrets/env
vars, for example:

- `CINODE_API_TOKEN`
- `CINODE_COMPANY_ID`

Use templates and placeholders in this repo. Do not add real personal data until
it has a clear operational purpose and has been reviewed under the privacy rules
in `docs/data-governance.md`.
