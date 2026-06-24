# Consultant portraits

Portrait images for generated HTML/PDF CVs.

## Convention

- File name: `<consultant-slug>.png` (for example `karin-toft.png`).
- Slug is derived from `canonicalName` in `consultants.yaml` unless `slug` is set explicitly.
- Images are extracted from the square portrait embedded in each consultant's source DOCX CV (`word/media/image2.png` in typical Cinode exports).

## Refresh portraits

```bash
pip install -r requirements.txt
python scripts/extract-photos.py
```

The script also writes the shared Axesslab banner logo to `templates/assets/axesslab-logo.png`.

## Overrides

Set optional `photoFile` on a consultant in `consultants.yaml` when the portrait should come from a custom path instead of `photos/<slug>.png`.
