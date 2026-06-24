# Source CV files

Store existing source CVs here for assignment-specific DOCX generation.

Recommended filename pattern:

```text
<employee-name> - <role> - <language>.docx
```

PDF files are supported as content sources, but DOCX files are preferred because
the `generate` automation can preserve their layout, styles, headers, footers,
tables, section order, and branding.

Examples:

```text
Joel Holmberg - Fullstack Developer - Swedish.docx
Joel Holmberg - Architect - English.docx
```

If a filename includes a client name, ignore the client name when setting the
`role` value in `consultants.yaml`.

Each source CV should be referenced from the consultant's `sourceCvFiles`
metadata before the `generate` Slack command uses it.
