"""Canonical assignment records and source scanner registry."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

import requests

ALLAKONSULT_BASE = "https://allakonsultuppdrag.se"
VERAMA_BASE = "https://app.verama.com"
ALLAKONSULT_USER_AGENT = "Mozilla/5.0 (compatible; AssignmentScanner/1.0)"
SCAN_USER_AGENT = "Mozilla/5.0 (compatible; AxessLabAssignmentScanner/1.0)"


@dataclass(frozen=True)
class SourceConfig:
    prefix: str
    key: str
    status: str = "active"


SOURCE_REGISTRY: tuple[SourceConfig, ...] = (
    SourceConfig(prefix="a", key="allakonsultuppdrag.se"),
    SourceConfig(prefix="v", key="verama.com"),
)

SOURCE_CONFIGS = {source.key: source for source in SOURCE_REGISTRY}
SOURCE_PREFERENCE = {source.key: index for index, source in enumerate(SOURCE_REGISTRY)}


@dataclass
class AssignmentRecord:
    source_key: str
    source_id: str
    listing_id: str
    title: str
    description: str = ""
    descriptionSummary: str = ""
    publishedDate: str | None = None
    lastApplicationDate: str | None = None
    startDate: str | None = None
    endDate: str | None = None
    duration: str = ""
    workMode: str = ""
    location: str = ""
    sourceUrl: str = ""
    broker: str = ""
    skills: list[Any] = field(default_factory=list)

    @property
    def dedupe_key(self) -> str:
        return f"{self.source_key}:{self.source_id}"

    @property
    def platform(self) -> str:
        return self.source_key

    @property
    def description_summary(self) -> str:
        return self.descriptionSummary

    @property
    def published_date(self) -> str | None:
        return self.publishedDate

    @property
    def last_application_date(self) -> str | None:
        return self.lastApplicationDate

    @property
    def start_date(self) -> str | None:
        return self.startDate

    @property
    def end_date(self) -> str | None:
        return self.endDate

    @property
    def work_mode(self) -> str:
        return self.workMode

    @property
    def source_url(self) -> str:
        return self.sourceUrl

    def to_dict(self) -> dict[str, Any]:
        return {
            "listing_id": self.listing_id,
            "source_key": self.source_key,
            "source_id": self.source_id,
            "title": self.title,
            "description": self.description,
            "descriptionSummary": self.descriptionSummary,
            "publishedDate": self.publishedDate,
            "lastApplicationDate": self.lastApplicationDate,
            "startDate": self.startDate,
            "endDate": self.endDate,
            "duration": self.duration,
            "workMode": self.workMode,
            "location": self.location,
            "sourceUrl": self.sourceUrl,
            "broker": self.broker,
            "skills": self.skills,
        }

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "AssignmentRecord":
        """Load both current canonical rows and the earlier snake_case shape."""
        return cls(
            source_key=str(row.get("source_key") or row.get("platform") or ""),
            source_id=str(row.get("source_id") or ""),
            listing_id=str(row.get("listing_id") or ""),
            title=str(row.get("title") or ""),
            description=str(row.get("description") or ""),
            descriptionSummary=str(
                row.get("descriptionSummary") or row.get("description_summary") or ""
            ),
            publishedDate=row.get("publishedDate") or row.get("published_date"),
            lastApplicationDate=row.get("lastApplicationDate")
            or row.get("last_application_date"),
            startDate=row.get("startDate") or row.get("start_date"),
            endDate=row.get("endDate") or row.get("end_date"),
            duration=str(row.get("duration") or ""),
            workMode=str(row.get("workMode") or row.get("work_mode") or ""),
            location=str(row.get("location") or ""),
            sourceUrl=str(row.get("sourceUrl") or row.get("source_url") or ""),
            broker=str(row.get("broker") or ""),
            skills=row.get("skills") or [],
        )


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
    seen_ids: set[str] | None = None,
    scan_date: date | None = None,
) -> tuple[list[AssignmentRecord], PlatformScanResult]:
    platform = "allakonsultuppdrag.se"
    session = _allakonsult_session()
    by_id: dict[str, AssignmentRecord] = {}
    page = 1
    total_pages: int | None = None
    _ = seen_ids, scan_date

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
                    source_key=platform,
                    source_id=source_id,
                    listing_id=f"{SOURCE_CONFIGS[platform].prefix}{source_id}",
                    title=row.get("title") or "",
                    description=row.get("description") or "",
                    descriptionSummary=row.get("descriptionSummary") or "",
                    publishedDate=row.get("publishedDate"),
                    lastApplicationDate=row.get("lastApplicationDate"),
                    startDate=row.get("startDate"),
                    endDate=row.get("endDate"),
                    duration=row.get("duration") or "",
                    workMode=row.get("workMode") or "",
                    location=row.get("location") or "",
                    sourceUrl=row.get("sourceUrl") or f"{ALLAKONSULT_BASE}/",
                    broker=row.get("broker") or "",
                    skills=row.get("skills") or [],
                )
                by_id[source_id] = record

            if not payload.get("hasNextPage"):
                break
            if total_pages is not None and page >= total_pages:
                break
            page += 1

        records = list(by_id.values())
        return records, PlatformScanResult(platform=platform, status="ok", count=len(records))
    except Exception as exc:  # noqa: BLE001
        return list(by_id.values()), PlatformScanResult(
            platform=platform,
            status="error",
            count=len(by_id),
            message=str(exc),
        )


def _verama_location(city: str | None, country_code: str | None) -> str:
    if city and country_code:
        return f"{city} ({country_code})"
    return city or country_code or ""


def _verama_work_mode(remoteness: Any, *extra_fields: str) -> str:
    extras = " ".join(field for field in extra_fields if field)
    normalized = extras.lower()
    if re.search(r"\b(remote|distans|fjärrarbete|fjarrarbete)\b", normalized):
        return "remote"
    try:
        remote_percent = int(remoteness)
    except (TypeError, ValueError):
        return ""
    if remote_percent >= 100:
        return "remote (100% remote)"
    if remote_percent > 0:
        return f"{remote_percent}% remote; hybrid"
    return "on-site"


def _first_text(data: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float)):
            return str(value)
    return ""


def _first_value(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


def _extract_verama_skills(detail: dict[str, Any]) -> list[Any]:
    for key in ("skills", "competences", "requiredSkills", "requiredCompetences"):
        value = detail.get(key)
        if isinstance(value, list):
            return value
    return []


def _derive_duration(detail: dict[str, Any]) -> str:
    explicit = _first_text(detail, "duration", "assignmentPeriod", "period")
    if explicit:
        return explicit
    start = _first_value(detail, "firstDayOfAssignment", "startDate", "assignmentStartDate")
    end = _first_value(detail, "lastDayOfAssignment", "endDate", "assignmentEndDate")
    if start and end:
        return f"{start} - {end}"
    return ""


def _title_is_clearly_outside_target(title: str) -> bool:
    text = title.lower()
    outside = re.compile(
        r"\b(sap|network|security operations|soc|hr|payroll|automation engineer|"
        r"factory|fpga|embedded|data engineer|devops|cloud engineer|mobile|ios|"
        r"android|testare|tester|qa|\.net|c#|python)\b"
    )
    target = re.compile(
        r"\b(accessibility|tillgänglighet|tillganglighet|wcag|frontend|front-end|"
        r"react|next|angular|wordpress|java|spring|fullstack|full-stack|ux|ui|"
        r"designer|projektledare|project manager|scrum master|agile coach|"
        r"project coordinator|projektkoordinator|developer|utvecklare|consultant|"
        r"konsult)\b"
    )
    return bool(outside.search(text)) and not target.search(text)


def _verama_location_prefilter_passes(record: AssignmentRecord) -> bool:
    location = record.location.lower()
    work_mode = record.workMode.lower()
    fields = f"{work_mode} {location}"
    if re.search(r"\b(remote|distans|fjärrarbete|fjarrarbete)\b", fields) and (
        "hybrid" not in fields or "100% remote" in fields
    ):
        return True
    near_stockholm = (
        "stockholm",
        "solna",
        "sundbyberg",
        "kista",
        "bromma",
        "sollentuna",
        "danderyd",
        "täby",
        "taby",
        "järfälla",
        "jarfalla",
        "nacka",
        "huddinge",
        "lidingö",
        "lidingo",
        "älvsjö",
        "alvsjo",
        "årsta",
        "arsta",
        "stockholms län",
        "stockholms lan",
        "göteborg",
        "goteborg",
        "gothenburg",
    )
    return any(place in location for place in near_stockholm)


def _title_is_strong_accessibility(title: str) -> bool:
    text = title.lower()
    return bool(
        re.search(
            r"tillgänglighetsgranskare|tillganglighetsgranskare|"
            r"tillgänglighetsspecialist|tillganglighetsspecialist|"
            r"accessibility specialist|accessibility consultant|wcag specialist|"
            r"document accessibility|dokumenttillgänglighet|dokumenttillganglighet|"
            r"webbtillgänglighetsspecialist|webbtillganglighetsspecialist",
            text,
        )
    )


def _should_fetch_verama_detail(
    record: AssignmentRecord,
    *,
    seen_ids: set[str],
    scan_date: date | None,
) -> bool:
    if record.source_id in seen_ids:
        return False

    if record.lastApplicationDate and scan_date:
        try:
            if date.fromisoformat(str(record.lastApplicationDate)[:10]) < scan_date:
                return False
        except ValueError:
            pass

    if not record.lastApplicationDate:
        return True

    if _title_is_clearly_outside_target(record.title):
        return False

    if (
        not _verama_location_prefilter_passes(record)
        and not _title_is_strong_accessibility(record.title)
    ):
        return False

    return True


def _merge_verama_detail(record: AssignmentRecord, detail: dict[str, Any]) -> AssignmentRecord:
    description = _first_text(
        detail,
        "description",
        "jobDescription",
        "assignmentDescription",
        "requestDescription",
    )
    summary = _first_text(detail, "descriptionSummary", "summary", "shortDescription")
    work_mode_detail = _first_text(detail, "workMode", "workingMode", "remoteDescription")
    work_mode = record.workMode
    if work_mode_detail and "remote" not in work_mode.lower():
        work_mode = f"{work_mode}; {work_mode_detail}".strip("; ")

    return AssignmentRecord(
        source_key=record.source_key,
        source_id=record.source_id,
        listing_id=record.listing_id,
        title=record.title,
        description=description or record.description,
        descriptionSummary=summary or (description[:300] if description else record.descriptionSummary),
        publishedDate=record.publishedDate,
        lastApplicationDate=record.lastApplicationDate
        or _first_value(
            detail,
            "lastDayOfApplications",
            "applicationDeadline",
            "deadline",
            "lastApplicationDate",
        ),
        startDate=_first_value(detail, "firstDayOfAssignment", "startDate", "assignmentStartDate"),
        endDate=_first_value(detail, "lastDayOfAssignment", "endDate", "assignmentEndDate"),
        duration=_derive_duration(detail),
        workMode=work_mode,
        location=record.location,
        sourceUrl=record.sourceUrl,
        broker=record.broker,
        skills=_extract_verama_skills(detail),
    )


class VeramaAuthError(RuntimeError):
    pass


def scan_verama(
    email: str,
    password: str,
    *,
    page_size: int = 100,
    headless: bool = True,
    seen_ids: set[str] | None = None,
    scan_date: date | None = None,
) -> tuple[list[AssignmentRecord], PlatformScanResult]:
    platform = "verama.com"
    seen_ids = seen_ids or set()

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

    by_id: dict[str, AssignmentRecord] = {}

    try:
        with sync_playwright() as playwright:
            def open_authenticated_context():
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
                return browser, context, auth_headers

            def api_headers(auth_headers: dict[str, str]) -> dict[str, str]:
                return {
                    **auth_headers,
                    "User-Agent": SCAN_USER_AGENT,
                    "accept": "application/json, text/plain, */*",
                    "referer": f"{VERAMA_BASE}/app/job-requests",
                }

            def fetch_detail(api, auth_headers: dict[str, str], source_id: str) -> dict[str, Any]:
                for url in (
                    f"{VERAMA_BASE}/api/job-requests/v2/{source_id}",
                    f"{VERAMA_BASE}/api/job-requests/{source_id}",
                ):
                    response = api.get(url, headers=api_headers(auth_headers), timeout=60000)
                    if response.status in (401, 403):
                        raise VeramaAuthError(
                            f"Verama detail API returned {response.status}"
                        )
                    if response.status == 200:
                        return response.json()
                return {}

            last_auth_error: Exception | None = None
            for auth_attempt in range(2):
                browser, context, auth_headers = open_authenticated_context()
                try:
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
                            headers=api_headers(auth_headers),
                            timeout=60000,
                        )
                        if response.status in (401, 403):
                            raise VeramaAuthError(
                                f"Verama job API returned {response.status}"
                            )
                        if response.status != 200:
                            raise RuntimeError(
                                f"Verama job API returned {response.status}: "
                                f"{response.text()[:200]}"
                            )

                        payload = response.json()
                        rows = payload.get("content") or []
                        for row in rows:
                            source_id = str(row["id"])
                            record = AssignmentRecord(
                                source_key=platform,
                                source_id=source_id,
                                listing_id=f"{SOURCE_CONFIGS[platform].prefix}{source_id}",
                                title=row.get("title") or "",
                                descriptionSummary=row.get("systemId") or "",
                                publishedDate=row.get("firstDayOfApplications"),
                                lastApplicationDate=row.get("lastDayOfApplications"),
                                workMode=_verama_work_mode(row.get("remoteness")),
                                location=_verama_location(row.get("city"), row.get("countryCode")),
                                sourceUrl=f"{VERAMA_BASE}/app/job-requests/{source_id}",
                                broker=row.get("originServiceName") or "",
                            )
                            if _should_fetch_verama_detail(
                                record,
                                seen_ids=seen_ids,
                                scan_date=scan_date,
                            ):
                                detail = fetch_detail(api, auth_headers, source_id)
                                if detail:
                                    record = _merge_verama_detail(record, detail)
                            by_id[source_id] = record

                        if payload.get("last") or not rows:
                            break
                        page_num += 1
                    browser.close()
                    break
                except VeramaAuthError as exc:
                    last_auth_error = exc
                    browser.close()
                    if auth_attempt == 1:
                        raise
                    continue
            else:
                if last_auth_error:
                    raise last_auth_error

        return list(by_id.values()), PlatformScanResult(
            platform=platform,
            status="ok",
            count=len(by_id),
        )
    except PlaywrightTimeoutError as exc:
        return list(by_id.values()), PlatformScanResult(
            platform=platform,
            status="error",
            count=len(by_id),
            message=f"Verama login or listing timed out: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return list(by_id.values()), PlatformScanResult(
            platform=platform,
            status="error",
            count=len(by_id),
            message=str(exc),
        )


PlatformScanner = Callable[..., tuple[list[AssignmentRecord], PlatformScanResult]]

PLATFORM_SCANNERS: dict[str, PlatformScanner] = {
    "allakonsultuppdrag.se": scan_allakonsultuppdrag,
    "verama.com": scan_verama,
}

DEFAULT_PLATFORMS = [source.key for source in SOURCE_REGISTRY if source.status == "active"]


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
    seen_ids_by_source = seen_ids_by_source or {}
    verama_email = os.environ.get("VERAMA_EMAIL") or "consulting@axesslab.com"
    verama_password = os.environ.get("VERAMA_PASSWORD")

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
            if not verama_password:
                results.append(
                    PlatformScanResult(
                        platform=platform_id,
                        status="skipped",
                        count=0,
                        message="VERAMA_PASSWORD is not set",
                    )
                )
                continue
            rows, result = scanner(
                verama_email,
                verama_password,
                headless=headless,
                seen_ids=seen_ids_by_source.get(platform_id, set()),
                scan_date=scan_date,
            )
        else:
            rows, result = scanner(
                max_pages=max_pages,
                seen_ids=seen_ids_by_source.get(platform_id, set()),
                scan_date=scan_date,
            )

        assignments.extend(rows)
        results.append(result)

    return assignments, results
