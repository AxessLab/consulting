"""Canonical assignment records and source scanner registry."""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable

import requests

ALLAKONSULT_BASE = "https://allakonsultuppdrag.se"
VERAMA_BASE = "https://app.verama.com"
ALLAKONSULT_USER_AGENT = "Mozilla/5.0 (compatible; AssignmentScanner/1.0)"
SCAN_USER_AGENT = "Mozilla/5.0 (compatible; AxessLabAssignmentScanner/1.0)"


@dataclass(frozen=True)
class SourceConfig:
    prefix: str
    source_key: str
    active: bool = True


SOURCE_REGISTRY: tuple[SourceConfig, ...] = (
    SourceConfig(prefix="a", source_key="allakonsultuppdrag.se"),
    SourceConfig(prefix="v", source_key="verama.com"),
)
SOURCE_BY_KEY = {source.source_key: source for source in SOURCE_REGISTRY}
PREFIX_BY_SOURCE = {source.source_key: source.prefix for source in SOURCE_REGISTRY}


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
        """Backward-compatible alias used by older curation helpers."""
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
        """Accept current canonical JSON plus older snake_case candidate files."""
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
            skills=row.get("skills") or [],
        )


@dataclass
class PlatformScanResult:
    source_key: str
    status: str
    count: int
    message: str | None = None

    @property
    def platform(self) -> str:
        """Backward-compatible alias used by existing prompt/output code."""
        return self.source_key


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
    source_key = "allakonsultuppdrag.se"
    prefix = PREFIX_BY_SOURCE[source_key]
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
                    listing_id=f"{prefix}{source_id}",
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
                by_key[source_id] = record

            if not payload.get("hasNextPage"):
                break
            if total_pages is not None and page >= total_pages:
                break
            page += 1

        records = list(by_key.values())
        return records, PlatformScanResult(source_key=source_key, status="ok", count=len(records))
    except Exception as exc:  # noqa: BLE001
        return list(by_key.values()), PlatformScanResult(
            source_key=source_key,
            status="error",
            count=len(by_key),
            message=str(exc),
        )


def _verama_location(city: str | None, country_code: str | None) -> str:
    if city and country_code:
        return f"{city} ({country_code})"
    return city or country_code or ""


def _first_value(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", text).strip()


def _verama_work_mode(row: dict[str, Any], detail: dict[str, Any]) -> str:
    raw_work_mode = str(
        _first_value(
            detail.get("workMode"),
            detail.get("remoteWork"),
            detail.get("locationType"),
            row.get("workMode"),
        )
        or ""
    )
    raw_location = str(_first_value(detail.get("location"), row.get("location")) or "")
    remoteness = _first_value(detail.get("remoteness"), row.get("remoteness"))

    try:
        remote_percent = int(remoteness)
    except (TypeError, ValueError):
        remote_percent = None

    normalized_fields = f"{raw_work_mode} {raw_location}".lower()
    if remote_percent == 100 or any(
        term in normalized_fields for term in ("distans", "fjärrarbete", "fjarrarbete")
    ):
        return "remote"
    if remote_percent is not None:
        if 1 <= remote_percent <= 99:
            return f"{remote_percent}% remote"
        if remote_percent == 0:
            return "on-site"
    if "hybrid" in normalized_fields:
        return "hybrid"
    if "remote" in normalized_fields:
        return "remote"
    return raw_work_mode


def _verama_skills(detail: dict[str, Any], row: dict[str, Any]) -> list[dict[str, Any]]:
    raw_skills = _first_value(detail.get("skills"), detail.get("competences"), row.get("skills")) or []
    normalized: list[dict[str, Any]] = []
    if not isinstance(raw_skills, list):
        return normalized
    for skill in raw_skills:
        if isinstance(skill, dict):
            name = _first_value(skill.get("name"), skill.get("title"), skill.get("label"))
            if name:
                normalized.append({"name": str(name)})
        elif skill:
            normalized.append({"name": str(skill)})
    return normalized


def _verama_record_from_rows(row: dict[str, Any], detail: dict[str, Any]) -> AssignmentRecord:
    source_key = "verama.com"
    prefix = PREFIX_BY_SOURCE[source_key]
    source_id = str(row["id"])
    description = str(
        _first_value(
            detail.get("description"),
            detail.get("jobDescription"),
            detail.get("assignmentDescription"),
            row.get("description"),
            row.get("jobDescription"),
        )
        or ""
    )
    summary = str(
        _first_value(
            detail.get("descriptionSummary"),
            detail.get("summary"),
            detail.get("shortDescription"),
            row.get("descriptionSummary"),
            row.get("summary"),
        )
        or ""
    )
    if not summary and description:
        summary = _strip_html(description)[:300]

    start_date = _first_value(
        detail.get("firstDayOfAssignment"),
        detail.get("startDate"),
        row.get("firstDayOfAssignment"),
    )
    end_date = _first_value(
        detail.get("lastDayOfAssignment"),
        detail.get("endDate"),
        row.get("lastDayOfAssignment"),
    )
    duration = str(
        _first_value(
            detail.get("duration"),
            detail.get("assignmentPeriod"),
            detail.get("period"),
            "",
        )
        or ""
    )
    if not duration and (start_date or end_date):
        duration = " - ".join(str(value) for value in (start_date, end_date) if value)

    city = _first_value(detail.get("city"), row.get("city"))
    country_code = _first_value(detail.get("countryCode"), row.get("countryCode"))

    return AssignmentRecord(
        source_key=source_key,
        source_id=source_id,
        listing_id=f"{prefix}{source_id}",
        title=str(_first_value(detail.get("title"), row.get("title")) or ""),
        description=description,
        description_summary=summary,
        published_date=_first_value(
            detail.get("firstDayOfApplications"),
            row.get("firstDayOfApplications"),
        ),
        last_application_date=_first_value(
            detail.get("lastDayOfApplications"),
            detail.get("applicationDeadline"),
            detail.get("deadline"),
            row.get("lastDayOfApplications"),
        ),
        start_date=start_date,
        end_date=end_date,
        duration=duration,
        work_mode=_verama_work_mode(row, detail),
        location=_verama_location(city, country_code),
        source_url=f"{VERAMA_BASE}/app/job-requests/{source_id}",
        broker=str(_first_value(detail.get("originServiceName"), row.get("originServiceName")) or ""),
        skills=_verama_skills(detail, row),
    )


def _verama_get_json(api: Any, path: str, auth_headers: dict[str, str]) -> tuple[int, Any]:
    response = api.get(
        f"{VERAMA_BASE}{path}",
        headers={
            **auth_headers,
            "user-agent": SCAN_USER_AGENT,
            "accept": "application/json, text/plain, */*",
            "referer": f"{VERAMA_BASE}/app/job-requests",
        },
        timeout=60000,
    )
    if response.status != 200:
        return response.status, response.text()[:300]
    return response.status, response.json()


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
            source_key=source_key,
            status="error",
            count=0,
            message="playwright is not installed; run pip install -r requirements.txt",
        )

    last_error: str | None = None
    for attempt in range(2):
        records: list[AssignmentRecord] = []

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
                by_source_id: dict[str, dict[str, Any]] = {}
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
                            "user-agent": SCAN_USER_AGENT,
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
                        by_source_id[str(row["id"])] = row

                    if payload.get("last") or not rows:
                        break
                    page_num += 1

                for source_id, row in by_source_id.items():
                    status, detail_payload = _verama_get_json(
                        api,
                        f"/api/job-requests/v2/{source_id}",
                        auth_headers,
                    )
                    if status == 404:
                        status, detail_payload = _verama_get_json(
                            api,
                            f"/api/job-requests/{source_id}",
                            auth_headers,
                        )
                    if status in (401, 403):
                        raise RuntimeError(f"Verama detail API returned {status}")
                    detail = detail_payload if isinstance(detail_payload, dict) else {}
                    records.append(_verama_record_from_rows(row, detail))

                browser.close()

            return records, PlatformScanResult(source_key=source_key, status="ok", count=len(records))
        except PlaywrightTimeoutError as exc:
            return records, PlatformScanResult(
                source_key=source_key,
                status="error",
                count=len(records),
                message=f"Verama login or listing timed out: {exc}",
            )
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            if attempt == 0 and any(code in last_error for code in ("401", "403")):
                continue
            return records, PlatformScanResult(
                source_key=source_key,
                status="error",
                count=len(records),
                message=last_error,
            )

    return [], PlatformScanResult(
        source_key=source_key,
        status="error",
        count=0,
        message=last_error or "Verama scan failed",
    )


PlatformScanner = Callable[..., tuple[list[AssignmentRecord], PlatformScanResult]]

PLATFORM_SCANNERS: dict[str, PlatformScanner] = {
    "allakonsultuppdrag.se": scan_allakonsultuppdrag,
    "verama.com": scan_verama,
}

DEFAULT_PLATFORMS = [
    source.source_key for source in SOURCE_REGISTRY if source.active and source.source_key in PLATFORM_SCANNERS
]


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
        scanner = PLATFORM_SCANNERS.get(platform_id)
        if scanner is None:
            results.append(
                PlatformScanResult(
                    source_key=platform_id,
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
                        source_key=platform_id,
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
