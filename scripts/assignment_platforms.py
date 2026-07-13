"""Normalized assignment records and platform scanner registry."""

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

SOURCE_REGISTRY: dict[str, dict[str, str]] = {
    "allakonsultuppdrag.se": {"prefix": "a"},
    "verama.com": {"prefix": "v"},
}


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
        """Backward-compatible alias while scripts migrate to source_key."""
        return self.source_key

    @property
    def dedupe_key(self) -> str:
        return f"{self.source_key}:{self.source_id}"

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
        """Backward-compatible alias while scripts migrate to source_key."""
        return self.source_key

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_key": self.source_key,
            "platform": self.source_key,
            "status": self.status,
            "count": self.count,
            "message": self.message,
        }


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
    prefix = SOURCE_REGISTRY[source_key]["prefix"]
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
                by_key[record.dedupe_key] = record

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


def _normalize_text(value: str) -> str:
    return value.lower()


def _parse_api_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _verama_work_mode(remoteness: Any, *extra_fields: str) -> str:
    extra = " ".join(field for field in extra_fields if field)
    extra_lower = _normalize_text(extra)
    explicit_remote = any(term in extra_lower for term in ("remote", "distans", "fjärr", "fjarr"))
    try:
        remote_percent = int(remoteness) if remoteness is not None else None
    except (TypeError, ValueError):
        remote_percent = None

    if remote_percent == 100 or explicit_remote:
        return "remote" if remote_percent in (None, 100) else f"remote ({remote_percent}% remote)"
    if remote_percent is None:
        return "on-site"
    if remote_percent <= 0:
        return "on-site"
    return f"hybrid {remote_percent}% remote"


def _verama_list_record(row: dict[str, Any]) -> AssignmentRecord:
    source_key = "verama.com"
    source_id = str(row["id"])
    location = _verama_location(row.get("city"), row.get("countryCode"))
    return AssignmentRecord(
        source_key=source_key,
        source_id=source_id,
        listing_id=f"{SOURCE_REGISTRY[source_key]['prefix']}{source_id}",
        title=row.get("title") or "",
        description="",
        description_summary="",
        published_date=row.get("firstDayOfApplications"),
        last_application_date=row.get("lastDayOfApplications"),
        start_date="",
        end_date="",
        duration="",
        work_mode=_verama_work_mode(row.get("remoteness"), location),
        location=location,
        source_url=f"{VERAMA_BASE}/app/job-requests/{source_id}",
        broker=row.get("originServiceName") or "",
        skills=[],
    )


def _verama_title_is_clearly_outside(title: str) -> bool:
    text = _normalize_text(title)
    outside = re.compile(
        r"\b(sap|network|nätverk|security operations|soc|hr|payroll|"
        r"automation engineer|factory|produktion|inköp|procurement|"
        r"business analyst|data analyst|testare|tester|embedded|fpga|"
        r"devops|cloud engineer|solution architect|platform architect)\b"
    )
    target_signal = re.compile(
        r"\b(accessibility|tillgänglighet|tillganglighet|wcag|frontend|front-end|"
        r"react|next|angular|wordpress|java|spring|fullstack|ux|ui|designer|"
        r"project manager|projektledare|scrum master|projektkoordinator|"
        r"agile coach|leveransansvarig|developer|utvecklare|consultant|konsult)\b"
    )
    return bool(outside.search(text)) and not bool(target_signal.search(text))


def _verama_title_is_plausible(title: str) -> bool:
    text = _normalize_text(title)
    return bool(
        re.search(
            r"\b(accessibility|tillgänglighet|tillganglighet|wcag|frontend|front-end|"
            r"react|next|angular|wordpress|java|spring|backend|fullstack|ux|ui|"
            r"designer|project manager|projektledare|scrum master|projektkoordinator|"
            r"agile coach|leveransansvarig|developer|utvecklare|consultant|konsult)\b",
            text,
        )
    )


def _verama_strong_a11y_title(title: str) -> bool:
    text = _normalize_text(title)
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


def _verama_location_precheck(record: AssignmentRecord) -> bool:
    fields = _normalize_text(f"{record.work_mode} {record.location}")
    if "hybrid" not in fields and any(
        term in fields for term in ("remote", "distans", "fjärrarbete", "fjarrarbete")
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
    title = _normalize_text(record.title)
    frontend = bool(re.search(r"\b(frontend|front-end|react|next|angular|wordpress)\b", title))
    return frontend and any(place in fields for place in ("göteborg", "goteborg", "gothenburg"))


def _should_fetch_verama_detail(
    record: AssignmentRecord,
    *,
    seen_ids: set[str],
    scan_date: date,
) -> bool:
    if record.source_id in seen_ids:
        return False
    last_app = _parse_api_date(record.last_application_date)
    if last_app and last_app < scan_date:
        return False
    if _verama_title_is_clearly_outside(record.title):
        return False
    if not _verama_location_precheck(record) and not _verama_strong_a11y_title(record.title):
        return False
    if not record.last_application_date:
        return True
    return _verama_title_is_plausible(record.title)


def _first_string(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _nested_string(payload: dict[str, Any], *paths: tuple[str, ...]) -> str:
    for path in paths:
        current: Any = payload
        for key in path:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(key)
        if isinstance(current, str) and current.strip():
            return current.strip()
    return ""


def _extract_verama_skills(value: Any) -> list[Any]:
    if not value:
        return []
    if isinstance(value, str):
        return [{"name": value}]
    if isinstance(value, list):
        skills: list[Any] = []
        for item in value:
            if isinstance(item, dict):
                name = item.get("name") or item.get("skillName") or item.get("title")
                skills.append({"name": name} if name else item)
            elif isinstance(item, str):
                skills.append({"name": item})
        return skills
    return []


def _merge_verama_detail(record: AssignmentRecord, detail: dict[str, Any]) -> AssignmentRecord:
    description = _first_string(
        detail,
        (
            "description",
            "jobDescription",
            "assignmentDescription",
            "longDescription",
            "requirementsDescription",
            "descriptionHtml",
        ),
    )
    if not description:
        description = _nested_string(detail, ("jobRequest", "description"), ("request", "description"))

    summary = _first_string(detail, ("descriptionSummary", "summary", "shortDescription"))
    start_date = _first_string(
        detail,
        ("firstDayOfAssignment", "startDate", "assignmentStartDate", "start"),
    )
    end_date = _first_string(
        detail,
        ("lastDayOfAssignment", "endDate", "assignmentEndDate", "end"),
    )
    last_application = record.last_application_date or _first_string(
        detail,
        (
            "lastDayOfApplications",
            "lastApplicationDate",
            "applicationDeadline",
            "deadline",
        ),
    )
    skills = (
        _extract_verama_skills(detail.get("skills"))
        or _extract_verama_skills(detail.get("competences"))
        or _extract_verama_skills(detail.get("requiredSkills"))
        or _extract_verama_skills(detail.get("skillRequirements"))
    )
    remote_text = _first_string(detail, ("remotenessDescription", "workMode", "locationDescription"))
    work_mode = record.work_mode
    if remote_text:
        remote_lower = _normalize_text(remote_text)
        if any(term in remote_lower for term in ("remote", "distans", "fjärr", "fjarr")):
            work_mode = _verama_work_mode(None, remote_text)
        elif "hybrid" in remote_lower:
            work_mode = f"{record.work_mode}; {remote_text}".strip("; ")
    duration = _first_string(detail, ("duration", "assignmentPeriod", "period"))
    if not duration and start_date and end_date:
        duration = f"{start_date} - {end_date}"

    record.description = description
    record.description_summary = summary or (description[:300].strip() if description else "")
    record.last_application_date = last_application
    record.start_date = start_date
    record.end_date = end_date
    record.duration = duration
    record.work_mode = work_mode
    record.skills = skills
    return record


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
            source_key=source_key,
            status="error",
            count=0,
            message="playwright is not installed; run pip install -r requirements.txt",
        )

    records_by_id: dict[str, AssignmentRecord] = {}

    try:
        def run_once() -> None:
            nonlocal records_by_id
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
                    "User-Agent": SCAN_USER_AGENT,
                    "Accept": "application/json, text/plain, */*",
                    "Referer": f"{VERAMA_BASE}/app/job-requests",
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
                    if response.status in (401, 403):
                        raise PermissionError(f"Verama job API returned {response.status}")
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
                                headers=request_headers,
                                timeout=60000,
                            )
                            if detail_response.status in (401, 403):
                                raise PermissionError(
                                    f"Verama detail API returned {detail_response.status}"
                                )
                            if detail_response.status == 404:
                                detail_response = api.get(
                                    f"{VERAMA_BASE}/api/job-requests/{record.source_id}",
                                    headers=request_headers,
                                    timeout=60000,
                                )
                            if detail_response.status == 200:
                                record = _merge_verama_detail(record, detail_response.json())
                        records_by_id[record.source_id] = record

                    if payload.get("last") or not rows:
                        break
                    page_num += 1

                browser.close()

        try:
            run_once()
        except PermissionError:
            records_by_id = {}
            run_once()

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
                seen_ids=(seen_ids_by_source or {}).get(platform_id, set()),
                scan_date=scan_date,
            )
        else:
            rows, result = scanner(max_pages=max_pages)

        assignments.extend(rows)
        results.append(result)

    return assignments, results
