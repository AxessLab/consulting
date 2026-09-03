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
CINODE_MARKET_BASE = "https://cinode.com"
CINODE_MARKET_COUNTRIES = ["sweden", "sverige"]
PLATFORM_PREFIXES = {
    "allakonsultuppdrag.se": "a",
    "verama.com": "v",
    "chaspartnernetwork.se": "c",
    "magnit-source.magnitglobal.com": "m",
    "cinode.com/market": "n",
}
_CINODE_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_CINODE_DATE_RE = re.compile(r"(\d{1,2})\s+([A-Za-z]{3}),\s*(\d{4})")
_CINODE_RANGE_RE = re.compile(
    r"(\d{1,2}\s+[A-Za-z]{3},\s*\d{4})\s+to\s+(\d{1,2}\s+[A-Za-z]{3},\s*\d{4})",
    re.I,
)
_CINODE_CARD_SPLIT_RE = re.compile(
    r'<div class="requests-list__card"\s+data-href="/market/requests/(\d+)"',
    re.I,
)
_CINODE_CSRF_RE = re.compile(
    r'name="__CsrfToken"[^>]*value="([^"]+)"|'
    r'value="([^"]+)"[^>]*name="__CsrfToken"',
    re.I,
)
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
                    listing_id=f"{PLATFORM_PREFIXES[platform]}{source_id}",
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


def _parse_date_prefix(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.fromisoformat(str(value)[:10])
        except ValueError:
            return None


def _verama_work_mode(remoteness: Any, *extra_fields: str) -> str:
    explicit = " ".join(extra_fields)
    explicit_norm = explicit.lower()
    if "distans" in explicit_norm or "fjärr" in explicit_norm or "fjarr" in explicit_norm:
        return "Remote"
    if remoteness is None:
        return explicit.strip()
    try:
        percent = int(remoteness)
    except (TypeError, ValueError):
        return explicit.strip()
    if percent >= 100:
        return "100% remote"
    if percent > 0:
        return f"Hybrid ({percent}% remote)"
    return "On-site"


def _verama_title_plausible(title: str) -> bool:
    title_norm = title.lower()
    outside = re.search(
        r"\b(sap|nätverk|network|security operations|soc|hr|payroll|lön|"
        r"automation engineer|factory|automotive|embedded|testare|tester)\b",
        title_norm,
        re.I,
    )
    target = re.search(
        r"\b(accessibility|tillgänglig|tillganglig|wcag|frontend|front-end|"
        r"react|next\.?js|angular|wordpress|java|spring|fullstack|full-stack|"
        r"ux|ui|designer|produktdesigner|product designer|scrum|projektledare|"
        r"project manager|project lead|projektkoordinator|developer|utvecklare|"
        r"konsult|consultant)\b",
        title_norm,
        re.I,
    )
    return bool(target) and not bool(outside)


def _verama_location_precheck(location: str, work_mode: str, title: str) -> bool:
    fields = f"{location} {work_mode}".lower()
    if "100% remote" in fields or "distans" in fields or "fjärr" in fields or "fjarr" in fields:
        return True
    near_stockholm = re.search(
        r"\b(stockholm|solna|sundbyberg|kista|bromma|sollentuna|danderyd|täby|taby|"
        r"järfälla|jarfalla|nacka|huddinge|lidingö|lidingo|älvsjö|alvsjo|årsta|arsta|"
        r"botkyrka|upplands väsby|upplands vasby|södertälje|sodertalje|haninge|"
        r"tyresö|tyreso|vällingby|vallingby|farsta)\b",
        fields,
        re.I,
    )
    if near_stockholm:
        return True
    if re.search(r"\b(göteborg|goteborg|gothenburg)\b", fields, re.I) and re.search(
        r"\b(frontend|front-end|react|angular|wordpress)\b",
        title,
        re.I,
    ):
        return True
    return bool(re.search(r"\b(accessibility|tillgänglig|tillganglig|wcag)\b", title, re.I))


def _verama_summary(description: str) -> str:
    text = _WHITESPACE_RE.sub(" ", description or "").strip()
    return text[:300]


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

    seen_ids = seen_ids or set()
    records: list[AssignmentRecord] = []
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

            def detail_for(source_id: str) -> dict[str, Any]:
                headers = {
                    **auth_headers,
                    "accept": "application/json, text/plain, */*",
                    "referer": f"{VERAMA_BASE}/app/job-requests/{source_id}",
                }
                detail_response = api.get(
                    f"{VERAMA_BASE}/api/job-requests/v2/{source_id}",
                    headers=headers,
                    timeout=60000,
                )
                if detail_response.status in {401, 403}:
                    raise RuntimeError(
                        f"Verama detail API returned {detail_response.status} for {source_id}"
                    )
                if detail_response.status != 200:
                    detail_response = api.get(
                        f"{VERAMA_BASE}/api/job-requests/{source_id}",
                        headers=headers,
                        timeout=60000,
                    )
                if detail_response.status != 200:
                    raise RuntimeError(
                        f"Verama detail API returned {detail_response.status} for {source_id}"
                    )
                return detail_response.json() or {}

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
                    remoteness = row.get("remoteness")
                    title = row.get("title") or ""
                    location = _verama_location(row.get("city"), row.get("countryCode"))
                    work_mode = _verama_work_mode(remoteness, row.get("workLocation") or "")
                    last_application_date = row.get("lastDayOfApplications")
                    should_detail = source_id not in seen_ids
                    last_app_dt = _parse_date_prefix(last_application_date)
                    if scan_date is not None and last_app_dt is not None:
                        should_detail = should_detail and last_app_dt.date() >= scan_date
                    if should_detail:
                        should_detail = _verama_title_plausible(title) and _verama_location_precheck(
                            location,
                            work_mode,
                            title,
                        )
                    if not last_application_date:
                        should_detail = True

                    description = ""
                    description_summary = ""
                    start_date = None
                    end_date = None
                    duration = ""
                    skills: list[dict[str, Any]] = []
                    if should_detail:
                        try:
                            detail = detail_for(source_id)
                            description = (
                                detail.get("description")
                                or detail.get("jobDescription")
                                or detail.get("assignmentDescription")
                                or ""
                            )
                            description_summary = (
                                detail.get("descriptionSummary")
                                or detail.get("summary")
                                or _verama_summary(description)
                            )
                            last_application_date = (
                                last_application_date
                                or detail.get("lastDayOfApplications")
                                or detail.get("lastApplicationDate")
                                or detail.get("applicationDeadline")
                                or detail.get("deadline")
                            )
                            start_date = (
                                detail.get("firstDayOfAssignment")
                                or detail.get("startDate")
                                or detail.get("assignmentStartDate")
                            )
                            end_date = (
                                detail.get("lastDayOfAssignment")
                                or detail.get("endDate")
                                or detail.get("assignmentEndDate")
                            )
                            duration = detail.get("duration") or detail.get("assignmentPeriod") or ""
                            detail_work_mode = _verama_work_mode(
                                remoteness,
                                str(detail.get("workLocation") or ""),
                                str(detail.get("workMode") or ""),
                                str(detail.get("remotenessText") or ""),
                            )
                            if detail_work_mode:
                                work_mode = detail_work_mode
                            detail_skills = (
                                detail.get("skills")
                                or detail.get("competences")
                                or detail.get("requirements")
                                or []
                            )
                            if isinstance(detail_skills, list):
                                for item in detail_skills:
                                    if isinstance(item, dict):
                                        name = item.get("name") or item.get("title") or item.get("label")
                                        if name:
                                            skills.append({"name": str(name)})
                                    elif item:
                                        skills.append({"name": str(item)})
                        except Exception:
                            # Detail is a matching aid; keep the list row visible for memory.
                            pass
                    records.append(
                        AssignmentRecord(
                            platform=platform,
                            source_id=source_id,
                            listing_id=f"v{source_id}",
                            title=title,
                            description=description,
                            description_summary=description_summary,
                            published_date=row.get("firstDayOfApplications"),
                            last_application_date=last_application_date,
                            start_date=start_date,
                            end_date=end_date,
                            duration=duration,
                            work_mode=work_mode,
                            location=location,
                            source_url=f"{VERAMA_BASE}/app/job-requests/{source_id}",
                            broker=row.get("originServiceName") or "",
                            skills=skills,
                        )
                    )

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


def _cinode_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": SCAN_USER_AGENT,
            "Accept": "text/html,application/json",
        }
    )
    return session


def _cinode_strip_html(value: str) -> str:
    text = _TAG_RE.sub(" ", html.unescape(value or ""))
    return _WHITESPACE_RE.sub(" ", text).strip()


def _cinode_parse_date(value: str | None) -> str | None:
    if not value:
        return None
    match = _CINODE_DATE_RE.search(value)
    if not match:
        return None
    month = _CINODE_MONTHS.get(match.group(2).lower())
    if not month:
        return None
    return f"{match.group(3)}-{month:02d}-{int(match.group(1)):02d}"


def _cinode_parse_range(value: str) -> tuple[str | None, str | None]:
    match = _CINODE_RANGE_RE.search(value or "")
    if match:
        return _cinode_parse_date(match.group(1)), _cinode_parse_date(match.group(2))
    from_match = re.search(
        r"From\s+(\d{1,2}\s+[A-Za-z]{3},\s*\d{4})",
        value or "",
        re.I,
    )
    if from_match:
        return _cinode_parse_date(from_match.group(1)), None
    return None, None


def _cinode_csrf(html_text: str) -> str:
    match = _CINODE_CSRF_RE.search(html_text)
    if not match:
        raise RuntimeError("Could not find Cinode Market CSRF token")
    return match.group(1) or match.group(2)


def _cinode_next_cursor(response: requests.Response, html_text: str) -> str | None:
    header = response.headers.get("X-Next-Cursor") or response.headers.get(
        "x-next-cursor"
    )
    if header:
        return header
    match = re.search(r'data-next-cursor="([^"]+)"', html_text)
    return match.group(1) if match else None


def _cinode_work_mode(html_chunk: str) -> str:
    remote = re.search(r"\((\d+%\s*remote)\)", html_chunk, re.I)
    if re.search(r"badge--hybrid", html_chunk, re.I):
        return f"Hybrid ({remote.group(1)})" if remote else "Hybrid"
    if re.search(r"badge--remote", html_chunk, re.I):
        return "Remote"
    return remote.group(1) if remote else ""


def _cinode_parse_cards(html_text: str) -> list[dict[str, str]]:
    parts = _CINODE_CARD_SPLIT_RE.split(html_text)
    cards: list[dict[str, str]] = []
    for index in range(1, len(parts), 2):
        source_id = parts[index]
        body = parts[index + 1] if index + 1 < len(parts) else ""
        title_match = re.search(
            r'e2e-market-request-link[^>]*>\s*(.*?)\s*</a>',
            body,
            re.I | re.S,
        )
        company_match = re.search(
            r'class="requests-list__card-company[^"]*"[^>]*>\s*(.*?)\s*</(?:a|span|div)>',
            body,
            re.I | re.S,
        )
        if not company_match:
            company_match = re.search(
                r'/market/requests/company/[^"]+[^>]*>(.*?)</a>',
                body,
                re.I | re.S,
            )
        city_match = re.search(
            r'/market/requests/city/[^"]+"[^>]*title="([^"]+)"',
            body,
            re.I,
        )
        announced_match = re.search(r"Announced\s+([^<]+)", body, re.I)
        deadline_match = re.search(r"Deadline\s+([^<]+)", body, re.I)
        range_text = ""
        cal_match = re.search(
            r'href="#icon-calendar"[\s\S]*?<p>(.*?)</p>',
            body,
            re.I,
        )
        if cal_match:
            range_text = _cinode_strip_html(cal_match.group(1))
        start_date, end_date = _cinode_parse_range(range_text)
        cards.append(
            {
                "source_id": source_id,
                "title": _cinode_strip_html(title_match.group(1) if title_match else ""),
                "company": _cinode_strip_html(
                    company_match.group(1) if company_match else ""
                ),
                "location": html.unescape(city_match.group(1)).strip()
                if city_match
                else "",
                "work_mode": _cinode_work_mode(body),
                "published_date": _cinode_parse_date(
                    _cinode_strip_html(announced_match.group(1))
                    if announced_match
                    else ""
                )
                or "",
                "last_application_date": _cinode_parse_date(
                    _cinode_strip_html(deadline_match.group(1))
                    if deadline_match
                    else ""
                )
                or "",
                "start_date": start_date or "",
                "end_date": end_date or "",
                "duration": range_text,
            }
        )
    return cards


def _cinode_parse_detail(html_text: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    desc_match = re.search(
        r'class="wysiwyg-output"[^>]*>(.*?)</div>\s*</div>',
        html_text,
        re.I | re.S,
    )
    if desc_match:
        parsed["description"] = _cinode_strip_html(desc_match.group(1))

    for label_raw, value_html in re.findall(
        r'<p class="details__item--label">\s*(.*?)\s*</p>\s*<p>(.*?)</p>',
        html_text,
        re.I | re.S,
    ):
        label = _cinode_strip_html(label_raw).rstrip(":").lower()
        value = _cinode_strip_html(value_html)
        if not value:
            continue
        if label.startswith("announced"):
            parsed["published_date"] = _cinode_parse_date(value)
        elif label.startswith("company"):
            parsed["company"] = value
        elif label.startswith("date"):
            start_date, end_date = _cinode_parse_range(value)
            parsed["start_date"] = start_date
            parsed["end_date"] = end_date
            parsed["date_range"] = value
        elif label.startswith("location"):
            parsed["location"] = value
        elif label.startswith("extent"):
            parsed["extent"] = value
        elif "remotely" in label:
            parsed["remote"] = value

    skills: list[dict[str, Any]] = []
    for raw in re.findall(
        r'class="details__skill"[^>]*>\s*<a[^>]*>(.*?)</a>',
        html_text,
        re.I | re.S,
    ):
        name = _cinode_strip_html(raw)
        if name:
            skills.append({"name": name})
    parsed["skills"] = skills
    return parsed


def scan_cinode_market(
    *,
    page_size: int = 100,
    max_pages: int | None = None,
) -> tuple[list[AssignmentRecord], PlatformScanResult]:
    """Scan public Cinode Market assignments in Sweden (country keys sweden + sverige)."""
    del page_size  # Market uses cursor pages, not a page size.
    platform = "cinode.com/market"
    session = _cinode_session()
    by_key: dict[str, AssignmentRecord] = {}

    try:
        landing = session.get(f"{CINODE_MARKET_BASE}/market", timeout=60)
        landing.raise_for_status()
        csrf = _cinode_csrf(landing.text)
        filter_url = f"{CINODE_MARKET_BASE}/market/requests/filters"
        payload = {
            "keywords": {"values": []},
            "countries": {"values": list(CINODE_MARKET_COUNTRIES)},
            "cities": {"values": []},
            "companies": {"values": []},
            "endCustomerAssignments": None,
            "remoteWork": {"values": []},
        }

        page = 1
        response = session.post(
            filter_url,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
                "X-Csrf-Token": csrf,
                "Referer": f"{CINODE_MARKET_BASE}/market",
                "Origin": CINODE_MARKET_BASE,
            },
            timeout=60,
        )
        response.raise_for_status()
        html_text = response.text
        cursor = _cinode_next_cursor(response, html_text)

        while True:
            for card in _cinode_parse_cards(html_text):
                source_id = card["source_id"]
                source_url = f"{CINODE_MARKET_BASE}/market/requests/{source_id}"
                title = card["title"]
                company = card["company"]
                location = card["location"]
                work_mode = card["work_mode"]
                published_date = card["published_date"] or None
                last_application_date = card["last_application_date"] or None
                start_date = card["start_date"] or None
                end_date = card["end_date"] or None
                duration = card["duration"]
                description = ""
                description_summary = f"Client: {company}" if company else ""
                skills: list[dict[str, Any]] = []

                try:
                    detail_resp = session.get(source_url, timeout=60)
                    detail_resp.raise_for_status()
                    detail = _cinode_parse_detail(detail_resp.text)
                    if detail.get("description"):
                        description = detail["description"]
                    if detail.get("company"):
                        company = detail["company"]
                        description_summary = f"Client: {company}"
                    if detail.get("location"):
                        location = detail["location"]
                    if detail.get("published_date"):
                        published_date = detail["published_date"]
                    if detail.get("start_date"):
                        start_date = detail["start_date"]
                    if detail.get("end_date"):
                        end_date = detail["end_date"]
                    if detail.get("date_range") and not duration:
                        duration = detail["date_range"]
                    if detail.get("extent"):
                        duration = (
                            f"{detail['extent']}"
                            if not duration
                            else f"{duration}; {detail['extent']}"
                        )
                    if detail.get("remote") and not work_mode:
                        work_mode = detail["remote"]
                    skills = detail.get("skills") or []
                    if description_summary and description:
                        description = f"{description_summary}\n\n{description}"
                    elif description_summary:
                        description = description_summary
                    skills_text = ", ".join(
                        str(item.get("name") or "") for item in skills if item.get("name")
                    )
                    if skills_text:
                        description = (
                            f"{description}\n\nSkills: {skills_text}"
                            if description
                            else f"Skills: {skills_text}"
                        )
                except Exception:  # noqa: BLE001
                    if description_summary:
                        description = description_summary

                record = AssignmentRecord(
                    platform=platform,
                    source_id=source_id,
                    listing_id=f"n{source_id}",
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
                    broker=company or "Cinode Market",
                    skills=skills,
                )
                by_key[record.dedupe_key] = record

            if max_pages is not None and page >= max_pages:
                break
            if not cursor:
                break
            page += 1
            more = session.get(
                f"{CINODE_MARKET_BASE}/market",
                params={"nextCursor": cursor},
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": f"{CINODE_MARKET_BASE}/market",
                },
                timeout=60,
            )
            more.raise_for_status()
            html_text = more.text
            cursor = _cinode_next_cursor(more, html_text)

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
    "allakonsultuppdrag.se": scan_allakonsultuppdrag,
    "verama.com": scan_verama,
    "chaspartnernetwork.se": scan_chaspartnernetwork,
    "magnit-source.magnitglobal.com": scan_magnitsource,
    "cinode.com/market": scan_cinode_market,
}

DEFAULT_PLATFORMS = list(PLATFORM_SCANNERS.keys())


def scan_platforms(
    platform_ids: list[str],
    *,
    max_pages: int | None = None,
    headless: bool = True,
    seen_keys: set[str] | None = None,
    scan_date: date | None = None,
) -> tuple[list[AssignmentRecord], list[PlatformScanResult]]:
    assignments: list[AssignmentRecord] = []
    results: list[PlatformScanResult] = []
    verama_email = os.environ.get("VERAMA_EMAIL")
    verama_password = os.environ.get("VERAMA_PASSWORD")
    seen_keys = seen_keys or set()

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
                seen_ids={
                    key.split(":", 1)[1]
                    for key in seen_keys
                    if key.startswith(f"{platform_id}:")
                },
                scan_date=scan_date,
            )
        else:
            rows, result = scanner(max_pages=max_pages)

        assignments.extend(rows)
        results.append(result)

    return assignments, results
