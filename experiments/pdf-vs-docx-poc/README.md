# PDF vs DOCX experiment (completed)

This folder validated that HTML → PDF produces readable assignment-specific CVs
while direct AI DOCX editing does not.

The production pipeline now lives at:

- `templates/cv.html.j2`
- `schemas/cv-content.schema.json`
- `scripts/render-cv.py`
- `examples/karin-toft-english.json`

See `scripts/README.md` and `automation-prompts/cv-generation.md`.
