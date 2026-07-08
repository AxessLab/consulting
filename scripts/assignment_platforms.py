"""Canonical assignment records and source scanner registry."""

from __future__ import annotations

import re
import os
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Callable

import requests

ALLAKONSULT_BASE = "https://allakonsultuppdrag.se"
VERAMA_BASE = "https://app.verama.com"
ALLAKONSULT_USER_AGENT = "Mozilla/5.0 (compatible; AssignmentScanner/1.0)"
SCAN_USER_AGENT = "Mozilla/5.0 (compatible; AssignmentScanner/1.0)"


@dataclass(frozen=True)
class SourceSpec:
    key: str
    prefix: str
    active: bool = True


SOURCE_REGISTRY: dict[str, SourceSpec] = {
    "allakonsultuppdrag.se": SourceSpec("allakonsultuppdrag.se", "a"),
    "verama.com": SourceSpec("verama.com", "v"),
}


@dataclass
class AssignmentRecord:
    listing_id: str
    source_key: str
    source_id: str
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
        """Backward-compatible alias for older scripts."""
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
        return asdict(self)

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "AssignmentRecord":
        source_key = row.get("source_key") or row.get("platform") or ""
        source_id = str(row.get("source_id") or "")
        listing_id = row.get("listing_id") or f"{SOURCE_REGISTRY[source_key].prefix}{source_id}"
        return cls(
            listing_id=listing_id,
            source_key=source_key,
            source_id=source_id,
            title=row.get("title") or "",
            description=row.get("description") or "",
            descriptionSummary=row.get("descriptionSummary")
            or row.get("description_summary")
            or "",
            publishedDate=row.get("publishedDate") or row.get("published_date"),
            lastApplicationDate=row.get("lastApplicationDate")
            or row.get("last_application_date"),
            startDate=row.get("startDate") or row.get("start_date"),
            endDate=row.get("endDate") or row.get("end_date"),
            duration=row.get("duration") or "",
            workMode=row.get("workMode") or row.get("work_mode") or "",
            location=row.get("location") or "",
            sourceUrl=row.get("sourceUrl") or row.get("source_url") or "",
            broker=row.get("broker") or "",
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
) -> tuple[list[AssignmentRecord], PlatformScanResult]:
    source_key = "allakonsultuppdrag.se"
    prefix = SOURCE_REGISTRY[source_key].prefix
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
                    listing_id=f"{prefix}{source_id}",
                    source_key=source_key,
                    source_id=source_id,
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


def _first_value(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _verama_work_mode(remoteness: Any, *extra_fields: str | None) -> str:
    explicit = " ".join(field or "" for field in extra_fields)
    normalized = explicit.lower()
    try:
        remote_percent = int(remoteness) if remoteness is not None else None
    except (TypeError, ValueError):
        remote_percent = None

    if remote_percent == 100 or re.search(r"\b(remote|distans|fjärrarbete|fjarrarbete)\b", normalized):
        return "100% remote" if remote_percent == 100 else "remote"
    if remote_percent is not None and remote_percent > 0:
        return f"hybrid, {remote_percent}% remote"
    if remote_percent == 0:
        return "on-site"
    return ""


def _skill_items(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    skills: list[Any] = []
    for item in value:
        if isinstance(item, str):
            skills.append(item)
        elif isinstance(item, dict):
            name = item.get("name") or item.get("title") or item.get("label")
            skills.append({"name": name} if name else item)
    return skills


def _verama_list_record(row: dict[str, Any]) -> AssignmentRecord:
    source_key = "verama.com"
    source_id = str(row["id"])
    location = _verama_location(row.get("city"), row.get("countryCode"))
    work_mode = _verama_work_mode(row.get("remoteness"), row.get("remotenessText"), location)
    return AssignmentRecord(
        listing_id=f"{SOURCE_REGISTRY[source_key].prefix}{source_id}",
        source_key=source_key,
        source_id=source_id,
        title=row.get("title") or "",
        descriptionSummary=row.get("summary") or "",
        publishedDate=row.get("firstDayOfApplications"),
        lastApplicationDate=row.get("lastDayOfApplications"),
        workMode=work_mode,
        location=location,
        sourceUrl=f"{VERAMA_BASE}/app/job-requests/{source_id}",
        broker=row.get("originServiceName") or "",
    )


def _merge_verama_detail(record: AssignmentRecord, detail: dict[str, Any]) -> AssignmentRecord:
    description = _first_value(
        detail,
        "description",
        "jobDescription",
        "assignmentDescription",
        "roleDescription",
        "descriptionText",
    )
    summary = _first_value(detail, "descriptionSummary", "summary", "shortDescription")
    start_date = _first_value(
        detail,
        "firstDayOfAssignment",
        "assignmentStartDate",
        "startDate",
        "startsAt",
    )
    end_date = _first_value(
        detail,
        "lastDayOfAssignment",
        "assignmentEndDate",
        "endDate",
        "endsAt",
    )
    last_application = _first_value(
        detail,
        "lastDayOfApplications",
        "lastApplicationDate",
        "applicationDeadline",
        "deadline",
        "lastDayToApply",
    )
    duration = _first_value(detail, "duration", "period", "assignmentPeriod") or ""
    if not duration and start_date and end_date:
        duration = f"{start_date} - {end_date}"

    skills = (
        _skill_items(detail.get("skills"))
        or _skill_items(detail.get("competences"))
        or _skill_items(detail.get("competencies"))
        or _skill_items(detail.get("requiredSkills"))
    )
    detail_work_mode = _first_value(detail, "workMode", "remoteDescription", "remotenessText")
    work_mode = _verama_work_mode(None, detail_work_mode) or record.workMode

    return AssignmentRecord(
        listing_id=record.listing_id,
        source_key=record.source_key,
        source_id=record.source_id,
        title=record.title,
        description=str(description or record.description or ""),
        descriptionSummary=str(summary or record.descriptionSummary or "")[:300],
        publishedDate=record.publishedDate,
        lastApplicationDate=record.lastApplicationDate or last_application,
        startDate=start_date or record.startDate,
        endDate=end_date or record.endDate,
        duration=str(duration or record.duration or ""),
        workMode=work_mode,
        location=record.location,
        sourceUrl=record.sourceUrl,
        broker=record.broker,
        skills=skills or record.skills,
    )


def _verama_title_outside_target(title: str) -> bool:
    normalized = title.lower()
    outside = (
        "sap ",
        "sap-",
        "network",
        "security",
        "cyber",
        "hr ",
        "payroll",
        "automation engineer",
        "factory",
        "embedded",
        "fpga",
        ".net",
        "data engineer",
        "cloud engineer",
    )
    target = (
        "accessibility",
        "tillgänglighet",
        "tillganglighet",
        "react",
        "frontend",
        "front-end",
        "angular",
        "wordpress",
        "java",
        "fullstack",
        "ux",
        "ui designer",
        "product designer",
        "projektledare",
        "project manager",
        "scrum master",
    )
    return any(term in normalized for term in outside) and not any(
        term in normalized for term in target
    )


def _verama_plausible_ambiguous(title: str) -> bool:
    return re.search(
        r"\b(consultant|konsult|developer|utvecklare|project lead|projektledare|lead|"
        r"designer|manager|scrum)\b",
        title,
        re.I,
    ) is not None


def _verama_strong_accessibility_title(title: str) -> bool:
    return re.search(
        r"(tillgänglighetsgranskare|tillganglighetsgranskare|"
        r"tillgänglighetsspecialist|tillganglighetsspecialist|"
        r"accessibility specialist|accessibility consultant|wcag specialist|"
        r"document accessibility|dokumenttillgänglighet|dokumenttillganglighet|"
        r"webbtillgänglighetsspecialist|webbtillganglighetsspecialist)",
        title,
        re.I,
    ) is not None


def _verama_location_precheck_passes(record: AssignmentRecord) -> bool:
    fields = f"{record.workMode} {record.location}".lower()
    if "100% remote" in fields or re.search(r"\b(distans|fjärrarbete|fjarrarbete)\b", fields):
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
        "botkyrka",
        "upplands väsby",
        "upplands vasby",
        "södertälje",
        "sodertalje",
        "haninge",
        "tyresö",
        "tyreso",
        "vällingby",
        "vallingby",
        "farsta",
    )
    if any(place in fields for place in near_stockholm):
        return True
    if re.search(r"\b(frontend|front-end|react|angular|wordpress)\b", record.title, re.I):
        return any(alias in fields for alias in ("gothenburg", "göteborg", "goteborg"))
    return False


def _verama_should_fetch_detail(
    record: AssignmentRecord,
    *,
    seen_ids: set[str],
    scan_date: date,
) -> bool:
    if record.source_id in seen_ids:
        return False
    last_application = _parse_date(record.lastApplicationDate)
    if last_application is not None and last_application < scan_date:
        return False
    if _verama_title_outside_target(record.title):
        return False
    if not _verama_location_precheck_passes(record) and not _verama_strong_accessibility_title(
        record.title
    ):
        return False
    if not record.lastApplicationDate:
        return True
    return _verama_plausible_ambiguous(record.title)


def scan_verama(
    email: str,
    password: str,
    *,
    seen_ids: set[str] | None = None,
    scan_date: date | None = None,
    page_size: int = 100,
    headless: bool = True,
) -> tuple[list[AssignmentRecord], PlatformScanResult]:
    source_key = "verama.com"
    seen_ids = seen_ids or set()
    scan_date = scan_date or date.today()

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

    by_id: dict[str, AssignmentRecord] = {}
    detail_fetches = 0
    detail_errors = 0

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
            request_headers = {
                **auth_headers,
                "user-agent": SCAN_USER_AGENT,
                "accept": "application/json, text/plain, */*",
                "referer": f"{VERAMA_BASE}/app/job-requests",
            }
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
                    headers=request_headers,
                    timeout=60000,
                )
                if response.status != 200:
                    raise RuntimeError(
                        f"Verama job API returned {response.status}: {response.text()[:200]}"
                    )

                payload = response.json()
                rows = payload.get("content") or []
                for row in rows:
                    record = _verama_list_record(row)
                    if _verama_should_fetch_detail(
                        record,
                        seen_ids=seen_ids,
                        scan_date=scan_date,
                    ):
                        detail_fetches += 1
                        detail_response = api.get(
                            f"{VERAMA_BASE}/api/job-requests/v2/{record.source_id}",
                            headers=request_headers,
                            timeout=60000,
                        )
                        if detail_response.status in (404, 405):
                            detail_response = api.get(
                                f"{VERAMA_BASE}/api/job-requests/{record.source_id}",
                                headers=request_headers,
                                timeout=60000,
                            )
                        if detail_response.status == 200:
                            record = _merge_verama_detail(record, detail_response.json())
                        else:
                            detail_errors += 1
                    by_id[record.source_id] = record

                if payload.get("last") or not rows:
                    break
                page_num += 1

            browser.close()

        message = None
        if detail_fetches or detail_errors:
            message = f"detail_fetches={detail_fetches}, detail_errors={detail_errors}"
        records = list(by_id.values())
        return records, PlatformScanResult(
            platform=source_key,
            status="ok",
            count=len(records),
            message=message,
        )
    except PlaywrightTimeoutError as exc:
        return list(by_id.values()), PlatformScanResult(
            platform=source_key,
            status="error",
            count=len(by_id),
            message=f"Verama login or listing timed out: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return list(by_id.values()), PlatformScanResult(
            platform=source_key,
            status="error",
            count=len(by_id),
            message=str(exc),
        )


PlatformScanner = Callable[..., tuple[list[AssignmentRecord], PlatformScanResult]]

PLATFORM_SCANNERS: dict[str, PlatformScanner] = {
    "allakonsultuppdrag.se": scan_allakonsultuppdrag,
    "verama.com": scan_verama,
}

DEFAULT_PLATFORMS = [key for key, spec in SOURCE_REGISTRY.items() if spec.active]
DEFAULT_SOURCES = DEFAULT_PLATFORMS


def scan_platforms(
    platform_ids: list[str],
    *,
    seen_ids_by_source: dict[str, set[str]] | None = None,
    scan_date: date | None = None,
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
                seen_ids=(seen_ids_by_source or {}).get(platform_id, set()),
                scan_date=scan_date,
                headless=headless,
            )
        else:
            rows, result = scanner(max_pages=max_pages)

        assignments.extend(rows)
        results.append(result)

    return assignments, results
