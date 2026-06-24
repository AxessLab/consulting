#!/usr/bin/env python3
"""Render assignment-specific CV HTML and PDF from structured JSON content."""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import shutil
import subprocess
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parent))

from consultant_utils import (
    LOGO_PATH,
    REPO_ROOT,
    assignment_output_dir,
    resolve_photo_path,
)

TEMPLATE_DIR = REPO_ROOT / "templates"
TEMPLATE_NAME = "cv.html.j2"
SCHEMA_PATH = REPO_ROOT / "schemas" / "cv-content.schema.json"

DEFAULT_LABELS = {
    "english": {
        "contact": "Contact",
        "selected_evidence": "Selected projects",
        "relevant_competence": "Techniques",
        "projects": "Projects and assignments",
        "skills": "Skills",
        "certifications": "Courses, certifications and education",
        "languages": "Languages",
    },
    "swedish": {
        "contact": "Kontakt",
        "selected_evidence": "Utvalda projekt",
        "relevant_competence": "Tekniker",
        "projects": "Projekt och uppdrag",
        "skills": "Kompetenser",
        "certifications": "Kurser, certifieringar och utbildning",
        "languages": "Språk",
    },
}


def load_schema() -> dict:
    with SCHEMA_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def validate_content(content: dict) -> None:
    schema = load_schema()
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(content), key=lambda err: list(err.path))
    if errors:
        messages = "\n".join(f"- {error.message} ({'/'.join(map(str, error.path))})" for error in errors)
        raise ValueError(f"CV content failed schema validation:\n{messages}")


def file_to_data_uri(path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(path.name)
    if not mime_type:
        mime_type = "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def build_labels(content: dict) -> dict[str, str]:
    language = content["language"]
    defaults = DEFAULT_LABELS[language]
    overrides = content.get("labels") or {}
    key_map = {
        "contact": "contact",
        "selectedEvidence": "selected_evidence",
        "relevantCompetence": "relevant_competence",
        "projects": "projects",
        "skills": "skills",
        "certifications": "certifications",
        "languages": "languages",
    }
    labels = dict(defaults)
    for source_key, target_key in key_map.items():
        if source_key in overrides:
            labels[target_key] = overrides[source_key]
    return labels


def render_html(content: dict) -> str:
    validate_content(content)

    portrait_path = resolve_photo_path(content["consultantSlug"])
    logo_path = LOGO_PATH if LOGO_PATH.is_file() else None

    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template(TEMPLATE_NAME)

    return template.render(
        language=content["language"],
        consultant_name=content["consultantName"],
        role_title=content["roleTitle"],
        contact=content["contact"],
        profile_paragraphs=content["profileParagraphs"],
        selected_evidence=content["selectedEvidence"],
        competence_chips=content["competenceChips"],
        projects=content["projects"],
        skill_levels=content["skillLevels"],
        certifications=content.get("certifications"),
        languages=content["languages"],
        labels=build_labels(content),
        portrait_data_uri=file_to_data_uri(portrait_path) if portrait_path else None,
        logo_data_uri=file_to_data_uri(logo_path) if logo_path else None,
    )


def output_paths(content: dict, output_dir: Path | None = None) -> tuple[Path, Path, Path]:
    directory = output_dir or assignment_output_dir(content)
    stem = f"{content['consultantSlug']}-{content['language']}"
    return directory / f"{stem}.json", directory / f"{stem}.html", directory / f"{stem}.pdf"


def find_browser() -> list[str] | None:
    candidates = [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path("/usr/bin/chromium"),
        Path("/usr/bin/chromium-browser"),
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/google-chrome-stable"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return [str(candidate)]
    for command in ("msedge", "microsoft-edge", "google-chrome", "chromium", "chromium-browser", "chrome"):
        resolved = shutil.which(command)
        if resolved:
            return [resolved]
    return None


def render_pdf(html_path: Path, pdf_path: Path) -> None:
    browser = find_browser()
    if not browser:
        raise RuntimeError(
            "No Chromium-based browser found for PDF rendering. "
            "Install Edge/Chrome or print the HTML file manually."
        )

    html_uri = html_path.resolve().as_uri()
    command = [
        *browser,
        "--headless",
        "--disable-gpu",
        "--no-pdf-header-footer",
        f"--print-to-pdf={pdf_path.resolve()}",
        html_uri,
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0 or not pdf_path.is_file():
        raise RuntimeError(
            "PDF rendering failed.\n"
            f"Command: {' '.join(command)}\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )


def render_cv(content: dict, output_dir: Path | None = None, write_json: bool = True) -> dict[str, Path]:
    html = render_html(content)
    json_path, html_path, pdf_path = output_paths(content, output_dir)
    html_path.parent.mkdir(parents=True, exist_ok=True)

    if write_json:
        json_path.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    html_path.write_text(html, encoding="utf-8")
    render_pdf(html_path, pdf_path)

    return {"json": json_path, "html": html_path, "pdf": pdf_path}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Path to CV content JSON.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Output directory. Defaults to generated-cvs/<assignment-id> - <assignment title>/.",
    )
    parser.add_argument(
        "--skip-json",
        action="store_true",
        help="Do not rewrite the JSON file (use when input is already stored).",
    )
    args = parser.parse_args()

    with args.input.open(encoding="utf-8") as handle:
        content = json.load(handle)

    try:
        outputs = render_cv(content, args.output_dir, write_json=not args.skip_json)
    except (ValueError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1

    for label, path in outputs.items():
        print(f"{label}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
