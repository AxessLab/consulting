"""Canonical assignment records and source scanner registry."""

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
class SourceDefinition:
    prefix: str
    key: str
    active: bool = True


SOURCE_REGISTRY: tuple[SourceDefinition, ...] = (
    SourceDefinition(prefix="a", key="allakonsultuppdrag.se"),
    SourceDefinition(prefix="v", key="verama.com"),
)
SOURCE_BY_KEY = {source.key: source for source in SOURCE_REGISTRY}
SOURCE_PREFIXES = {source.key: source.prefix for source in SOURCE_REGISTRY}


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

    @property
    def platform(self) -> str:
        """Legacy alias used by older helper code."""
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
        source_key = row.get("source_key") or row.get("platform") or ""
        return cls(
            source_key=source_key,
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
        """Legacy alias used by older helper code."""
        return self.source_key

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["platform"] = self.source_key
        return payload


def _source_prefix(source_key: str) -> str:
    return SOURCE_PREFIXES[source_key]


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
    **_: Any,
) -> tuple[list[AssignmentRecord], PlatformScanResult]:
    source_key = "allakonsultuppdrag.se"
    prefix = _source_prefix(source_key)
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
                if row.get("id") is None:
                    continue
                source_id = str(row["id"])
                by_id[source_id] = AssignmentRecord(
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

            if not payload.get("hasNextPage"):
                break
            if total_pages is not None and page >= total_pages:
                break
            page += 1

        records = list(by_id.values())
        return records, PlatformScanResult(source_key=source_key, status="ok", count=len(records))
    except Exception as exc:  # noqa: BLE001
        return list(by_id.values()), PlatformScanResult(
            source_key=source_key,
            status="error",
            count=len(by_id),
            message=str(exc),
        )


def _normalize_text(value: str) -> str:
    lowered = value.lower()
    normalized = unicodedata.normalize("NFKD", lowered)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _verama_location(city: str | None, country_code: str | None) -> str:
    if city and country_code:
        return f"{city} ({country_code})"
    return city or country_code or ""


def _verama_work_mode(remoteness: Any) -> str:
    if remoteness is None:
        return "on-site"
    try:
        remote_pct = int(remoteness)
    except (TypeError, ValueError):
        return str(remoteness)
    if remote_pct >= 100:
        return "100% remote"
    if remote_pct > 0:
        return f"hybrid ({remote_pct}% remote)"
    return "on-site"


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


VERAMA_NEAR_STOCKHOLM = {
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
}

VERAMA_A11Y_TITLE = re.compile(
    r"\b(tillganglighetsgranskare|tillganglighetsspecialist|"
    r"accessibility specialist|accessibility consultant|wcag specialist|"
    r"document accessibility|dokumenttillganglighet|"
    r"webbtillganglighetsspecialist)\b",
    re.I,
)

VERAMA_TARGET_TITLE = re.compile(
    r"\b(accessibility|tillganglighet|wcag|react|next\.?js|frontend|front-end|"
    r"angular|wordpress|java|spring|backend|fullstack|full-stack|ux|ui|"
    r"product designer|interaction design|interaktionsdesign|tjanstedesign|"
    r"project manager|projektledare|scrum master|projektkoordinator|"
    r"project coordinator|agile coach|leveransansvarig|developer|utvecklare|"
    r"systemutvecklare|consultant|konsult)\b",
    re.I,
)

VERAMA_OUTSIDE_TITLE = re.compile(
    r"\b(sap|network|nätverk|natverk|security operations|soc|hr|payroll|"
    r"automation engineer|factory|produktion|embedded|fpga|mekanik|mechanical|"
    r"test engineer|data engineer|devops|cloud engineer)\b",
    re.I,
)


def _verama_title_is_plausible(title: str) -> bool:
    normalized = _normalize_text(title)
    if VERAMA_A11Y_TITLE.search(normalized):
        return True
    if VERAMA_OUTSIDE_TITLE.search(normalized) and not re.search(
        r"\b(react|frontend|angular|wordpress|java|ux|ui)\b", normalized
    ):
        return False
    return VERAMA_TARGET_TITLE.search(normalized) is not None


def _verama_location_precheck(record: AssignmentRecord) -> bool:
    fields = _normalize_text(f"{record.work_mode} {record.location}")
    if "100% remote" in fields or "distans" in fields or "fjarrarbete" in fields:
        return True
    if "hybrid" in fields and not any(place in fields for place in VERAMA_NEAR_STOCKHOLM):
        return False
    if any(place in fields for place in VERAMA_NEAR_STOCKHOLM):
        return True
    title = _normalize_text(record.title)
    frontend = re.search(r"\b(react|frontend|front-end|angular|wordpress)\b", title)
    if frontend and any(city in fields for city in ("gothenburg", "goteborg")):
        return True
    return False


def _verama_should_fetch_detail(
    record: AssignmentRecord,
    *,
    seen_ids: set[str],
    scan_date: date,
) -> bool:
    if record.source_id in seen_ids:
        return False
    deadline = _parse_date(record.last_application_date)
    if deadline is not None and deadline < scan_date:
        return False
    if not _verama_title_is_plausible(record.title):
        return False
    if not _verama_location_precheck(record) and not VERAMA_A11Y_TITLE.search(
        _normalize_text(record.title)
    ):
        return False
    return True


def _first_string(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _first_value(payload: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return value
    return None


def _extract_verama_skills(payload: dict[str, Any]) -> list[Any]:
    for key in ("skills", "competences", "requiredSkills", "tags"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _merge_verama_detail(record: AssignmentRecord, detail: dict[str, Any]) -> AssignmentRecord:
    description = _first_string(
        detail,
        (
            "description",
            "jobDescription",
            "assignmentDescription",
            "roleDescription",
            "requirements",
            "longDescription",
        ),
    )
    if not description:
        text_blocks = [
            value.strip()
            for value in detail.values()
            if isinstance(value, str) and len(value.strip()) > 120
        ]
        description = "\n\n".join(dict.fromkeys(text_blocks))

    summary = _first_string(detail, ("descriptionSummary", "summary", "shortDescription"))
    if not summary and description:
        summary = description[:300]

    start = _first_value(detail, ("firstDayOfAssignment", "startDate", "assignmentStartDate"))
    end = _first_value(detail, ("lastDayOfAssignment", "endDate", "assignmentEndDate"))
    deadline = _first_value(
        detail,
        (
            "lastDayOfApplications",
            "lastApplicationDate",
            "applicationDeadline",
            "deadline",
        ),
    )
    duration = _first_string(detail, ("duration", "assignmentPeriod", "period"))
    if not duration and (start or end):
        duration = " - ".join(str(item) for item in (start, end) if item)

    explicit_work_mode = _first_string(detail, ("workMode", "workloadLocation", "remoteInfo"))
    work_mode = record.work_mode
    if explicit_work_mode and re.search(
        r"\b(remote|distans|fjärrarbete|fjarrarbete|hybrid)\b",
        explicit_work_mode,
        re.I,
    ):
        work_mode = f"{record.work_mode}; {explicit_work_mode}".strip("; ")

    return AssignmentRecord(
        source_key=record.source_key,
        source_id=record.source_id,
        listing_id=record.listing_id,
        title=record.title,
        description=description,
        description_summary=summary,
        published_date=record.published_date,
        last_application_date=str(deadline) if deadline else record.last_application_date,
        start_date=str(start) if start else record.start_date,
        end_date=str(end) if end else record.end_date,
        duration=duration or record.duration,
        work_mode=work_mode,
        location=record.location,
        source_url=record.source_url,
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
    **_: Any,
) -> tuple[list[AssignmentRecord], PlatformScanResult]:
    source_key = "verama.com"
    prefix = _source_prefix(source_key)
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

    def run_once() -> tuple[list[AssignmentRecord], int]:
        by_id: dict[str, AssignmentRecord] = {}
        detail_fetches = 0
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
            page.locator(
                'input[type="email"], input[name="email"], input[name="username"]'
            ).first.fill(email)
            page.locator('input[type="password"]').first.fill(password)
            page.locator(
                'button[type="submit"], button:has-text("Logga in"), button:has-text("Log in")'
            ).first.click()
            page.wait_for_timeout(8000)
            page.goto(f"{VERAMA_BASE}/app/job-requests", wait_until="networkidle", timeout=90000)
            page.wait_for_timeout(3000)

            if not auth_headers:
                browser.close()
                raise RuntimeError("Could not capture Verama auth headers after login")

            api = context.request
            api_headers = {
                **auth_headers,
                "User-Agent": SCAN_USER_AGENT,
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
                    headers=api_headers,
                    timeout=60000,
                )
                if response.status in {401, 403}:
                    browser.close()
                    raise VeramaAuthError(
                        f"Verama job API returned {response.status}; retrying login"
                    )
                if response.status != 200:
                    browser.close()
                    raise RuntimeError(
                        f"Verama job API returned {response.status}: {response.text()[:200]}"
                    )

                payload = response.json()
                rows = payload.get("content") or []
                for row in rows:
                    if row.get("id") is None:
                        continue
                    source_id = str(row["id"])
                    record = AssignmentRecord(
                        source_key=source_key,
                        source_id=source_id,
                        listing_id=f"{prefix}{source_id}",
                        title=row.get("title") or "",
                        published_date=row.get("firstDayOfApplications"),
                        last_application_date=row.get("lastDayOfApplications")
                        or row.get("lastApplicationDate"),
                        work_mode=_verama_work_mode(row.get("remoteness")),
                        location=_verama_location(row.get("city"), row.get("countryCode")),
                        source_url=f"{VERAMA_BASE}/app/job-requests/{source_id}",
                        broker=row.get("originServiceName") or "",
                    )

                    if _verama_should_fetch_detail(
                        record,
                        seen_ids=seen_ids,
                        scan_date=scan_date,
                    ):
                        detail_response = api.get(
                            f"{VERAMA_BASE}/api/job-requests/v2/{source_id}",
                            headers=api_headers,
                            timeout=60000,
                        )
                        if detail_response.status == 404:
                            detail_response = api.get(
                                f"{VERAMA_BASE}/api/job-requests/{source_id}",
                                headers=api_headers,
                                timeout=60000,
                            )
                        if detail_response.status in {401, 403}:
                            browser.close()
                            raise VeramaAuthError(
                                f"Verama detail API returned {detail_response.status}; retrying login"
                            )
                        if detail_response.status == 200:
                            record = _merge_verama_detail(record, detail_response.json())
                            detail_fetches += 1

                    by_id[source_id] = record

                if payload.get("last") or not rows:
                    break
                page_num += 1

            browser.close()
        return list(by_id.values()), detail_fetches

    records: list[AssignmentRecord] = []
    try:
        detail_fetches = 0
        for attempt in range(2):
            try:
                records, detail_fetches = run_once()
                break
            except VeramaAuthError:
                if attempt == 1:
                    raise
        message = f"detail_fetches={detail_fetches}"
        return records, PlatformScanResult(
            source_key=source_key,
            status="ok",
            count=len(records),
            message=message,
        )
    except PlaywrightTimeoutError as exc:
        return records, PlatformScanResult(
            source_key=source_key,
            status="error",
            count=len(records),
            message=f"Verama login or listing timed out: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return records, PlatformScanResult(
            source_key=source_key,
            status="error",
            count=len(records),
            message=str(exc),
        )


PlatformScanner = Callable[..., tuple[list[AssignmentRecord], PlatformScanResult]]

PLATFORM_SCANNERS: dict[str, PlatformScanner] = {
    "allakonsultuppdrag.se": scan_allakonsultuppdrag,
    "verama.com": scan_verama,
}

DEFAULT_PLATFORMS = [source.key for source in SOURCE_REGISTRY if source.active]


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
            rows, result = scanner(
                max_pages=max_pages,
                seen_ids=seen_ids_by_source.get(platform_id, set()),
                scan_date=scan_date,
            )

        assignments.extend(rows)
        results.append(result)

    return assignments, results
