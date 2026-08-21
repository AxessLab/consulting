"""Normalized assignment records and platform scanner registry."""

from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass, field
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
SOURCE_PREFIXES = {
    "verama.com": "v",
    "chaspartnernetwork.se": "c",
    "allakonsultuppdrag.se": "a",
}
ACTIVE_SOURCE_ORDER = (
    "verama.com",
    "chaspartnernetwork.se",
    "allakonsultuppdrag.se",
)
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


@dataclass
class AssignmentRecord:
    platform: str
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
        return f"{self.platform}:{self.source_id}"

    @property
    def source_key(self) -> str:
        return self.platform

    def to_dict(self) -> dict[str, Any]:
        return {
            "listing_id": self.listing_id,
            "source_key": self.platform,
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
        return cls(
            platform=row.get("source_key") or row.get("platform") or "",
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
    platform = "allakonsultuppdrag.se"
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
                    platform=platform,
                    source_id=source_id,
                    listing_id=f"a{source_id}",
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
        return records, PlatformScanResult(platform=platform, status="ok", count=len(records))
    except Exception as exc:  # noqa: BLE001
        return list(by_key.values()), PlatformScanResult(
            platform=platform,
            status="error",
            count=len(by_key),
            message=str(exc),
        )


def _verama_location(city: str | None, country_code: str | None) -> str:
    if city and country_code:
        return f"{city} ({country_code})"
    return city or country_code or ""


def _normalize_for_checks(value: str) -> str:
    return html.unescape(value or "").lower()


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _verama_work_mode(remoteness: Any) -> str:
    if remoteness is None:
        return ""
    try:
        value = int(remoteness)
    except (TypeError, ValueError):
        return str(remoteness)
    if value >= 100:
        return "100% remote"
    if value > 0:
        return f"Hybrid ({value}% remote)"
    return "On-site"


def _verama_is_accessibility_title(title: str) -> bool:
    normalized = _normalize_for_checks(title)
    return any(
        term in normalized
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


def _verama_title_clearly_outside(title: str) -> bool:
    normalized = _normalize_for_checks(title)
    positive = re.search(
        r"\b(accessibility|tillgänglighet|tillganglighet|wcag|react|next\.?js|"
        r"frontend|front-end|angular|wordpress|java|spring|backend|fullstack|"
        r"full-stack|ux|ui|designer|projektledare|project manager|scrum|"
        r"agile|koordinator|coordinator|developer|utvecklare|konsult|consultant)\b",
        normalized,
        re.I,
    )
    negative = re.search(
        r"\b(sap|network|nätverk|natverk|security operations|soc|hr|payroll|"
        r"automation engineer|factory|produktion|analyst|analytiker|embedded|"
        r"fpga|devops|cloud|data engineer|mobile|ios|android|\.net|c#|php|vue)\b",
        normalized,
        re.I,
    )
    return bool(negative and not positive)


def _verama_location_precheck(record: AssignmentRecord) -> bool:
    fields = _normalize_for_checks(f"{record.work_mode} {record.location}")
    if "100% remote" in fields or "distans" in fields or "fjärrarbete" in fields:
        return True
    if any(
        place in fields
        for place in (
            "stockholm",
            "solna",
            "sundbyberg",
            "kista",
            "bromma",
            "sollentuna",
            "danderyd",
            "täby",
            "järfälla",
            "nacka",
            "huddinge",
            "lidingö",
            "älvsjö",
            "årsta",
            "stockholms län",
            "botkyrka",
            "upplands väsby",
            "södertälje",
            "haninge",
            "tyresö",
            "vällingby",
            "farsta",
        )
    ):
        return True
    frontend_title = re.search(r"\b(frontend|front-end|react|angular|wordpress)\b", record.title, re.I)
    return bool(frontend_title and ("göteborg" in fields or "gothenburg" in fields))


def _verama_should_fetch_detail(
    record: AssignmentRecord,
    *,
    seen_ids: set[str],
    scan_date: date,
) -> bool:
    if record.source_id in seen_ids:
        return False
    last_application = _parse_date(record.last_application_date)
    if last_application is not None and last_application < scan_date:
        return False
    if _verama_title_clearly_outside(record.title):
        return False
    if not _verama_location_precheck(record) and not _verama_is_accessibility_title(record.title):
        return False
    return True


def _first_nested_value(data: Any, keys: set[str]) -> Any:
    if isinstance(data, dict):
        for key, value in data.items():
            if key.lower() in keys and value not in (None, "", []):
                return value
        for value in data.values():
            found = _first_nested_value(value, keys)
            if found not in (None, "", []):
                return found
    elif isinstance(data, list):
        for value in data:
            found = _first_nested_value(value, keys)
            if found not in (None, "", []):
                return found
    return None


def _verama_skill_list(detail: dict[str, Any]) -> list[dict[str, Any]]:
    value = _first_nested_value(
        detail,
        {"skills", "competences", "competencies", "requiredskills", "requirements"},
    )
    skills: list[dict[str, Any]] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                name = item.get("name") or item.get("title") or item.get("label")
            else:
                name = str(item)
            if name:
                skills.append({"name": str(name)})
    return skills


def _verama_text_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return _WHITESPACE_RE.sub(" ", _TAG_RE.sub(" ", html.unescape(value))).strip()
    return str(value).strip()


def _verama_apply_detail(record: AssignmentRecord, detail: dict[str, Any]) -> None:
    description = _first_nested_value(
        detail,
        {"description", "jobdescription", "assignmentdescription", "requestdescription"},
    )
    summary = _first_nested_value(detail, {"descriptionsummary", "summary", "shortdescription"})
    last_application = _first_nested_value(
        detail,
        {
            "lastdayofapplications",
            "lastapplicationdate",
            "applicationdeadline",
            "deadline",
            "offerdeadline",
            "responsedeadline",
        },
    )
    start_date = _first_nested_value(detail, {"firstdayofassignment", "startdate", "assignmentstartdate"})
    end_date = _first_nested_value(detail, {"lastdayofassignment", "enddate", "assignmentenddate"})
    duration = _first_nested_value(detail, {"duration", "extent", "scope"})
    work_mode = _first_nested_value(detail, {"workmode", "worklocation", "remote", "remoteness"})

    if description:
        record.description = _verama_text_value(description)
    if summary:
        record.description_summary = _verama_text_value(summary)
    elif record.description and not record.description_summary:
        record.description_summary = record.description[:300]
    if last_application and not record.last_application_date:
        record.last_application_date = _verama_text_value(last_application)
    if start_date:
        record.start_date = _verama_text_value(start_date)
    if end_date:
        record.end_date = _verama_text_value(end_date)
    if duration:
        record.duration = _verama_text_value(duration)
    if work_mode and not record.work_mode:
        record.work_mode = _verama_text_value(work_mode)
    skills = _verama_skill_list(detail)
    if skills:
        record.skills = skills


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
    scan_date = scan_date or date.today()

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
                    source_id = str(row["id"])
                    record = AssignmentRecord(
                        platform=platform,
                        source_id=source_id,
                        listing_id=f"v{source_id}",
                        title=row.get("title") or "",
                        description_summary=row.get("systemId") or "",
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
                        detail_payload: dict[str, Any] | None = None
                        for endpoint in (
                            f"{VERAMA_BASE}/api/job-requests/v2/{source_id}",
                            f"{VERAMA_BASE}/api/job-requests/{source_id}",
                        ):
                            detail_response = api.get(
                                endpoint,
                                headers={
                                    **auth_headers,
                                    "accept": "application/json, text/plain, */*",
                                    "referer": f"{VERAMA_BASE}/app/job-requests",
                                },
                                timeout=60000,
                            )
                            if detail_response.status == 200:
                                detail_payload = detail_response.json()
                                break
                            if detail_response.status in {401, 403}:
                                raise RuntimeError(
                                    f"Verama detail API returned {detail_response.status}"
                                )
                        if isinstance(detail_payload, dict):
                            _verama_apply_detail(record, detail_payload)
                    records.append(record)

                if payload.get("last") or not rows:
                    break
                page_num += 1

            browser.close()

        return records, PlatformScanResult(platform=platform, status="ok", count=len(records))
    except PlaywrightTimeoutError as exc:
        return records, PlatformScanResult(
            platform=platform,
            status="error",
            count=len(records),
            message=f"Verama login or listing timed out: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return records, PlatformScanResult(
            platform=platform,
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
    platform = "chaspartnernetwork.se"
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
                    platform=platform,
                    source_id=source_id,
                    listing_id=f"c{source_id}",
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
            platform=platform, status="ok", count=len(records)
        )
    except Exception as exc:  # noqa: BLE001
        return records, PlatformScanResult(
            platform=platform,
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
    platform = "magnit-source.magnitglobal.com"
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
                    platform=platform,
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
            platform=platform, status="ok", count=len(records)
        )
    except Exception as exc:  # noqa: BLE001
        records = list(by_key.values())
        return records, PlatformScanResult(
            platform=platform,
            status="error",
            count=len(records),
            message=str(exc),
        )


PlatformScanner = Callable[..., tuple[list[AssignmentRecord], PlatformScanResult]]

PLATFORM_SCANNERS: dict[str, PlatformScanner] = {
    "verama.com": scan_verama,
    "chaspartnernetwork.se": scan_chaspartnernetwork,
    "allakonsultuppdrag.se": scan_allakonsultuppdrag,
    "magnit-source.magnitglobal.com": scan_magnitsource,
}

DEFAULT_PLATFORMS = list(ACTIVE_SOURCE_ORDER)


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
                headless=headless,
                seen_ids=seen_ids_by_source.get(platform_id, set()),
                scan_date=scan_date,
            )
        else:
            rows, result = scanner(max_pages=max_pages)

        assignments.extend(rows)
        results.append(result)

    return assignments, results
