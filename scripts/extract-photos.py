#!/usr/bin/env python3
"""Extract consultant portraits and the shared Axesslab logo from source DOCX CVs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from consultant_utils import (
    LOGO_PATH,
    PHOTOS_DIR,
    consultant_slug,
    extract_images_from_docx,
    first_docx_for_consultant,
    load_consultants,
    pick_portrait_and_logo,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--logo-source",
        type=Path,
        help="DOCX file to extract the shared banner logo from.",
    )
    args = parser.parse_args()

    consultants = load_consultants()
    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    LOGO_PATH.parent.mkdir(parents=True, exist_ok=True)

    logo_source = args.logo_source
    if logo_source is None:
        for consultant in consultants:
            docx_path = first_docx_for_consultant(consultant)
            if docx_path:
                logo_source = docx_path
                break

    if logo_source and logo_source.is_file():
        _, logo = pick_portrait_and_logo(extract_images_from_docx(logo_source))
        if logo:
            LOGO_PATH.write_bytes(logo)
            print(f"Wrote logo: {LOGO_PATH}")
    else:
        print("No logo source DOCX found.", file=sys.stderr)

    extracted = 0
    missing = 0

    for consultant in consultants:
        slug = consultant_slug(consultant)
        target = PHOTOS_DIR / f"{slug}.png"

        docx_path = first_docx_for_consultant(consultant)
        if not docx_path:
            print(f"No DOCX source for {consultant['canonicalName']} ({slug})")
            missing += 1
            continue

        portrait, _ = pick_portrait_and_logo(extract_images_from_docx(docx_path))
        if not portrait:
            print(f"No portrait image in {docx_path}")
            missing += 1
            continue

        target.write_bytes(portrait)
        print(f"Wrote portrait: {target} (from {docx_path.name})")
        extracted += 1

    print(f"Done. extracted={extracted} missing={missing}")
    return 0 if missing == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
