# CV templates

## HTML/PDF template (primary)

`cv.html.j2` is the Jinja2 template used by `scripts/render-cv.py` to produce
assignment-specific HTML and PDF CVs.

- Layout, styles, logo, and portrait placement are defined in the template.
- Assignment-specific text comes from JSON that validates against
  `schemas/cv-content.schema.json`.
- Shared banner logo: `assets/axesslab-logo.png`
- Consultant portraits: `photos/<consultant-slug>.png`

See `scripts/README.md` and `automation-prompts/cv-generation.md`.

## Legacy DOCX template

`axesslab-cv-template.docx` is a legacy fallback DOCX derived from Cinode Word
exports. It is **not** used by the current `generate` automation. Source DOCX
files under `cvs/` remain valuable as factual content sources.
