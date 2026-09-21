"""Hostname-matched job-page templates (extension capture examples)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from letter_writer.job_extraction import extract_job_page_metadata
from letter_writer.page_templates import (
    attach_jobs_ch_company_about,
    extract_from_captured_page,
    match_page_template,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "extensions" / "job-capture" / "examples"

JOBS_CH_UBS_URL = (
    "https://www.jobs.ch/fr/offres-emplois/detail/4fb22d9e-9326-4f87-b5f9-4289c8b414a6/"
)
JOBS_CH_COMPANY_URL = (
    "https://www.jobs.ch/fr/entreprises/fae27eab-1cee-43a7-b16c-852d50d17e50-ubs-card-center-ag/"
)
JOBS_CH_COMPANY_LEAD = (
    "Die UBS Card Center AG, eine Tochtergesellschaft der UBS Switzerland AG, "
    "ist der führende Kreditkartenprozessor der Schweiz."
)
JOBS_CH_UBS_TITLE = "Senior AI Machine Learning Engineer 100% (f/m/d)"
JOBS_CH_UBS_LOCATION = "Flughofstrasse 35, 8152 Glattbrugg"
JOBS_CH_UBS_SALARY = "CHF 85 035 - 125 035/an"
JOBS_CH_UBS_BODY = (
    "Your team We are looking for a highly experienced Senior AI Machine Learning Engineer "
    "to design, build, and operate enterprise-scale AI solutions for a leading financial institution."
)

JOBS_CH_COMPACT = f"""
<html lang="fr"><head>
<script type="application/ld+json">
{{"@context":"https://schema.org","@type":"JobPosting",
 "title":"C++ Embedded Software Engineer (w/m/d) 80-100%",
 "hiringOrganization":{{"@type":"Organization","name":"Metrohm AG"}},
 "url":"https://www.jobs.ch/fr/offres-emplois/detail/cee928f4-9f1a-480b-a582-71301e050729/",
 "description":"<p>Die Metrohm AG ist ein führendes Unternehmen in der instrumentellen Analytik.</p>"}}
</script>
</head><body>
<h1>1 393 Offres d'emploi de 1. Senior C++ Engineer</h1>
<a data-cy="job-link" id="vacancy-link-43c22c54-a16a-44bf-b4ef-d9d17f9f969c" class="cursor_pointer"
   title="C++ Engineer" href="https://www.jobs.ch/fr/offres-emplois/detail/43c22c54-a16a-44bf-b4ef-d9d17f9f969c/">
  <div data-cy="vacancy-serp-item">C++ Engineer Metrohm AG</div>
</a>
<a data-cy="job-link" id="vacancy-link-4fb22d9e-9326-4f87-b5f9-4289c8b414a6" class="cursor_pointer"
   title="{JOBS_CH_UBS_TITLE}" href="{JOBS_CH_UBS_URL}">
  <div data-cy="vacancy-serp-item-active">{JOBS_CH_UBS_TITLE} UBS Card Center AG Glattbrugg</div>
</a>
<div data-cy="vacancy-layout-standard">
  <div data-cy="vacancy-title">{JOBS_CH_UBS_TITLE}</div>
  <div data-cy="vacancy-company"><a data-cy="company-link">UBS Card Center AG</a></div>
  <div data-cy="vacancy-logo"><p class="textStyle_body2 pt_s8">Glattbrugg</p></div>
  <a data-cy="info-location-link">Flughofstrasse 35, 8152\u00a0Glattbrugg</a>
  <li data-cy="info-salary_estimate">
    <span class="textStyle_caption1">CHF 85\u202f035 - 125\u202f035/an</span>
    <div>Estimation salariale de jobs.ch</div>
  </li>
  <div data-cy="vacancy-description">
    <section data-cy="jobfit-teaser-cta">Vous correspondez très bien à ce poste</section>
    <h3>À propos de cette offre</h3>
    <p>{JOBS_CH_UBS_BODY}</p>
  </div>
</div>
<a class="cursor_pointer color-palette_link.default" href="/fr/entreprises/fae27eab-1cee-43a7-b16c-852d50d17e50-ubs-card-center-ag/" data-discover="true"><span>Voir le profil de l’entreprise</span></a>
<a href="/fr/entreprises/start/">Entreprises</a>
<a href="/fr/entreprises/fae27eab-1cee-43a7-b16c-852d50d17e50-ubs-card-center-ag/offres-emplois/">13 offres d'emploi</a>
</body></html>
"""

JOBS_CH_INNER_COMPACT = f"""
<html lang="fr"><head>
<link rel="canonical" href="{JOBS_CH_UBS_URL}" />
<script type="application/ld+json">
{{"@context":"https://schema.org","@type":"JobPosting",
 "title":"{JOBS_CH_UBS_TITLE}",
 "hiringOrganization":{{"@type":"Organization","name":"UBS Card Center AG"}},
 "url":"{JOBS_CH_UBS_URL}",
 "description":"<p>{JOBS_CH_UBS_BODY}</p>"}}
</script>
</head><body>
<h1>{JOBS_CH_UBS_TITLE}</h1>
<div data-cy="vacancy-layout-standard">
  <div data-cy="vacancy-title">{JOBS_CH_UBS_TITLE}</div>
  <div data-cy="vacancy-company"><a data-cy="company-link">UBS Card Center AG</a></div>
  <div data-cy="vacancy-logo"><p class="textStyle_body2 pt_s8">Glattbrugg</p></div>
  <a data-cy="info-location-link">Flughofstrasse 35, 8152\u00a0Glattbrugg</a>
  <li data-cy="info-salary_estimate">
    <span class="textStyle_caption1">CHF 85\u202f035 - 125\u202f035/an</span>
    <div>Estimation salariale de jobs.ch</div>
  </li>
  <div data-cy="vacancy-description">
    <section data-cy="jobfit-teaser-cta">Vous correspondez très bien à ce poste</section>
    <h2>À propos de cette offre</h2>
    <p>{JOBS_CH_UBS_BODY}</p>
  </div>
</div>
<a class="cursor_pointer color-palette_link.default" href="/fr/entreprises/fae27eab-1cee-43a7-b16c-852d50d17e50-ubs-card-center-ag/" data-discover="true"><span>Voir le profil de l’entreprise</span></a>
<a data-cy="job-link" id="vacancy-link-56a7326e-430e-4234-914c-d1a39bd16b35" class="cursor_pointer"
   href="https://www.jobs.ch/fr/offres-emplois/detail/56a7326e-430e-4234-914c-d1a39bd16b35/">Similar job</a>
</body></html>
"""

_JOBS_CH_COMPARE_KEYS = (
    "job_title",
    "company_name",
    "location",
    "job_text",
    "language",
    "point_of_contact",
    "source_url",
    "company_profile_url",
)

JOBS_CH_COMPANY_COMPACT = f"""
<html lang="fr"><head>
<link rel="canonical" href="{JOBS_CH_COMPANY_URL}" />
</head><body>
<h1 data-cy="company-name">UBS Card Center AG</h1>
<div data-cy="teased-text">L'entreprise apporte une contribution stable et rentable au résultat global de la société mère.</div>
<div data-cy="company-description">
<p>{JOBS_CH_COMPANY_LEAD} Weit über 3 Millionen Kreditkarten von Visa und Mastercard werden zuverlässig über unsere Systeme abgewickelt.</p>
<p>Weitere Infos und unsere offenen Stellen findest Du auf www.cardcenter.ch.</p>
</div>
</body></html>
"""

SWISSDEV_COMPACT = """
<html><body>
<div class="job-details-wrapper">
  <div class="card-body whole-job-wrapper">
    <h1>System Engineer / System Administrator 80-100%</h1>
    <div aria-label="annual salary range" class="salary-info">CHF 85'000 - 100'000</div>
    <div aria-label="hiring organization">Intersim AG</div>
    <div aria-label="hiring organization address"><span>Kirchbergstrasse 105, Burgdorf</span></div>
    <div class="job-essential-info-card-badge"> Language</div>
    <span class="font-weight-bold">German</span>
    <div class="job-details-section-box"><h2>Requirements</h2><p>Linux und Microsoft 365.</p></div>
    <div class="job-details-section-box"><h2>Responsibilities</h2><p>Server-Infrastrukturen betreuen.</p></div>
  </div>
</div>
<aside>Unrelated listing: Senior AI Machine Learning Engineer</aside>
</body></html>
"""

LINKEDIN_COMPACT = """
<html><head><title>Senior Solution Architect (a) | Adnovum | LinkedIn</title></head>
<body>
<nav>Home</nav>
<div aria-label="Company, Adnovum."><a>Adnovum</a></div>
<p>
  <span>Bern, Berne, Switzerland</span>
  <span> · </span>
  <span>3 months ago</span>
</p>
<div id="JobDetails_AboutTheJob_4418521487">
  <h2>About the job</h2>
  <p>What you're going to do</p>
  <p>To strengthen our team in Bern we are looking for a Senior Solution Architect.</p>
</div>
<div id="JobDetailsSimilarJobsSlot_4418521487">
  <h2>More jobs</h2>
  <span>Zurich, Switzerland (On-site)</span>
</div>
<div id="JobDetails_AboutTheCompany_4418521487">Company HQ in Zurich</div>
</body></html>
"""


def _load_example(name: str) -> str:
    path = EXAMPLES / name
    if not path.is_file():
        pytest.skip(f"missing example {path}")
    return path.read_text(encoding="utf-8", errors="replace")


def test_match_page_template_hosts():
    assert match_page_template("https://www.jobs.ch/fr/offres-emplois/?term=cpp") == "jobs.ch"
    assert match_page_template("https://jobs.ch/de/stellenangebote/") == "jobs.ch"
    assert (
        match_page_template("https://www.jobs.ch/fr/offres-emplois/detail/abc/")
        == "jobs.ch_inner"
    )
    assert (
        match_page_template(
            "https://www.jobs.ch/fr/entreprises/fae27eab-1cee-43a7-b16c-852d50d17e50-ubs-card-center-ag/"
        )
        == "jobs.ch_company"
    )
    assert match_page_template("https://swissdevjobs.ch/jobs/x") == "swissdevjobs.ch"
    assert match_page_template("https://www.linkedin.com/jobs/view/123") == "LinkedIn"
    assert match_page_template("https://jobs.example/role") is None
    assert match_page_template("https://notjobs.ch/x") is None


def test_jobs_ch_serp_uses_selected_card_not_json_ld():
    parsed = extract_from_captured_page(
        JOBS_CH_COMPACT, "https://www.jobs.ch/fr/offres-emplois/?term=cpp"
    )
    assert parsed["template"] == "jobs.ch"
    assert parsed["job_title"] == JOBS_CH_UBS_TITLE
    assert parsed["company_name"] == "UBS Card Center AG"
    assert parsed["location"] == JOBS_CH_UBS_LOCATION
    assert parsed["salary"] == JOBS_CH_UBS_SALARY
    assert "Estimation" not in parsed["salary"]
    assert "Senior AI Machine Learning Engineer" in parsed["job_text"]
    assert "Vous correspondez" not in parsed["job_text"]
    assert "Metrohm" not in parsed["job_text"]
    assert "Metrohm" not in parsed["job_title"]
    assert "1 393" not in parsed["job_text"]
    assert parsed["source_url"] == JOBS_CH_UBS_URL
    assert parsed["company_profile_url"] == JOBS_CH_COMPANY_URL
    assert parsed["additional_company_info"] == ""


def test_jobs_ch_source_url_is_absolute_www():
    relative = JOBS_CH_COMPACT.replace(
        f'href="{JOBS_CH_UBS_URL}"',
        'href="/fr/offres-emplois/detail/4fb22d9e-9326-4f87-b5f9-4289c8b414a6/"',
    )
    parsed = extract_from_captured_page(
        relative, "https://www.jobs.ch/fr/offres-emplois/?term=cpp"
    )
    assert parsed["source_url"] == JOBS_CH_UBS_URL
    inner_relative = JOBS_CH_INNER_COMPACT.replace(
        f'href="{JOBS_CH_UBS_URL}"',
        'href="/fr/offres-emplois/detail/4fb22d9e-9326-4f87-b5f9-4289c8b414a6/"',
    ).replace(
        f'"url":"{JOBS_CH_UBS_URL}"',
        '"url":"/fr/offres-emplois/detail/4fb22d9e-9326-4f87-b5f9-4289c8b414a6/"',
    )
    inner = extract_from_captured_page(
        inner_relative,
        "https://jobs.ch/fr/offres-emplois/detail/4fb22d9e-9326-4f87-b5f9-4289c8b414a6/",
    )
    assert inner["source_url"] == JOBS_CH_UBS_URL
    assert inner["source_url"].startswith("https://www.jobs.ch/")


def test_jobs_ch_inner_matches_serp_fields():
    serp = extract_from_captured_page(
        JOBS_CH_COMPACT, "https://www.jobs.ch/fr/offres-emplois/?term=cpp"
    )
    inner = extract_from_captured_page(JOBS_CH_INNER_COMPACT, JOBS_CH_UBS_URL)
    assert inner["template"] == "jobs.ch_inner"
    assert serp["template"] == "jobs.ch"
    for key in _JOBS_CH_COMPARE_KEYS:
        assert inner[key] == serp[key], key
    assert serp["salary"] == JOBS_CH_UBS_SALARY
    assert inner["salary"] == JOBS_CH_UBS_SALARY
    assert "56a7326e" not in inner["source_url"]


def test_jobs_ch_location_falls_back_to_logo_city():
    html = JOBS_CH_COMPACT.replace(
        '<a data-cy="info-location-link">Flughofstrasse 35, 8152\u00a0Glattbrugg</a>',
        "",
    )
    parsed = extract_from_captured_page(
        html, "https://www.jobs.ch/fr/offres-emplois/?term=cpp"
    )
    assert parsed["location"] == "Glattbrugg"


def test_swissdevjobs_compact_uses_section_boxes():
    parsed = extract_from_captured_page(SWISSDEV_COMPACT, "https://swissdevjobs.ch/jobs/system-engineer")
    assert parsed["template"] == "swissdevjobs.ch"
    assert parsed["job_title"].startswith("System Engineer")
    assert parsed["company_name"] == "Intersim AG"
    assert "Burgdorf" in parsed["location"]
    assert "85" in parsed["salary"]
    assert parsed["language"] == "German"
    assert "Requirements" in parsed["job_text"]
    assert "Linux" in parsed["job_text"]
    assert "Senior AI Machine Learning Engineer" not in parsed["job_text"]


def test_linkedin_compact_uses_about_the_job_not_similar():
    parsed = extract_from_captured_page(
        LINKEDIN_COMPACT, "https://www.linkedin.com/jobs/view/4418521487"
    )
    assert parsed["template"] == "LinkedIn"
    assert parsed["job_title"].startswith("Senior Solution Architect")
    assert parsed["company_name"] == "Adnovum"
    assert parsed["location"].startswith("Bern")
    assert "About the job" in parsed["job_text"]
    assert "Senior Solution Architect" in parsed["job_text"]
    assert "More jobs" not in parsed["job_text"]
    assert "On-site" not in parsed["location"]


def test_unknown_host_does_not_parse():
    parsed = extract_from_captured_page(JOBS_CH_COMPACT, "https://jobs.example/metrohm")
    assert parsed["template"] is None
    assert parsed["job_text"] == ""
    assert parsed["job_title"] == ""


def test_extract_job_page_metadata_skips_llm_when_template_has_posting():
    client = MagicMock()
    result = extract_job_page_metadata(
        "Cookie accept\n1 393 Offres\nAller directement au contenu",
        client,
        html=JOBS_CH_COMPACT,
        source_url="https://www.jobs.ch/fr/offres-emplois/?term=cpp",
    )
    client.call.assert_not_called()
    assert result["company_name"] == "UBS Card Center AG"
    assert "Senior AI Machine Learning Engineer" in result["job_text"]
    assert "Cookie" not in result["job_text"]
    assert result["source_url"] == JOBS_CH_UBS_URL


def test_extract_job_page_metadata_still_calls_llm_for_unknown_host():
    client = MagicMock()
    client.call.return_value = (
        '{"job_text":"Zürich sucht eine Entwicklerin.","company_name":"Acme",'
        '"job_title":"Engineerin","location":"Zürich","language":"German",'
        '"salary":null,"point_of_contact":null}'
    )
    result = extract_job_page_metadata(
        "Cookie accept\nZürich sucht eine Entwicklerin",
        client,
        html="<html><body>Zürich sucht eine Entwicklerin</body></html>",
        source_url="https://jobs.example/acme",
    )
    client.call.assert_called_once()
    assert result["company_name"] == "Acme"


def test_jobs_ch_saved_serp_and_inner_are_the_same_posting():
    serp_html = _load_example("jobs.ch.html")
    inner_html = _load_example("jobs.ch_inner.html")
    serp = extract_from_captured_page(
        serp_html, "https://www.jobs.ch/fr/offres-emplois/?term=cpp"
    )
    inner = extract_from_captured_page(inner_html, JOBS_CH_UBS_URL)
    assert serp["template"] == "jobs.ch"
    assert inner["template"] == "jobs.ch_inner"
    assert serp["job_title"] == JOBS_CH_UBS_TITLE
    assert serp["company_name"] == "UBS Card Center AG"
    assert serp["location"] == JOBS_CH_UBS_LOCATION
    assert "CHF 85" in serp["salary"]
    assert "125" in serp["salary"]
    assert "/an" in serp["salary"]
    assert "Estimation" not in serp["salary"]
    assert inner["salary"].startswith("CHF 85")
    assert "Estimation" not in inner["salary"]
    assert "Your team" in serp["job_text"] or "Your\xa0team" in serp["job_text"]
    assert "Metrohm" not in serp["job_text"]
    assert "1 393" not in serp["job_text"]
    assert "Aller directement" not in serp["job_text"]
    assert "Vous correspondez" not in serp["job_text"]
    assert serp["source_url"] == JOBS_CH_UBS_URL
    assert serp["company_profile_url"] == JOBS_CH_COMPANY_URL
    for key in _JOBS_CH_COMPARE_KEYS:
        assert inner[key] == serp[key], key


def test_swissdevjobs_saved_example():
    html = _load_example("swissdevjobs.ch.html")
    parsed = extract_from_captured_page(html, "https://swissdevjobs.ch/jobs/system-engineer")
    assert "System Engineer" in parsed["job_title"]
    assert "🏆" not in parsed["job_title"]
    assert parsed["company_name"] == "Intersim AG"
    assert "Burgdorf" in parsed["location"]
    assert "85" in parsed["salary"]
    assert parsed["language"] == "German"
    assert "Requirements" in parsed["job_text"]


def test_linkedin_saved_example():
    html = _load_example("LinkedIn.html")
    parsed = extract_from_captured_page(html, "https://www.linkedin.com/jobs/view/4418521487")
    assert "Solution Architect" in parsed["job_title"]
    assert parsed["company_name"] == "Adnovum"
    assert "Bern" in parsed["location"]
    assert "About the job" in parsed["job_text"]
    assert "More jobs" not in parsed["job_text"]


def test_jobs_ch_company_compact_uses_description_not_teaser():
    parsed = extract_from_captured_page(JOBS_CH_COMPANY_COMPACT, JOBS_CH_COMPANY_URL)
    assert parsed["template"] == "jobs.ch_company"
    assert parsed["company_name"] == "UBS Card Center AG"
    assert parsed["additional_company_info"].startswith(JOBS_CH_COMPANY_LEAD)
    assert "teased" not in parsed["additional_company_info"].lower()
    assert "contribution stable" not in parsed["additional_company_info"]
    assert parsed["job_text"] == ""
    assert parsed["source_url"] == JOBS_CH_COMPANY_URL
    assert parsed["company_profile_url"] == JOBS_CH_COMPANY_URL


def test_attach_company_about_fills_from_fetched_profile():
    parsed = extract_from_captured_page(
        JOBS_CH_COMPACT, "https://www.jobs.ch/fr/offres-emplois/?term=cpp"
    )
    assert parsed["additional_company_info"] == ""
    attach_jobs_ch_company_about(parsed, fetch_html=lambda url: JOBS_CH_COMPANY_COMPACT)
    assert parsed["additional_company_info"].startswith(JOBS_CH_COMPANY_LEAD)
    assert "www.cardcenter.ch" in parsed["additional_company_info"]
    assert "contribution stable" not in parsed["additional_company_info"]


def test_attach_company_about_stays_empty_when_fetch_fails():
    parsed = extract_from_captured_page(
        JOBS_CH_COMPACT, "https://www.jobs.ch/fr/offres-emplois/?term=cpp"
    )
    attach_jobs_ch_company_about(parsed, fetch_html=lambda url: "")
    assert parsed["additional_company_info"] == ""


def test_extract_job_page_metadata_includes_attached_company_about():
    client = MagicMock()
    parsed = extract_from_captured_page(
        JOBS_CH_COMPACT, "https://www.jobs.ch/fr/offres-emplois/?term=cpp"
    )
    attach_jobs_ch_company_about(parsed, fetch_html=lambda url: JOBS_CH_COMPANY_COMPACT)
    result = extract_job_page_metadata(
        "ignored chrome",
        client,
        html=JOBS_CH_COMPACT,
        source_url="https://www.jobs.ch/fr/offres-emplois/?term=cpp",
        parsed_page=parsed,
    )
    client.call.assert_not_called()
    assert result["additional_company_info"].startswith(JOBS_CH_COMPANY_LEAD)


def test_jobs_ch_saved_company_example():
    html = _load_example("jobs.ch_company.html")
    parsed = extract_from_captured_page(html, JOBS_CH_COMPANY_URL)
    assert parsed["template"] == "jobs.ch_company"
    assert parsed["company_name"] == "UBS Card Center AG"
    assert parsed["additional_company_info"].startswith(JOBS_CH_COMPANY_LEAD)
    assert "Kreditkartenprozessor" in parsed["additional_company_info"]
    assert "contribution stable" not in parsed["additional_company_info"]
    assert parsed["source_url"] == JOBS_CH_COMPANY_URL
