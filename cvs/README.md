# Source CV files

Store existing source CVs here for assignment-specific DOCX generation.

Recommended filename pattern:

```text
<employee-name> - <role> - <language>.pdf
```

Examples:

```text
Joel Holmberg - Fullstack Developer - Swedish.pdf
Joel Holmberg - Architect - English.pdf
```

If a filename includes a client name, ignore the client name when setting the
`role` value in `consultants.yaml`.

Each source CV should be referenced from the consultant's `sourceCvFiles`
metadata before the `generate` Slack command uses it.
