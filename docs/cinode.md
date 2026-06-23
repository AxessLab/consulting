# Cinode integration

The fit automation uses Cinode profile data together with curated CV summaries
from this repo.

## Endpoint

Fetch consultant profile data with:

```text
GET https://api.cinode.com/v0.1/companies/{companyId}/users/{companyUserId}/profile
```

Where:

- `{companyId}` is the Cinode company id.
- `{companyUserId}` is the consultant's `cinodeCompanyUserId` from
  `consultants.yaml`.

## Required configuration

Configure these as Cursor Automation secrets/env vars. Do not commit real values
to this repository.

- `CINODE_API_TOKEN`
- `CINODE_COMPANY_ID`

`consultants.yaml` may contain a placeholder `companyId` for schema validation
and documentation, but runtime automations should prefer the configured
`CINODE_COMPANY_ID` secret/env var when available.

## Authentication

Use `CINODE_API_TOKEN` in the automation runtime according to Cinode's API
authentication requirements.

Do not write the token to logs, Slack messages, generated files, or prompt
output.

## Data use

Use Cinode profile data only for the requested fit analysis. Combine it with the
curated CV summary to identify relevant evidence, missing evidence, and practical
CV updates before applying.
