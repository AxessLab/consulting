# Consulting automation data

This private repository is the source of truth for consultant metadata and
manually curated CV/application summaries used by Cursor Automations that
analyze consultant fit for IT assignments posted in Slack.

The repository is intentionally simple and human-editable. It contains plain
YAML and Markdown only, with no application code, build step, runtime services,
or stored secrets.

## Consultant metadata

Consultant lookup data is stored in `consultants.yaml`.

Each consultant entry includes:

- `canonicalName`: the preferred display name.
- `aliases`: names the Slack automation may fuzzy match against.
- `cinodeCompanyUserId`: the consultant's Cinode company user id.
- `mainRoles`: short role tags used for assignment matching.
- `locations`: location tags used for assignment matching.
- `cvs`: one or more CV variants for this consultant (see below).
- `active`: whether the consultant should be considered for new matches.

The YAML structure is documented in `schemas/consultants.schema.json`.

## CV variants

A consultant may have multiple CV variants. Each variant in `cvs` includes:

- `id`: stable machine-readable identifier.
- `label`: human-readable name shown in Slack replies.
- `summaryFile`: path to the curated Markdown summary for this variant.
- `rawFiles`: optional paths to source CV documents under `cvs/`.
- `roles`: role and skill tags used to match this variant against assignments.
- `emphasis`: short note on what this variant leads with.
- `active`: whether this variant should be considered for matching.

Raw CV files live under `cvs/`. Curated summaries live under `cv-summaries/`.
Each variant should have its own curated summary file.

The `fit` and `generate` automations score active variants against the
assignment and use the best-matching one.

## CV summaries

Curated CV/application summaries live under `cv-summaries/`.

Each file should follow the structure in `cv-summaries/_template.md` and should
contain factual, reviewed, non-sensitive information that helps the automation
compare an assignment ad with the consultant's relevant experience for that
specific CV variant.

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
Cinode using the consultant's `cinodeCompanyUserId`, select the best-matching
active CV variant for the assignment, load that variant's curated summary from
this repo, fetch the assignment ad page, and post a Slack thread reply with fit
analysis and CV improvement suggestions.

Prompt guidance for this automation is in `automation-prompts/fit-analysis.md`.

## Slack generate command

A third automation is triggered from Slack thread replies using:

`generate <assignment id> <name>`

Examples:

- `generate 12345 Joel`
- `generate 12345 Joel Holmberg`

The automation follows the same consultant lookup, Cinode fetch, assignment ad
fetch, and CV variant selection steps as `fit`. It then uses the selected
variant's curated summary and raw CV file to produce tailored application
guidance for the assignment.

Prompt guidance for this automation is in `automation-prompts/generate-cv.md`.

## Cinode IDs

`companyId` identifies the Cinode company. Each consultant's
`cinodeCompanyUserId` identifies the user within that company.

The fit and generate automations use these values to fetch:

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
