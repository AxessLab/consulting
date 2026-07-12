"""Normalized assignment records and source scanner registry."""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Callable

import requests

ALLAKONSULT_BASE = "https://allakonsultuppdrag.se"
VERAMA_BASE = "https://app.verama.com"
SCAN_USER_AGENT = "Mozilla/5.0 (compatible; AssignmentScanner/1.0)"


@dataclass(frozen=True)
class SourceConfig:
    key: str
    prefix: str
    active: bool = True


SOURCE_REGISTRY: dict[str, SourceConfig] = {
    "allakonsultuppdrag.se": SourceConfig(key="allakonsultuppdrag.se", prefix="a"),
    "verama.com": SourceConfig(key="verama.com", prefix="v"),
}

CROSS_SOURCE_PREFERENCE = {"verama.com": 0, "allakonsultuppdrag.se": 1}


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
    skills: list[Any] = field(default_factory=list)
    detail_fetched: bool = True

    def __init__(
        self,
        source_key: str | None = None,
        source_id: str = "",
        listing_id: str = "",
        title: str = "",
        description: str = "",
        description_summary: str = "",
        published_date: str | None = None,
        last_application_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        duration: str = "",
        work_mode: str = "",
        location: str = "",
        source_url: str = "",
        broker: str = "",
        skills: list[Any] | None = None,
        detail_fetched: bool = True,
        platform: str | None = None,
    ) -> None:
        self.source_key = source_key or platform or ""
        self.source_id = str(source_id)
        self.listing_id = listing_id
        self.title = title
        self.description = description
        self.description_summary = description_summary
        self.published_date = published_date
        self.last_application_date = last_application_date
        self.start_date = start_date
        self.end_date = end_date
        self.duration = duration
        self.work_mode = work_mode
        self.location = location
        self.source_url = source_url
        self.broker = broker
        self.skills = skills or []
        self.detail_fetched = detail_fetched

    @property
    def platform(self) -> str:
        """Backward-compatible alias used by older prompt examples."""
        return self.source_key

    @property
    def dedupe_key(self) -> str:
        return f"{self.source_key}:{self.source_id}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_canonical_dict(self) -> dict[str, Any]:
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


@dataclass
class PlatformScanResult:
    platform: str
    status: str
    count: int
    message: str | None = None

    @property
    def source_key(self) -> str:
        return self.platform


def source_prefix(source_key: str) -> str:
    return SOURCE_REGISTRY[source_key].prefix


def _normalize_text(value: str) -> str:
    lowered = value.lower()
    normalized = unicodedata.normalize("NFKD", lowered)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _allakonsult_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": SCAN_USER_AGENT,
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
    prefix = source_prefix(source_key)
    session = _allakonsult_session()
    by_source_id: dict[str, AssignmentRecord] = {}
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
                    detail_fetched=True,
                )
                by_source_id[source_id] = record

            if not payload.get("hasNextPage"):
                break
            if total_pages is not None and page >= total_pages:
                break
            page += 1

        records = list(by_source_id.values())
        return records, PlatformScanResult(platform=source_key, status="ok", count=len(records))
    except Exception as exc:  # noqa: BLE001
        return list(by_source_id.values()), PlatformScanResult(
            platform=source_key,
            status="error",
            count=len(by_source_id),
            message=str(exc),
        )


def _verama_location(city: str | None, country_code: str | None) -> str:
    if city and country_code:
        return f"{city} ({country_code})"
    return city or country_code or ""


def _verama_work_mode(remoteness: Any, *fields: str) -> str:
    explicit = " ".join(field for field in fields if field)
    normalized = _normalize_text(explicit)
    if any(term in normalized for term in ("remote", "distans", "fjarrarbete")):
        if remoteness not in (None, ""):
            return f"{remoteness}% remote"
        return "remote"
    if remoteness not in (None, ""):
        try:
            numeric = int(remoteness)
        except (TypeError, ValueError):
            return str(remoteness)
        if numeric == 100:
            return "remote"
        if numeric > 0:
            return f"{numeric}% remote"
        return "on-site"
    return explicit.strip()


def _detail_value(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, "", []):
            return value
    return None


def _first_text(payload: dict[str, Any], *keys: str) -> str:
    value = _detail_value(payload, *keys)
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(str(item) for item in value if item)
    return ""


def _verama_skills(detail: dict[str, Any]) -> list[Any]:
    for key in ("skills", "competences", "requiredSkills", "niceToHaveSkills"):
        value = detail.get(key)
        if isinstance(value, list):
            return value
    return []


def _title_clearly_outside_target(title: str) -> bool:
    normalized = _normalize_text(title)
    outside = re.compile(
        r"\b(sap functional|sap consultant|network|security operations|soc |"
        r"hr|payroll|automation engineer|factory|fpga|embedded|mechanical|"
        r"data engineer|data scientist|cloud engineer|devops|mobile|ios|android)\b"
    )
    has_target_signal = re.search(
        r"\b(accessibility|tillganglighet|wcag|react|next|frontend|front-end|"
        r"angular|wordpress|java|spring|fullstack|ux|ui|product designer|"
        r"project manager|projektledare|scrum master|agile coach)\b",
        normalized,
    )
    return outside.search(normalized) is not None and has_target_signal is None


def _location_prefilter_fails(record: AssignmentRecord) -> bool:
    fields = _normalize_text(f"{record.work_mode} {record.location}")
    if any(term in fields for term in ("remote", "distans", "fjarrarbete")):
        return False
    stockholm = (
        "stockholm",
        "solna",
        "sundbyberg",
        "kista",
        "bromma",
        "sollentuna",
        "danderyd",
        "taby",
        "jarfalla",
        "nacka",
        "huddinge",
        "lidingo",
        "alvsjo",
        "arsta",
        "stockholms lan",
        "botkyrka",
        "upplands vasby",
        "sodertalje",
        "haninge",
        "tyreso",
        "vallingby",
        "farsta",
    )
    if any(place in fields for place in stockholm):
        return False
    title = _normalize_text(record.title)
    is_frontend = re.search(r"\b(frontend|front-end|react|angular|wordpress)\b", title)
    if is_frontend and any(place in fields for place in ("gothenburg", "goteborg")):
        return False
    strong_a11y = re.search(
        r"\b(tillganglighetsgranskare|tillganglighetsspecialist|"
        r"accessibility specialist|accessibility consultant|wcag specialist)\b",
        title,
    )
    return strong_a11y is None


def _should_fetch_verama_detail(
    record: AssignmentRecord,
    *,
    seen_ids: set[str],
    scan_date: date,
) -> bool:
    if record.source_id in seen_ids:
        return False
    deadline = _parse_iso_date(record.last_application_date)
    if deadline is not None and deadline < scan_date:
        return False
    if _title_clearly_outside_target(record.title):
        return False
    if _location_prefilter_fails(record):
        return False
    if not record.last_application_date:
        return True
    return True


def _verama_list_record(row: dict[str, Any]) -> AssignmentRecord:
    source_key = "verama.com"
    source_id = str(row["id"])
    prefix = source_prefix(source_key)
    work_mode = _verama_work_mode(row.get("remoteness"), row.get("workMode") or "")
    return AssignmentRecord(
        source_key=source_key,
        source_id=source_id,
        listing_id=f"{prefix}{source_id}",
        title=row.get("title") or "",
        description="",
        description_summary="",
        published_date=row.get("firstDayOfApplications"),
        last_application_date=row.get("lastDayOfApplications"),
        work_mode=work_mode,
        location=_verama_location(row.get("city"), row.get("countryCode")),
        source_url=f"{VERAMA_BASE}/app/job-requests/{source_id}",
        broker=row.get("originServiceName") or "",
        skills=[],
        detail_fetched=False,
    )


def _merge_verama_detail(record: AssignmentRecord, detail: dict[str, Any]) -> AssignmentRecord:
    description = _first_text(
        detail,
        "description",
        "jobDescription",
        "assignmentDescription",
        "longDescription",
    )
    summary = _first_text(detail, "descriptionSummary", "summary", "shortDescription")
    if not summary and description:
        summary = description[:300]

    first_assignment_day = _detail_value(
        detail,
        "firstDayOfAssignment",
        "startDate",
        "assignmentStartDate",
    )
    last_assignment_day = _detail_value(
        detail,
        "lastDayOfAssignment",
        "endDate",
        "assignmentEndDate",
    )
    deadline = (
        record.last_application_date
        or _detail_value(detail, "lastDayOfApplications", "applicationDeadline", "deadline")
    )

    explicit_remote = " ".join(
        str(value)
        for value in (
            detail.get("workMode"),
            detail.get("remotenessText"),
            detail.get("remoteText"),
            detail.get("location"),
        )
        if value
    )
    work_mode = _verama_work_mode(detail.get("remoteness"), record.work_mode, explicit_remote)

    duration = _first_text(detail, "duration", "assignmentPeriod", "period")
    if not duration and first_assignment_day and last_assignment_day:
        duration = f"{first_assignment_day} - {last_assignment_day}"

    record.description = description
    record.description_summary = summary
    record.last_application_date = str(deadline) if deadline else record.last_application_date
    record.start_date = str(first_assignment_day) if first_assignment_day else record.start_date
    record.end_date = str(last_assignment_day) if last_assignment_day else record.end_date
    record.duration = duration
    record.work_mode = work_mode or record.work_mode
    record.skills = _verama_skills(detail)
    record.detail_fetched = True
    return record


def _verama_headers(auth_headers: dict[str, str]) -> dict[str, str]:
    return {
        **auth_headers,
        "User-Agent": SCAN_USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Referer": f"{VERAMA_BASE}/app/job-requests",
    }


def scan_verama(
    email: str,
    password: str,
    *,
    page_size: int = 100,
    headless: bool = True,
    seen_ids: set[str] | None = None,
    scan_date: date | None = None,
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

    by_source_id: dict[str, AssignmentRecord] = {}

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
                    headers=_verama_headers(auth_headers),
                    timeout=60000,
                )
                if response.status in (401, 403):
                    raise RuntimeError(f"Verama job API returned {response.status}; re-login needed")
                if response.status != 200:
                    raise RuntimeError(
                        f"Verama job API returned {response.status}: {response.text()[:200]}"
                    )

                payload = response.json()
                rows = payload.get("content") or []
                for row in rows:
                    record = _verama_list_record(row)
                    by_source_id[record.source_id] = record

                if payload.get("last") or not rows:
                    break
                page_num += 1

            for record in list(by_source_id.values()):
                if not _should_fetch_verama_detail(
                    record,
                    seen_ids=seen_ids,
                    scan_date=scan_date,
                ):
                    continue
                detail_response = api.get(
                    f"{VERAMA_BASE}/api/job-requests/v2/{record.source_id}",
                    headers=_verama_headers(auth_headers),
                    timeout=60000,
                )
                if detail_response.status in (401, 403):
                    raise RuntimeError(f"Verama detail API returned {detail_response.status}")
                if detail_response.status == 404:
                    detail_response = api.get(
                        f"{VERAMA_BASE}/api/job-requests/{record.source_id}",
                        headers=_verama_headers(auth_headers),
                        timeout=60000,
                    )
                if detail_response.status != 200:
                    continue
                by_source_id[record.source_id] = _merge_verama_detail(
                    record,
                    detail_response.json(),
                )

            browser.close()

        records = list(by_source_id.values())
        return records, PlatformScanResult(platform=source_key, status="ok", count=len(records))
    except PlaywrightTimeoutError as exc:
        return list(by_source_id.values()), PlatformScanResult(
            platform=source_key,
            status="error",
            count=len(by_source_id),
            message=f"Verama login or listing timed out: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return list(by_source_id.values()), PlatformScanResult(
            platform=source_key,
            status="error",
            count=len(by_source_id),
            message=str(exc),
        )


PlatformScanner = Callable[..., tuple[list[AssignmentRecord], PlatformScanResult]]

PLATFORM_SCANNERS: dict[str, PlatformScanner] = {
    "allakonsultuppdrag.se": scan_allakonsultuppdrag,
    "verama.com": scan_verama,
}

DEFAULT_PLATFORMS = [key for key, config in SOURCE_REGISTRY.items() if config.active]


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
                    message=f"Unknown source: {platform_id}",
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
                seen_ids=seen_ids_by_source.get(platform_id, set()),
                scan_date=scan_date,
            )
        else:
            rows, result = scanner(max_pages=max_pages)

        assignments.extend(rows)
        results.append(result)

    return assignments, results
