from finetune.job_text import clean_job_excerpt

LINKEDIN_SCRAPE = """
viboo logo
viboo
Share
Show more options
Senior Software Engineer (f/m/d)
Zürich Metropolitan Area · Reposted 2 weeks ago · Over 100 people clicked apply
Promoted by hirer · Responses managed off LinkedIn
Hybrid
Matches your job preferences, workplace type is Hybrid.
Apply
Save
About the job
About viboo
Our mission at viboo is to reduce the environmental impact of buildings while helping
operators cut heating energy use by 20-40% through predictive AI on existing IoT hardware.
We are looking for a senior engineer to own backend services and ML operations.
Requirements
5+ years Python, Kubernetes, and time-series data at scale.
"""


def test_strips_linkedin_chrome_and_starts_at_about_section():
    excerpt = clean_job_excerpt(LINKEDIN_SCRAPE, max_chars=500)
    assert "Apply" not in excerpt
    assert "clicked apply" not in excerpt
    assert "Show more options" not in excerpt
    assert "Our mission at viboo" in excerpt
    assert "Requirements" in excerpt or "5+ years Python" in excerpt


def test_respects_char_limit():
    excerpt = clean_job_excerpt(LINKEDIN_SCRAPE, max_chars=120)
    assert len(excerpt) <= 120
    assert excerpt


def test_empty_input():
    assert clean_job_excerpt("") == ""
    assert clean_job_excerpt("Apply\nSave\nShare", max_chars=200) == ""
