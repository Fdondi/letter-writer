"""Hostname-matched parsers for captured job pages.

Templates correspond to saved examples in ``extensions/job-capture/examples/``.
When the capture URL's host matches an example filename (``jobs.ch.html`` →
``jobs.ch``, ``jobs.ch_inner.html`` → detail URL on ``jobs.ch``,
``jobs.ch_company.html`` → company profile on ``jobs.ch``,
``LinkedIn.html`` → ``linkedin.com``), parse the posting from the DOM / JSON-LD
instead of dumping the whole tab to the model.

On jobs.ch vacancy pages, a company-profile CTA (``Voir le profil de l'entreprise``
and DE/EN equivalents) is followed after parse so the main
``[data-cy="company-description"]`` text can fill About the Company. Fetch
failures leave that field empty — do not invent copy.

If selectors miss a field, leave it empty. Do not invent values or fall back to
search-result chrome (for example jobs.ch ``h1`` is the search query, and
jobs.ch search JSON-LD may describe a different vacancy than the selected card).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

# Example filename stem → hostname suffixes. LinkedIn.html is not a domain.
# jobs.ch vs jobs.ch_inner is chosen in _match_jobs_ch_template.
_TEMPLATE_HOSTS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("swissdevjobs.ch", ("swissdevjobs.ch",)),
    ("LinkedIn", ("linkedin.com",)),
)

_JOBS_CH_ORIGIN = "https://www.jobs.ch"
_JOBS_CH_DETAIL_PATH_RE = re.compile(
    r"/(offres-emplois|stellenangebote|vacancies)/detail/",
    re.IGNORECASE,
)
_JOBS_CH_COMPANY_KINDS = frozenset({"entreprises", "unternehmen", "companies"})
_JOBS_CH_PROFILE_CTA_HINTS = (
    "profil de l",
    "unternehmensprofil",
    "firmenprofil",
    "view company profile",
    "see company profile",
)
_JOBS_CH_COMPANY_FETCH_TIMEOUT_S = 8.0
_JOBS_CH_FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; LetterWriterJobCapture/1.0)",
    "Accept": "text/html,application/xhtml+xml",
}

_LINKEDIN_REMOVE = (
    "nav",
    "header",
    '[id^="JobDetailsSimilarJobsSlot_"]',
    '[id^="JobDetailsPeopleWhoCanHelpSlot_"]',
    '[id^="JobDetails_Premium"]',
    '[id^="JobDetails_ResumeReview_"]',
    '[id^="JobDetails_AboutTheCompany_"]',
)

_COUNTRY_HINT = re.compile(
    r"\b(Switzerland|Schweiz|Suisse|Svizzera|Germany|Deutschland|"
    r"Austria|Österreich|France|Italy|Italia)\b",
    re.IGNORECASE,
)


def empty_parse(template: Optional[str] = None) -> Dict[str, Any]:
    return {
        "template": template,
        "job_text": "",
        "job_title": "",
        "company_name": "",
        "location": "",
        "language": "",
        "salary": "",
        "point_of_contact": None,
        "source_url": "",
        "company_profile_url": "",
        "additional_company_info": "",
    }


def match_page_template(source_url: str, html: str = "") -> Optional[str]:
    """Return the example-filename stem if ``source_url`` matches a template host."""
    host = (urlparse(source_url or "").hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return None
    if host == "jobs.ch" or host.endswith(".jobs.ch"):
        return _match_jobs_ch_template(source_url, html)
    for name, domains in _TEMPLATE_HOSTS:
        for domain in domains:
            if host == domain or host.endswith("." + domain):
                return name
    return None


def _match_jobs_ch_template(source_url: str, html: str) -> str:
    """SERP, clicked-through detail, or company-profile page on jobs.ch."""
    if html:
        soup = _soup(html)
        if soup.select_one('[data-cy="vacancy-serp-item-active"]'):
            return "jobs.ch"
        if soup.select_one('[data-cy="company-description"]') and not soup.select_one(
            '[data-cy="vacancy-layout-standard"]'
        ):
            return "jobs.ch_company"
        if soup.select_one('[data-cy="vacancy-description"]') or _JOBS_CH_DETAIL_PATH_RE.search(
            source_url or ""
        ):
            return "jobs.ch_inner"
    if _JOBS_CH_DETAIL_PATH_RE.search(source_url or ""):
        return "jobs.ch_inner"
    if _is_jobs_ch_company_profile_href(source_url or ""):
        return "jobs.ch_company"
    return "jobs.ch"


def extract_from_captured_page(html: str, source_url: str = "") -> Dict[str, Any]:
    """Parse a captured page when a hostname template matches; otherwise empty fields."""
    name = match_page_template(source_url, html)
    if not name:
        return empty_parse()
    parser = _PARSERS.get(name)
    if parser is None:
        return empty_parse(name)
    try:
        parsed = parser(str(html or ""), source_url)
    except Exception:
        logger.exception("page template %s failed for %s", name, source_url)
        return empty_parse(name)
    parsed["template"] = name
    return parsed


def html_fragment_to_text(html: str) -> str:
    """Visible text from an HTML fragment; keeps native spelling (umlauts)."""
    text = str(html or "").strip()
    if not text:
        return ""
    if "<" not in text:
        return _normalize_ws(text)
    soup = BeautifulSoup(text, "html.parser")
    return _visible_text(soup)


def parse_json_ld_job_posting(html: str) -> Dict[str, Any]:
    """First JSON-LD JobPosting on the page, or empty fields."""
    soup = BeautifulSoup(str(html or ""), "html.parser")
    return _job_posting_from_soup(soup)


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(str(html or ""), "html.parser")


def _visible_text(node: Any) -> str:
    if node is None:
        return ""
    for tag in node.find_all(["script", "style", "svg", "noscript"]) if hasattr(node, "find_all") else []:
        tag.decompose()
    return _normalize_ws(node.get_text("\n", strip=True))


def _normalize_ws(text: str) -> str:
    text = (
        str(text or "")
        .replace("\u00a0", " ")
        .replace("\u202f", " ")
        .replace("\u2007", " ")
        .replace("\u2009", " ")
    )
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _clean(val: Any) -> str:
    if val is None:
        return ""
    return str(val).strip()


def _first_text(root: Any, selectors: Iterable[str]) -> str:
    if root is None:
        return ""
    for sel in selectors:
        el = root.select_one(sel)
        if el is None:
            continue
        text = _visible_text(el)
        if text:
            return text
    return ""


def _poc_from_contact(contact: Any) -> Optional[Dict[str, str]]:
    if not isinstance(contact, dict):
        return None
    poc = {
        "name": _clean(contact.get("name")),
        "role": _clean(
            contact.get("role") or contact.get("contactType") or contact.get("jobTitle")
        ),
        "contact_details": _clean(
            contact.get("contact_details")
            or contact.get("email")
            or contact.get("telephone")
            or contact.get("url")
        ),
        "notes": _clean(contact.get("notes")),
    }
    if not poc["name"] and not poc["contact_details"]:
        return None
    return poc


def _walk_json_ld(data: Any) -> Iterable[dict]:
    if isinstance(data, list):
        for item in data:
            yield from _walk_json_ld(item)
        return
    if not isinstance(data, dict):
        return
    yield data
    graph = data.get("@graph")
    if graph is not None:
        yield from _walk_json_ld(graph)


def _is_job_posting(item: dict) -> bool:
    t = item.get("@type")
    if t == "JobPosting":
        return True
    if isinstance(t, list) and "JobPosting" in t:
        return True
    return False


def _load_json_ld_scripts(soup: BeautifulSoup) -> List[Any]:
    out: List[Any] = []
    for script in soup.find_all("script"):
        t = (script.get("type") or "").lower()
        if "ld+json" not in t:
            continue
        raw = (script.string or script.get_text() or "").strip()
        if not raw:
            continue
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                try:
                    out.append(json.loads(raw[start : end + 1]))
                except json.JSONDecodeError:
                    continue
    return out


def _job_posting_from_soup(soup: BeautifulSoup) -> Dict[str, Any]:
    parsed = empty_parse()
    for blob in _load_json_ld_scripts(soup):
        for item in _walk_json_ld(blob):
            if not _is_job_posting(item):
                continue
            parsed.update(_fields_from_job_posting(item))
            return parsed
    return parsed


def _org_name(org: Any) -> str:
    if isinstance(org, dict):
        return _clean(org.get("name"))
    return _clean(org)


def _format_address(addr: Any) -> str:
    if isinstance(addr, list) and addr:
        addr = addr[0]
    if not isinstance(addr, dict):
        return _clean(addr)
    parts = [
        _clean(addr.get("streetAddress")),
        " ".join(
            p
            for p in (_clean(addr.get("postalCode")), _clean(addr.get("addressLocality") or addr.get("addressRegion")))
            if p
        ),
        _clean(addr.get("addressCountry")),
    ]
    return ", ".join(p for p in parts if p)


def _format_job_location(loc: Any) -> str:
    if isinstance(loc, list) and loc:
        loc = loc[0]
    if isinstance(loc, str):
        return _clean(loc)
    if not isinstance(loc, dict):
        return ""
    named = _clean(loc.get("name"))
    addr = _format_address(loc.get("address"))
    return addr or named


def _format_salary(amount: Any) -> str:
    if not isinstance(amount, dict):
        return _clean(amount)
    currency = _clean(amount.get("currency"))
    value = amount.get("value")
    if isinstance(value, dict):
        vmin = value.get("minValue")
        vmax = value.get("maxValue")
        single = value.get("value")
        unit = _clean(value.get("unitText"))
        if vmin is not None and vmax is not None:
            body = f"{vmin}–{vmax}"
        elif single is not None and str(single).strip():
            body = str(single).strip()
        else:
            body = ""
        if not body:
            return ""
        return " ".join(p for p in (currency, body, unit) if p)
    if value is not None and str(value).strip():
        return " ".join(p for p in (currency, str(value).strip()) if p)
    return ""


def _fields_from_job_posting(item: dict) -> Dict[str, Any]:
    desc = item.get("description")
    job_text = html_fragment_to_text(desc) if isinstance(desc, str) else ""
    return {
        "job_text": job_text,
        "job_title": _clean(item.get("title")),
        "company_name": _org_name(item.get("hiringOrganization")),
        "location": _format_job_location(item.get("jobLocation")),
        "language": "",
        "salary": _format_salary(item.get("baseSalary")),
        "point_of_contact": _poc_from_contact(item.get("applicationContact")),
        "source_url": _clean(item.get("url")),
    }


def _fill_missing(target: Dict[str, Any], source: Dict[str, Any], keys: Iterable[str]) -> None:
    for key in keys:
        if key == "point_of_contact":
            if not target.get("point_of_contact") and source.get("point_of_contact"):
                target["point_of_contact"] = source["point_of_contact"]
            continue
        if not _clean(target.get(key)) and _clean(source.get(key)):
            target[key] = source[key]


def _jobs_ch_selected_vacancy_link(soup: BeautifulSoup) -> Optional[Tag]:
    """Selected SERP card: cursor_pointer vacancy-link wrapping vacancy-serp-item-active."""
    link = soup.select_one(
        'a.cursor_pointer[id^="vacancy-link-"]:has([data-cy="vacancy-serp-item-active"])'
    )
    if isinstance(link, Tag):
        return link
    active = soup.select_one('[data-cy="vacancy-serp-item-active"]')
    if active is None:
        return None
    parent = active.find_parent("a", id=re.compile(r"^vacancy-link-"))
    return parent if isinstance(parent, Tag) else None


def _jobs_ch_job_text(soup: BeautifulSoup) -> str:
    desc = soup.select_one('[data-cy="vacancy-description"]')
    if desc is None:
        return ""
    for el in desc.select('[data-cy="jobfit-teaser-cta"], [data-cy="vacancy-mood"]'):
        el.decompose()
    return _visible_text(desc)


def _jobs_ch_location(layout: Any) -> str:
    street = _first_text(layout, ('[data-cy="info-location-link"]',))
    if street:
        return street
    logo = layout.select_one('[data-cy="vacancy-logo"]') if hasattr(layout, "select_one") else None
    if logo is not None:
        for p in logo.select("p.textStyle_body2"):
            text = _visible_text(p)
            if text:
                return text
    return ""


def _jobs_ch_salary(root: Any) -> str:
    """Range from the vacancy info bar, not the salary-teaser CTA."""
    estimate = root.select_one('[data-cy="info-salary_estimate"]') if hasattr(root, "select_one") else None
    if estimate is None:
        return ""
    caption = estimate.select_one("span.textStyle_caption1")
    if caption is not None:
        text = _visible_text(caption)
        if text:
            return text
    raw = _visible_text(estimate)
    if not raw:
        return ""
    cut = re.split(r"\s+Estimation\s+", raw, maxsplit=1, flags=re.IGNORECASE)[0]
    return cut.strip()


def _jobs_ch_vacancy_fields(soup: BeautifulSoup) -> Dict[str, Any]:
    """Shared vacancy panel on jobs.ch SERP preview and detail page."""
    parsed = empty_parse()
    layout = soup.select_one('[data-cy="vacancy-layout-standard"]') or soup
    parsed["job_title"] = _first_text(layout, ('[data-cy="vacancy-title"]',))
    parsed["company_name"] = _first_text(
        layout,
        (
            '[data-cy="vacancy-company"] [data-cy="company-link"]',
            '[data-cy="company-link"]',
        ),
    )
    parsed["location"] = _jobs_ch_location(layout)
    parsed["salary"] = _jobs_ch_salary(layout)
    parsed["job_text"] = _jobs_ch_job_text(soup)
    parsed["company_profile_url"] = _jobs_ch_company_profile_url(soup)
    return parsed


def _absolute_jobs_ch_url(href: str) -> str:
    """Turn a jobs.ch path or host variant into https://www.jobs.ch/..."""
    raw = _clean(href)
    if not raw:
        return ""
    if raw.startswith("//"):
        raw = "https:" + raw
    joined = urljoin(_JOBS_CH_ORIGIN + "/", raw)
    parsed = urlparse(joined)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https"):
        return ""
    if host and host not in ("jobs.ch", "www.jobs.ch") and not host.endswith(".jobs.ch"):
        return ""
    path = parsed.path or "/"
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{_JOBS_CH_ORIGIN}{path}{query}"


def _fold_quotes(text: str) -> str:
    return (
        str(text or "")
        .replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u00b4", "'")
        .replace("`", "'")
    )


def _is_jobs_ch_company_profile_href(href: str) -> bool:
    """True for /{locale}/entreprises/{id-slug}/ — not listings, reviews, or /start/."""
    abs_url = _absolute_jobs_ch_url(href)
    path = urlparse(abs_url).path if abs_url else urlparse(href or "").path
    segs = [p for p in (path or "").split("/") if p]
    if len(segs) < 2:
        return False
    if len(segs[0]) == 2 and segs[0].isalpha():
        kind = segs[1].lower() if len(segs) > 1 else ""
        slug = segs[2] if len(segs) > 2 else ""
        rest = segs[3:]
    else:
        kind = segs[0].lower()
        slug = segs[1] if len(segs) > 1 else ""
        rest = segs[2:]
    if kind not in _JOBS_CH_COMPANY_KINDS:
        return False
    if not slug or slug.lower() == "start":
        return False
    return not rest


def _jobs_ch_company_profile_url(soup: BeautifulSoup) -> str:
    """Prefer the 'view company profile' CTA; fall back to the company-name link."""
    ranked: List[Tuple[int, str]] = []
    for a in soup.select("a[href]"):
        href = _clean(a.get("href"))
        if not _is_jobs_ch_company_profile_href(href):
            continue
        abs_url = _absolute_jobs_ch_url(href)
        if not abs_url:
            continue
        text = _fold_quotes(_visible_text(a)).lower()
        score = 1
        if any(hint in text for hint in _JOBS_CH_PROFILE_CTA_HINTS):
            score = 3
        elif (a.get("data-cy") or "") == "company-link":
            score = 2
        ranked.append((score, abs_url))
    if not ranked:
        return ""
    ranked.sort(key=lambda item: -item[0])
    return ranked[0][1]


def parse_jobs_ch_company_about(html: str) -> str:
    """Main company-profile copy. Prefer company-description; never the teased snippet."""
    soup = _soup(html)
    desc = soup.select_one('[data-cy="company-description"]')
    text = _visible_text(desc)
    if text:
        return text
    return _employer_overview_from_soup(soup)


def _employer_overview_from_soup(soup: BeautifulSoup) -> str:
    for blob in _load_json_ld_scripts(soup):
        for item in _walk_json_ld(blob):
            overview = item.get("employerOverview")
            if isinstance(overview, str) and overview.strip():
                return html_fragment_to_text(overview)
    return ""


def _http_get_jobs_ch(url: str) -> str:
    try:
        with httpx.Client(
            timeout=_JOBS_CH_COMPANY_FETCH_TIMEOUT_S,
            follow_redirects=True,
            headers=_JOBS_CH_FETCH_HEADERS,
        ) as client:
            response = client.get(url)
    except Exception:
        logger.exception("jobs.ch company profile fetch failed for %s", url)
        return ""
    if response.status_code != 200:
        logger.warning("jobs.ch company profile HTTP %s for %s", response.status_code, url)
        return ""
    return response.text or ""


def fetch_jobs_ch_company_about(
    url: str,
    *,
    fetch_html: Optional[Callable[[str], str]] = None,
) -> str:
    abs_url = _absolute_jobs_ch_url(url)
    if not abs_url or not _is_jobs_ch_company_profile_href(abs_url):
        return ""
    getter = fetch_html if fetch_html is not None else _http_get_jobs_ch
    try:
        html = getter(abs_url)
    except Exception:
        logger.exception("jobs.ch company profile fetch callback failed for %s", abs_url)
        return ""
    if not html:
        return ""
    return parse_jobs_ch_company_about(html)


def attach_jobs_ch_company_about(
    parsed: Dict[str, Any],
    *,
    fetch_html: Optional[Callable[[str], str]] = None,
) -> Dict[str, Any]:
    """Fill additional_company_info from the company-profile URL when missing.

    Does not invent text: a failed fetch or unmatched markup leaves the field empty.
    """
    if not parsed:
        return parsed
    if _clean(parsed.get("additional_company_info")):
        return parsed
    url = _clean(parsed.get("company_profile_url"))
    parsed["additional_company_info"] = fetch_jobs_ch_company_about(url, fetch_html=fetch_html)
    return parsed


def _jobs_ch_canonical_url(soup: BeautifulSoup, source_url: str) -> str:
    link = soup.find("link", rel=lambda v: bool(v) and "canonical" in str(v).lower())
    if isinstance(link, Tag):
        href = _absolute_jobs_ch_url(_clean(link.get("href")))
        if _JOBS_CH_DETAIL_PATH_RE.search(href):
            return href
    ld = _job_posting_from_soup(soup)
    ld_url = _absolute_jobs_ch_url(_clean(ld.get("source_url")))
    if _JOBS_CH_DETAIL_PATH_RE.search(ld_url):
        return ld_url
    if _JOBS_CH_DETAIL_PATH_RE.search(source_url or ""):
        return _absolute_jobs_ch_url(source_url)
    return ""


def _parse_jobs_ch(html: str, source_url: str) -> Dict[str, Any]:
    """jobs.ch search+preview: selected card is cursor_pointer vacancy-link, not JSON-LD."""
    del source_url
    soup = _soup(html)
    parsed = _jobs_ch_vacancy_fields(soup)
    link = _jobs_ch_selected_vacancy_link(soup)
    if link is not None:
        parsed["source_url"] = _absolute_jobs_ch_url(_clean(link.get("href")))
        if not parsed["job_title"]:
            parsed["job_title"] = _clean(link.get("title"))
    return parsed


def _parse_jobs_ch_inner(html: str, source_url: str) -> Dict[str, Any]:
    """jobs.ch clicked-through detail page (jobs.ch_inner.html). Same panel as SERP preview."""
    soup = _soup(html)
    parsed = _jobs_ch_vacancy_fields(soup)
    parsed["source_url"] = _jobs_ch_canonical_url(soup, source_url)
    if not parsed["job_text"] or not parsed["job_title"]:
        ld = _job_posting_from_soup(soup)
        _fill_missing(
            parsed,
            ld,
            ("job_title", "company_name", "location", "salary", "job_text", "point_of_contact", "source_url"),
        )
        parsed["source_url"] = _absolute_jobs_ch_url(parsed.get("source_url") or "")
    return parsed


def _parse_jobs_ch_company(html: str, source_url: str) -> Dict[str, Any]:
    """jobs.ch company profile (jobs.ch_company.html): about text, not a vacancy."""
    soup = _soup(html)
    parsed = empty_parse("jobs.ch_company")
    parsed["company_name"] = _first_text(soup, ('[data-cy="company-name"]',))
    parsed["additional_company_info"] = parse_jobs_ch_company_about(html)
    canonical = ""
    link = soup.find("link", rel=lambda v: bool(v) and "canonical" in str(v).lower())
    if isinstance(link, Tag):
        canonical = _absolute_jobs_ch_url(_clean(link.get("href")))
    parsed["source_url"] = canonical or _absolute_jobs_ch_url(source_url)
    parsed["company_profile_url"] = parsed["source_url"]
    return parsed


def _swissdevjobs_language(root: Tag) -> str:
    for node in root.find_all(string=re.compile(r"^\s*Language\s*$")):
        parent = node.parent
        if parent is None:
            continue
        bold = parent.find_next("span", class_=lambda c: bool(c) and "font-weight-bold" in c)
        if bold is None:
            continue
        text = _visible_text(bold)
        if text and text.lower() != "language":
            return text
    return ""


def _parse_swissdevjobs(html: str, source_url: str) -> Dict[str, Any]:
    """swissdevjobs.ch: visible detail sections; JSON-LD only fills gaps."""
    del source_url
    soup = _soup(html)
    parsed = empty_parse("swissdevjobs.ch")
    container = soup.select_one(".whole-job-wrapper") or soup.select_one(".job-details-wrapper") or soup
    parsed["job_title"] = _first_text(container, ("h1",))
    parsed["company_name"] = _first_text(container, ('[aria-label="hiring organization"]',))
    parsed["location"] = _first_text(container, ('[aria-label="hiring organization address"]',))
    parsed["salary"] = _first_text(container, ('[aria-label="annual salary range"]', ".salary-info"))
    parsed["language"] = _swissdevjobs_language(container if isinstance(container, Tag) else soup)

    sections: List[str] = []
    title = parsed["job_title"]
    if title:
        sections.append(title)
    for box in container.select(".job-details-section-box"):
        text = _visible_text(box)
        if text:
            sections.append(text)
    parsed["job_text"] = "\n\n".join(sections).strip()

    ld = _job_posting_from_soup(soup)
    _fill_missing(
        parsed,
        ld,
        ("job_title", "company_name", "location", "salary", "job_text", "point_of_contact"),
    )
    return parsed


def _decompose_all(soup: BeautifulSoup, selectors: Iterable[str]) -> None:
    for sel in selectors:
        for el in soup.select(sel):
            el.decompose()


def _linkedin_title_company(soup: BeautifulSoup) -> Tuple[str, str]:
    raw = ""
    if soup.title:
        raw = soup.title.get_text(" ", strip=True)
    parts = [p.strip() for p in raw.split("|") if p.strip()]
    if parts and parts[-1].lower() == "linkedin":
        parts = parts[:-1]
    title = parts[0] if parts else ""
    company = parts[1] if len(parts) > 1 else ""
    return title, company


def _linkedin_company_from_aria(soup: BeautifulSoup) -> str:
    el = soup.select_one('[aria-label^="Company, "]')
    if el is None:
        return ""
    label = _clean(el.get("aria-label"))
    if "," in label:
        rest = label.split(",", 1)[1].strip().rstrip(".")
        if rest:
            return rest
    return _visible_text(el)


def _linkedin_location(soup: BeautifulSoup) -> str:
    for p in soup.find_all("p"):
        span_texts = [_visible_text(s) for s in p.find_all("span")]
        joined = " ".join(span_texts)
        timeish = any(
            "ago" in t.lower() or t.lower() in {"yesterday", "just now"} for t in span_texts
        )
        if not timeish:
            continue
        for t in span_texts:
            if "," in t and "ago" not in t.lower() and _COUNTRY_HINT.search(t):
                return t
        if _COUNTRY_HINT.search(joined):
            for t in span_texts:
                if "," in t:
                    return t
    for span in soup.find_all("span"):
        text = _visible_text(span)
        if "," in text and _COUNTRY_HINT.search(text) and "ago" not in text.lower():
            if "(" in text and any(k in text.lower() for k in ("on-site", "hybrid", "remote")):
                continue
            return text
    return ""


def _parse_linkedin(html: str, source_url: str) -> Dict[str, Any]:
    """LinkedIn job detail: hashed classes; select by id prefix and aria-label."""
    del source_url
    soup = _soup(html)
    _decompose_all(soup, _LINKEDIN_REMOVE)
    parsed = empty_parse("LinkedIn")
    title, company_from_title = _linkedin_title_company(soup)
    parsed["job_title"] = title
    parsed["company_name"] = _linkedin_company_from_aria(soup) or company_from_title
    about = soup.select_one('[id^="JobDetails_AboutTheJob_"]')
    parsed["job_text"] = _visible_text(about)
    parsed["location"] = _linkedin_location(soup)
    if not parsed["job_title"]:
        alert = soup.select_one('[aria-label^="Set alert for similar jobs as "]')
        if alert is not None:
            label = _clean(alert.get("aria-label"))
            prefix = "Set alert for similar jobs as "
            if label.lower().startswith(prefix.lower()):
                parsed["job_title"] = label[len(prefix) :].strip()
    return parsed


_PARSERS: Dict[str, Callable[[str, str], Dict[str, Any]]] = {
    "jobs.ch": _parse_jobs_ch,
    "jobs.ch_inner": _parse_jobs_ch_inner,
    "jobs.ch_company": _parse_jobs_ch_company,
    "swissdevjobs.ch": _parse_swissdevjobs,
    "LinkedIn": _parse_linkedin,
}
