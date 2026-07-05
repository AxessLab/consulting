"""Canonical assignment records and source scanner registry."""

from __future__ import annotations

import html
import os
import re
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


@dataclass
class AssignmentRecord:
    """Canonical assignment shape shared by all downstream filtering."""

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

    # Backwards-compatible aliases for older helper code. New JSON output uses
    # the canonical field names above.
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
class SourceScanResult:
    source_key: str
    status: str
    count: int
    message: str | None = None

    @property
    def platform(self) -> str:
        return self.source_key


PlatformScanResult = SourceScanResult


def source_prefix(source_key: str) -> str:
    config = SOURCE_REGISTRY.get(source_key)
    return config.prefix if config else ""


def _first_value(data: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        value = data.get(name)
        if value not in (None, ""):
            return value
    return None


def _plain_text(value: Any) -> str:
    if not value:
        return ""
    text = str(value)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _allakonsult_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": SCAN_USER_AGENT, "Accept": "application/json"})
    return session


def scan_allakonsultuppdrag(
    *,
    page_size: int = 100,
    max_pages: int | None = None,
) -> tuple[list[AssignmentRecord], SourceScanResult]:
    source_key = "allakonsultuppdrag.se"
    prefix = source_prefix(source_key)
    session = _allakonsult_session()
    by_id: dict[str, AssignmentRecord] = {}
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
                by_id[source_id] = AssignmentRecord(
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

            if not payload.get("hasNextPage"):
                break
            if total_pages is not None and page >= total_pages:
                break
            page += 1

        records = list(by_id.values())
        return records, SourceScanResult(source_key=source_key, status="ok", count=len(records))
    except Exception as exc:  # noqa: BLE001
        return [], SourceScanResult(
            source_key=source_key,
            status="error",
            count=len(by_id),
            message=str(exc),
        )


def _verama_location(city: str | None, country_code: str | None) -> str:
    if city and country_code:
        return f"{city} ({country_code})"
    return city or country_code or ""


def _verama_work_mode(row: dict[str, Any]) -> str:
    remoteness = row.get("remoteness")
    explicit = " ".join(
        str(value)
        for value in (
            row.get("workMode"),
            row.get("remote"),
            row.get("remoteType"),
            row.get("locationType"),
        )
        if value not in (None, "")
    )
    if remoteness == 100:
        return "remote"
    if isinstance(remoteness, int) and 0 < remoteness < 100:
        return f"{remoteness}% remote hybrid"
    if remoteness == 0:
        return explicit or "on-site"
    if re.search(r"\b(remote|distans|fjärrarbete|fjarrarbete)\b", explicit, re.I):
        return explicit
    return explicit


def _verama_list_record(row: dict[str, Any]) -> AssignmentRecord:
    source_key = "verama.com"
    source_id = str(row["id"])
    return AssignmentRecord(
        listing_id=f"{source_prefix(source_key)}{source_id}",
        source_key=source_key,
        source_id=source_id,
        title=row.get("title") or "",
        description="",
        descriptionSummary=row.get("descriptionSummary") or "",
        publishedDate=row.get("firstDayOfApplications"),
        lastApplicationDate=row.get("lastDayOfApplications"),
        startDate=None,
        endDate=None,
        duration="",
        workMode=_verama_work_mode(row),
        location=_verama_location(row.get("city"), row.get("countryCode")),
        sourceUrl=f"{VERAMA_BASE}/app/job-requests/{source_id}",
        broker=row.get("originServiceName") or "",
        skills=[],
    )


TARGET_TITLE_HINT = re.compile(
    r"\b(accessibility|tillgänglighet|tillganglighet|wcag|frontend|front-end|"
    r"react|next\.?js|angular|wordpress|java|spring|fullstack|full-stack|"
    r"ux|ui|product designer|user experience|interaktionsdesign|tjänstedesign|"
    r"tjanstedesign|project manager|projektledare|scrum master|"
    r"projektkoordinator|agile coach|leveransansvarig|developer|utvecklare|"
    r"consultant|konsult|designer|tech lead|systemutvecklare)\b",
    re.I,
)

OUTSIDE_TITLE = re.compile(
    r"\b(sap|network|nätverk|security operations|soc|iam specialist|hr|payroll|"
    r"lönespecialist|automation engineer|factory|plc|embedded|fpga|mobile|ios|"
    r"android|data engineer|data scientist|python|\.net|c#|devops|cloud|"
    r"mechanical|mechatronic|test engineer|qa engineer)\b",
    re.I,
)

A11Y_TITLE_HINT = re.compile(
    r"\b(tillgänglighetsgranskare|tillganglighetsgranskare|"
    r"tillgänglighetsspecialist|tillganglighetsspecialist|"
    r"accessibility specialist|accessibility consultant|wcag specialist|"
    r"document accessibility|dokumenttillgänglighet|dokumenttillganglighet|"
    r"webbtillgänglighetsspecialist|webbtillganglighetsspecialist)\b",
    re.I,
)

STOCKHOLM_OR_NEAR = re.compile(
    r"\b(stockholm|solna|sundbyberg|kista|bromma|sollentuna|danderyd|täby|taby|"
    r"järfälla|jarfalla|nacka|huddinge|lidingö|lidingo|älvsjö|alvsjo|årsta|arsta|"
    r"stockholms län|stockholms lan|botkyrka|upplands väsby|upplands vasby|"
    r"södertälje|sodertalje|haninge|tyresö|tyreso|vällingby|vallingby|farsta)\b",
    re.I,
)

GOTHENBURG = re.compile(r"\b(gothenburg|göteborg|goteborg)\b", re.I)


def _verama_location_precheck_fails(record: AssignmentRecord) -> bool:
    fields = f"{record.workMode} {record.location}"
    if re.search(r"\b(remote|distans|fjärrarbete|fjarrarbete)\b", fields, re.I):
        if not re.search(r"\bhybrid\b", fields, re.I):
            return False
    if STOCKHOLM_OR_NEAR.search(record.location):
        return False
    title = record.title
    if re.search(r"\b(frontend|front-end|react|next\.?js|angular|wordpress)\b", title, re.I):
        return not GOTHENBURG.search(record.location)
    return True


def _should_fetch_verama_detail(
    record: AssignmentRecord,
    *,
    seen_ids: set[str],
    scan_date: date,
) -> bool:
    if record.source_id in seen_ids:
        return False

    deadline = _parse_date(record.lastApplicationDate)
    if deadline is not None and deadline < scan_date:
        return False

    title = record.title
    if OUTSIDE_TITLE.search(title) and not TARGET_TITLE_HINT.search(title):
        return False

    if (
        _verama_location_precheck_fails(record)
        and not A11Y_TITLE_HINT.search(title)
    ):
        return False

    return TARGET_TITLE_HINT.search(title) is not None or record.lastApplicationDate is None


def _normalize_verama_skills(detail: dict[str, Any]) -> list[Any]:
    for name in ("skills", "competences", "requiredCompetences", "requestedCompetences"):
        value = detail.get(name)
        if isinstance(value, list):
            return value
    return []


def _merge_verama_detail(record: AssignmentRecord, detail: dict[str, Any]) -> AssignmentRecord:
    description = _plain_text(
        _first_value(
            detail,
            (
                "description",
                "jobDescription",
                "assignmentDescription",
                "requestDescription",
                "projectDescription",
            ),
        )
    )
    summary = _plain_text(
        _first_value(detail, ("descriptionSummary", "summary", "shortDescription"))
    )
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
    duration = _plain_text(_first_value(detail, ("duration", "period", "assignmentPeriod")))
    if not duration and (start_date or end_date):
        duration = " - ".join(str(value) for value in (start_date, end_date) if value)

    work_mode = record.workMode
    detail_work_mode = _plain_text(
        _first_value(detail, ("workMode", "remote", "remoteType", "locationType"))
    )
    if detail_work_mode and detail_work_mode.lower() not in work_mode.lower():
        work_mode = " ".join(part for part in (work_mode, detail_work_mode) if part)

    return AssignmentRecord(
        listing_id=record.listing_id,
        source_key=record.source_key,
        source_id=record.source_id,
        title=record.title,
        description=description,
        descriptionSummary=summary or record.descriptionSummary,
        publishedDate=record.publishedDate,
        lastApplicationDate=record.lastApplicationDate
        or _first_value(
            detail,
            (
                "lastDayOfApplications",
                "lastApplicationDate",
                "applicationDeadline",
                "deadline",
            ),
        ),
        startDate=start_date,
        endDate=end_date,
        duration=duration,
        workMode=work_mode,
        location=record.location,
        sourceUrl=record.sourceUrl,
        broker=record.broker,
        skills=_normalize_verama_skills(detail),
    )


class VeramaAuthError(RuntimeError):
    pass


def _verama_api_headers(auth_headers: dict[str, str]) -> dict[str, str]:
    return {
        **auth_headers,
        "user-agent": SCAN_USER_AGENT,
        "accept": "application/json, text/plain, */*",
        "referer": f"{VERAMA_BASE}/app/job-requests",
    }


def _scan_verama_once(
    playwright: Any,
    *,
    email: str,
    password: str,
    page_size: int,
    headless: bool,
    seen_ids: set[str],
    scan_date: date,
) -> list[AssignmentRecord]:
    browser = playwright.chromium.launch(headless=headless)
    try:
        context = browser.new_context(user_agent=SCAN_USER_AGENT, locale="sv-SE")
        page = context.new_page()
        auth_headers: dict[str, str] = {}

        def capture_auth_headers(request: Any) -> None:
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
        headers = _verama_api_headers(auth_headers)
        by_id: dict[str, AssignmentRecord] = {}
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
                headers=headers,
                timeout=60000,
            )
            if response.status in (401, 403):
                raise VeramaAuthError(
                    f"Verama job API returned {response.status}: {response.text()[:200]}"
                )
            if response.status != 200:
                raise RuntimeError(
                    f"Verama job API returned {response.status}: {response.text()[:200]}"
                )

            payload = response.json()
            rows = payload.get("content") or []
            for row in rows:
                record = _verama_list_record(row)
                if _should_fetch_verama_detail(
                    record,
                    seen_ids=seen_ids,
                    scan_date=scan_date,
                ):
                    detail_response = api.get(
                        f"{VERAMA_BASE}/api/job-requests/v2/{record.source_id}",
                        headers=headers,
                        timeout=60000,
                    )
                    if detail_response.status == 404:
                        detail_response = api.get(
                            f"{VERAMA_BASE}/api/job-requests/{record.source_id}",
                            headers=headers,
                            timeout=60000,
                        )
                    if detail_response.status in (401, 403):
                        raise VeramaAuthError(
                            f"Verama detail API returned {detail_response.status}"
                        )
                    if detail_response.status == 200:
                        record = _merge_verama_detail(record, detail_response.json())
                by_id[record.source_id] = record

            if payload.get("last") or not rows:
                break
            page_num += 1

        return list(by_id.values())
    finally:
        browser.close()


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

    seen_ids = seen_ids or set()
    scan_date = scan_date or date.today()

    try:
        with sync_playwright() as playwright:
            for attempt in range(2):
                try:
                    records = _scan_verama_once(
                        playwright,
                        email=email,
                        password=password,
                        page_size=page_size,
                        headless=headless,
                        seen_ids=seen_ids,
                        scan_date=scan_date,
                    )
                    return records, SourceScanResult(
                        source_key=source_key,
                        status="ok",
                        count=len(records),
                    )
                except VeramaAuthError:
                    if attempt == 1:
                        raise
                    continue
    except PlaywrightTimeoutError as exc:
        return [], SourceScanResult(
            source_key=source_key,
            status="error",
            count=0,
            message=f"Verama login or listing timed out: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return [], SourceScanResult(
            source_key=source_key,
            status="error",
            count=0,
            message=str(exc),
        )

    return [], SourceScanResult(
        source_key=source_key,
        status="error",
        count=0,
        message="Verama scan ended unexpectedly",
    )


SourceScanner = Callable[..., tuple[list[AssignmentRecord], SourceScanResult]]

SOURCE_SCANNERS: dict[str, SourceScanner] = {
    "allakonsultuppdrag.se": scan_allakonsultuppdrag,
    "verama.com": scan_verama,
}

PLATFORM_SCANNERS = SOURCE_SCANNERS
DEFAULT_SOURCES = [key for key, config in SOURCE_REGISTRY.items() if config.active]
DEFAULT_PLATFORMS = DEFAULT_SOURCES


def scan_sources(
    source_keys: list[str],
    *,
    seen_ids_by_source: dict[str, set[str]] | None = None,
    scan_date: date | None = None,
    max_pages: int | None = None,
    headless: bool = True,
) -> tuple[list[AssignmentRecord], list[SourceScanResult]]:
    assignments: list[AssignmentRecord] = []
    results: list[SourceScanResult] = []
    seen_ids_by_source = seen_ids_by_source or {}
    verama_email = os.environ.get("VERAMA_EMAIL")
    verama_password = os.environ.get("VERAMA_PASSWORD")

    for source_key in source_keys:
        scanner = SOURCE_SCANNERS.get(source_key)
        if scanner is None:
            results.append(
                SourceScanResult(
                    source_key=source_key,
                    status="error",
                    count=0,
                    message=f"Unknown source: {source_key}",
                )
            )
            continue

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

        if result.status == "ok":
            assignments.extend(rows)
        results.append(result)

    return assignments, results


def scan_platforms(
    platform_ids: list[str],
    *,
    max_pages: int | None = None,
    headless: bool = True,
    seen_ids_by_source: dict[str, set[str]] | None = None,
    scan_date: date | None = None,
) -> tuple[list[AssignmentRecord], list[SourceScanResult]]:
    return scan_sources(
        platform_ids,
        seen_ids_by_source=seen_ids_by_source,
        scan_date=scan_date,
        max_pages=max_pages,
        headless=headless,
    )
