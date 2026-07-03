"""Normalized assignment records and source scanner registry."""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Callable

import requests

ALLAKONSULT_BASE = "https://allakonsultuppdrag.se"
VERAMA_BASE = "https://app.verama.com"
ALLAKONSULT_USER_AGENT = "Mozilla/5.0 (compatible; AssignmentScanner/1.0)"
SCAN_USER_AGENT = "Mozilla/5.0 (compatible; AssignmentScanner/1.0)"


@dataclass(frozen=True)
class SourceConfig:
    key: str
    prefix: str


SOURCE_REGISTRY: dict[str, SourceConfig] = {
    "allakonsultuppdrag.se": SourceConfig(key="allakonsultuppdrag.se", prefix="a"),
    "verama.com": SourceConfig(key="verama.com", prefix="v"),
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


@dataclass
class PlatformScanResult:
    source_key: str
    status: str
    count: int
    message: str | None = None

    @property
    def platform(self) -> str:
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
                    source_key=source_key,
                    source_id=source_id,
                    listing_id=f"{prefix}{source_id}",
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
                by_key[record.source_id] = record

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


def _verama_work_mode(remoteness: Any, *extra_fields: str | None) -> str:
    explicit = " ".join(field or "" for field in extra_fields).lower()
    if any(term in explicit for term in ("distans", "fjärr", "fjarr", "remote")):
        if "hybrid" not in explicit:
            return "remote"

    try:
        remote_percentage = int(remoteness)
    except (TypeError, ValueError):
        remote_percentage = None

    if remote_percentage == 100:
        return "remote"
    if remote_percentage and 0 < remote_percentage < 100:
        return f"hybrid ({remote_percentage}% remote)"
    if remote_percentage == 0:
        return "on-site"
    return explicit.strip() or ""


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _normalize_text(value: str) -> str:
    return value.casefold()


TARGET_TITLE_TERMS = re.compile(
    r"\b("
    r"accessibility|tillgänglighet|tillganglighet|wcag|"
    r"frontend|front-end|react|next\.?js|angular|wordpress|"
    r"java|spring|backend|systemutvecklare|fullstack|full-stack|"
    r"ux|ui|product designer|interaction designer|interaktionsdesigner|"
    r"projektledare|project manager|scrum master|projektkoordinator|"
    r"project coordinator|agile coach|leveransansvarig|developer|utvecklare|consultant|konsult"
    r")\b",
    re.I,
)

TITLE_EXCLUSIONS = re.compile(
    r"\b("
    r"sap|network|nätverk|security operations|soc|hr|payroll|lön|lon|"
    r"automation engineer|factory|produktion|embedded|fpga|data engineer|"
    r"analyst|business controller|test manager|devops|cloud architect"
    r")\b",
    re.I,
)

STOCKHOLM_OR_GOTHENBURG = re.compile(
    r"(stockholm|solna|sundbyberg|kista|bromma|sollentuna|danderyd|täby|taby|"
    r"järfälla|jarfalla|nacka|huddinge|lidingö|lidingo|älvsjö|alvsjo|årsta|"
    r"arsta|stockholms län|stockholms lan|botkyrka|upplands väsby|upplands vasby|"
    r"södertälje|sodertalje|haninge|tyresö|tyreso|vällingby|vallingby|farsta|"
    r"göteborg|goteborg|gothenburg)",
    re.I,
)

ACCESSIBILITY_TITLE = re.compile(
    r"(tillgänglighetsgranskare|tillganglighetsgranskare|"
    r"tillgänglighetsspecialist|tillganglighetsspecialist|"
    r"accessibility specialist|accessibility consultant|wcag specialist|"
    r"document accessibility|dokumenttillgänglighet|webbtillgänglighetsspecialist)",
    re.I,
)


def _verama_list_row_should_fetch_detail(
    record: AssignmentRecord,
    *,
    seen_ids: set[str],
    scan_date: date,
) -> bool:
    if record.source_id in seen_ids:
        return False

    last_application_date = _parse_date(record.lastApplicationDate)
    if last_application_date is not None and last_application_date < scan_date:
        return False

    title = _normalize_text(record.title)
    is_accessibility_title = ACCESSIBILITY_TITLE.search(title) is not None
    if TITLE_EXCLUSIONS.search(title) and not TARGET_TITLE_TERMS.search(title):
        return False
    if not TARGET_TITLE_TERMS.search(title):
        return False

    location_text = _normalize_text(f"{record.location} {record.workMode}")
    location_precheck_passes = (
        "remote" in location_text
        or "distans" in location_text
        or "fjärr" in location_text
        or "fjarr" in location_text
        or STOCKHOLM_OR_GOTHENBURG.search(location_text) is not None
    )
    if not location_precheck_passes and not is_accessibility_title:
        return False

    return True


def _first_string(payload: Any, keys: tuple[str, ...]) -> str:
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in payload.values():
            nested = _first_string(value, keys)
            if nested:
                return nested
    elif isinstance(payload, list):
        for item in payload:
            nested = _first_string(item, keys)
            if nested:
                return nested
    return ""


def _first_value(payload: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return value
    return None


def _verama_skills(detail: dict[str, Any]) -> list[Any]:
    raw_skills = _first_value(
        detail,
        ("skills", "competences", "competencies", "requiredSkills", "technologies"),
    )
    if not isinstance(raw_skills, list):
        return []

    skills: list[Any] = []
    for skill in raw_skills:
        if isinstance(skill, str):
            skills.append(skill)
        elif isinstance(skill, dict):
            name = skill.get("name") or skill.get("label") or skill.get("title")
            if name:
                skills.append({"name": str(name)})
    return skills


def _merge_verama_detail(
    record: AssignmentRecord,
    detail: dict[str, Any],
) -> AssignmentRecord:
    description = _first_string(
        detail,
        (
            "description",
            "jobDescription",
            "assignmentDescription",
            "roleDescription",
            "longDescription",
            "text",
        ),
    )
    summary = _first_string(detail, ("descriptionSummary", "summary", "shortDescription"))
    if not summary and description:
        summary = description[:300]

    start_date = _first_value(
        detail,
        ("firstDayOfAssignment", "assignmentStartDate", "startDate", "start"),
    )
    end_date = _first_value(
        detail,
        ("lastDayOfAssignment", "assignmentEndDate", "endDate", "end"),
    )
    deadline = record.lastApplicationDate or _first_value(
        detail,
        (
            "lastDayOfApplications",
            "lastApplicationDate",
            "applicationDeadline",
            "deadline",
        ),
    )
    duration = _first_string(detail, ("duration", "period", "assignmentPeriod"))
    if not duration and (start_date or end_date):
        duration = " - ".join(str(item) for item in (start_date, end_date) if item)

    detail_work_mode = _first_string(detail, ("workMode", "remotenessDescription", "remote"))

    return AssignmentRecord(
        listing_id=record.listing_id,
        source_key=record.source_key,
        source_id=record.source_id,
        title=record.title,
        description=description,
        descriptionSummary=summary,
        publishedDate=record.publishedDate,
        lastApplicationDate=str(deadline) if deadline else record.lastApplicationDate,
        startDate=str(start_date) if start_date else None,
        endDate=str(end_date) if end_date else None,
        duration=duration,
        workMode=_verama_work_mode(None, detail_work_mode) or record.workMode,
        location=record.location,
        sourceUrl=record.sourceUrl,
        broker=record.broker,
        skills=_verama_skills(detail),
    )


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
    prefix = SOURCE_REGISTRY[source_key].prefix
    seen_ids = seen_ids or set()
    scan_date = scan_date or date.today()

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

    records_by_id: dict[str, AssignmentRecord] = {}

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)

            def login() -> tuple[Any, Any, dict[str, str]]:
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
                    context.close()
                    raise RuntimeError("Could not capture Verama auth headers after login")
                return context, context.request, auth_headers

            context, api, auth_headers = login()

            def request_headers() -> dict[str, str]:
                return {
                    **auth_headers,
                    "User-Agent": SCAN_USER_AGENT,
                    "Accept": "application/json, text/plain, */*",
                    "Referer": f"{VERAMA_BASE}/app/job-requests",
                }

            relogged = False
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
                    headers=request_headers(),
                    timeout=60000,
                )
                if response.status in (401, 403) and not relogged:
                    context.close()
                    context, api, auth_headers = login()
                    relogged = True
                    continue
                if response.status != 200:
                    raise RuntimeError(
                        f"Verama job API returned {response.status}: {response.text()[:200]}"
                    )

                payload = response.json()
                rows = payload.get("content") or []
                for row in rows:
                    source_id = str(row["id"])
                    remoteness = row.get("remoteness")
                    record = AssignmentRecord(
                        source_key=source_key,
                        source_id=source_id,
                        listing_id=f"{prefix}{source_id}",
                        title=row.get("title") or "",
                        description="",
                        descriptionSummary="",
                        publishedDate=row.get("firstDayOfApplications"),
                        lastApplicationDate=row.get("lastDayOfApplications"),
                        workMode=_verama_work_mode(remoteness),
                        location=_verama_location(row.get("city"), row.get("countryCode")),
                        sourceUrl=f"{VERAMA_BASE}/app/job-requests/{source_id}",
                        broker=row.get("originServiceName") or "",
                    )

                    if _verama_list_row_should_fetch_detail(
                        record,
                        seen_ids=seen_ids,
                        scan_date=scan_date,
                    ):
                        detail_response = api.get(
                            f"{VERAMA_BASE}/api/job-requests/v2/{source_id}",
                            headers=request_headers(),
                            timeout=60000,
                        )
                        if detail_response.status == 404:
                            detail_response = api.get(
                                f"{VERAMA_BASE}/api/job-requests/{source_id}",
                                headers=request_headers(),
                                timeout=60000,
                            )
                        if detail_response.status == 200:
                            detail_payload = detail_response.json()
                            if isinstance(detail_payload, dict):
                                record = _merge_verama_detail(record, detail_payload)
                        elif detail_response.status not in (401, 403):
                            # Keep the list row for memory even when one detail request fails.
                            pass

                    records_by_id[record.source_id] = record

                if payload.get("last") or not rows:
                    break
                page_num += 1

            context.close()
            browser.close()

        records = list(records_by_id.values())
        return records, PlatformScanResult(source_key=source_key, status="ok", count=len(records))
    except PlaywrightTimeoutError as exc:
        return list(records_by_id.values()), PlatformScanResult(
            source_key=source_key,
            status="error",
            count=len(records_by_id),
            message=f"Verama login or listing timed out: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return list(records_by_id.values()), PlatformScanResult(
            source_key=source_key,
            status="error",
            count=len(records_by_id),
            message=str(exc),
        )


PlatformScanner = Callable[..., tuple[list[AssignmentRecord], PlatformScanResult]]

PLATFORM_SCANNERS: dict[str, PlatformScanner] = {
    "allakonsultuppdrag.se": scan_allakonsultuppdrag,
    "verama.com": scan_verama,
}

DEFAULT_PLATFORMS = list(SOURCE_REGISTRY.keys())
DEFAULT_SOURCES = DEFAULT_PLATFORMS


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
                    source_key=platform_id,
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
                seen_ids=seen_ids_by_source.get(platform_id, set()),
                scan_date=scan_date,
            )
        else:
            rows, result = scanner(max_pages=max_pages)

        assignments.extend(rows)
        results.append(result)

    return assignments, results
