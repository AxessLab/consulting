"""Normalized assignment records and platform scanner registry."""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Callable

import requests

ALLAKONSULT_BASE = "https://allakonsultuppdrag.se"
VERAMA_BASE = "https://app.verama.com"
ALLAKONSULT_USER_AGENT = "Mozilla/5.0 (compatible; AssignmentScanner/1.0)"
SCAN_USER_AGENT = "Mozilla/5.0 (compatible; AssignmentScanner/1.0)"
SOURCE_REGISTRY: dict[str, dict[str, str]] = {
    "allakonsultuppdrag.se": {"prefix": "a"},
    "verama.com": {"prefix": "v"},
}

NEAR_STOCKHOLM_FOR_PREFILTER = (
    "stockholm",
    "solna",
    "sundbyberg",
    "kista",
    "bromma",
    "sollentuna",
    "danderyd",
    "taby",
    "täby",
    "jarfalla",
    "järfälla",
    "nacka",
    "huddinge",
    "lidingo",
    "lidingö",
    "alvsjo",
    "älvsjö",
    "arsta",
    "årsta",
    "stockholms lan",
    "stockholms län",
    "botkyrka",
    "upplands vasby",
    "upplands väsby",
    "sodertalje",
    "södertälje",
    "haninge",
    "tyreso",
    "tyresö",
    "vallingby",
    "vällingby",
    "farsta",
)
A11Y_STRONG_PREFILTER = re.compile(
    r"tillg[aä]nglighetsgransk|tillg[aä]nglighetsspecialist|"
    r"accessibility (specialist|consultant)|wcag specialist|"
    r"document accessibility|dokumenttillg[aä]nglighet|webbtillg[aä]nglighetsspecialist",
    re.I,
)
VERAMA_EXCLUDED_TITLE = re.compile(
    r"\b(sap|network|nätverk|security operations|soc|hr|payroll|lön|"
    r"automation engineer|factory|automationstekniker)\b",
    re.I,
)
VERAMA_PLAUSIBLE_TITLE = re.compile(
    r"\b(accessibility|tillg[aä]nglighet|wcag|frontend|front-end|react|"
    r"angular|wordpress|java|backend|fullstack|full-stack|ux|ui|designer|"
    r"product designer|projektledare|project manager|scrum|agile|coordinator|"
    r"koordinator|consultant|konsult|developer|utvecklare|systemutvecklare)\b",
    re.I,
)


@dataclass
class AssignmentRecord:
    platform: str
    source_id: str
    listing_id: str
    title: str
    description: str = ""
    description_summary: str = ""
    published_date: str | None = None
    last_application_date: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    duration: str = ""
    work_mode: str = ""
    location: str = ""
    source_url: str = ""
    broker: str = ""
    skills: list[dict[str, Any]] = field(default_factory=list)

    @property
    def dedupe_key(self) -> str:
        return f"{self.platform}:{self.source_id}"

    @property
    def source_key(self) -> str:
        return self.platform

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PlatformScanResult:
    platform: str
    status: str
    count: int
    message: str | None = None


def _allakonsult_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": ALLAKONSULT_USER_AGENT,
            "Accept": "application/json",
        }
    )
    return session


def scan_allakonsultuppdrag(
    *,
    page_size: int = 100,
    max_pages: int | None = None,
) -> tuple[list[AssignmentRecord], PlatformScanResult]:
    platform = "allakonsultuppdrag.se"
    session = _allakonsult_session()
    by_key: dict[str, AssignmentRecord] = {}
    page = 1
    total_pages: int | None = None

    try:
        while True:
            if max_pages is not None and page > max_pages:
                break

            response = session.get(
                f"{ALLAKONSULT_BASE}/api/assignments",
                params={"page": page, "pageSize": page_size},
                timeout=60,
            )
            response.raise_for_status()
            payload = response.json()
            total_pages = payload.get("totalPages", total_pages)

            for row in payload.get("data") or []:
                source_id = str(row["id"])
                record = AssignmentRecord(
                    platform=platform,
                    source_id=source_id,
                    listing_id=f"{SOURCE_REGISTRY[platform]['prefix']}{source_id}",
                    title=row.get("title") or "",
                    description=row.get("description") or "",
                    description_summary=row.get("descriptionSummary") or "",
                    published_date=row.get("publishedDate"),
                    last_application_date=row.get("lastApplicationDate"),
                    start_date=row.get("startDate"),
                    end_date=row.get("endDate"),
                    duration=row.get("duration") or "",
                    work_mode=row.get("workMode") or "",
                    location=row.get("location") or "",
                    source_url=row.get("sourceUrl") or f"{ALLAKONSULT_BASE}/",
                    broker=row.get("broker") or "",
                    skills=row.get("skills") or [],
                )
                by_key[record.dedupe_key] = record

            if not payload.get("hasNextPage"):
                break
            if total_pages is not None and page >= total_pages:
                break
            page += 1

        records = list(by_key.values())
        return records, PlatformScanResult(platform=platform, status="ok", count=len(records))
    except Exception as exc:  # noqa: BLE001
        return list(by_key.values()), PlatformScanResult(
            platform=platform,
            status="error",
            count=len(by_key),
            message=str(exc),
        )


def _verama_location(city: str | None, country_code: str | None) -> str:
    if city and country_code:
        return f"{city} ({country_code})"
    return city or country_code or ""


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _first_present(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _normalize_remoteness(remoteness: Any, location: str = "") -> str:
    fields = f"{remoteness} {location}".lower()
    if remoteness == 100 or "remote" in fields or "distans" in fields or "fjärr" in fields:
        return "remote" if remoteness == 100 else f"{remoteness}% remote" if remoteness else "remote"
    if isinstance(remoteness, int) and remoteness > 0:
        return f"hybrid ({remoteness}% remote)"
    if remoteness == 0:
        return "on-site"
    return ""


def _location_prefilter_passes(record: AssignmentRecord) -> bool:
    title = record.title or ""
    if A11Y_STRONG_PREFILTER.search(title):
        return True
    fields = f"{record.work_mode} {record.location}".lower()
    if "remote" in fields or "distans" in fields or "fjärr" in fields:
        return True
    normalized_location = fields.translate(str.maketrans({"å": "a", "ä": "a", "ö": "o"}))
    if any(place in normalized_location for place in NEAR_STOCKHOLM_FOR_PREFILTER):
        return True
    if re.search(r"\b(frontend|front-end|react|angular|wordpress)\b", title, re.I) and re.search(
        r"gothenburg|goteborg|göteborg",
        normalized_location,
        re.I,
    ):
        return True
    return False


def _verama_should_fetch_detail(
    record: AssignmentRecord,
    *,
    seen_source_ids: set[str],
    scan_date: date,
) -> bool:
    if record.source_id in seen_source_ids:
        return False
    if not record.last_application_date:
        return True
    last_app = _parse_date(record.last_application_date)
    if last_app is not None and last_app < scan_date:
        return False
    if VERAMA_EXCLUDED_TITLE.search(record.title):
        return False
    if not _location_prefilter_passes(record):
        return False
    return bool(VERAMA_PLAUSIBLE_TITLE.search(record.title))


def _stringify_detail_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_stringify_detail_value(item) for item in value if item)
    if isinstance(value, dict):
        for key in ("text", "description", "value", "name"):
            if key in value:
                return _stringify_detail_value(value[key])
    return str(value)


def _verama_description(detail: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "description",
        "jobDescription",
        "assignmentDescription",
        "requestDescription",
        "longDescription",
        "requirements",
        "competenceRequirements",
    ):
        value = _stringify_detail_value(detail.get(key)).strip()
        if value and value not in parts:
            parts.append(value)
    return "\n\n".join(parts)


def _verama_skills(detail: dict[str, Any]) -> list[dict[str, Any]]:
    raw_skills = _first_present(
        detail,
        ("skills", "competences", "competencies", "requiredSkills", "requestedSkills"),
    )
    skills: list[dict[str, Any]] = []
    if not isinstance(raw_skills, list):
        return skills
    for skill in raw_skills:
        if isinstance(skill, dict):
            name = _first_present(skill, ("name", "label", "title", "competenceName"))
            if name:
                skills.append({"name": str(name)})
        elif skill:
            skills.append({"name": str(skill)})
    return skills


def _merge_verama_detail(record: AssignmentRecord, detail: dict[str, Any]) -> None:
    description = _verama_description(detail)
    if description:
        record.description = description
        record.description_summary = description[:300]
    record.skills = _verama_skills(detail)
    record.last_application_date = record.last_application_date or _first_present(
        detail,
        ("lastDayOfApplications", "lastApplicationDate", "deadline", "applicationDeadline"),
    )
    record.start_date = _first_present(
        detail,
        ("firstDayOfAssignment", "assignmentStartDate", "startDate", "start"),
    )
    record.end_date = _first_present(
        detail,
        ("lastDayOfAssignment", "assignmentEndDate", "endDate", "end"),
    )
    duration = _first_present(detail, ("duration", "assignmentDuration", "period"))
    if duration:
        record.duration = str(duration)
    explicit_work_mode = _first_present(detail, ("workMode", "workPlace", "remoteDescription"))
    if explicit_work_mode:
        record.work_mode = f"{record.work_mode}; {explicit_work_mode}".strip("; ")


def scan_verama(
    email: str,
    password: str,
    *,
    page_size: int = 100,
    headless: bool = True,
    seen_source_ids: set[str] | None = None,
    scan_date: date | None = None,
) -> tuple[list[AssignmentRecord], PlatformScanResult]:
    platform = "verama.com"
    seen_source_ids = seen_source_ids or set()
    scan_date = scan_date or date.today()

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError:
        return [], PlatformScanResult(
            platform=platform,
            status="error",
            count=0,
            message="playwright is not installed; run pip install -r requirements.txt",
        )

    by_key: dict[str, AssignmentRecord] = {}

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            context = browser.new_context(user_agent=SCAN_USER_AGENT, locale="sv-SE")
            page = context.new_page()
            auth_headers: dict[str, str] = {}

            def capture_auth_headers(request) -> None:
                if "job-requests/v2" not in request.url or auth_headers:
                    return
                for key in (
                    "authorization",
                    "x-session",
                    "x-context-id",
                    "x-frontend-version",
                    "accept-language",
                ):
                    value = request.headers.get(key)
                    if value:
                        auth_headers[key] = value

            page.on("request", capture_auth_headers)
            page.goto(f"{VERAMA_BASE}/sv/login", wait_until="domcontentloaded", timeout=60000)
            page.locator('input[type="email"], input[name="email"]').first.fill(email)
            page.locator('input[type="password"]').first.fill(password)
            page.locator(
                'button[type="submit"], button:has-text("Logga in"), button:has-text("Log in")'
            ).first.click()
            page.wait_for_timeout(8000)
            page.goto(f"{VERAMA_BASE}/app/job-requests", wait_until="networkidle", timeout=90000)
            page.wait_for_timeout(3000)

            if not auth_headers:
                raise RuntimeError("Could not capture Verama auth headers after login")

            api = context.request
            page_num = 0
            while True:
                response = api.get(
                    f"{VERAMA_BASE}/api/job-requests/v2",
                    params={
                        "page": str(page_num),
                        "size": str(page_size),
                        "query": "",
                        "dedicated": "false",
                        "favouritesOnly": "false",
                        "recommendedOnly": "false",
                        "sort": "firstDayOfApplications,DESC",
                    },
                    headers={
                        **auth_headers,
                        "accept": "application/json, text/plain, */*",
                        "referer": f"{VERAMA_BASE}/app/job-requests",
                    },
                    timeout=60000,
                )
                if response.status != 200:
                    raise RuntimeError(
                        f"Verama job API returned {response.status}: {response.text()[:200]}"
                    )

                payload = response.json()
                rows = payload.get("content") or []
                for row in rows:
                    source_id = str(row["id"])
                    remoteness = row.get("remoteness")
                    location = _verama_location(row.get("city"), row.get("countryCode"))
                    record = AssignmentRecord(
                        platform=platform,
                        source_id=source_id,
                        listing_id=f"{SOURCE_REGISTRY[platform]['prefix']}{source_id}",
                        title=row.get("title") or "",
                        published_date=row.get("firstDayOfApplications"),
                        last_application_date=row.get("lastDayOfApplications"),
                        work_mode=_normalize_remoteness(remoteness, location),
                        location=location,
                        source_url=f"{VERAMA_BASE}/app/job-requests/{source_id}",
                        broker=row.get("originServiceName") or "",
                    )

                    if _verama_should_fetch_detail(
                        record,
                        seen_source_ids=seen_source_ids,
                        scan_date=scan_date,
                    ):
                        detail_response = api.get(
                            f"{VERAMA_BASE}/api/job-requests/v2/{source_id}",
                            headers={
                                **auth_headers,
                                "accept": "application/json, text/plain, */*",
                                "referer": f"{VERAMA_BASE}/app/job-requests",
                            },
                            timeout=60000,
                        )
                        if detail_response.status == 404:
                            detail_response = api.get(
                                f"{VERAMA_BASE}/api/job-requests/{source_id}",
                                headers={
                                    **auth_headers,
                                    "accept": "application/json, text/plain, */*",
                                    "referer": f"{VERAMA_BASE}/app/job-requests",
                                },
                                timeout=60000,
                            )
                        if detail_response.status == 200:
                            _merge_verama_detail(record, detail_response.json())
                        elif detail_response.status in (401, 403):
                            raise RuntimeError(
                                f"Verama detail API returned {detail_response.status} for {source_id}"
                            )
                    by_key[record.dedupe_key] = record

                if payload.get("last") or not rows:
                    break
                page_num += 1

            browser.close()

        records = list(by_key.values())
        return records, PlatformScanResult(platform=platform, status="ok", count=len(records))
    except PlaywrightTimeoutError as exc:
        return list(by_key.values()), PlatformScanResult(
            platform=platform,
            status="error",
            count=len(by_key),
            message=f"Verama login or listing timed out: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return list(by_key.values()), PlatformScanResult(
            platform=platform,
            status="error",
            count=len(by_key),
            message=str(exc),
        )


PlatformScanner = Callable[..., tuple[list[AssignmentRecord], PlatformScanResult]]

PLATFORM_SCANNERS: dict[str, PlatformScanner] = {
    "allakonsultuppdrag.se": scan_allakonsultuppdrag,
    "verama.com": scan_verama,
}

DEFAULT_PLATFORMS = list(PLATFORM_SCANNERS.keys())


def scan_platforms(
    platform_ids: list[str],
    *,
    max_pages: int | None = None,
    headless: bool = True,
    seen_ids_by_source: dict[str, set[str]] | None = None,
    scan_date: date | None = None,
) -> tuple[list[AssignmentRecord], list[PlatformScanResult]]:
    assignments: list[AssignmentRecord] = []
    results: list[PlatformScanResult] = []
    verama_email = os.environ.get("VERAMA_EMAIL")
    verama_password = os.environ.get("VERAMA_PASSWORD")
    seen_ids_by_source = seen_ids_by_source or {}
    scan_date = scan_date or date.today()

    for platform_id in platform_ids:
        scanner = PLATFORM_SCANNERS.get(platform_id)
        if scanner is None:
            results.append(
                PlatformScanResult(
                    platform=platform_id,
                    status="error",
                    count=0,
                    message=f"Unknown platform: {platform_id}",
                )
            )
            continue

        if platform_id == "verama.com":
            if not verama_email or not verama_password:
                results.append(
                    PlatformScanResult(
                        platform=platform_id,
                        status="skipped",
                        count=0,
                        message="VERAMA_EMAIL and VERAMA_PASSWORD are not set",
                    )
                )
                continue
            rows, result = scanner(
                verama_email,
                verama_password,
                headless=headless,
                seen_source_ids=seen_ids_by_source.get(platform_id, set()),
                scan_date=scan_date,
            )
        else:
            rows, result = scanner(max_pages=max_pages)

        assignments.extend(rows)
        results.append(result)

    return assignments, results
