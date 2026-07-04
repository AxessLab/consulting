"""Canonical assignment records and source scanner registry."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
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
    scanner: "SourceScanner"
    active: bool = True


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
    skills: list[dict[str, Any]] = field(default_factory=list)

    @property
    def dedupe_key(self) -> str:
        return f"{self.source_key}:{self.source_id}"

    # Compatibility aliases for older helper code and curated JSON.
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
        """Load canonical records while tolerating older snake_case outputs."""
        source_key = row.get("source_key") or row.get("platform") or ""
        return cls(
            listing_id=str(row.get("listing_id") or row.get("id") or ""),
            source_key=str(source_key),
            source_id=str(row.get("source_id") or ""),
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
class SourceScanResult:
    source_key: str
    status: str
    count: int
    message: str | None = None

    @property
    def platform(self) -> str:
        return self.source_key

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_key": self.source_key,
            "platform": self.source_key,
            "status": self.status,
            "count": self.count,
            "message": self.message,
        }


PlatformScanResult = SourceScanResult


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
) -> tuple[list[AssignmentRecord], SourceScanResult]:
    source_key = "allakonsultuppdrag.se"
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
                    listing_id=f"a{source_id}",
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
                by_source_id[source_id] = record

            if not payload.get("hasNextPage"):
                break
            if total_pages is not None and page >= total_pages:
                break
            page += 1

        records = list(by_source_id.values())
        return records, SourceScanResult(source_key=source_key, status="ok", count=len(records))
    except Exception as exc:  # noqa: BLE001
        return list(by_source_id.values()), SourceScanResult(
            source_key=source_key,
            status="error",
            count=len(by_source_id),
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


VERAMA_STRONG_A11Y_TITLE = re.compile(
    r"\b(tillgänglighetsgranskare|tillganglighetsgranskare|"
    r"tillgänglighetsspecialist|tillganglighetsspecialist|"
    r"accessibility specialist|accessibility consultant|wcag specialist|"
    r"document accessibility|dokumenttillgänglighet|dokumenttillganglighet|"
    r"webbtillgänglighetsspecialist|webbtillganglighetsspecialist)\b",
    re.I,
)

VERAMA_TARGET_TITLE = re.compile(
    r"\b(accessibility|tillgänglighet|tillganglighet|wcag|frontend|front-end|"
    r"react|next\.?js|angular|wordpress|java|spring|backend|systemutvecklare|"
    r"fullstack|full-stack|full stack|ux|ui|product designer|designer|"
    r"interaction design|interaktionsdesign|tjänstedesign|tjanstedesign|"
    r"project manager|projektledare|scrum master|projektkoordinator|"
    r"project coordinator|agile coach|leveransansvarig|developer|utvecklare|"
    r"konsult|consultant)\b",
    re.I,
)

VERAMA_CLEARLY_OUTSIDE_TITLE = re.compile(
    r"\b(sap|network|security operations|soc|hr|payroll|lön|lon|automation "
    r"engineer|factory|industrial|embedded|fpga|mechanical|mekanik|"
    r"electronics|elektronik|data engineer|data scientist|business analyst|"
    r"test engineer|qa engineer|mobile developer|ios|android)\b",
    re.I,
)

VERAMA_NEAR_STOCKHOLM = re.compile(
    r"\b(stockholm|solna|sundbyberg|kista|bromma|sollentuna|danderyd|"
    r"täby|taby|järfälla|jarfalla|nacka|huddinge|lidingö|lidingo|"
    r"älvsjö|alvsjo|årsta|arsta|stockholms län|stockholms lan|botkyrka|"
    r"upplands väsby|upplands vasby|södertälje|sodertalje|haninge|"
    r"tyresö|tyreso|vällingby|vallingby|farsta)\b",
    re.I,
)

VERAMA_GOTHENBURG = re.compile(r"\b(göteborg|goteborg|gothenburg)\b", re.I)


def _verama_work_mode(remoteness: Any, *extra_fields: str) -> str:
    extras = " ".join(field for field in extra_fields if field)
    if re.search(r"\b(remote|distans|fjärrarbete|fjarrarbete)\b", extras, re.I):
        return "remote"
    try:
        remote_percentage = int(remoteness)
    except (TypeError, ValueError):
        return ""
    if remote_percentage >= 100:
        return "remote"
    if remote_percentage > 0:
        return f"{remote_percentage}% remote"
    return "on-site"


def _verama_list_record(row: dict[str, Any]) -> AssignmentRecord:
    source_id = str(row["id"])
    location = _verama_location(row.get("city"), row.get("countryCode"))
    work_mode = _verama_work_mode(row.get("remoteness"), location)
    return AssignmentRecord(
        listing_id=f"v{source_id}",
        source_key="verama.com",
        source_id=source_id,
        title=row.get("title") or "",
        description="",
        descriptionSummary="",
        publishedDate=row.get("firstDayOfApplications"),
        lastApplicationDate=row.get("lastDayOfApplications"),
        startDate=None,
        endDate=None,
        duration="",
        workMode=work_mode,
        location=location,
        sourceUrl=f"{VERAMA_BASE}/app/job-requests/{source_id}",
        broker=row.get("originServiceName") or "",
        skills=[],
    )


def _nested_get(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


def _stringify_description(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_stringify_description(item) for item in value if item)
    if isinstance(value, dict):
        return "\n".join(
            _stringify_description(item)
            for item in value.values()
            if isinstance(item, (str, list, dict))
        )
    return ""


def _verama_skills(detail: dict[str, Any]) -> list[dict[str, str]]:
    raw = (
        detail.get("skills")
        or detail.get("competences")
        or detail.get("competencies")
        or detail.get("requirements")
        or []
    )
    if isinstance(raw, dict):
        raw = list(raw.values())
    skills: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return skills
    for item in raw:
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, dict):
            name = str(
                item.get("name")
                or item.get("title")
                or item.get("label")
                or item.get("competence")
                or ""
            ).strip()
        else:
            name = ""
        if name:
            skills.append({"name": name})
    return skills


def _merge_verama_detail(record: AssignmentRecord, detail: dict[str, Any]) -> AssignmentRecord:
    description = _stringify_description(
        _nested_get(
            detail,
            (
                "description",
                "jobDescription",
                "assignmentDescription",
                "roleDescription",
                "requirementsDescription",
            ),
        )
    )
    summary = (
        _nested_get(detail, ("descriptionSummary", "summary", "shortDescription"))
        or description[:300]
    )
    detail_location = _verama_location(detail.get("city"), detail.get("countryCode"))
    location = record.location or detail_location
    detail_work_mode = _verama_work_mode(
        detail.get("remoteness"),
        str(detail.get("workMode") or ""),
        str(detail.get("remoteDescription") or ""),
        location,
    )
    start_date = _nested_get(
        detail,
        ("firstDayOfAssignment", "assignmentStartDate", "startDate", "start"),
    )
    end_date = _nested_get(
        detail,
        ("lastDayOfAssignment", "assignmentEndDate", "endDate", "end"),
    )
    return AssignmentRecord(
        listing_id=record.listing_id,
        source_key=record.source_key,
        source_id=record.source_id,
        title=record.title or detail.get("title") or "",
        description=description or record.description,
        descriptionSummary=str(summary or record.descriptionSummary or ""),
        publishedDate=record.publishedDate
        or _nested_get(detail, ("firstDayOfApplications", "publishedDate")),
        lastApplicationDate=record.lastApplicationDate
        or _nested_get(
            detail,
            ("lastDayOfApplications", "applicationDeadline", "deadline", "lastApplicationDate"),
        ),
        startDate=start_date or record.startDate,
        endDate=end_date or record.endDate,
        duration=str(_nested_get(detail, ("duration", "assignmentPeriod", "period")) or ""),
        workMode=detail_work_mode or record.workMode,
        location=location,
        sourceUrl=record.sourceUrl,
        broker=record.broker or str(detail.get("originServiceName") or ""),
        skills=_verama_skills(detail),
    )


def _verama_location_precheck(record: AssignmentRecord) -> bool:
    fields = f"{record.workMode} {record.location}"
    if re.search(r"\b(100\s*%\s*remote|distans|fjärrarbete|fjarrarbete)\b", fields, re.I):
        return True
    if re.search(r"\b[1-9]\d?\s*%\s*remote\b", fields, re.I):
        return False
    if re.search(r"\bremote\b", fields, re.I):
        return True
    if VERAMA_NEAR_STOCKHOLM.search(record.location):
        return True
    title = record.title
    if re.search(r"\b(frontend|front-end|react|angular|wordpress)\b", title, re.I):
        return VERAMA_GOTHENBURG.search(record.location) is not None
    return False


def _verama_should_fetch_detail(
    record: AssignmentRecord,
    *,
    seen_ids: set[str],
    scan_date: date,
) -> bool:
    if record.source_id in seen_ids:
        return False
    last_app = _parse_date(record.lastApplicationDate)
    if last_app is not None and last_app < scan_date:
        return False
    strong_a11y = VERAMA_STRONG_A11Y_TITLE.search(record.title) is not None
    if not strong_a11y and not _verama_location_precheck(record):
        return False
    if VERAMA_CLEARLY_OUTSIDE_TITLE.search(record.title) and not strong_a11y:
        return False
    if not VERAMA_TARGET_TITLE.search(record.title) and record.lastApplicationDate:
        return False
    return True


def scan_verama(
    email: str,
    password: str,
    *,
    page_size: int = 100,
    headless: bool = True,
    seen_ids: set[str] | None = None,
    scan_date: date | None = None,
) -> tuple[list[AssignmentRecord], SourceScanResult]:
    source_key = "verama.com"
    seen_ids = seen_ids or set()
    scan_date = scan_date or date.today()

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError:
        return [], SourceScanResult(
            source_key=source_key,
            status="error",
            count=0,
            message="playwright is not installed; run pip install -r requirements.txt",
        )

    records_by_id: dict[str, AssignmentRecord] = {}

    try:
        with sync_playwright() as playwright:
            browser = None
            context = None
            api = None
            auth_headers: dict[str, str] = {}

            def login() -> None:
                nonlocal browser, context, api, auth_headers
                if context is not None:
                    context.close()
                if browser is not None:
                    browser.close()
                browser = playwright.chromium.launch(headless=headless)
                context = browser.new_context(user_agent=SCAN_USER_AGENT, locale="sv-SE")
                page = context.new_page()
                auth_headers = {}

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
                    'button[type="submit"], button:has-text("Logga in"), '
                    'button:has-text("Log in")'
                ).first.click()
                page.wait_for_timeout(8000)
                page.goto(
                    f"{VERAMA_BASE}/app/job-requests",
                    wait_until="networkidle",
                    timeout=90000,
                )
                page.wait_for_timeout(3000)

                if not auth_headers:
                    raise RuntimeError("Could not capture Verama auth headers after login")
                api = context.request

            def api_get_json(url: str, *, params: dict[str, str] | None = None) -> dict[str, Any]:
                nonlocal api
                request_headers = {
                    **auth_headers,
                    "accept": "application/json, text/plain, */*",
                    "referer": f"{VERAMA_BASE}/app/job-requests",
                    "user-agent": SCAN_USER_AGENT,
                }
                assert api is not None
                response = api.get(
                    url,
                    params=params,
                    headers=request_headers,
                    timeout=60000,
                )
                if response.status in (401, 403):
                    login()
                    request_headers = {
                        **auth_headers,
                        "accept": "application/json, text/plain, */*",
                        "referer": f"{VERAMA_BASE}/app/job-requests",
                        "user-agent": SCAN_USER_AGENT,
                    }
                    assert api is not None
                    response = api.get(
                        url,
                        params=params,
                        headers=request_headers,
                        timeout=60000,
                    )
                if response.status != 200:
                    raise RuntimeError(
                        f"Verama API returned {response.status}: {response.text()[:200]}"
                    )
                return response.json()

            login()
            page_num = 0
            while True:
                payload = api_get_json(
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
                    record = _verama_list_record(row)
                    if _verama_should_fetch_detail(
                        record,
                        seen_ids=seen_ids,
                        scan_date=scan_date,
                    ):
                        detail = None
                        for detail_url in (
                            f"{VERAMA_BASE}/api/job-requests/v2/{record.source_id}",
                            f"{VERAMA_BASE}/api/job-requests/{record.source_id}",
                        ):
                            try:
                                detail = api_get_json(detail_url)
                                break
                            except RuntimeError:
                                if detail_url.endswith(f"/{record.source_id}") and "/v2/" in detail_url:
                                    continue
                                raise
                        if detail:
                            record = _merge_verama_detail(record, detail)
                    records_by_id[record.source_id] = record

                if payload.get("last") or not rows:
                    break
                page_num += 1

            if context is not None:
                context.close()
            if browser is not None:
                browser.close()

        records = list(records_by_id.values())
        return records, SourceScanResult(source_key=source_key, status="ok", count=len(records))
    except PlaywrightTimeoutError as exc:
        return list(records_by_id.values()), SourceScanResult(
            source_key=source_key,
            status="error",
            count=len(records_by_id),
            message=f"Verama login or listing timed out: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return list(records_by_id.values()), SourceScanResult(
            source_key=source_key,
            status="error",
            count=len(records_by_id),
            message=str(exc),
        )


SourceScanner = Callable[..., tuple[list[AssignmentRecord], SourceScanResult]]

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

PLATFORM_SCANNERS: dict[str, SourceScanner] = {
    key: config.scanner for key, config in SOURCE_REGISTRY.items()
}

DEFAULT_SOURCES = [key for key, config in SOURCE_REGISTRY.items() if config.active]
DEFAULT_PLATFORMS = DEFAULT_SOURCES


def scan_platforms(
    platform_ids: list[str],
    *,
    max_pages: int | None = None,
    headless: bool = True,
    seen_ids_by_source: dict[str, set[str]] | None = None,
    scan_date: date | None = None,
) -> tuple[list[AssignmentRecord], list[SourceScanResult]]:
    assignments: list[AssignmentRecord] = []
    results: list[SourceScanResult] = []
    verama_email = os.environ.get("VERAMA_EMAIL")
    verama_password = os.environ.get("VERAMA_PASSWORD")
    seen_ids_by_source = seen_ids_by_source or {}
    scan_date = scan_date or date.today()

    for source_key in platform_ids:
        config = SOURCE_REGISTRY.get(source_key)
        if config is None:
            results.append(
                SourceScanResult(
                    source_key=source_key,
                    status="error",
                    count=0,
                    message=f"Unknown source: {source_key}",
                )
            )
            continue
        scanner = config.scanner

        if source_key == "verama.com":
            if not verama_email or not verama_password:
                results.append(
                    SourceScanResult(
                        source_key=source_key,
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
                seen_ids=seen_ids_by_source.get(source_key, set()),
                scan_date=scan_date,
            )
        else:
            rows, result = scanner(max_pages=max_pages)

        assignments.extend(rows)
        results.append(result)

    return assignments, results
