import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "screen-job" / "scripts" / "fetch_posting.py"


def load_fetcher() -> ModuleType:
    spec = importlib.util.spec_from_file_location("screen_job_fetch_posting", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_fetches_greenhouse_posting_without_rendering_page() -> None:
    fetcher = load_fetcher()
    requested: list[str] = []

    def fetch_json(url: str) -> dict[str, object]:
        requested.append(url)
        return {
            "absolute_url": "https://boards.greenhouse.io/corelight/jobs/8055858",
            "title": "Enterprise AI Automation Engineer",
            "location": {"name": "North America"},
            "metadata": [{"name": "Workforce Classification", "value": "Regular Full-Time"}],
            "content": "&lt;p&gt;Build AI workflows.&lt;/p&gt;&lt;p&gt;$128K-$178K&lt;/p&gt;",
            "first_published": "2026-07-16T17:21:18-04:00",
            "updated_at": "2026-08-06T17:29:13-04:00",
        }

    result = fetcher.fetch_posting(
        "https://job-boards.greenhouse.io/corelight/jobs/8055858?gh_jid=8055858",
        fetch_json,
    )

    assert requested == ["https://boards-api.greenhouse.io/v1/boards/corelight/jobs/8055858"]
    assert result["provider"] == "greenhouse"
    assert result["employment_type"] == "Regular Full-Time"
    assert result["description"] == "Build AI workflows.\n$128K-$178K"


def test_fetches_one_ashby_posting_from_board_feed() -> None:
    fetcher = load_fetcher()
    requested: list[str] = []

    def fetch_json(url: str) -> dict[str, object]:
        requested.append(url)
        return {
            "jobs": [
                {"id": "different", "title": "Other"},
                {
                    "id": "5e650527-d8dd-413a-9cfb-d7d68143274b",
                    "title": "Applied AI Engineer",
                    "location": "United States & Canada",
                    "employmentType": "FullTime",
                    "workplaceType": "Remote",
                    "jobUrl": "https://jobs.ashbyhq.com/workos/5e650527-d8dd-413a-9cfb-d7d68143274b",
                    "descriptionPlain": "Ship production AI systems.",
                    "publishedAt": "2026-08-01T00:00:00Z",
                    "compensation": {"compensationTierSummary": "$175K - $275K"},
                },
            ]
        }

    result = fetcher.fetch_posting(
        "https://jobs.ashbyhq.com/workos/5e650527-d8dd-413a-9cfb-d7d68143274b/application",
        fetch_json,
    )

    assert requested == [
        "https://api.ashbyhq.com/posting-api/job-board/workos?includeCompensation=true"
    ]
    assert result["provider"] == "ashby"
    assert result["title"] == "Applied AI Engineer"
    assert result["workplace_type"] == "Remote"
    assert result["compensation"] == {"compensationTierSummary": "$175K - $275K"}


@pytest.mark.parametrize(
    "url",
    [
        "http://job-boards.greenhouse.io/corelight/jobs/8055858",
        "https://example.com/jobs/123",
        "https://jobs.ashbyhq.com/workos/application",
    ],
)
def test_rejects_unsupported_or_invalid_posting_urls(url: str) -> None:
    fetcher = load_fetcher()

    with pytest.raises(ValueError):
        fetcher.fetch_posting(url, lambda _: {})
