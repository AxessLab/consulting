"""Shared helpers for consultant slug and photo resolution."""

from __future__ import annotations

import re
import struct
import unicodedata
import zipfile
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONSULTANTS_PATH = REPO_ROOT / "consultants.yaml"
PHOTOS_DIR = REPO_ROOT / "photos"
LOGO_PATH = REPO_ROOT / "templates" / "assets" / "axesslab-logo.png"
INVALID_PATH_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
MAX_ASSIGNMENT_FOLDER_LENGTH = 180


def sanitize_assignment_title_for_path(title: str) -> str:
    """Make an assignment title safe for cross-platform directory names."""
    label = title.replace(":", " - ")
    label = INVALID_PATH_CHARS.sub("", label)
    label = re.sub(r"\s+", " ", label).strip(" .")
    return label


def assignment_folder_name(assignment_id: str, assignment_title: str) -> str:
    """Build generated-cvs subdirectory name: `<id> - <assignment title>`."""
    label = sanitize_assignment_title_for_path(assignment_title)
    folder = f"{assignment_id} - {label}" if label else str(assignment_id)
    if len(folder) > MAX_ASSIGNMENT_FOLDER_LENGTH:
        folder = folder[:MAX_ASSIGNMENT_FOLDER_LENGTH].rstrip(" .")
    return folder


def assignment_output_dir(content: dict, repo_root: Path | None = None) -> Path:
    root = repo_root or REPO_ROOT
    folder = content.get("assignmentFolder") or assignment_folder_name(
        str(content["assignmentId"]),
        content["assignmentTitle"],
    )
    return root / "generated-cvs" / folder


def slugify_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    return slug


def load_consultants() -> list[dict]:
    with CONSULTANTS_PATH.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return data["consultants"]


def consultant_slug(consultant: dict) -> str:
    return consultant.get("slug") or slugify_name(consultant["canonicalName"])


def png_dimensions(data: bytes) -> tuple[int, int] | None:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    return struct.unpack(">II", data[16:24])


def extract_images_from_docx(docx_path: Path) -> dict[str, bytes]:
    images: dict[str, bytes] = {}
    with zipfile.ZipFile(docx_path) as archive:
        for name in archive.namelist():
            if name.startswith("word/media/") and name.lower().endswith(".png"):
                images[name] = archive.read(name)
    return images


def pick_portrait_and_logo(images: dict[str, bytes]) -> tuple[bytes | None, bytes | None]:
    if not images:
        return None, None

    scored: list[tuple[str, bytes, int, int, float]] = []
    for name, data in images.items():
        dims = png_dimensions(data)
        if not dims:
            continue
        width, height = dims
        ratio = width / height if height else 999.0
        scored.append((name, data, width, height, ratio))

    if not scored:
        return None, None

    portrait = min(scored, key=lambda item: abs(item[4] - 1.0))[1]
    logo = max(scored, key=lambda item: item[2] / max(item[3], 1))[1]
    if portrait is logo and len(scored) > 1:
        logo = max(scored, key=lambda item: item[2])[1]
    return portrait, logo


def first_docx_for_consultant(consultant: dict) -> Path | None:
    for variant in consultant.get("cvs", []):
        for raw_file in variant.get("rawFiles", []):
            path = REPO_ROOT / raw_file
            if path.suffix.lower() == ".docx" and path.is_file():
                return path
    return None


def resolve_photo_path(slug: str, consultants: list[dict] | None = None) -> Path | None:
    consultants = consultants or load_consultants()
    consultant = next(
        (item for item in consultants if consultant_slug(item) == slug),
        None,
    )
    if consultant:
        override = consultant.get("photoFile")
        if override:
            path = REPO_ROOT / override
            if path.is_file():
                return path

    default = PHOTOS_DIR / f"{slug}.png"
    if default.is_file():
        return default

    if consultant:
        docx_path = first_docx_for_consultant(consultant)
        if docx_path:
            portrait, _ = pick_portrait_and_logo(extract_images_from_docx(docx_path))
            if portrait:
                PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
                default.write_bytes(portrait)
                return default
    return None
