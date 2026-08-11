"""Normalized assignment records and platform scanner registry."""

from __future__ import annotations

import html
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Callable

import requests

ALLAKONSULT_BASE = "https://allakonsultuppdrag.se"
VERAMA_BASE = "https://app.verama.com"
CHAS_BASE = "https://chaspartnernetwork.se"
MAGNIT_BROWSE_BASE = "https://magnit-source.magnitglobal.com"
MAGNIT_API_BASE = "https://app-openmarketgateway-prod.azurewebsites.net"
ALLAKONSULT_USER_AGENT = "Mozilla/5.0 (compatible; AssignmentScanner/1.0)"
SCAN_USER_AGENT = "Mozilla/5.0 (compatible; AxessLabAssignmentScanner/1.0)"
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_DATE_RANGE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2})\s*-\s*(\d{4}-\d{2}-\d{2})"
)
_DEADLINE_RE = re.compile(r"Deadline:\s*(\d{4}-\d{2}-\d{2})", re.I)
_ORG_COMMENT_RE = re.compile(
    r'call-off-organization[^>]*>(.*?)</div>',
    re.I | re.S,
)
_INFO_FIELD_RE = re.compile(
    r'<div class="(location|worktype|extent|consultants|interval)">\s*'
    r"(?:<[^>]+>\s*)*<span>(.*?)</span>",
    re.I | re.S,
)
_LI_ITEM_RE = re.compile(r"<li\b[^>]*>(.*?)</li>", re.I | re.S)

SOURCE_REGISTRY: tuple[dict[str, str], ...] = (
    {"prefix": "v", "source_key": "verama.com"},
    {"prefix": "c", "source_key": "chaspartnernetwork.se"},
    {"prefix": "a", "source_key": "allakonsultuppdrag.se"},
)
SOURCE_PREFIXES = {row["source_key"]: row["prefix"] for row in SOURCE_REGISTRY}
DEFAULT_SOURCES = [row["source_key"] for row in SOURCE_REGISTRY]


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
    def dedupe_key(self) -> str:
        return f"{self.source_key}:{self.source_id}"

    @property
    def platform(self) -> str:
        """Backward-compatible alias for older prompt/debug helpers."""
        return self.source_key

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "AssignmentRecord":
        data = dict(row)
        if "source_key" not in data and "platform" in data:
            data["source_key"] = data.pop("platform")
        allowed = set(cls.__dataclass_fields__)
        return cls(**{key: value for key, value in data.items() if key in allowed})


@dataclass
class PlatformScanResult:
    source_key: str
    status: str
    count: int
    message: str | None = None

    @property
    def platform(self) -> str:
        """Backward-compatible alias for older prompt/debug helpers."""
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
                    listing_id=f"{SOURCE_PREFIXES[source_key]}{source_id}",
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


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _verama_list_record(row: dict[str, Any]) -> AssignmentRecord:
    source_key = "verama.com"
    source_id = str(row["id"])
    remoteness = row.get("remoteness")
    work_mode = f"{remoteness}% remote" if remoteness is not None else ""
    if remoteness == 100:
        work_mode = "remote"
    elif isinstance(remoteness, int) and 0 < remoteness < 100:
        work_mode = f"hybrid, {remoteness}% remote"
    elif remoteness == 0:
        work_mode = "on-site"

    return AssignmentRecord(
        source_key=source_key,
        source_id=source_id,
        listing_id=f"{SOURCE_PREFIXES[source_key]}{source_id}",
        title=row.get("title") or "",
        description="",
        description_summary="",
        published_date=row.get("firstDayOfApplications"),
        last_application_date=row.get("lastDayOfApplications"),
        work_mode=work_mode,
        location=_verama_location(row.get("city"), row.get("countryCode")),
        source_url=f"{VERAMA_BASE}/app/job-requests/{source_id}",
        broker=row.get("originServiceName") or "",
    )


def _verama_title_outside_target(title: str) -> bool:
    text = title.lower()
    outside = re.compile(
        r"\b(sap|network|nätverk|security|säkerhet|devops|cloud|hr|payroll|"
        r"automation engineer|factory|mekanik|mechanical|embedded|fpga|"
        r"data engineer|python|\.net|c#|mobile|ios|android|testare|tester)\b",
        re.I,
    )
    target = re.compile(
        r"\b(accessibility|tillgänglighet|tillganglighet|wcag|react|next|"
        r"frontend|front-end|angular|wordpress|java|spring|fullstack|"
        r"full-stack|ux|ui|designer|projektledare|project manager|scrum master|"
        r"agile coach|koordinator|coordinator)\b",
        re.I,
    )
    return bool(outside.search(text)) and not bool(target.search(text))


def _verama_strong_a11y_title(title: str) -> bool:
    text = title.lower()
    return any(
        term in text
        for term in (
            "tillgänglighetsgransk",
            "tillganglighetsgransk",
            "tillgänglighetsspecialist",
            "tillganglighetsspecialist",
            "accessibility specialist",
            "accessibility consultant",
            "wcag specialist",
        )
    )


def _verama_location_prefilter(record: AssignmentRecord) -> bool:
    fields = f"{record.work_mode} {record.location}".lower()
    near_stockholm = re.compile(
        r"stockholm|solna|sundbyberg|kista|bromma|sollentuna|danderyd|täby|taby|"
        r"järfälla|jarfalla|nacka|huddinge|lidingö|lidingo|älvsjö|alvsjo|"
        r"årsta|arsta|stockholms län|stockholms lan|botkyrka|upplands väsby|"
        r"upplands vasby|södertälje|sodertalje|haninge|tyresö|tyreso|"
        r"vällingby|vallingby|farsta|remote|distans|fjärrarbete|fjarrarbete"
    )
    gothenburg_frontend = re.search(r"göteborg|goteborg|gothenburg", fields) and re.search(
        r"react|next|frontend|front-end|angular|wordpress",
        record.title,
        re.I,
    )
    return bool(near_stockholm.search(fields) or gothenburg_frontend)


def _verama_should_fetch_detail(
    record: AssignmentRecord,
    *,
    seen_ids: set[str],
    scan_date: date | None,
) -> bool:
    if record.source_id in seen_ids:
        return False

    deadline = _parse_date(record.last_application_date)
    if deadline is not None and scan_date is not None and deadline < scan_date:
        return False

    if _verama_title_outside_target(record.title):
        return False

    if not _verama_location_prefilter(record) and not _verama_strong_a11y_title(record.title):
        return False

    return True


def _first_detail_value(detail: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = detail.get(key)
        if value not in (None, "", []):
            return value
    return None


def _verama_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return _WHITESPACE_RE.sub(" ", _TAG_RE.sub(" ", html.unescape(value))).strip()
    if isinstance(value, list):
        return "\n".join(_verama_text(item) for item in value if _verama_text(item))
    if isinstance(value, dict):
        for key in ("description", "jobDescription", "text", "value", "name"):
            if value.get(key):
                return _verama_text(value[key])
    return str(value).strip()


def _verama_skills(detail: dict[str, Any]) -> list[dict[str, Any]]:
    raw_skills = _first_detail_value(
        detail,
        "skills",
        "competences",
        "competencies",
        "skillRequirements",
        "requiredSkills",
    )
    if not isinstance(raw_skills, list):
        return []
    skills: list[dict[str, Any]] = []
    for item in raw_skills:
        if isinstance(item, dict):
            name = item.get("name") or item.get("title") or item.get("label")
        else:
            name = item
        if name:
            skills.append({"name": str(name).strip()})
    return skills


def _verama_apply_detail(record: AssignmentRecord, detail: dict[str, Any]) -> AssignmentRecord:
    description = _verama_text(
        _first_detail_value(
            detail,
            "description",
            "jobDescription",
            "assignmentDescription",
            "requestDescription",
            "descriptionHtml",
        )
    )
    summary = _verama_text(_first_detail_value(detail, "descriptionSummary", "summary"))
    start = _first_detail_value(detail, "firstDayOfAssignment", "startDate", "assignmentStartDate")
    end = _first_detail_value(detail, "lastDayOfAssignment", "endDate", "assignmentEndDate")
    duration = _verama_text(_first_detail_value(detail, "duration", "assignmentPeriod", "period"))
    if not duration and start and end:
        duration = f"{str(start)[:10]} - {str(end)[:10]}"

    deadline = _first_detail_value(
        detail,
        "lastDayOfApplications",
        "lastApplicationDate",
        "applicationDeadline",
        "deadline",
    )
    work_mode_detail = _verama_text(_first_detail_value(detail, "workMode", "remotenessText"))
    if work_mode_detail and re.search(r"remote|distans|fjärr|hybrid", work_mode_detail, re.I):
        record.work_mode = f"{record.work_mode}; {work_mode_detail}".strip("; ")

    record.description = description
    record.description_summary = summary or (description[:300] if description else "")
    record.last_application_date = str(deadline) if deadline else record.last_application_date
    record.start_date = str(start)[:10] if start else record.start_date
    record.end_date = str(end)[:10] if end else record.end_date
    record.duration = duration or record.duration
    record.skills = _verama_skills(detail)
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

    by_key: dict[str, AssignmentRecord] = {}

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
                    headers={
                        **auth_headers,
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
                    record = _verama_list_record(row)
                    if _verama_should_fetch_detail(
                        record,
                        seen_ids=seen_ids,
                        scan_date=scan_date,
                    ):
                        detail_response = api.get(
                            f"{VERAMA_BASE}/api/job-requests/v2/{record.source_id}",
                            headers={
                                **auth_headers,
                                "accept": "application/json, text/plain, */*",
                                "referer": f"{VERAMA_BASE}/app/job-requests/{record.source_id}",
                            },
                            timeout=60000,
                        )
                        if detail_response.status == 404:
                            detail_response = api.get(
                                f"{VERAMA_BASE}/api/job-requests/{record.source_id}",
                                headers={
                                    **auth_headers,
                                    "accept": "application/json, text/plain, */*",
                                    "referer": f"{VERAMA_BASE}/app/job-requests/{record.source_id}",
                                },
                                timeout=60000,
                            )
                        if detail_response.status == 200:
                            record = _verama_apply_detail(record, detail_response.json() or {})
                    by_key[record.dedupe_key] = record

                if payload.get("last") or not rows:
                    break
                page_num += 1

            browser.close()

        records = list(by_key.values())
        return records, PlatformScanResult(source_key=source_key, status="ok", count=len(records))
    except PlaywrightTimeoutError as exc:
        records = list(by_key.values())
        return records, PlatformScanResult(
            source_key=source_key,
            status="error",
            count=len(records),
            message=f"Verama login or listing timed out: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        records = list(by_key.values())
        return records, PlatformScanResult(
            source_key=source_key,
            status="error",
            count=len(records),
            message=str(exc),
        )


def _chas_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": SCAN_USER_AGENT,
            "Accept": "application/json, text/html, */*",
        }
    )
    return session


def _chas_strip_html(value: str) -> str:
    text = _TAG_RE.sub(" ", html.unescape(value or ""))
    return _WHITESPACE_RE.sub(" ", text).strip()


def _chas_fetch_call_off_index(
    session: requests.Session,
    *,
    page_size: int = 100,
    max_pages: int | None = None,
) -> dict[str, dict[str, str]]:
    """Map call_off id → title/link/date from the public WP REST API."""
    index: dict[str, dict[str, str]] = {}
    page = 1
    total_pages = 1

    while page <= total_pages:
        if max_pages is not None and page > max_pages:
            break
        response = session.get(
            f"{CHAS_BASE}/wp-json/wp/v2/call_off",
            params={
                "per_page": page_size,
                "page": page,
                "orderby": "date",
                "order": "desc",
            },
            timeout=60,
        )
        response.raise_for_status()
        total_pages = int(response.headers.get("X-WP-TotalPages") or "1")
        for row in response.json() or []:
            source_id = str(row["id"])
            title = row.get("title") or {}
            index[source_id] = {
                "title": _chas_strip_html(
                    title.get("rendered") if isinstance(title, dict) else str(title)
                ),
                "link": row.get("link") or "",
                "date": (row.get("date") or "")[:10] or "",
            }
        page += 1

    return index


def _chas_konsult_ids(session: requests.Session) -> set[str]:
    response = session.get(
        f"{CHAS_BASE}/wp-admin/admin-ajax.php",
        params={
            "action": "cpn_filter_call_offs",
            "sort": "",
            "avtal_placeringsort": "",
            "anbudstyp": "Konsult",
            "fritext": "",
            "distance": "",
        },
        timeout=60,
    )
    response.raise_for_status()
    return set(re.findall(r'call-off-listitem" id="(\d+)"', response.text))


def _chas_parse_detail(html_text: str) -> dict[str, str]:
    """Extract location, dates, description, and client org from a detail page."""
    fields: dict[str, str] = {}
    for class_name, raw in _INFO_FIELD_RE.findall(html_text):
        value = _chas_strip_html(raw)
        if value and value != "-":
            fields[class_name] = value

    deadline_match = _DEADLINE_RE.search(html_text)
    if deadline_match:
        fields["deadline"] = deadline_match.group(1)

    interval = fields.get("interval", "")
    range_match = _DATE_RANGE_RE.search(interval)
    if range_match:
        fields["start_date"] = range_match.group(1)
        fields["end_date"] = range_match.group(2)

    org_match = _ORG_COMMENT_RE.search(html_text)
    if org_match:
        org = _chas_strip_html(org_match.group(1))
        if org:
            fields["organization"] = org

    desc_match = re.search(
        r"Uppdragsbeskrivning</h2>\s*(.*?)(?:<h2\b|#\s*Skicka in ansökan)",
        html_text,
        re.I | re.S,
    )
    if desc_match:
        fields["description"] = _chas_strip_html(desc_match.group(1))

    return fields


def scan_chaspartnernetwork(
    *,
    page_size: int = 100,
    max_pages: int | None = None,
) -> tuple[list[AssignmentRecord], PlatformScanResult]:
    source_key = "chaspartnernetwork.se"
    session = _chas_session()
    records: list[AssignmentRecord] = []

    try:
        index = _chas_fetch_call_off_index(
            session, page_size=page_size, max_pages=max_pages
        )
        konsult_ids = _chas_konsult_ids(session)
        selected_ids = [source_id for source_id in index if source_id in konsult_ids]
        # Preserve REST order (newest first); fall back to any konsult id missing from page window.
        if max_pages is None:
            for source_id in konsult_ids:
                if source_id not in index:
                    selected_ids.append(source_id)

        for source_id in selected_ids:
            meta = index.get(source_id) or {}
            source_url = meta.get("link") or f"{CHAS_BASE}/?post_type=call_off&p={source_id}"
            title = meta.get("title") or ""
            published_date = meta.get("date") or None
            description = ""
            description_summary = ""
            location = ""
            work_mode = ""
            duration = ""
            start_date = None
            end_date = None
            last_application_date = None

            try:
                detail = session.get(source_url, timeout=60)
                detail.raise_for_status()
                parsed = _chas_parse_detail(detail.text)
                location = parsed.get("location", "")
                work_mode = parsed.get("worktype", "")
                duration = parsed.get("extent", "") or parsed.get("interval", "")
                start_date = parsed.get("start_date")
                end_date = parsed.get("end_date")
                last_application_date = parsed.get("deadline")
                description = parsed.get("description", "")
                organization = parsed.get("organization", "")
                if organization:
                    description_summary = f"Client: {organization}"
                    if description:
                        description = f"Client: {organization}\n\n{description}"
                    else:
                        description = description_summary
                if not title:
                    title_match = re.search(
                        r'<h3 class="item-header"[^>]*>(.*?)</h3>',
                        detail.text,
                        re.I | re.S,
                    )
                    if title_match:
                        title = _chas_strip_html(title_match.group(1))
            except Exception:  # noqa: BLE001
                # Keep the REST stub so the listing still sees the assignment.
                pass

            records.append(
                AssignmentRecord(
                    source_key=source_key,
                    source_id=source_id,
                    listing_id=f"{SOURCE_PREFIXES[source_key]}{source_id}",
                    title=title,
                    description=description,
                    description_summary=description_summary,
                    published_date=published_date,
                    last_application_date=last_application_date,
                    start_date=start_date,
                    end_date=end_date,
                    duration=duration,
                    work_mode=work_mode,
                    location=location,
                    source_url=source_url,
                    broker="Chas Partner Network",
                )
            )

        return records, PlatformScanResult(
            source_key=source_key, status="ok", count=len(records)
        )
    except Exception as exc:  # noqa: BLE001
        return records, PlatformScanResult(
            source_key=source_key,
            status="error",
            count=len(records),
            message=str(exc),
        )


def _magnit_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": SCAN_USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": MAGNIT_BROWSE_BASE,
        }
    )
    return session


def _magnit_strip_html(value: str) -> str:
    text = _TAG_RE.sub(" ", html.unescape(value or ""))
    return _WHITESPACE_RE.sub(" ", text).strip()


def _magnit_date(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    return text[:10] if text else None


def _magnit_is_sweden(location: str) -> bool:
    loc = (location or "").upper()
    return "SWE" in loc or loc.endswith(", SE") or loc == "SE"


def _magnit_parse_skills_html(skills_html: str) -> list[dict[str, Any]]:
    skills: list[dict[str, Any]] = []
    for raw in _LI_ITEM_RE.findall(skills_html or ""):
        name = _magnit_strip_html(raw)
        if name:
            skills.append({"name": name})
    return skills


def scan_magnitsource(
    *,
    page_size: int = 20,
    max_pages: int | None = None,
) -> tuple[list[AssignmentRecord], PlatformScanResult]:
    """Scan Magnit Source open IT jobs in Sweden via the public jobsearch API."""
    source_key = "magnit-source.magnitglobal.com"
    session = _magnit_session()
    records: list[AssignmentRecord] = []
    by_key: dict[str, AssignmentRecord] = {}

    try:
        continuation_token: Any = None
        page = 1
        while True:
            if max_pages is not None and page > max_pages:
                break

            payload: dict[str, Any] = {
                "searchTerm": "",
                "selectedCategories": ["11"],
                "selectedhoursPerWeeks": [],
                "selectedLocationTypes": [],
                "selectedExperiences": [],
                "selectedStartDates": [],
                "selectedContractDurations": [],
                "selectedLocations": [],
                "selectedStatuses": ["4"],
                "tenant": None,
                "pageSize": page_size,
                "sortOption": {"orderBy": "PublishedDate", "direction": "Desc"},
                "continuationToken": continuation_token,
            }
            response = session.post(
                f"{MAGNIT_API_BASE}/api/jobsearch",
                json=payload,
                timeout=60,
            )
            response.raise_for_status()
            body = response.json() or {}
            jobs = body.get("jobs") or []

            for row in jobs:
                location = row.get("location") or ""
                if not _magnit_is_sweden(location):
                    continue

                source_id = str(row.get("id") or "").strip()
                if not source_id:
                    continue

                title = row.get("title") or ""
                company = (row.get("company") or "").strip()
                source_url = f"{MAGNIT_BROWSE_BASE}/browse/job/{source_id}"
                work_mode = row.get("workLocationType") or ""
                start_date = _magnit_date(row.get("startDate"))
                last_application_date = _magnit_date(row.get("submissionDeadline"))
                published_date = None
                end_date = None
                duration = ""
                description = ""
                description_summary = f"Client: {company}" if company else ""
                skills: list[dict[str, Any]] = []

                try:
                    detail_resp = session.get(
                        f"{MAGNIT_API_BASE}/api/jobsearch/{source_id}/details",
                        timeout=60,
                    )
                    detail_resp.raise_for_status()
                    detail = detail_resp.json() or {}
                    request_details = detail.get("requestDetails") or {}
                    candidate_reqs = detail.get("candidateRequirements") or {}
                    technical = detail.get("technicalDetails") or {}

                    if not title:
                        title = detail.get("title") or title
                    if not company:
                        company = (detail.get("company") or "").strip()
                        if company:
                            description_summary = f"Client: {company}"

                    location = (
                        request_details.get("location")
                        or detail.get("location")
                        or location
                    )
                    work_mode = (
                        candidate_reqs.get("workLocationType")
                        or detail.get("workLocationType")
                        or work_mode
                        or ""
                    )
                    start_date = _magnit_date(
                        request_details.get("startDate")
                    ) or start_date
                    end_date = _magnit_date(request_details.get("endDate"))
                    last_application_date = _magnit_date(
                        request_details.get("submissionDeadline")
                    ) or last_application_date
                    published_date = _magnit_date(
                        technical.get("dateFirstPublished")
                    )
                    hours = request_details.get("hoursPerWeek")
                    if hours is not None and str(hours).strip():
                        duration = f"{hours} h/week"

                    skills_html = detail.get("jobSkills") or ""
                    desc_html = detail.get("jobDescription") or ""
                    skills = _magnit_parse_skills_html(skills_html)
                    skills_text = _magnit_strip_html(skills_html)
                    desc_text = _magnit_strip_html(desc_html)
                    parts: list[str] = []
                    if description_summary:
                        parts.append(description_summary)
                    if skills_text:
                        parts.append(skills_text)
                    if desc_text:
                        parts.append(desc_text)
                    description = "\n\n".join(parts)
                except Exception:  # noqa: BLE001
                    # Keep the list stub so the listing still sees the assignment.
                    if description_summary:
                        description = description_summary

                record = AssignmentRecord(
                    source_key=source_key,
                    source_id=source_id,
                    listing_id=f"m{source_id}",
                    title=title,
                    description=description,
                    description_summary=description_summary,
                    published_date=published_date,
                    last_application_date=last_application_date,
                    start_date=start_date,
                    end_date=end_date,
                    duration=duration,
                    work_mode=work_mode if isinstance(work_mode, str) else "",
                    location=location,
                    source_url=source_url,
                    broker="Magnit Source",
                    skills=skills,
                )
                by_key[record.dedupe_key] = record

            continuation_token = body.get("continuationToken")
            if not continuation_token or not jobs:
                break
            page += 1

        records = list(by_key.values())
        return records, PlatformScanResult(
            source_key=source_key, status="ok", count=len(records)
        )
    except Exception as exc:  # noqa: BLE001
        records = list(by_key.values())
        return records, PlatformScanResult(
            source_key=source_key,
            status="error",
            count=len(records),
            message=str(exc),
        )


PlatformScanner = Callable[..., tuple[list[AssignmentRecord], PlatformScanResult]]

PLATFORM_SCANNERS: dict[str, PlatformScanner] = {
    "verama.com": scan_verama,
    "chaspartnernetwork.se": scan_chaspartnernetwork,
    "allakonsultuppdrag.se": scan_allakonsultuppdrag,
    # Kept for ad-hoc debugging, but inactive by default and not part of the
    # current assignment-listing source registry.
    "magnit-source.magnitglobal.com": scan_magnitsource,
}

DEFAULT_PLATFORMS = DEFAULT_SOURCES


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
