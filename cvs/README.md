# Source CV files

Store existing source CVs here as factual content sources for assignment-specific
HTML/PDF generation.

Recommended filename pattern:

```text
<employee-name> - <role> - <language>.docx
```

DOCX files are preferred because they include embedded portrait images and rich
factual content. PDF files are also supported as content sources when no DOCX is
available for a variant.

Examples:

```text
Joel Holmberg - Fullstack Developer - Swedish.docx
Joel Holmberg - Architect - English.docx
```

If a filename includes a client name, ignore the client name when setting the
`role` value in `consultants.yaml`.

Each source CV should be listed in the consultant's CV variant `rawFiles` in
`consultants.yaml` before the `generate` Slack command uses it.

Refresh portrait images extracted from these files with:

```bash
python scripts/extract-photos.py
```
