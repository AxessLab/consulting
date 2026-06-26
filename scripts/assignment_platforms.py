"""Canonical assignment records and source scanner registry."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable

import requests

ALLAKONSULT_BASE = "https://allakonsultuppdrag.se"
VERAMA_BASE = "https://app.verama.com"
ASSIGNMENT_SCANNER_USER_AGENT = "Mozilla/5.0 (compatible; AssignmentScanner/1.0)"


@dataclass
class AssignmentRecord:
    source_key: str
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
    def platform(self) -> str:
        """Backward-compatible alias used by older scripts."""
        return self.source_key

    @property
    def dedupe_key(self) -> str:
        return f"{self.source_key}:{self.source_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "listing_id": self.listing_id,
            "source_key": self.source_key,
            "source_id": self.source_id,
            "title": self.title,
            "description": self.description,
            "descriptionSummary": self.description_summary,
            "publishedDate": self.published_date,
            "lastApplicationDate": self.last_application_date,
            "startDate": self.start_date,
            "endDate": self.end_date,
            "duration": self.duration,
            "workMode": self.work_mode,
            "location": self.location,
            "sourceUrl": self.source_url,
            "broker": self.broker,
            "skills": self.skills,
        }

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "AssignmentRecord":
        """Load canonical rows, while accepting the previous snake_case shape."""
        return cls(
            source_key=row.get("source_key") or row.get("platform") or "",
            source_id=str(row.get("source_id") or ""),
            listing_id=str(row.get("listing_id") or ""),
            title=row.get("title") or "",
            description=row.get("description") or "",
            description_summary=row.get("descriptionSummary")
            or row.get("description_summary")
            or "",
            published_date=row.get("publishedDate") or row.get("published_date"),
            last_application_date=row.get("lastApplicationDate")
            or row.get("last_application_date"),
            start_date=row.get("startDate") or row.get("start_date"),
            end_date=row.get("endDate") or row.get("end_date"),
            duration=row.get("duration") or "",
            work_mode=row.get("workMode") or row.get("work_mode") or "",
            location=row.get("location") or "",
            source_url=row.get("sourceUrl") or row.get("source_url") or "",
            broker=row.get("broker") or "",
            skills=normalize_skills(row.get("skills") or []),
        )


@dataclass
class PlatformScanResult:
    platform: str
    status: str
    count: int
    message: str | None = None


@dataclass(frozen=True)
class SourceConfig:
    key: str
    prefix: str
    scanner: Callable[..., tuple[list[AssignmentRecord], PlatformScanResult]]
    active: bool = True


def normalize_skills(raw_skills: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_skills, list):
        return []
    normalized: list[dict[str, Any]] = []
    for skill in raw_skills:
        if isinstance(skill, dict):
            name = skill.get("name")
            if name:
                normalized.append({"name": str(name)})
        elif skill:
            normalized.append({"name": str(skill)})
    return normalized


def _allakonsult_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": ASSIGNMENT_SCANNER_USER_AGENT,
            "Accept": "application/json",
        }
    )
    return session


def scan_allakonsultuppdrag(
    *,
    page_size: int = 100,
    max_pages: int | None = None,
) -> tuple[list[AssignmentRecord], PlatformScanResult]:
    source_key = "allakonsultuppdrag.se"
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
                    source_key=source_key,
                    source_id=source_id,
                    listing_id=f"a{source_id}",
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
                    skills=normalize_skills(row.get("skills") or []),
                )
                by_key[record.dedupe_key] = record

            if not payload.get("hasNextPage"):
                break
            if total_pages is not None and page >= total_pages:
                break
            page += 1

        records = list(by_key.values())
        return records, PlatformScanResult(platform=source_key, status="ok", count=len(records))
    except Exception as exc:  # noqa: BLE001
        return list(by_key.values()), PlatformScanResult(
            platform=source_key,
            status="error",
            count=len(by_key),
            message=str(exc),
        )


def _verama_location(city: str | None, country_code: str | None) -> str:
    if city and country_code:
        return f"{city} ({country_code})"
    return city or country_code or ""


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _first_value(mapping: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def _verama_detail_text(row: dict[str, Any], detail: dict[str, Any]) -> str:
    return _first_text(
        detail.get("description"),
        detail.get("jobDescription"),
        detail.get("assignmentDescription"),
        detail.get("requestDescription"),
        row.get("description"),
        row.get("jobDescription"),
    )


def _verama_summary(description: str, row: dict[str, Any], detail: dict[str, Any]) -> str:
    summary = _first_text(
        detail.get("descriptionSummary"),
        detail.get("summary"),
        detail.get("shortDescription"),
        row.get("descriptionSummary"),
        row.get("summary"),
        row.get("systemId"),
    )
    if summary:
        return summary
    return description[:300]


def _verama_work_mode(row: dict[str, Any], detail: dict[str, Any]) -> str:
    raw_remoteness = _first_value(detail, ("remoteness", "remotePercentage"))
    if raw_remoteness is None:
        raw_remoteness = _first_value(row, ("remoteness", "remotePercentage"))

    explicit = _first_text(
        str(detail.get("workMode") or ""),
        str(detail.get("workingRemote") or ""),
        str(detail.get("locationType") or ""),
        str(row.get("workMode") or ""),
    )
    explicit_lower = explicit.lower()
    location_text = _first_text(
        detail.get("location"),
        detail.get("city"),
        row.get("location"),
        row.get("city"),
    ).lower()

    try:
        remoteness = int(raw_remoteness) if raw_remoteness is not None else None
    except (TypeError, ValueError):
        remoteness = None

    if remoteness == 100:
        return "remote"
    if remoteness is not None and 1 <= remoteness <= 99:
        return f"{remoteness}% remote"
    if any(term in f"{explicit_lower} {location_text}" for term in ("remote", "distans", "fjärrarbete", "fjarrarbete")):
        return "remote"
    if explicit:
        return explicit
    if remoteness == 0:
        return "on-site"
    return ""


def _verama_duration(detail: dict[str, Any]) -> str:
    return _first_text(
        detail.get("duration"),
        detail.get("assignmentDuration"),
        detail.get("period"),
    )


def _verama_skills(row: dict[str, Any], detail: dict[str, Any]) -> list[dict[str, Any]]:
    return normalize_skills(detail.get("skills") or row.get("skills") or [])


def _verama_date(row: dict[str, Any], detail: dict[str, Any], keys: tuple[str, ...]) -> Any:
    return _first_value(detail, keys) or _first_value(row, keys)


def scan_verama(
    email: str,
    password: str,
    *,
    page_size: int = 100,
    headless: bool = True,
) -> tuple[list[AssignmentRecord], PlatformScanResult]:
    source_key = "verama.com"

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError:
        return [], PlatformScanResult(
            platform=source_key,
            status="error",
            count=0,
            message="playwright is not installed; run pip install -r requirements.txt",
        )

    records_by_id: dict[str, AssignmentRecord] = {}

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            context = browser.new_context(user_agent=ASSIGNMENT_SCANNER_USER_AGENT, locale="sv-SE")
            page = context.new_page()

            def login_and_capture_headers() -> dict[str, str]:
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
                page.remove_listener("request", capture_auth_headers)

                if not auth_headers:
                    raise RuntimeError("Could not capture Verama auth headers after login")
                return auth_headers

            auth_headers = login_and_capture_headers()

            api = context.request

            def request_json(url: str, *, params: dict[str, str] | None = None) -> dict[str, Any]:
                nonlocal auth_headers
                headers = {
                    **auth_headers,
                    "accept": "application/json, text/plain, */*",
                    "referer": f"{VERAMA_BASE}/app/job-requests",
                    "user-agent": ASSIGNMENT_SCANNER_USER_AGENT,
                }
                response = api.get(url, params=params, headers=headers, timeout=60000)
                if response.status in (401, 403):
                    auth_headers = login_and_capture_headers()
                    headers.update(auth_headers)
                    response = api.get(url, params=params, headers=headers, timeout=60000)
                if response.status != 200:
                    raise RuntimeError(
                        f"Verama job API returned {response.status}: {response.text()[:200]}"
                    )
                return response.json()

            def fetch_detail(source_id: str) -> dict[str, Any]:
                last_error: Exception | None = None
                for path in (
                    f"{VERAMA_BASE}/api/job-requests/v2/{source_id}",
                    f"{VERAMA_BASE}/api/job-requests/{source_id}",
                ):
                    try:
                        return request_json(path)
                    except Exception as exc:  # noqa: BLE001
                        last_error = exc
                if last_error:
                    raise last_error
                return {}

            page_num = 0
            while True:
                payload = request_json(
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
                )
                rows = payload.get("content") or []
                for row in rows:
                    source_id = str(row["id"])
                    detail = fetch_detail(source_id)
                    description = _verama_detail_text(row, detail)
                    city = _first_text(detail.get("city"), row.get("city"))
                    country_code = _first_text(detail.get("countryCode"), row.get("countryCode"))
                    record = AssignmentRecord(
                        source_key=source_key,
                        source_id=source_id,
                        listing_id=f"v{source_id}",
                        title=_first_text(detail.get("title"), row.get("title")),
                        description=description,
                        description_summary=_verama_summary(description, row, detail),
                        published_date=_verama_date(
                            row,
                            detail,
                            ("firstDayOfApplications", "publishedDate", "createdDate"),
                        ),
                        last_application_date=_verama_date(
                            row,
                            detail,
                            (
                                "lastDayOfApplications",
                                "deadline",
                                "applicationDeadline",
                                "lastApplicationDate",
                            ),
                        ),
                        start_date=_verama_date(
                            row,
                            detail,
                            ("firstDayOfAssignment", "startDate", "assignmentStartDate"),
                        ),
                        end_date=_verama_date(
                            row,
                            detail,
                            ("lastDayOfAssignment", "endDate", "assignmentEndDate"),
                        ),
                        duration=_verama_duration(detail),
                        work_mode=_verama_work_mode(row, detail),
                        location=_verama_location(city, country_code),
                        source_url=f"{VERAMA_BASE}/app/job-requests/{source_id}",
                        broker=_first_text(detail.get("originServiceName"), row.get("originServiceName")),
                        skills=_verama_skills(row, detail),
                    )
                    records_by_id[source_id] = record

                if payload.get("last") or not rows:
                    break
                page_num += 1

            browser.close()

        records = list(records_by_id.values())
        return records, PlatformScanResult(platform=source_key, status="ok", count=len(records))
    except PlaywrightTimeoutError as exc:
        return list(records_by_id.values()), PlatformScanResult(
            platform=source_key,
            status="error",
            count=len(records_by_id),
            message=f"Verama login or listing timed out: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return list(records_by_id.values()), PlatformScanResult(
            platform=source_key,
            status="error",
            count=len(records_by_id),
            message=str(exc),
        )


PlatformScanner = Callable[..., tuple[list[AssignmentRecord], PlatformScanResult]]

SOURCE_REGISTRY: dict[str, SourceConfig] = {
    "allakonsultuppdrag.se": SourceConfig(
        key="allakonsultuppdrag.se",
        prefix="a",
        scanner=scan_allakonsultuppdrag,
    ),
    "verama.com": SourceConfig(
        key="verama.com",
        prefix="v",
        scanner=scan_verama,
    ),
}

PLATFORM_SCANNERS: dict[str, PlatformScanner] = {
    key: config.scanner for key, config in SOURCE_REGISTRY.items()
}

DEFAULT_PLATFORMS = [key for key, config in SOURCE_REGISTRY.items() if config.active]


def scan_platforms(
    platform_ids: list[str],
    *,
    max_pages: int | None = None,
    headless: bool = True,
) -> tuple[list[AssignmentRecord], list[PlatformScanResult]]:
    assignments: list[AssignmentRecord] = []
    results: list[PlatformScanResult] = []
    verama_email = os.environ.get("VERAMA_EMAIL")
    verama_password = os.environ.get("VERAMA_PASSWORD")

    for platform_id in platform_ids:
        source_config = SOURCE_REGISTRY.get(platform_id)
        if source_config is None or not source_config.active:
            results.append(
                PlatformScanResult(
                    platform=platform_id,
                    status="error",
                    count=0,
                    message=f"Unknown or inactive source: {platform_id}",
                )
            )
            continue
        scanner = source_config.scanner

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
            )
        else:
            rows, result = scanner(max_pages=max_pages)

        assignments.extend(rows)
        results.append(result)

    return assignments, results
